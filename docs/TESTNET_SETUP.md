# Cartha Validator - Testnet Setup Guide

This guide will help you set up and run a Cartha validator on the public testnet.

## Prerequisites

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) package manager (or `pip`)
- Bittensor wallet with registered validator hotkey
- Access to the testnet verifier URL

**Note**: On testnet, all validators are allowed - no whitelist is required. Whitelist restrictions only apply to mainnet.

### Installing `uv`

If you don't have `uv` installed, you can install it with:

**macOS/Linux:**

```bash
curl -LsSf https://astral.sh/uv/run.sh | sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Or via pip:**

```bash
pip install uv
```

After installation, restart your terminal or run `source ~/.bashrc` (or `source ~/.zshrc` on macOS).

## Installation

### Option 1: Using `uv` (Recommended)

`uv` automatically manages virtual environments - no need to create one manually! It will create a `.venv` directory in the project and handle all dependency isolation.

```bash
cd cartha-subnet-validator
uv sync  # Creates .venv automatically and installs dependencies
```

Then use `uv run` to execute commands (it automatically uses the project's virtual environment):

```bash
uv run python -m cartha_validator.main --help  # Runs in the project's virtual environment
```

### Option 2: Using `pip`

```bash
cd cartha-subnet-validator
pip install -e .
```

## Testnet Configuration

### Environment Variables

Set the following environment variables:

```bash
# Required: Testnet verifier URL
export CARTHA_VERIFIER_URL="https://cartha-verifier-826542474079.us-central1.run.app"

# Required: Bittensor network configuration
export CARTHA_NETWORK="test"  # Use "test" for testnet
export CARTHA_NETUID=78       # Testnet subnet UID

# Optional: Leaderboard API (defaults to production URL if not set)
export LEADERBOARD_API_URL="https://cartha-leaderboard-api-826542474079.us-central1.run.app"

# Optional: Validator-specific settings
export VALIDATOR_LOG_DIR="validator_logs"
export VALIDATOR_POLL_INTERVAL=300  # Seconds between runs
```

### Verify Configuration

```bash
# Test verifier connection
curl "${CARTHA_VERIFIER_URL}/health"

# Test verified miners endpoint
curl "${CARTHA_VERIFIER_URL}/v1/verified-miners"

# Test leaderboard API connection (if configured)
if [ -n "${LEADERBOARD_API_URL}" ]; then
  curl "${LEADERBOARD_API_URL}/health"
fi
```

## Running the Validator

Run your validator to start scoring miners and publishing weights:

```bash
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --use-verified-amounts
```

This will:

- Fetch verified miners from the verifier
- Score miners using verifier-supplied amounts
- Calculate normalized weights based on miner scores
- Publish weights to the Bittensor subnet
- Show detailed debug logs (enabled by default) including:
  - Per-miner scoring details
  - Full ranking with all miners
  - Position aggregation by pool

**Note**: Debug logging is enabled by default. Use `--logging.debug=False` to reduce verbosity.

**⚠️ Important**: You **must** use the `--use-verified-amounts` flag. This tells the validator to use verified miner data from the verifier instead of querying RPC endpoints directly.

## Validator Workflow

### Step 1: Fetch Verified Miners

The validator fetches the verified miner list from the verifier:

```bash
# Manual check
curl "${CARTHA_VERIFIER_URL}/v1/verified-miners?epoch=$(date -u +%Y-%m-%dT00:00:00Z)"
```

### Step 2: Score Miners

For each verified miner, the validator:

1. Fetches miner data from the verifier
2. Filters out expired pools (pools with `expires_at` in the past)
3. Calculates scores based on:
   - Locked amount
   - Lock duration (lockDays)
   - Pool weights
   - Expired pool filtering

### Step 3: Cache & Publish Weights

- Normalized weights are computed once per weekly epoch
- Weights are cached for the entire week
- Cached weights are published to Bittensor via `set_weights()` every Bittensor epoch (tempo blocks)
- Daily expiry checks update cached weights when pools expire

## Configuration Options

### Command Line Arguments

```bash
uv run python -m cartha_validator.main --help
```

Key options:

- `--verifier-url`: Verifier endpoint URL (required)
- `--netuid`: Subnet UID (default: 35, use 78 for testnet)
- `--subtensor.network`: Bittensor network (use `test` for testnet, `finney` for mainnet)
- `--wallet-name`: Coldkey wallet name (required)
- `--wallet-hotkey`: Hotkey name (required)
- `--epoch`: Override epoch version (defaults to current Friday 00:00 UTC)
- `--timeout`: HTTP timeout for verifier calls (default: 15s)
- `--logging.debug`: Enable debug logging (enabled by default, use `--logging.debug=False` to disable)

### Configuration File

Edit `cartha_validator/config.py` to customize:

- Pool weights
- Max lock days
- Epoch schedule

**Note**: 
- The verifier handles all on-chain validation and provides verified miner data. Validators only query the verifier and score miners - no RPC endpoints needed.
- Validator whitelist is managed by the verifier, not configured locally in the validator.

## Testnet-Specific Notes

### Validator Whitelist

**Testnet**: On testnet, all validators are allowed to query verified miners - no whitelist is required. You can proceed directly to running your validator.

**Mainnet**: On mainnet, validators must be whitelisted by the subnet owner. The whitelist is managed by the verifier, not configured locally in the validator. Contact the subnet owner to get your validator hotkey added to the verifier's whitelist for mainnet.

### Recommended Testnet Configuration

```python
# In config.py or via environment
pool_weights = {"default": 1.0}
max_lock_days = 365
```

### Epoch Schedule

- **Weekly Epoch Start**: Friday 00:00 UTC
- **Weekly Epoch End**: Thursday 23:59 UTC (7 days total)
- **Epoch Version**: ISO8601 format (`YYYY-MM-DDT00:00:00Z`)
- **Weight Calculation**: Once per week at epoch start
- **Weight Publishing**: Every Bittensor epoch (tempo blocks) throughout the week
- **Daily Expiry Checks**: Performed daily during the week to filter expired pools
- Validators should run continuously to catch epoch boundaries and perform daily checks

## Monitoring

### Logging

The validator uses Bittensor's logging system and **debug logging is enabled by default** for detailed diagnostics.

**Logging Levels:**

- **Debug** (default): Detailed information including full rankings, per-miner scoring, and position aggregation
- **Info**: General progress and important events
- **Warning**: Non-critical issues
- **Error**: Critical errors

**Controlling Logging:**

```bash
# Debug logging enabled by default (shows all details)
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <wallet> \
  --wallet-hotkey <hotkey> \
  --use-verified-amounts

