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

### Software Requirements
- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) for dependency management
- Bittensor wallet (coldkey and hotkey)
- Access to Cartha verifier instance
- **Validator Whitelist**: Your validator hotkey must be whitelisted by the subnet owner

### Minimum Compute Requirements
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Disk**: 20 GB SSD
- **Network**: Stable internet connection with minimal downtime

## How It Works

The validator operates on a **weekly epoch cycle** (Friday 00:00 UTC → Thursday 23:59 UTC):

1. **Weekly Epoch Detection** - Detects the current weekly epoch (Friday 00:00 UTC boundary)
2. **Validator Whitelist Check** - Verifies that the validator hotkey is whitelisted (required to query verified miners)
3. **Fetch Verified Miners** - Retrieves the epoch-frozen miner list from the verifier for the current weekly epoch
4. **Fetch Deregistered Hotkeys** - Retrieves list of deregistered hotkeys from the verifier (all positions scored as 0)
5. **Daily Expiry Checks** - Performs daily checks during the week to filter out expired pools and deregistered hotkeys
6. **Score Liquidity** - Calculates scores based on:
   - Locked USDC amounts (6 decimals)
   - Lock duration (with Model-1 boost)
   - Pool weights (configurable per pool)
   - Expired pool filtering (pools with `expires_at` in the past are excluded)
7. **Cache & Publish** - Normalizes scores to weights, caches them for the week, and publishes via `set_weights` to Bittensor every Bittensor epoch (tempo blocks)
8. **Submit Rankings** - Automatically submits ranking data to the leaderboard API after successfully publishing weights (if leaderboard API is configured)

**Note**: The verifier handles all on-chain validation and RPC queries. Validators do not need to configure RPC endpoints.

## Scoring Algorithm

The validator uses a direct scoring system that preserves competitive differences:

- **Raw Score Calculation:**
  ```
  raw = poolWeight * amount * min(lockDays, maxLockDays) / maxLockDays
  ```

- **Normalized Weights:**
  ```
  weight = raw / sum(all_raw_scores)
  ```

Scores are used directly without exponential normalization, ensuring that differences in liquidity positions translate proportionally to weight distribution.

## Documentation

- **[Command Reference](docs/COMMANDS.md)** - Complete documentation for all command-line arguments
- **[Architecture Guide](docs/ARCHITECTURE.md)** - Deep dive into validator internals and design
- **[Testnet Setup](docs/TESTNET_SETUP.md)** - Step-by-step testnet deployment guide
- **[Version Control](docs/VERSION_CONTROL.md)** - Version management and CI/CD workflows
- **[Feedback & Support](docs/FEEDBACK.md)** - Get help and provide feedback

## Security

Cartha Validator enforces strict security policies:

- **Validator Whitelist** - Only whitelisted validators can query verified miners. Non-whitelisted validators will be rejected with a clear error message directing them to contact the subnet owner.
- **Epoch Freezing** - Uses verifier's epoch-frozen snapshots to prevent manipulation
- **Verifier-Based Validation** - The verifier handles all on-chain validation and RPC queries, ensuring consistent and secure verification
- **Registration Validation** - Checks that the validator hotkey is registered before running
- **Deregistered Hotkey Filtering** - Automatically scores all positions for deregistered hotkeys as 0
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

## Version Control & Auto-Updater

Cartha Validator includes automated version management and update capabilities:

### Version Management

- **Semantic Versioning**: Uses semantic versioning (major.minor.patch) in `pyproject.toml`
- **CI/CD Enforcement**: Version bumps are required when merging from `staging` to `main`
- **Version Utilities**: Helper scripts for version management:
  ```bash
  # Get current version
  python scripts/get_version.py

  # Bump version (major, minor, or patch)
  python scripts/bump_version.py patch
  python scripts/bump_version.py minor
  python scripts/bump_version.py major
  ```

### Auto-Updater System

The validator includes an automated update system that:

- **Checks GitHub Releases**: Automatically checks for new releases on GitHub
- **PM2 Process Management**: Manages validator process via PM2 (survives SSH disconnect)
- **Automatic Updates**: Pulls latest code, installs dependencies, and restarts validator
- **Environment Validation**: Validates `.env` file before restarting
- **Failure Handling**: Keeps validator running on current version if update fails

#### Initial Setup

```bash
# One-time installation
cd cartha-validator
chmod +x scripts/run.sh
./scripts/run.sh
```

This will:
- Install PM2 globally
- Install Python dependencies
- Create PM2 ecosystem configuration
- Set up PM2 to start on system boot
- Start both validator manager and validator processes

#### Managing Validator

```bash
# Check status of both processes
pm2 status

# View validator logs locally
pm2 logs cartha-validator

# View manager logs
pm2 logs cartha-validator-manager

# Manual restart (if needed)
pm2 restart cartha-validator

# Stop both processes
pm2 stop all

# Start both processes
pm2 start ecosystem.config.js
```

**Note**: The validator manager automatically handles updates. You typically only need to interact with PM2 for manual restarts or troubleshooting.

#### Configuration

Configure the auto-updater via `scripts/update_config.yaml`:

```yaml
github_repo: "General-Tao-Ventures/cartha-validator"
check_interval: 3600  # Check every hour
pm2_app_name: "cartha-validator"
```

See `scripts/update_config.yaml` for all configuration options.

### Accessing Logs

**Validators** (local access):
```bash
pm2 logs cartha-validator
pm2 logs cartha-validator --err  # Error logs only
pm2 logs cartha-validator-manager  # Manager logs
```

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
