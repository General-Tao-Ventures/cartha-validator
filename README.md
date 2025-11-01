# Cartha Subnet Validator

Reference tooling for Cartha subnet operators. This repository contains the code that validators run
to consume the public verifier APIs, replay vault events, and publish weekly weights on Bittensor.

## Requirements

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) for dependency management

## Getting Started

```bash
# Install workspace dependencies
uv sync

# Lint, type-check, and test
make test
```

## Package Layout

```text
cartha_validator/   # Validator entrypoint, config, indexer, scoring, weight publisher
abis/               # Vault ABI definitions used for log decoding
tests/              # pytest suites for replay helpers
```

## Tooling

- **Logging:** Always use `bittensor.logging.*` in backend code.
- **Linting:** `ruff`
- **Type Checking:** `mypy`
- **Testing:** `pytest`

## Mining SN35 (Cartha) Guidance

Unlike other Bittensor subnets, SN35 miners do **not** run a miner node from this
repository. Instead, miners register on the subnet and use the CLI to prove their locked USDC to
the verifier; validators then replay vault events and assign weights on their behalf during each
epoch. As long as you remain verified, emissions continue without keeping additional software
online.

- Install and use the CLI by following the instructions in the [`cartha-cli`](../cartha-cli) repo.
- The CLI walkthrough in that repository covers registration, proving deposits, and day-to-day
  operations for miners on SN35.

For the validator responsibility side, continue with the modules in this repository.

## Related Repositories

- [`cartha-cli`](../cartha-cli) – Typer CLI for miners.