# Disable debug logging (show only info and above)
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <wallet> \
  --wallet-hotkey <hotkey> \
  --logging.debug=False \
  --use-verified-amounts

# Explicitly enable debug (redundant since it's default, but shown for clarity)
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <wallet> \
  --wallet-hotkey <hotkey> \
  --logging.debug \
  --use-verified-amounts
```

**What Debug Logging Shows:**

- Full ranking details (all miners, not just top 5)
- Detailed scoring calculations per pool
- Position aggregation by pool
- Epoch detection and processing steps (weekly epoch boundaries)
- Daily expiry check status and expired pool filtering
- Metagraph sync information (block numbers, tempo)
- Weight caching and publishing status
- Epoch fallback events (when verifier returns last frozen epoch)

### Logs

Validator logs are written to:

- Console output (via `bittensor.logging`)
- Log files in `validator_logs/` (if configured)

### Check Validator Status

```bash
# View recent logs
tail -f validator_logs/weights_*.json

# Check last run
ls -lt validator_logs/ | head -5

# View latest log file content
cat $(ls -t validator_logs/weights_*.json | head -1) | jq .

# Check for expired pools in latest run
cat $(ls -t validator_logs/weights_*.json | head -1) | jq '.summary.expired_pools'
```

### Health Checks

```bash
# Verifier health
curl "${CARTHA_VERIFIER_URL}/health"

# Verified miners count
curl "${CARTHA_VERIFIER_URL}/v1/verified-miners" | jq 'length'
```

## Troubleshooting

### "Cannot fetch verified miners"

**Problem**: Validator can't connect to verifier

**Solution**:

```bash
# Verify verifier URL
echo $CARTHA_VERIFIER_URL

# Test connectivity
curl "${CARTHA_VERIFIER_URL}/health"
curl "${CARTHA_VERIFIER_URL}/v1/verified-miners"

