# Cartha Validator Command Reference

Complete documentation for the Cartha validator command-line interface.

## Usage

```bash
uv run python -m cartha_validator.main [OPTIONS]
```

## Command-Line Arguments

### Wallet Configuration

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--wallet-name` | string | - | Name of the wallet (coldkey) to use for signing weights. Required unless using `--hotkey-ss58` with `--dry-run`. |
| `--wallet-hotkey` | string | `default` | Name of the hotkey to use for this validator. Defaults to "default" if not specified. |
| `--hotkey-ss58` | string | - | Hotkey SS58 address to use directly (e.g., for subnet owners). In dry-run mode, can be used without wallet credentials. In production mode, must match the wallet's hotkey address. |

### Verifier Configuration

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--verifier-url` | string | `https://cartha-verifier-193291340038.us-central1.run.app` | Base URL for the Cartha verifier |
| `--timeout` | float | `15.0` | HTTP timeout (seconds) for verifier calls |

### Leaderboard Configuration

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--leaderboard-api-url` | string | `https://cartha-leaderboard-api-193291340038.us-central1.run.app` | Leaderboard API URL for submitting rankings. Use empty string (`""`) to disable. |

### Network Configuration

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--netuid` | integer | `35` | Subnet UID to publish weights against |
| `--network` | string | `finney` | Bittensor network name (via Bittensor args) |

### Epoch Configuration

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--epoch` | string | Current Friday 00:00 UTC | Epoch version identifier (ISO string format) |

### Execution Mode

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--dry-run` | flag | `False` | Do not publish weights; print the computed vector instead |
| `--use-verified-amounts` | flag | `False` | Skip on-chain replay and use verifier's amount field directly. **⚠️ FORBIDDEN on mainnet** |
| `--run-once` | flag | `False` | Run once and exit (default: run continuously as daemon) |
| `--poll-interval` | integer | `300` | Polling interval in seconds when running continuously (default: 5 minutes) |

### Logging & Output

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--log-dir` | string | `validator_logs` | Directory to save epoch weight logs (default: `validator_logs`) |
| `--logging.debug` | flag | `True` | Enable debug logging (default: enabled, use `--logging.debug=False` to disable) |

### Bittensor Arguments

The validator also accepts standard Bittensor CLI arguments:

- `--subtensor.network` - Bittensor network (default: `finney`)
- `--subtensor.chain_endpoint` - Custom subtensor endpoint
- `--logging.*` - Bittensor logging configuration

See `--help` for complete list of Bittensor arguments.

## Examples

### Dry Run (Testing)

```bash
# See computed weights without publishing
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --dry-run
```

### Production Run (Single Execution)

```bash
# Run once and publish weights
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --run-once
```

### Continuous Daemon Mode

```bash
# Run continuously, checking every 5 minutes
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --poll-interval 300
```

### Testnet Development (Skip On-Chain Replay)

```bash
# Use verifier amounts directly (testnet only!)
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --use-verified-amounts \
  --dry-run
```

**⚠️ Warning:** `--use-verified-amounts` is **FORBIDDEN on mainnet** (netuid 35, network "finney"). The validator will refuse to run with this flag on mainnet to enforce on-chain validation.

### Using Direct Hotkey SS58 Address

For subnet owners or users who want to specify their hotkey by SS58 address instead of wallet file:

```bash
# Dry-run with SS58 address only (no wallet required)
uv run python -m cartha_validator.main \
  --hotkey-ss58 5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty \
  --netuid 35 \
  --dry-run

# Production with SS58 + wallet (validates they match)
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --hotkey-ss58 5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty \
  --netuid 35
```

**Note:** In production mode, the `--hotkey-ss58` address must match the wallet's hotkey address. This is useful for validation and for subnet owners who want to explicitly specify their hotkey.

### Custom Verifier URL

```bash
# Use a different verifier instance
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --verifier-url http://localhost:8000
```

### Custom Leaderboard API URL

```bash
# Use a different leaderboard API instance
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --leaderboard-api-url http://localhost:8001

# Disable leaderboard submissions
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --leaderboard-api-url ""
```

### Custom Epoch

```bash
# Process a specific epoch
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --epoch 2024-01-05T00:00:00Z
```

### Debug Logging

```bash
# Enable verbose debug output
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --logging.debug
```

## Configuration File

The validator uses `cartha_validator/config.py` for default settings. You can override these via environment variables or command-line arguments.

### Default Settings

```python
netuid: 35
verifier_url: "https://cartha-verifier-193291340038.us-central1.run.app"
leaderboard_api_url: "https://cartha-leaderboard-api-193291340038.us-central1.run.app"
max_lock_days: 365
token_decimals: 6
epoch_weekday: 4  # Friday
epoch_time: 00:00 UTC
```

## Environment Variables

You can set these environment variables to configure the validator:

