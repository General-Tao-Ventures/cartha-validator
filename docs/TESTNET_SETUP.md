# Cartha Validator - Testnet Setup Guide

This guide will help you set up and run a Cartha validator on the public testnet.

## Prerequisites

- Python 3.11
- [`uv`](https://github.com/astral-sh/uv) package manager (or `pip`)
- Bittensor wallet with registered validator hotkey
- Access to the testnet verifier URL
- **Validator Whitelist**: Your validator hotkey must be whitelisted by the subnet owner

### Installing `uv`

If you don't have `uv` installed, you can install it with:

**macOS/Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
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
```

## Running the Validator

### Dry Run Mode (Recommended for Testing)

Run the validator without publishing weights:

```bash
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --dry-run \
  --use-verified-amounts
```

This will:

- Fetch verified miners from the verifier
- Score miners using verifier-supplied amounts (no RPC replay)
- Print the computed weights without publishing
- Show detailed debug logs (enabled by default) including:
  - Per-miner scoring details
  - Replay timing and RPC lag (if using full replay)
  - Full ranking with all miners
  - Position aggregation by pool
- Help you verify the scoring logic

**Note**: Debug logging is enabled by default. To reduce verbosity, add `--logging.debug=False`.

### Full Replay Mode

For full on-chain replay (requires RPC endpoints):

```bash
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --dry-run
```

**⚠️ Important**: In testnet demo mode, RPC endpoints are **not available**. You **must** use the `--use-verified-amounts` flag for testnet. Without this flag, the validator will attempt to connect to RPC endpoints (default: `localhost:8545`) and fail with connection errors.

### Production Mode (Publish Weights)

Once you're confident, publish weights to the subnet:

```bash
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --use-verified-amounts
```

**Warning**: This will publish weights to the testnet. Only do this if you're confident in your validator setup.

## Validator Workflow

### Step 1: Fetch Verified Miners

The validator fetches the verified miner list from the verifier:

```bash
# Manual check
curl "${CARTHA_VERIFIER_URL}/v1/verified-miners?epoch=$(date -u +%Y-%m-%dT00:00:00Z)"
```

### Step 2: Score Miners

For each verified miner, the validator:

1. (Optional) Replays on-chain events to get current positions (or uses verifier-supplied amounts with `--use-verified-amounts`)
2. Filters out expired pools (pools with `expires_at` in the past)
3. Calculates scores based on:
   - Locked amount
   - Lock duration (lockDays)
   - Pool weights
   - Temperature curve
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
- `--dry-run`: Skip `set_weights`, print computed vector
- `--logging.debug`: Enable debug logging (enabled by default, use `--logging.debug=False` to disable)

### Configuration File

Edit `cartha_validator/config.py` to customize:

- Validator whitelist (list of allowed validator hotkey SS58 addresses)
- Pool weights
- Max lock days
- Score temperature
- Epoch schedule

**Note**: The verifier handles all on-chain validation and RPC queries. Validators do not need to configure RPC endpoints.

## Testnet-Specific Notes

### Validator Whitelist

**Important**: Only whitelisted validators can query verified miners. If your validator is not whitelisted, you will see an error message directing you to contact the subnet owner.

To configure the whitelist, edit `cartha_validator/config.py`:

```python
DEFAULT_SETTINGS = ValidatorSettings(
    validator_whitelist=[
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",  # Example hotkey
        # Add more whitelisted hotkeys here
    ],
    pool_weights={"default": 1.0},
    max_lock_days=365,
)
```

**Note**: An empty whitelist (`[]`) means all validators are allowed. This is useful for testing but should be configured properly for production.

### Recommended Testnet Configuration

```python
# In config.py or via environment
validator_whitelist = [
    "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",  # Your validator hotkey
]
pool_weights = {"default": 1.0}
max_lock_days = 365
score_temperature = 1000.0
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

- **Debug** (default): Detailed information including replay timing, RPC lag, full rankings, per-miner scoring
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
  --dry-run

# Disable debug logging (show only info and above)
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <wallet> \
  --wallet-hotkey <hotkey> \
  --logging.debug=False \
  --dry-run

# Explicitly enable debug (redundant since it's default, but shown for clarity)
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <wallet> \
  --wallet-hotkey <hotkey> \
  --logging.debug \
  --dry-run
```

**What Debug Logging Shows:**

- Per-miner replay timing and RPC lag
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

### "Validator rejected" or "not whitelisted"

**Problem**: Validator hotkey is not in the whitelist

**Solution**:

- Contact the subnet owner to add your validator hotkey to the whitelist
- The error message will show your hotkey address - provide this to the subnet owner
- Once whitelisted, update `cartha_validator/config.py` with the whitelist (or leave empty `[]` if subnet owner manages it server-side)
- Restart the validator after whitelist is updated

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
- Ensure `--dry-run` is not set if you want to publish
- Check wallet has sufficient TAO for transactions

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

### Step 1: Dry Run

```bash
uv run python -m cartha_validator.main \
  --verifier-url "${CARTHA_VERIFIER_URL}" \
  --netuid 78 \
  --subtensor.network test \
  --wallet-name <your-wallet-name> \
  --wallet-hotkey <your-hotkey-name> \
  --dry-run \
  --use-verified-amounts
```

Expected output:

- List of verified miners
- Computed scores
- Normalized weights vector
- No `set_weights` call

### Step 2: Verify Scoring Logic

Check the output JSON files:

```bash
cat validator_logs/weights_*.json | jq .
```

Verify:

- Scores are in [0, 1] range
- Weights sum to 1.0
- Miners are ranked correctly
- Expired pools are filtered out (check `summary.expired_pools` in log file)
- Epoch version matches expected weekly epoch

### Step 3: Test with Real Data

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
  --dry-run \
  --use-verified-amounts
```

### Step 4: Publish (When Ready)

```bash
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
