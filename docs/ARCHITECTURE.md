# Cartha Subnet Validator – Architecture Overview

The validator is a lightweight daemon that operates on a **weekly epoch cycle**. It fetches epoch-frozen miner lists from the Cartha verifier, reconstructs liquidity positions via on-chain replay (or verifier-supplied amounts), scores miners, caches weights for the week, and publishes them to Bittensor every Bittensor epoch.

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
| `cartha_validator/indexer.py` | Event replay helpers for Model‑1 vault semantics (lock created/updated/released). |
| `cartha_validator/scoring.py` | Liquidity scoring with pool weights, lock duration boost, and temperature curve (`1 - exp(-raw/temperature)`). |
| `cartha_validator/weights.py` | Normalises scores, derives/queries `version_key`, wraps `set_weights` with cooldown checks. |
| `cartha_validator/config.py` | Typed settings (verifier URL, validator whitelist, pool weights, max lock days, epoch schedule). |
| `cartha_validator/epoch.py` | Weekly epoch boundary helpers (Friday 00:00 UTC → Thursday 23:59 UTC). |
| `cartha_validator/logging.py` | ANSI color codes and emoji helpers for rich terminal output. |
| `cartha_validator/register.py` | Registration helpers (ensure hotkey is registered). |

## Epoch Flow

### Weekly Epoch Cycle

The validator operates on a **weekly epoch** (Friday 00:00 UTC → Thursday 23:59 UTC):

1. **Weekly Epoch Detection** – Detects current weekly epoch start (Friday 00:00 UTC boundary)
2. **Validator Whitelist Check** – Verifies that the validator hotkey is in the whitelist before querying
3. **Fetch Frozen Snapshot** – `GET /v1/verified-miners?epoch=<version>` from the verifier. This list is
   frozen at Friday 00:00 UTC and contains `(hotkey, slot_uid, chain_id, vault, pool_id, amount, expires_at, …)`.
   - **Epoch Fallback**: If requested epoch isn't frozen yet, verifier returns last frozen epoch
   - **Note**: The verifier handles all on-chain validation and RPC queries
4. **Resolve UIDs** – For each hotkey, the validator asks the local subtensor for its UID on netuid 35
5. **Aggregate Liquidity** – 
   - Uses verifier-supplied `amount` field (verifier handles all on-chain validation)
   - Positions are aggregated per UID across all pools
   - **Expired Pool Filtering**: Pools with `expires_at` in the past are excluded
6. **Score Miners** – Pools are aggregated per UID. The boost formula is:
   ```
   raw = poolWeight * amount * min(lockDays, maxLockDays) / maxLockDays
   score = 1 - exp(-raw / score_temperature)    # score_temperature defaults to 1000
   ```
7. **Normalise Weights** – `weight = score / Σ(score)`; weights sum to 1
8. **Cache Weights** – Weights are cached for the entire weekly epoch
9. **Publish** – `weights.publish()` checks version requirements and calls
   `subtensor.set_weights()` with the UID vector, values, and version
   - **Cooldown Check**: Skips if not enough blocks have passed since last update (unless `force=True`)
   - **Bittensor Epoch**: Publishes cached weights every Bittensor epoch (tempo blocks) throughout the week

### Daily Expiry Checks

During a weekly epoch, the validator performs **daily expiry checks**:
- Checks if 24 hours have passed since last check
- Re-fetches verified miners to get updated `expires_at` values
- Filters out expired pools and recalculates weights
- Updates cached weights with filtered results
- Forces weight publication (bypasses cooldown)

### Continuous Daemon Mode

When running continuously (default):
- **Polling**: Checks for new epochs every `--poll-interval` seconds (default: 300s = 5 minutes)
- **Metagraph Syncing**: Syncs metagraph every 100 blocks to stay current
- **Bittensor Epoch Publishing**: Publishes cached weights every Bittensor epoch (tempo blocks)
- **Startup Behavior**: On startup, always fetches and publishes weights (bypasses cooldown with `force=True`)

If `--dry-run` is provided, the vector is printed instead of being published. All log output is routed
through `bittensor.logging` and can be expanded with the standard `--logging.debug` flag (enabled by default).

## Operational Flags

| Flag | Effect |
| --- | --- |
| `--dry-run` | Skip `set_weights` and emit the ranking as JSON. |
| `--use-verified-amounts` | Bypass on-chain replay and trust the verifier's `amount` field. **⚠️ FORBIDDEN on mainnet** (netuid 35, network "finney"). Useful for testnet/local testing. |
| `--epoch` | Provide an explicit epoch version (defaults to the current Friday 00:00 UTC). |
| `--timeout` | Adjust HTTP timeout for verifier calls (default: 15.0 seconds). |
| `--run-once` | Run once and exit (default: run continuously as daemon). |
| `--poll-interval` | Polling interval in seconds when running continuously (default: 300 = 5 minutes). |
| `--log-dir` | Directory to save epoch weight logs (default: `validator_logs`). |
| `--logging.debug` | Enable debug logging (enabled by default, use `--logging.debug=False` to disable). |

## External Dependencies

- **Cartha Verifier API** – Single source of truth for the verified miner set and their last
  known liquidity. Provides epoch-frozen snapshots and `expires_at` timestamps for pool expiry filtering.
- **EVM Vaults** – Event replay source for production runs (Model‑1 semantics used for scoring).
  Required on mainnet; optional on testnet with `--use-verified-amounts`.
- **Bittensor Subtensor** – Target for `set_weights` submissions, also used to resolve hotkeys ⇢ UIDs,
  query metagraph state, and check cooldown periods.

## Logging & Metrics

Key instrumentation surfaced via logs (with ANSI colors and emojis):

- **Epoch Information**: Weekly epoch version, epoch fallback events, daily expiry check status
- **Replay Metrics**: Per-miner replay timings (`avgReplayMs`), global `avgReplay_ms` metric
- **RPC Metrics**: RPC lag (difference between current head and snapshot block), connection status
- **Processing Metrics**: Skipped/failure counts (missing UID, replay failure, missing metadata, expired pools)
- **Publishing Metrics**: Weight publication status, cooldown checks, version key used
- **Metagraph Sync**: Block numbers, tempo (Bittensor epoch length), network status
- **Final Summary**: Miner counts, scored/skipped/failures, expired pools, dry-run flag, version key

### Log Output

- **Console**: Rich ANSI-colored output with emojis for better visibility
- **Log Files**: Detailed JSON logs saved to `validator_logs/` with full ranking and metrics
- **Debug Mode**: Enabled by default; shows full rankings, detailed scoring, and per-miner metrics

This information makes the validator suitable for continuous daemon operation or cron-based scheduling without
additional instrumentation.

## Security Features

- **Validator Whitelist**: Only whitelisted validators can query verified miners. Non-whitelisted validators are rejected with a clear error message.
- **Registration Check**: Validates hotkey is registered before running
- **Version Control**: Validators must meet the minimum version requirement set on-chain (`weight_versions` hyperparameter)
- **Expired Pool Filtering**: Automatically excludes pools with `expires_at` in the past
- **Epoch Freezing**: Uses verifier's epoch-frozen snapshots to prevent manipulation
- **Verifier-Based Validation**: The verifier handles all on-chain validation and RPC queries, ensuring consistent and secure verification
