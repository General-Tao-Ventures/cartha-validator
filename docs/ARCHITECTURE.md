# Cartha Subnet Validator – Architecture Overview

The validator is a lightweight daemon that operates on a **weekly epoch cycle**. It fetches epoch-frozen miner lists from the Cartha verifier, scores miners using a transparent liquidity-weighted formula, caches weights for the week, and publishes them to Bittensor every Bittensor epoch.

```
┌───────────┐      ┌────────────────┐      ┌──────────────┐
│  Verifier │ ---> │ Validator Main │ ---> │  Subtensor    │
│ (FastAPI) │      │ (this project) │      │ set_weights() │
└───────────┘      └────────────────┘      └──────────────┘
          ▲                 │                      ▲
          │                 ▼                      │
    EVM vaults        Lock replay / scoring    (every tempo blocks)
                      Cache weights (weekly)
                      Daily expiry checks
```

## Major Modules

| Module | Responsibility |
| --- | --- |
| `cartha_validator/main.py` | CLI entrypoint, daemon loop, weekly epoch detection, daily expiry checks, metagraph syncing, weight caching, Bittensor epoch integration. |
| `cartha_validator/epoch_runner.py` | Orchestrates single epoch execution: fetches verified miners, processes entries, scores, and publishes weights. |
| `cartha_validator/processor.py` | Processes verifier entries: UID resolution, position replay/aggregation, expired pool filtering, scoring orchestration. |
| `cartha_validator/indexer.py` | Event replay helpers for Model-1 vault semantics (lock created/updated/released). Legacy path, not used by default. |
| `cartha_validator/scoring.py` | Liquidity scoring with pool weights and lock duration boost. Returns raw scores directly for proportional weight distribution. |
| `cartha_validator/weights.py` | Normalises scores, allocates fixed trader pool weight, handles emission-burn fallback, wraps `set_weights` with cooldown checks. |
| `cartha_validator/config.py` | Typed settings (verifier URL, validator whitelist, pool weights, max lock days, epoch schedule, trader pool config, min assets threshold). |
| `cartha_validator/epoch.py` | Weekly epoch boundary helpers (Friday 00:00 UTC → Thursday 23:59 UTC). |
| `cartha_validator/pool_weights.py` | Pool weight querying from on-chain parent vault contracts (PRE_DEX = equal weights; POST_DEX = on-chain allocations). |
| `cartha_validator/leaderboard_client.py` | Sends full ranking to Cartha leaderboard API after weights are published. |
| `cartha_validator/logging.py` | ANSI color codes and emoji helpers for rich terminal output. |
| `cartha_validator/register.py` | Registration helpers (ensure hotkey is registered on subnet before running). |

---

## Scoring Algorithm

### Overview

Each miner is scored based on the **sum of contributions from all their active liquidity positions**. A position's contribution is the product of three factors:

```
position_score = pool_weight × amount_usdc × lock_boost
```

Where:

- **`pool_weight`** — multiplier for the pool the USDC is locked in (currently `1.0` for all pools in PRE_DEX mode; post-DEX will use on-chain allocations)
- **`amount_usdc`** — the USDC amount frozen at epoch start (`original_amount_usdc`). Mid-epoch top-ups appear as `pending_amount` and do **not** count until the following epoch
- **`lock_boost`** — proportional to lock duration, capped at `max_lock_days` (default: 365)

```
lock_boost = min(lock_days, max_lock_days) / max_lock_days
```

A position locked for 365 days achieves the maximum boost of `1.0`. A position locked for 182 days achieves `0.5`. This design rewards long-term commitment.

### Per-Position Scoring (Not Per-Miner)

Each position is scored **individually** — the validator does not collapse multiple positions into a single average. A miner with 5 positions in different pools (or with different lock durations) earns the sum of all 5 position scores. This ensures every federated miner position contributes its own distinct boost to the total score.

```
raw_score(miner) = Σ position_score(i)   for all active positions i
```

### Minimum Assets Threshold

Principal miners with a total vault balance below `100,000 USDC` (configurable via `min_total_assets_usdc`) receive a score of `0.0` regardless of lock duration or pool. Since the principal miner's score drives all ALPHA emissions for their vault, federated miners inside that vault also receive no rewards for the epoch. This prevents dust positions from gaming the weight distribution.

