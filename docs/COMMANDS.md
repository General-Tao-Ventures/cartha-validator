# Cartha Validator Command Reference

Complete documentation for the Cartha validator command-line interface.

## Usage

```bash
uv run python -m cartha_validator.main [OPTIONS]
```

## Command-Line Arguments

### Required Arguments

| Argument | Type | Description |
| --- | --- | --- |
| `--wallet-name` | string | Name of the wallet (coldkey) to use for signing weights |
| `--wallet-hotkey` | string | Name of the hotkey to use for this validator |

### Verifier Configuration

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `--verifier-url` | string | `https://cartha-verifier-826542474079.us-central1.run.app` | Base URL for the Cartha verifier |
| `--timeout` | float | `15.0` | HTTP timeout (seconds) for verifier calls |

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
| `--log-dir` | string | `validator_logs` | Directory to save epoch weight logs |
| `--logging.debug` | flag | `True` | Enable debug logging (default: enabled) |

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

### Custom Verifier URL

```bash
# Use a different verifier instance
uv run python -m cartha_validator.main \
  --wallet-name cold \
  --wallet-hotkey hot \
  --netuid 35 \
  --verifier-url http://localhost:8000
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
verifier_url: "https://cartha-verifier-826542474079.us-central1.run.app"
max_lock_days: 365
token_decimals: 6
score_temperature: 1000.0
epoch_weekday: 4  # Friday
epoch_time: 00:00 UTC
```

## Environment Variables

You can set these environment variables to configure the validator:

| Variable | Description | Default |
| --- | --- | --- |
| `CARTHA_VERIFIER_URL` | Verifier endpoint URL | `https://cartha-verifier-826542474079.us-central1.run.app` |
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
- Check for new epochs every 5 minutes (or your configured interval)
- Process epochs automatically when they become available
- Publish weights to the Bittensor network
- Log all operations to `validator_logs/`

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
Environment="CARTHA_VERIFIER_URL=https://cartha-verifier-826542474079.us-central1.run.app"
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
- Use `--epoch` to manually specify epoch if needed

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
- Per-miner replay timing
- RPC call details
- Scoring calculations
- Weight normalization steps

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
weights_2024-01-05_00-00-00_20240105_120000.json
```

Each log file contains the complete epoch processing results.

---

For more help, see [Feedback & Support](FEEDBACK.md).

