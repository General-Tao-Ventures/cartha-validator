"""Configuration helpers for validator loop."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from datetime import time
from pathlib import Path

import bittensor as bt
from pydantic import BaseModel, Field, HttpUrl

from .epoch import epoch_start

DEFAULT_VERIFIER_URL = "https://cartha-verifier-826542474079.us-central1.run.app"

# Default leaderboard API URL
DEFAULT_LEADERBOARD_API_URL = "https://cartha-leaderboard-api-826542474079.us-central1.run.app"

# Default parent vault address (Base Sepolia testnet)
# In the future, this can be a list of multiple parent vaults
DEFAULT_PARENT_VAULT_ADDRESS = "0x0dB1218cbCFf1D49181cc810a2b0D54D44652A8d"

# Default public Base Sepolia RPC endpoint
DEFAULT_BASE_SEPOLIA_RPC_URL = "https://sepolia.base.org"


def load_env_file() -> None:
    """Load environment variables from .env file if it exists."""
    env_file = Path(".env")
    if env_file.exists():
        with env_file.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    # Remove quotes if present
                    value = value.strip('"').strip("'")
                    # Only set if not already in environment
                    if key not in os.environ:
                        os.environ[key] = value


class ValidatorSettings(BaseModel):
    """Typed configuration for validator components."""

    netuid: int = 35
    verifier_url: HttpUrl | str = DEFAULT_VERIFIER_URL
    rpc_urls: Mapping[int, str] = Field(default_factory=dict)
    pool_weights: Mapping[str, float] = Field(default_factory=dict)
    parent_vault_address: str = Field(
        default=DEFAULT_PARENT_VAULT_ADDRESS,
        description="Parent vault contract address for querying pool weights",
    )
    parent_vault_rpc_url: str = Field(
        default=DEFAULT_BASE_SEPOLIA_RPC_URL,
        description="RPC URL for querying parent vault contract",
    )
    max_lock_days: int = 365
    token_decimals: int = 6
    epoch_weekday: int = 4  # Friday
    epoch_time: time = time(hour=0, minute=0)
    epoch_timezone: str = "UTC"
    validator_whitelist: list[str] = Field(
        default_factory=list,
        description="List of validator hotkey SS58 addresses allowed to query verified miners. Empty list means all validators are allowed.",
    )
    # Timing and sync configuration
    metagraph_sync_interval: int = Field(
        default=100,
        description="Sync metagraph every N blocks (default: 100 blocks, ~20 minutes)",
    )
    default_tempo: int = Field(
        default=360,
        description="Default Bittensor epoch length (tempo) in blocks if not available from metagraph (default: 360 blocks)",
    )
    epoch_length_blocks: int = Field(
        default=360,
        description="Fallback epoch length in blocks for cooldown checks (default: 360 blocks)",
    )
    # Network configuration
    testnet_netuid: int = Field(
        default=78,
        description="NetUID for testnet subnet (default: 78)",
    )
    # HTTP and polling configuration
    timeout: float = Field(
        default=15.0,
        description="HTTP timeout when calling the verifier in seconds (default: 15.0)",
    )
    set_weights_timeout: float = Field(
        default=90.0,
        description="Timeout for set_weights operation in seconds (default: 90.0)",
    )
    poll_interval: int = Field(
        default=300,
        description="Polling interval in seconds when running continuously (default: 300 = 5 minutes)",
    )
    # Logging configuration
    log_dir: str = Field(
        default="validator_logs",
        description="Directory to save epoch weight logs (default: validator_logs)",
    )
    leaderboard_api_url: str | None = Field(
        default=DEFAULT_LEADERBOARD_API_URL,
        description="Leaderboard API URL for submitting rankings (default: production URL)",
    )


DEFAULT_SETTINGS = ValidatorSettings(
    rpc_urls={31337: "http://localhost:8545"},
    pool_weights={"default": 1.0},
    max_lock_days=365,
    metagraph_sync_interval=100,
    default_tempo=360,
    epoch_length_blocks=360,
    testnet_netuid=78,
    timeout=15.0,
    set_weights_timeout=90.0,
    poll_interval=300,
    log_dir="validator_logs",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the validator.

    Returns:
        Parsed arguments namespace with config attached
    """
    # Load .env file if it exists
    load_env_file()
    
    parser = argparse.ArgumentParser(description="Cartha subnet validator cron runner")
    parser.add_argument(
        "--verifier-url",
        default=str(DEFAULT_SETTINGS.verifier_url),
        help="Verifier base URL.",
    )
    parser.add_argument(
        "--netuid", type=int, default=DEFAULT_SETTINGS.netuid, help="Subnet netuid."
    )
    parser.add_argument(
        "--wallet-name",
        type=str,
        required=True,
        help="Name of the wallet (coldkey) to use for signing weights.",
    )
    parser.add_argument(
        "--wallet-hotkey",
        type=str,
        required=True,
        help="Name of the hotkey to use for this validator.",
    )
    parser.add_argument(
        "--epoch",
        default=None,
        help="Epoch version identifier (defaults to current Friday 00:00 UTC ISO string).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_SETTINGS.timeout,
        help=f"HTTP timeout when calling the verifier (default: {DEFAULT_SETTINGS.timeout} seconds).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not publish weights; print the computed vector instead.",
    )
    # use_verified_amounts defaults to True - use --no-use-verified-amounts to disable
    parser.add_argument(
        "--no-use-verified-amounts",
        dest="use_verified_amounts",
        action="store_false",
        help="Disable verified amounts mode and use on-chain replay instead (not recommended). Verified amounts mode is enabled by default.",
    )
    # Keep --use-verified-amounts for backward compatibility (does nothing since it's already default)
    parser.add_argument(
        "--use-verified-amounts",
        dest="use_verified_amounts",
        action="store_true",
        help="Use the verifier's verified amount field (default: enabled). This flag is kept for backward compatibility.",
    )
    # Set default value - verified amounts mode is now the default
    parser.set_defaults(use_verified_amounts=True)
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run once and exit (default: run continuously as daemon).",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_SETTINGS.poll_interval,
        help=f"Polling interval in seconds when running continuously (default: {DEFAULT_SETTINGS.poll_interval} = {DEFAULT_SETTINGS.poll_interval // 60} minutes).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=DEFAULT_SETTINGS.log_dir,
        help=f"Directory to save epoch weight logs (default: {DEFAULT_SETTINGS.log_dir}).",
    )
    parser.add_argument(
        "--parent-vault-address",
        type=str,
        default=os.environ.get("PARENT_VAULT_ADDRESS", DEFAULT_PARENT_VAULT_ADDRESS),
        help=f"Parent vault contract address for querying pool weights from chain (default: {DEFAULT_PARENT_VAULT_ADDRESS}). Can also be set via PARENT_VAULT_ADDRESS env var.",
    )
    parser.add_argument(
        "--parent-vault-rpc-url",
        type=str,
        default=os.environ.get("PARENT_VAULT_RPC_URL", DEFAULT_BASE_SEPOLIA_RPC_URL),
        help=f"RPC URL for querying parent vault contract (default: {DEFAULT_BASE_SEPOLIA_RPC_URL}). Can also be set via PARENT_VAULT_RPC_URL env var.",
    )
    parser.add_argument(
        "--leaderboard-api-url",
        type=str,
        default=os.environ.get("LEADERBOARD_API_URL", DEFAULT_LEADERBOARD_API_URL),
        help=f"Leaderboard API URL for submitting rankings (default: {DEFAULT_LEADERBOARD_API_URL}). Can also be set via LEADERBOARD_API_URL env var. Use empty string to disable.",
    )
    # Add bittensor subtensor, wallet, and logging args (like template does)
    bt.subtensor.add_args(parser)
    bt.wallet.add_args(parser)
    bt.logging.add_args(parser)

    # Parse args normally to get both our custom args and bt args
    parsed_args = parser.parse_args()

    # Check if --logging.debug was explicitly set to False in command line
    debug_explicitly_disabled = (
        "--logging.debug=False" in sys.argv or "--no-logging.debug" in sys.argv
    )

    # Create bt.Config object for proper Bittensor integration
    # bt.config() needs a parser with args added, but it will parse sys.argv itself
    # So we create a fresh parser here
    bt_parser = argparse.ArgumentParser()
    bt.subtensor.add_args(bt_parser)
    bt.wallet.add_args(bt_parser)
    bt.logging.add_args(bt_parser)
    config = bt.config(bt_parser)

    # Enable debug logging by default unless explicitly disabled
    if not debug_explicitly_disabled:
        config.logging.debug = True

    # Override wallet name/hotkey from our custom args (--wallet-name/--wallet-hotkey)
    config.wallet.name = parsed_args.wallet_name
    config.wallet.hotkey = parsed_args.wallet_hotkey

    # Override netuid from our args
    config.netuid = parsed_args.netuid

    # Override subtensor network if provided
    if hasattr(parsed_args, "subtensor_network") and parsed_args.subtensor_network:
        config.subtensor.network = parsed_args.subtensor_network

    # Attach config to parsed_args
    parsed_args.config = config

    return parsed_args


def epoch_version(value: str | None) -> str:
    """Get epoch version string.

    Args:
        value: Optional epoch version string

    Returns:
        Epoch version string (ISO8601 format)
    """
    if value:
        return value
    start = epoch_start()
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")