# Check network/firewall
ping $(echo "${CARTHA_VERIFIER_URL}" | sed 's|https\?://||' | cut -d/ -f1)
```

### "Validator rejected" or "not whitelisted" (Mainnet Only)

**Problem**: On mainnet, validator hotkey is not in the whitelist

**Solution**:

- **Testnet**: This error should not occur on testnet as all validators are allowed
- **Mainnet**: Contact the subnet owner to add your validator hotkey to the verifier's whitelist
- The error message will show your hotkey address - provide this to the subnet owner
- The whitelist is managed by the verifier, not configured locally in the validator

### "No verified miners found"

**Problem**: Verifier returns empty list

**Solution**:

- Check if miners have submitted lock proofs
- Verify epoch version matches current epoch
- Check verifier logs for issues

### "set_weights failed"

**Problem**: Can't publish weights to subnet

**Solution**:

- Verify wallet is registered as validator
- Check Bittensor network connectivity
- Check wallet has sufficient TAO for transactions
- Verify you're using the correct network (`test`) and netuid (`78`)

### "Scoring errors"

**Problem**: Errors during scoring calculation

**Solution**:

- Check validator logs for details
- Verify miner data format from verifier
- Ensure pool weights are configured correctly
- Check for division by zero or invalid values
- Verify expired pool filtering is working correctly

### "Epoch fallback detected"

**Problem**: Validator logs show epoch fallback event

**Solution**:

- This is **normal behavior** - the verifier returns the last frozen epoch if the requested epoch isn't frozen yet
- Validator automatically uses the frozen epoch data for consistency
- No action needed; validator will process the correct epoch when it becomes available

### "No cached weights available"

**Problem**: Validator logs show "No cached weights available"

**Solution**:

- This can happen on startup before first weekly epoch is processed
- Validator will fetch and compute weights on next weekly epoch boundary
- Ensure validator is running continuously to catch epoch boundaries

## Testing Your Validator

### Step 1: Verify Scoring Logic

Run your validator and check the output JSON files:

```bash
# Run validator
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --use-verified-amounts

# Check output logs
cat validator_logs/weights_*.json | jq .
```

Verify:

- Scores are in [0, 1] range
- Weights sum to 1.0
- Miners are ranked correctly
- Expired pools are filtered out (check `summary.expired_pools` in log file)
- Epoch version matches expected weekly epoch
- Weights are published to the subnet

### Step 2: Test with Real Data

Once miners have submitted proofs:

```bash
# Check verified miners
curl "${CARTHA_VERIFIER_URL}/v1/verified-miners" | jq 'length'

# Run validator
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --use-verified-amounts
```

## Automation

### Continuous Daemon Mode (Recommended)

Run validator continuously to catch weekly epoch boundaries and perform daily expiry checks:

```bash
# Run as daemon (default behavior)
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --use-verified-amounts \
  --poll-interval 300
```

The validator will:
- Detect weekly epoch boundaries (Friday 00:00 UTC)
- Compute and cache weights once per week
- Publish cached weights every Bittensor epoch (tempo blocks)
- Perform daily expiry checks during the week
- Sync metagraph every 100 blocks

### Cron Job (Alternative)

Run validator on a schedule (e.g., after epoch freeze):

```bash
# Add to crontab
0 1 * * 5  # Friday 01:00 UTC (after epoch freeze)
cd /path/to/cartha-subnet-validator && \
  uv run python -m cartha_validator.main \
    --verifier-url "${CARTHA_VERIFIER_URL}" \
    --netuid 78 \
    --subtensor.network test \
    --wallet-name <your-wallet-name> \
    --wallet-hotkey <your-hotkey-name> \
    --use-verified-amounts \
    --run-once
```

**Note**: Using cron with `--run-once` means weights are only published once per week. For continuous operation with Bittensor epoch publishing, use daemon mode instead.

### Systemd Service

Create a systemd service for continuous operation:

```ini
[Unit]
Description=Cartha Validator
After=network.target

[Service]
Type=simple
User=validator
WorkingDirectory=/path/to/cartha-subnet-validator
Environment="CARTHA_VERIFIER_URL=https://cartha-verifier-826542474079.us-central1.run.app"
ExecStart=/path/to/uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --use-verified-amounts
Restart=always

[Install]
WantedBy=multi-user.target
```

## Understanding Weekly Epochs

The validator operates on a **weekly epoch cycle**:

- **Epoch Start**: Friday 00:00 UTC
- **Epoch End**: Thursday 23:59 UTC (7 days)
- **Weight Calculation**: Once per week at epoch start
- **Weight Publishing**: Every Bittensor epoch (tempo blocks) throughout the week
- **Daily Checks**: Validator checks for expired pools daily during the week

This means:
- Weights are computed once per week and cached
- The same weights are published every Bittensor epoch during the week
- Expired pools are filtered out daily, updating cached weights
- New weekly epochs trigger a fresh weight calculation

## Next Steps

- Review the [Validator README](../README.md) for advanced configuration
- Check [Architecture Docs](../docs/ARCHITECTURE.md) for scoring details and weekly epoch system
- Review [Command Reference](../docs/COMMANDS.md) for all available options
- Monitor validator performance and adjust scoring parameters
- Check log files in `validator_logs/` for detailed metrics
- Provide feedback via [GitHub Issues](../../.github/ISSUE_TEMPLATE/)

## Additional Resources

- [Validator README](../README.md) - Full validator documentation
- [Testnet Guide](../../TESTNET_GUIDE.md) - Overall testnet overview
- [Scoring Logic](../cartha_validator/scoring.py) - Scoring implementation
- [Weights Publishing](../cartha_validator/weights.py) - Weight calculation