| Variable | Description | Default |
| --- | --- | --- |
| `CARTHA_VERIFIER_URL` | Verifier endpoint URL | `https://cartha-verifier-193291340038.us-central1.run.app` |
| `LEADERBOARD_API_URL` | Leaderboard API endpoint URL | `https://cartha-leaderboard-api-193291340038.us-central1.run.app` |
| `CARTHA_NETUID` | Subnet netuid | `35` |

## Common Workflows

### First-Time Setup

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Test with dry-run:**
   ```bash
   uv run python -m cartha_validator.main \
     --wallet-name cold \
     --wallet-hotkey hot \
     --netuid 35 \
     --dry-run
   ```

3. **Verify output** - Check that weights are computed correctly

4. **Run in production:**
   ```bash
   uv run python -m cartha_validator.main \
     --wallet-name cold \
     --wallet-hotkey hot \
     --netuid 35 \
     --run-once
   ```

### Continuous Operation

For production deployments, run the validator as a daemon:

```bash
# Run continuously (default behavior)
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --poll-interval 300
```

The validator will:
- Check for new weekly epochs every 5 minutes (or your configured interval)
- Process weekly epochs automatically when they become available (Friday 00:00 UTC)
- Perform daily expiry checks during the week to filter expired pools
- Cache computed weights for the entire week
- Publish cached weights every Bittensor epoch (tempo blocks) throughout the week
- Sync metagraph every 100 blocks to stay current
- Log all operations to `validator_logs/` with detailed JSON logs

### Systemd Service

Create a systemd service file for automatic startup:

```ini
[Unit]
Description=Cartha Validator
After=network.target

[Service]
Type=simple
User=validator
WorkingDirectory=/path/to/cartha-validator
Environment="CARTHA_VERIFIER_URL=https://cartha-verifier-193291340038.us-central1.run.app"
ExecStart=/path/to/venv/bin/python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Troubleshooting

### Verifier Connection Errors

- Check `--verifier-url` is correct
- Verify network connectivity: `curl $CARTHA_VERIFIER_URL/health`
- Check firewall rules if using local verifier

### RPC Connection Errors

- Ensure RPC endpoints are configured in `config.py` or via environment
- Verify RPC endpoints are accessible
- Check RPC rate limits

### Weight Publishing Failures

- Verify wallet has sufficient balance for transaction fees
- Check Bittensor network connectivity
- Ensure hotkey is registered on the subnet

### Epoch Detection Issues

- Verify system clock is synchronized (NTP)
- Check timezone settings (epochs are UTC-based)
- Weekly epochs start Friday 00:00 UTC → Thursday 23:59 UTC
- Use `--epoch` to manually specify epoch if needed
- Validator performs daily expiry checks during the week

### Debugging

Enable debug logging to see detailed information:

```bash
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --logging.debug \
  --dry-run
```

This will show:
- Per-miner replay timing and RPC lag
- Full ranking details (all miners, not just top 5)
- Detailed scoring calculations per pool
- Weight normalization steps
- Epoch detection and fallback events
- Daily expiry check status
- Metagraph sync information
- Expired pool filtering

## Output Format

### Dry-Run Output

When using `--dry-run`, the validator prints a ranked JSON structure:

```json
{
  "epoch": "2024-01-05T00:00:00Z",
  "weights": {
    "1": 0.15,
    "2": 0.12,
    "3": 0.10,
    ...
  },
  "scores": {
    "1": 0.85,
    "2": 0.72,
    "3": 0.60,
    ...
  }
}
```

### Log Files

Weight logs are saved to `validator_logs/` with filenames like:
```
weights_2024-01-05T00-00-00Z_20240105_120000.json
```

Each log file contains:
- Epoch version and timestamp
- Dry-run flag
- Summary metrics (total rows, miners, scored, skipped, failures, expired pools, replay timing, RPC lag)
- Complete ranking with UID, hotkey, slot_uid, score, weight, and position details

### Continuous Operation Details

When running in daemon mode (default, without `--run-once`):

- **Weekly Epoch Detection**: Detects new weekly epochs (Friday 00:00 UTC boundary)
- **Weight Caching**: Computes and caches weights once per week
- **Bittensor Epoch Publishing**: Publishes cached weights every Bittensor epoch (tempo blocks)
- **Daily Expiry Checks**: Checks for expired pools daily and updates cached weights
- **Metagraph Syncing**: Syncs metagraph every 100 blocks
- **Startup Behavior**: Always fetches and publishes weights on startup (bypasses cooldown)

### Epoch Fallback Behavior

If the requested epoch isn't frozen yet, the verifier returns the last frozen epoch. The validator:
- Logs the epoch fallback event
- Uses the frozen epoch data for consistency
- Continues processing with the frozen epoch version

---

For more help, see [Feedback & Support](FEEDBACK.md).

