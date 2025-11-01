# Cartha Subnet Validator – Architecture Overview

The validator is a lightweight cron-style worker. Each epoch it talks to the Cartha verifier,
reconstructs up-to-date liquidity per miner, scores the set, and pushes weights to Bittensor.

```
┌───────────┐      ┌────────────────┐      ┌──────────────┐
│  Verifier │ ---> │ Validator Main │ ---> │  Subtensor    │
│ (FastAPI) │      │ (this project) │      │ set_weights() │
└───────────┘      └────────────────┘      └──────────────┘
          ▲                 │
          │                 ▼
    EVM vaults        Lock replay / scoring
```

## Major Modules

| Module | Responsibility |
| --- | --- |
| `cartha_validator/main.py` | CLI entrypoint, verifier fetch, UID resolution, replay orchestration, publishing. |
| `cartha_validator/indexer.py` | Event helpers for Model‑1 vault semantics (lock created/updated/released). |
| `cartha_validator/scoring.py` | Liquidity scoring and boost curve (`1 - exp(-raw/temperature)`). |
| `cartha_validator/weights.py` | Normalises scores, derives a `version_key`, and wraps `set_weights`. |
| `cartha_validator/config.py` | Typed settings (verifier URL, RPCs, pool weights, max lock days, epoch schedule). |

## Epoch Flow

1. **Fetch snapshot** – `GET /v1/verified-miners?epoch=<version>` from the verifier. This list is
   frozen at Friday 00:00 UTC and contains `(hotkey, slot_uid, chain_id, vault, pool_id, amount, …)`.
2. **Resolve UIDs** – For each hotkey the validator asks the local subtensor for its UID on netuid 35.
3. **Replay liquidity** – By default, the validator replays vault events using `indexer.replay_owner`.
   For development, the `--use-verified-amounts` flag skips the RPC and uses the verifier’s stored
   `amount`.
4. **Score miners** – Pools are aggregated per UID. The boost formula is
   ```
   raw = poolWeight * amount * min(lockDays, maxLockDays) / maxLockDays
   score = 1 - exp(-raw / score_temperature)    # score_temperature defaults to 1000
   ```
5. **Normalise weights** – `weight = score / Σ(score)`; weights sum to 1.
6. **Publish** – `weights.publish()` queries the current `WeightsVersionKey`, then calls
   `subtensor.set_weights()` with the UID vector, values, and version.

If `--dry-run` is provided the vector is printed instead of being published. All log output is routed
through `bittensor.logging` and can be expanded with the standard `--logging.debug` flag.

## Operational Flags

| Flag | Effect |
| --- | --- |
| `--dry-run` | Skip `set_weights` and emit the ranking as JSON. |
| `--use-verified-amounts` | Bypass on-chain replay and trust the verifier’s `amount` field. Useful for local testing. |
| `--epoch` | Provide an explicit epoch version (defaults to the current Friday 00:00 UTC). |
| `--timeout` | Adjust HTTP timeout for verifier calls. |

## External Dependencies

- **Cartha Verifier API** – Single source of truth for the verified miner set and their last
  known liquidity.
- **EVM Vaults** – Event replay source for production runs (Model‑1 semantics used for scoring).
- **Bittensor Subtensor** – Target for `set_weights` submissions, also used to resolve hotkeys ⇢ UIDs.

## Logging & Metrics

Key instrumentation surfaced via logs:

- Replay timings (`avgReplayMs` per miner, global `avgReplay_ms` metric).
- RPC lag (difference between current head and snapshot block).
- Skipped/failure counts (missing UID, replay failure, missing metadata).
- Final summary with miner counts, dry-run flag, and version key.

This information makes the validator suitable for cron or supervisor-based scheduling without
additional instrumentation.
