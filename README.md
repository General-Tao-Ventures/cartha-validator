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

```
packages/
  validator/   # Event replay + scoring logic + weight publisher
  subnet/      # Epoch scheduler utilities shared across validator tooling
  abis/        # Vault ABI definitions used for log decoding
```

Each package provides its own `pyproject.toml` so it can be packaged independently while sharing this
workspace.

## Tooling

- **Logging:** Always use `bittensor.logging.*` in backend code.
- **Linting:** `ruff`
- **Type Checking:** `mypy`
- **Testing:** `pytest`

## Related Repositories

- [`cartha-verifier`](../cartha-verifier) – private FastAPI service we operate.
- [`cartha-cli`](../cartha-cli) – Typer CLI for miners.
