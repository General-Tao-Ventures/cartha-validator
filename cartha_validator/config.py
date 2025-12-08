"""Configuration helpers for validator loop."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from datetime import time

import bittensor as bt
from pydantic import BaseModel, Field, HttpUrl

from .epoch import epoch_start

DEFAULT_VERIFIER_URL = "https://cartha-verifier-826542474079.us-central1.run.app"


class ValidatorSettings(BaseModel):
    """Typed configuration for validator components."""

    netuid: int = 35
    verifier_url: HttpUrl | str = DEFAULT_VERIFIER_URL
    rpc_urls: Mapping[int, str] = Field(default_factory=dict)
    pool_weights: Mapping[str, float] = Field(default_factory=dict)
    max_lock_days: int = 365
    token_decimals: int = 6
    score_temperature: float = 1000.0
    epoch_weekday: int = 4  # Friday
    epoch_time: time = time(hour=0, minute=0)
    epoch_timezone: str = "UTC"
    validator_whitelist: list[str] = Field(
        default_factory=list,
        description="List of validator hotkey SS58 addresses allowed to query verified miners. Empty list means all validators are allowed.",
    )


DEFAULT_SETTINGS = ValidatorSettings(
    rpc_urls={31337: "http://localhost:8545"},
    pool_weights={"default": 1.0},
    max_lock_days=365,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the validator.

    Returns:
        Parsed arguments namespace with config attached
    """
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
        default=15.0,
        help="HTTP timeout when calling the verifier.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not publish weights; print the computed vector instead.",
    )
    parser.add_argument(
        "--use-verified-amounts",
        action="store_true",
        help="Skip on-chain replay and use the verifier's amount field directly (dev/testing only).",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run once and exit (default: run continuously as daemon).",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,
        help="Polling interval in seconds when running continuously (default: 300 = 5 minutes).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="validator_logs",
        help="Directory to save epoch weight logs (default: validator_logs).",
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
