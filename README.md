# Cartha Validator

**The official validator implementation for Cartha subnet (SN35).** Score miners based on their USDC liquidity positions, compute weights, and publish them to the Bittensor network—all with built-in on-chain event replay and robust scoring algorithms.

## Why Cartha Validator?

Cartha Validator provides a complete, production-ready solution for running a validator on the Cartha subnet:

- **📊 Intelligent Scoring** - Score miners based on locked USDC amounts, lock duration, and pool weights
- **⛓️ On-Chain Validation** - Replay vault events from the blockchain to verify positions independently
- **🔄 Epoch Management** - Automatic epoch detection and weight publishing at Friday 00:00 UTC
- **🛡️ Security First** - Enforces on-chain validation on mainnet, preventing shortcuts that could compromise security
- **📈 Production Ready** - Continuous daemon mode with configurable polling intervals and comprehensive logging

## Quick Start

```bash
# Install dependencies
uv sync

# Run a dry-run to see computed weights
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --dry-run

# Run in production mode (publishes weights)
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35
```

## Requirements

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) for dependency management
- Bittensor wallet (coldkey and hotkey)
- Access to Cartha verifier instance
- EVM RPC endpoints for on-chain replay (required for mainnet)

## How It Works

The validator operates on a weekly epoch cycle (Friday 00:00 UTC):

1. **Fetch Verified Miners** - Retrieves the epoch-frozen miner list from the verifier
2. **Replay Positions** - For each miner, replays vault events from the blockchain to reconstruct their USDC positions
3. **Score Liquidity** - Calculates scores based on:
   - Locked USDC amounts (6 decimals)
   - Lock duration (with Model-1 boost)
   - Pool weights (configurable per pool)
   - Temperature curve (default: 1000)
4. **Normalize & Publish** - Normalizes scores to weights and publishes via `set_weights` to Bittensor

## Scoring Algorithm

The validator uses a sophisticated scoring system:

- **Raw Score Calculation:**
  ```
  raw = poolWeight * amount * min(lockDays, maxLockDays) / maxLockDays
  ```

- **Temperature Curve:**
  ```
  score = 1 - exp(-raw / temperature)
  ```

- **Normalized Weights:**
  ```
  weight = score / sum(all_scores)
  ```

This ensures fair distribution of rewards proportional to liquidity contribution while preventing any single miner from dominating.

## Documentation

- **[Command Reference](docs/COMMANDS.md)** - Complete documentation for all command-line arguments
- **[Architecture Guide](docs/ARCHITECTURE.md)** - Deep dive into validator internals and design
- **[Testnet Setup](docs/TESTNET_SETUP.md)** - Step-by-step testnet deployment guide
- **[Feedback & Support](docs/FEEDBACK.md)** - Get help and provide feedback

## Security

Cartha Validator enforces strict security policies:

- **On-Chain Validation Required** - The `--use-verified-amounts` flag is **forbidden on mainnet** (netuid 35, network "finney") to ensure all positions are verified via blockchain replay
- **Epoch Freezing** - Uses verifier's epoch-frozen snapshots to prevent manipulation
- **Independent Verification** - Replays events directly from the blockchain, not relying solely on verifier data

## Development

   ```bash
# Run tests
make test

# Format code
uv run ruff format

# Type check
uv run mypy cartha_validator
```

## Related Repositories

- **[cartha-verifier](../cartha-verifier)** - The API service that provides epoch-frozen miner lists
- **[cartha-cli](../cartha-cli)** - Miner tooling for registration and lock proof submission

---

**Made with ❤ by GTV**