### Weight Normalization

After all miners are scored:

```
remaining_weight = 1.0 - trader_pool_weight          # = 0.756098
weight(miner_i) = (score_i / Σ score_j) × remaining_weight
```

Where `Σ score_j` sums only miners with `score > 0`.

### Fixed Allocations

| Recipient | Allocation | Purpose |
| --- | --- | --- |
| Incentive Pool (`5EPdZM...`) | **24.3902%** fixed | Ecosystem incentives — airdrops, trader rewards, community programs |
| Qualified miners | **75.6098%** proportional | Rewards liquidity providers |
| Subnet owner hotkey | **75.6098%** (fallback) | Emission burning when no miners qualify |

If no miners meet the minimum threshold, the miner allocation is routed to the subnet owner hotkey for **emission burning** — reducing inflation rather than wasting it.

### Display Score (Leaderboard Only)

The validator computes a display score for the leaderboard frontend (not used for on-chain weights):

```
display_score = (raw_score / max_raw_score) × 1000
```

This normalizes all scores to a 0–1000 scale for visual comparison.

### Estimated Daily Emissions

For informational display only:

```
emissions_per_day(miner) = weight(miner) × 2952.0 ALPHA/day
```

---

## Epoch Flow

### Weekly Epoch Cycle

The validator operates on a **weekly epoch** (Friday 00:00 UTC → Thursday 23:59 UTC):

1. **Weekly Epoch Detection** — Detects current weekly epoch start (Friday 00:00 UTC boundary)
2. **Validator Whitelist Check** — Verifies that the validator hotkey is in the whitelist before querying
3. **Fetch Frozen Snapshot** — `GET /v1/verified-miners?epoch=<version>&validator_hotkey=<ss58>&netuid=<n>` from the verifier. This list is frozen at Friday 00:00 UTC and contains `(hotkey, slot_uid, pool_id, amount, lock_days, expires_at, deregistered_at, …)`.
   - **Epoch Fallback**: If requested epoch isn't frozen yet, verifier returns last frozen epoch
4. **Fetch Deregistered Hotkeys** — `GET /v1/deregistered-hotkeys?epoch_version=<version>`. Returns hotkeys deregistered mid-epoch (all their positions score 0)
5. **Resolve UIDs** — For each hotkey, asks the local subtensor for its UID on netuid 35
6. **Aggregate Positions** — Each pool position is kept as a distinct entry (not collapsed by pool). Positions are keyed as `pool_id#index` to preserve individual lock boosts
7. **Filter Expired Pools** — Pools with `expires_at < now` are excluded before scoring
8. **Filter Deregistered Hotkeys** — All positions for deregistered hotkeys are excluded (score = 0)
9. **Apply Minimum Threshold** — Miners with total locked USDC < 100,000 score 0
10. **Score Miners** — `scoring.score_entry()` sums all position contributions per miner
11. **Normalise Weights** — `weights._normalize()` allocates fixed trader pool weight and normalizes miners proportionally to fill the remainder
12. **Cache Weights** — Weights are cached for the entire weekly epoch
13. **Publish** — `weights.publish()` checks cooldown and calls `subtensor.set_weights()` every Bittensor epoch (tempo blocks) throughout the week
14. **Submit Leaderboard** — After successful publication, full ranking is sent to the leaderboard API

### Daily Expiry Checks

During a weekly epoch, the validator performs **daily expiry checks**:
- Checks if 24 hours have passed since last check
- Re-fetches verified miners to get updated `expires_at` values
- Re-fetches deregistered hotkeys list
- Filters out expired pools and newly deregistered hotkeys
- Recalculates and re-caches weights with filtered results
- Forces weight re-publication (bypasses cooldown)

### Continuous Daemon Mode

When running continuously (default):
- **Polling**: Checks for new epochs every `--poll-interval` seconds (default: 300s = 5 minutes)
- **Metagraph Syncing**: Syncs metagraph every 100 blocks (~20 min) to stay current
- **Bittensor Epoch Publishing**: Publishes cached weights every Bittensor epoch (tempo blocks)
- **Startup Behavior**: On startup, always fetches and publishes weights (bypasses cooldown with `force=True`)

