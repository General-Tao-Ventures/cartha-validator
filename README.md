# Cartha Validator

**The official validator implementation for Cartha subnet (SN35).** Score miners based on their USDC liquidity positions, compute weights, and publish them to the Bittensor network—all with built-in on-chain event replay and robust scoring algorithms.

## Why Cartha Validator?

Cartha Validator provides a complete, production-ready solution for running a validator on the Cartha subnet:

- **📊 Intelligent Scoring** - Score miners based on locked USDC amounts, lock duration, pool weights, and expired pool filtering
- **🔄 Weekly Epoch Management** - Automatic weekly epoch detection (Friday 00:00 UTC) with daily expiry checks
- **🔒 Validator Whitelist** - Only whitelisted validators can query verified miners (contact subnet owner to be added)

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
- **Validator Whitelist**: Your validator hotkey must be whitelisted by the subnet owner

## How It Works

The validator operates on a **weekly epoch cycle** (Friday 00:00 UTC → Thursday 23:59 UTC):

1. **Weekly Epoch Detection** - Detects the current weekly epoch (Friday 00:00 UTC boundary)
2. **Validator Whitelist Check** - Verifies that the validator hotkey is whitelisted (required to query verified miners)
3. **Fetch Verified Miners** - Retrieves the epoch-frozen miner list from the verifier for the current weekly epoch
4. **Daily Expiry Checks** - Performs daily checks during the week to filter out expired pools
5. **Score Liquidity** - Calculates scores based on:
   - Locked USDC amounts (6 decimals)
   - Lock duration (with Model-1 boost)
   - Pool weights (configurable per pool)
   - Temperature curve (default: 1000)
   - Expired pool filtering (pools with `expires_at` in the past are excluded)
6. **Cache & Publish** - Normalizes scores to weights, caches them for the week, and publishes via `set_weights` to Bittensor every Bittensor epoch (tempo blocks)

**Note**: The verifier handles all on-chain validation and RPC queries. Validators do not need to configure RPC endpoints.

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

- **Validator Whitelist** - Only whitelisted validators can query verified miners. Non-whitelisted validators will be rejected with a clear error message directing them to contact the subnet owner.
- **Epoch Freezing** - Uses verifier's epoch-frozen snapshots to prevent manipulation
- **Verifier-Based Validation** - The verifier handles all on-chain validation and RPC queries, ensuring consistent and secure verification
- **Registration Validation** - Checks that the validator hotkey is registered before running
- **Expired Pool Filtering** - Automatically filters out pools that have expired (`expires_at` in the past)
- **Version Control** - Validators must meet the minimum version requirement set on-chain

## Key Features

### Weekly Epoch System
- **Epoch Duration**: Friday 00:00 UTC → Thursday 23:59 UTC (7 days)
- **Weight Calculation**: Computed once per week at epoch start
- **Weight Publishing**: Cached weights are republished every Bittensor epoch (tempo blocks) throughout the week
- **Daily Expiry Checks**: Validator checks for expired pools daily and updates weights accordingly

### Continuous Operation
- **Daemon Mode**: Runs continuously, checking for new epochs every `--poll-interval` seconds (default: 300s = 5 minutes)
- **Metagraph Syncing**: Automatically syncs metagraph every 100 blocks to stay current
- **Bittensor Epoch Integration**: Publishes cached weights every Bittensor epoch (tempo) during the weekly cycle
- **Startup Behavior**: On startup, always fetches and publishes weights (bypasses cooldown)

### Epoch Fallback
- If the requested epoch isn't frozen yet, the verifier returns the last frozen epoch
- Validator automatically uses the frozen epoch data for consistency
- Logs epoch fallback events for transparency

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
