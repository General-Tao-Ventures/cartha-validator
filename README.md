# Cartha Subnet Validator

Validator reference implementation for Cartha SN35. It consumes the verifier’s epoch-frozen miner
list, reconstructs each hotkey’s vault positions, scores liquidity, and publishes weights back to
Bittensor.

## Requirements

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) for dependency + task management
- Access to a Cartha verifier instance (local or remote)
- Optional: access to the relevant EVM RPCs if you want full on-chain replay

## Install & Test

```bash
uv sync              # install dependencies into .venv
make test            # ruff lint + mypy + pytest
```

## Repository Layout

```text
cartha_validator/    validator CLI, config, indexer, scoring and weight publisher
abis/                vault ABI used during event replay
tests/               unit tests covering replay, scoring, publishing
docs/                architecture and operator notes
```

## Running Against a Local Verifier

1. **Launch the verifier**
   ```bash
   cd ../cartha-verifier
   cp ops/.env.example .env                 # adjust for SQLite or Postgres
   uv sync
   uv run python -m uvicorn cartha_verifier.app:APP --host 127.0.0.1 --port 8000
   ```
   Seed mock data if you want a local dry-run (e.g. using the snippet in `scripts/mock_scenarios.py`).

2. **Dry-run the validator (no on-chain replay)**
   ```bash
   cd ../cartha-subnet-validator
   source .venv/bin/activate
   uv run python -m cartha_validator.main \
     --verifier-url http://127.0.0.1:8000 \
     --netuid 35 \
     --dry-run \
     --use-verified-amounts
   ```
   The command fetches the frozen miner list, derives scores using verifier-supplied amounts, and
   prints the ranked vector instead of publishing it to the chain.

3. **Full replay + publish (production)**
   Configure the required RPC endpoints in `config.py` (or env) and drop the
   `--use-verified-amounts` flag. Omit `--dry-run` to submit weights via `set_weights`.

## Validator CLI Reference

`uv run python -m cartha_validator.main [options]`

| Flag | Description |
| --- | --- |
| `--verifier-url` | Base URL for the Cartha verifier (default from `config.py`). |
| `--netuid` | Subnet UID to publish weights against. |
| `--epoch` | Override epoch version (defaults to current Friday 00:00 UTC). |
| `--timeout` | HTTP timeout (s) for verifier calls, default 15. |
| `--dry-run` | Skip `set_weights`; pretty-print the computed vector. |
| `--use-verified-amounts` | Development helper: bypass EVM replay and use the verifier’s `amount` field directly. |

All logging goes through `bittensor.logging`. Run with `--logging.debug` (Bittensor CLI flag) to see
per-miner diagnostics (replay timing, RPC lag, scoring contributions, etc.).

## Scoring & Weights

- For each hotkey, positions are grouped by pool (`pool_id`).
- Liquidity is converted from raw USDC (6 decimals) into tokens and multiplied by the Model‑1
  lock boost:  
  `raw = poolWeight * amount * min(lockDays, maxLockDays) / maxLockDays`
- Raw totals run through the temperature curve (default 1000) to keep scores in `[0, 1]`:
  `score = 1 - exp(-raw / temperature)`
- Normalised weights are `score / sum(score)` and are submitted via `set_weights` with the current
  `WeightsVersionKey`.

## Testing & Tooling

- `make test` → ruff, mypy, pytest
- `uv run pytest -s tests/test_scoring.py::test_multi_wallet_ranking_outputs_json` → prints the
  ranked JSON for inspection
- Logging from both verifier and validator is human-readable and suitable for terminal dashboards.

## Mining Note

SN35 miners do **not** run a node from this repository. They register via `cartha-cli`, lock USDC,
and submit a single LockProof to the verifier. Validators (this project) replay the vault events
or consume the verifier snapshot to set weights. Refer miners to [`cartha-cli`](../cartha-cli) for
onboarding instructions.

## Related Repositories

- [`cartha-verifier`](../cartha-verifier) – API the validator consumes.
- [`cartha-cli`](../cartha-cli) – Miner tooling that produces LockProofs.