If `--dry-run` is provided, the weight vector is printed instead of being published. All log output is routed through `bittensor.logging` and can be expanded with the standard `--logging.debug` flag (enabled by default).

---

## Federated Miners and the Principal Miner Layer

The validator scores the **principal miner's hotkey** based on the **total USDC locked across all positions in their vault** — including positions placed by federated miners who lock USDC through the principal's vault address.

**Every federated miner position makes a distinct, independent contribution to the principal miner's final score.** Because positions are scored individually (not collapsed), a federated miner who locks 50,000 USDC for 365 days contributes exactly twice the score of one who locks for 182 days — at the same USDC amount. This makes the system robust and fair:

- Federated miners with longer lock commitments are rewarded proportionally more
- The principal miner's Bittensor weight — and thus their subnet emissions — directly reflects the quality and commitment of their entire federated pool
- Mid-epoch top-ups by federated miners are not counted until the next epoch (epoch freeze prevents gaming)

The distribution of earned ALPHA from the principal miner to individual federated miners is handled by the **`cartha-principal-rewards`** tool, which applies the same scoring formula at a finer granularity to determine each federated miner's fair share (see the principal rewards layer below).

### Principal Rewards Layer (Off-Chain)

After the Bittensor weight system determines how much ALPHA flows to each principal miner's hotkey, a second scoring layer governs how the principal distributes those earnings to their federated miners:

```
position_score = pool_weight × scoring_amount × lock_boost

home_share   = home_total_score  / total_score     (principal's own positions)
guest_share  = guest_total_score / total_score     (all federated miners)

home_alpha   = total_alpha × home_share            (no commission applied)
guest_gross  = total_alpha × guest_share
commission   = guest_gross × commission_rate
guest_net    = guest_gross - commission

each_guest_reward = guest_net × (guest_score_i / guest_total_score)
```

**Home positions** are the principal's own EVM address (no commission deducted). **Guest positions** are all other federated miners (commission applies before distribution). This segmentation ensures the principal is compensated for operating the vault while guaranteeing every federated miner receives a fair, score-proportional share.

---

## Pool Weight Modes

### Current: PRE_DEX Equal Weights

All 6 market pools receive identical weight (`1.0`). Scoring is purely a function of USDC amount × lock duration. Pool choice does not differentiate scores.

### Future: POST_DEX On-Chain Weights

When the Cartha DEX launches, `PRE_DEX_EQUAL_WEIGHTS` will be set to `False`. Pool weights will be fetched on-chain from `calculateTargetAllocations()` on the parent vault contracts:

| Pool | Parent Vault | Network |
| --- | --- | --- |
| BTC/USD, ETH/USD | Cryptos parent vault | Base Mainnet |
| EUR/USD, GBP/USD, JPY/USD | Currencies parent vault | Base Mainnet |
| GOLD/USD | Commodities parent vault | Base Mainnet |

The code for on-chain weight queries already exists in `pool_weights.py` but is inactive until DEX launch.

---

## Operational Flags

| Flag | Effect |
| --- | --- |
| `--dry-run` | Skip `set_weights` and emit the ranking as JSON. |
| `--no-use-verified-amounts` | Disable verified amounts mode and fall back to on-chain EVM event replay. Not recommended — verified amounts mode is the **default and required mode** on mainnet (netuid 35). |
| `--epoch` | Provide an explicit epoch version (defaults to the current Friday 00:00 UTC). |
| `--timeout` | Adjust HTTP timeout for verifier calls (default: 15.0 seconds). |
| `--run-once` | Run once and exit (default: run continuously as daemon). |
| `--poll-interval` | Polling interval in seconds when running continuously (default: 300 = 5 minutes). |
| `--log-dir` | Directory to save epoch weight logs (default: `validator_logs`). |
| `--logging.debug` | Enable debug logging (enabled by default, use `--logging.debug=False` to disable). |

---

## Configuration Reference

| Parameter | Default | Description |
| --- | --- | --- |
| `netuid` | `35` | Subnet UID on Bittensor |
| `verifier_url` | `https://api.cartha.finance` | Verifier API base URL |
| `max_lock_days` | `365` | Lock duration cap for boost formula |
| `token_decimals` | `6` | USDC decimal places |
| `pool_weights` | `{}` (equal) | Pool weight multipliers (pool_id → float) |
| `epoch_weekday` | `4` (Friday) | Weekly epoch start day |
| `epoch_time` | `00:00 UTC` | Weekly epoch start time |
| `metagraph_sync_interval` | `100` blocks | How often to sync metagraph (~20 min) |
| `default_tempo` | `360` blocks | Fallback Bittensor epoch length |
| `epoch_length_blocks` | `360` blocks | Fallback cooldown check length |
| `testnet_netuid` | `78` | Testnet subnet UID |
| `timeout` | `15.0s` | HTTP timeout for verifier requests |
| `set_weights_timeout` | `90.0s` | Timeout for `set_weights` operation |
| `poll_interval` | `300s` | Daemon polling interval (5 minutes) |
| `log_dir` | `validator_logs` | JSON log output directory |
| `trader_rewards_pool_hotkey` | `5EPdZM…` | Fixed trader pool hotkey |
| `trader_rewards_pool_weight` | `0.243902` | Trader pool fixed weight (24.3902%) |
| `daily_alpha_emissions` | `2952.0` | Total ALPHA/day (display only) |
| `min_total_assets_usdc` | `100,000.0` | Minimum USDC for any weight allocation |
| `validator_whitelist` | `[]` (all) | Hotkeys allowed to query verifier |

---

## External Dependencies

- **Cartha Verifier API** — Single source of truth for the verified miner set and their epoch-frozen liquidity amounts. Provides `expires_at`, `deregistered_at`, `scoring_amount`, and `pending_amount` per position.
- **EVM Vaults** — Legacy on-chain event replay source (`LockCreated`, `LockUpdated`, `LockReleased`). Used only when `--no-use-verified-amounts` is passed.
- **Bittensor Subtensor** — Target for `set_weights` submissions; also used to resolve hotkeys to UIDs, query metagraph state, and check cooldown periods.
- **Cartha Leaderboard API** — Receives ranking data after each successful weight publication for frontend display.

---

## Logging & Metrics

Key instrumentation surfaced via logs (with ANSI colors and emojis):

- **Epoch Information**: Weekly epoch version, epoch fallback events, daily expiry check status
- **Scoring Details**: Per-position breakdown (pool, amount, lock days, boost, contribution)
- **Weight Allocation**: Per-UID score → weight mapping, trader pool fixed allocation, emission burn events
- **Replay Metrics**: Per-miner replay timings (`avgReplayMs`), global `avgReplay_ms` metric
- **Processing Metrics**: Skipped/failure counts (missing UID, replay failure, expired pools, deregistered hotkeys, below threshold)
- **Publishing Metrics**: Weight publication status, cooldown checks, version key used
- **Metagraph Sync**: Block numbers, tempo (Bittensor epoch length), network status

### Log Output

- **Console**: Rich ANSI-colored output with emojis for better visibility
- **Log Files**: Detailed JSON logs saved to `validator_logs/` with full ranking and metrics
- **Debug Mode**: Enabled by default; shows full rankings, detailed per-position scoring, and per-miner metrics

---

## Security Features

- **Validator Whitelist**: Only whitelisted validators can query verified miners. Non-whitelisted validators are rejected with a clear error message directing them to contact the subnet owner.
- **Registration Check**: Validates hotkey is registered on subnet before running
- **Version Control**: Validators must meet the minimum version requirement set on-chain (`weight_versions` hyperparameter)
- **Deregistered Hotkey Filtering**: All positions for deregistered hotkeys are automatically scored 0
- **Expired Pool Filtering**: Pools with `expires_at` in the past are automatically excluded
- **Epoch Freezing**: Uses verifier's epoch-frozen snapshots (`original_amount_usdc`) to prevent mid-epoch manipulation
- **Minimum Assets Threshold**: Principal miners below 100,000 USDC total vault balance score 0 — all federated miners in that vault also receive no rewards for the epoch
- **Emission Burning Fallback**: When no miners qualify, remaining weight routes to subnet owner hotkey for burning rather than accumulating
