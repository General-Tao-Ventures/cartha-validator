"""Validator cron entrypoint."""

from __future__ import annotations

import time

import bittensor as bt

from .config import DEFAULT_SETTINGS, epoch_version, parse_args
from .epoch import epoch_start
from .epoch_runner import run_epoch
from .logging import (
    ANSI_BOLD,
    ANSI_CYAN,
    ANSI_DIM,
    ANSI_GREEN,
    ANSI_MAGENTA,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
    EMOJI_BLOCK,
    EMOJI_COIN,
    EMOJI_GEAR,
    EMOJI_NETWORK,
    EMOJI_ROCKET,
    EMOJI_SUCCESS,
    EMOJI_WARNING,
)
from .weights import publish


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments (delegates to config.parse_args)."""
    return parse_args()


def _epoch_version(value: str | None) -> str:
    """Get epoch version (delegates to config.epoch_version)."""
    return epoch_version(value)


def main() -> None:
    args = _parse_args()
    config = args.config

    # Set up Bittensor logging FIRST with proper config (like template does)
    # Debug logging is already enabled by default in _parse_args() if not explicitly disabled
    bt.logging.set_config(config=config.logging)

    # Log the full config for reference (like template does)
    bt.logging.info(config)

    bt.logging.info("Setting up bittensor objects.")

    # Initialize wallet using config (ensures proper Bittensor integration)
    wallet = bt.wallet(config=config)
    bt.logging.info(f"Wallet: {wallet}")

    # Initialize subtensor using config
    subtensor = bt.subtensor(config=config)
    bt.logging.info(f"Subtensor: {subtensor}")

    # Create and sync metagraph (like template does)
    metagraph = subtensor.metagraph(args.netuid)
    bt.logging.info(f"Metagraph: {metagraph}")

    # Sync metagraph initially to get latest state
    metagraph.sync(subtensor=subtensor)

    # Check if validator is registered
    hotkey_ss58 = wallet.hotkey.ss58_address
    is_registered = subtensor.is_hotkey_registered_on_subnet(
        hotkey_ss58=hotkey_ss58,
        netuid=args.netuid,
    )

    if not is_registered:
        bt.logging.error(
            f"Wallet: {wallet} is not registered on netuid {args.netuid}. "
            "Please register the hotkey before running the validator."
        )
        raise RuntimeError(
            f"Validator not registered: hotkey {hotkey_ss58} not found on netuid {args.netuid}"
        )

    validator_uid = metagraph.hotkeys.index(hotkey_ss58)

    # Detect network type for security enforcement
    network_name = (
        config.subtensor.network
        if hasattr(config.subtensor, "network")
        else subtensor.network
    )
    is_mainnet = network_name == "finney" or args.netuid == 35

    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_NETWORK} Running validator{ANSI_RESET} "
        f"on subnet: {ANSI_BOLD}{ANSI_CYAN}{args.netuid}{ANSI_RESET} "
        f"with uid {ANSI_BOLD}{ANSI_MAGENTA}{validator_uid}{ANSI_RESET} "
        f"{ANSI_DIM}(network: {subtensor.chain_endpoint}){ANSI_RESET}"
    )

    # SECURITY: Enforce RPC validation on mainnet
    if is_mainnet and args.use_verified_amounts:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}🚨 SECURITY ERROR:{ANSI_RESET}\n"
            f"  {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} is {ANSI_BOLD}FORBIDDEN{ANSI_RESET} on mainnet!\n"
            f"  {ANSI_DIM}On-chain RPC validation is REQUIRED for production security.{ANSI_RESET}\n"
            f"  {ANSI_BOLD}Reason:{ANSI_RESET} Validators must verify locked assets on-chain to prevent fraud.\n"
            f"  {ANSI_BOLD}Action:{ANSI_RESET} Remove {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} and configure RPC endpoints."
        )
        raise RuntimeError(
            "Security violation: --use-verified-amounts cannot be used on mainnet. "
            "RPC validation is required for production security."
        )

    # Warn if RPC endpoints are missing on mainnet
    if is_mainnet and not args.use_verified_amounts:
        settings = DEFAULT_SETTINGS.model_copy(
            update={"verifier_url": args.verifier_url, "netuid": args.netuid},
        )
        if not settings.rpc_urls:
            bt.logging.error(
                f"{ANSI_BOLD}{ANSI_RED}🚨 CONFIGURATION ERROR:{ANSI_RESET}\n"
                f"  No RPC endpoints configured for mainnet validation!\n"
                f"  {ANSI_BOLD}Required:{ANSI_RESET} Configure RPC URLs in {ANSI_BOLD}config.py{ANSI_RESET} or via environment variables.\n"
                f"  {ANSI_DIM}Example:{ANSI_RESET} Set RPC_URLS environment variable or edit DEFAULT_SETTINGS.rpc_urls"
            )
            raise RuntimeError(
                "RPC endpoints must be configured for mainnet. "
                "On-chain validation is required for production security."
            )
        # Check for localhost RPC on mainnet (likely misconfiguration)
        for chain_id, rpc_url in settings.rpc_urls.items():
            if "localhost" in rpc_url or "127.0.0.1" in rpc_url:
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}⚠️  WARNING:{ANSI_RESET}\n"
                    f"  Chain {chain_id} is configured with localhost RPC ({rpc_url}).\n"
                    f"  {ANSI_DIM}This is likely incorrect for mainnet. Verify your RPC configuration.{ANSI_RESET}"
                )

    settings = DEFAULT_SETTINGS.model_copy(
        update={"verifier_url": args.verifier_url, "netuid": args.netuid},
    )

    if args.run_once:
        # Single run mode
        epoch_version = _epoch_version(args.epoch)
        run_epoch(
            verifier_url=args.verifier_url,
            epoch_version=epoch_version,
            settings=settings,
            timeout=args.timeout,
            dry_run=args.dry_run,
            use_verified_amounts=args.use_verified_amounts,
            subtensor=subtensor,
            wallet=wallet,
            metagraph=metagraph,
            validator_uid=validator_uid,
            args=args,
        )
    else:
        # Continuous daemon mode
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_ROCKET} Starting validator daemon{ANSI_RESET} "
            f"{ANSI_DIM}(polling every {args.poll_interval} seconds, use --run-once for single execution){ANSI_RESET}"
        )
        # Track weekly epoch (Friday 00:00 UTC → Thursday 23:59 UTC)
        last_weekly_epoch_version = None
        cached_weights: dict[int, float] | None = None
        cached_scores: dict[int, float] | None = None
        cached_epoch_version: str | None = None

        step = 0
        last_metagraph_sync = 0
        metagraph_sync_interval = 100  # Sync metagraph every 100 blocks
        last_weight_publish_block = 0

        current_block = subtensor.get_current_block()
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_BLOCK} Validator starting{ANSI_RESET} "
            f"at block: {ANSI_BOLD}{current_block}{ANSI_RESET}"
        )

        # Get Bittensor epoch length (tempo) from metagraph
        metagraph.sync(subtensor=subtensor)
        bittensor_epoch_length = getattr(
            metagraph, "tempo", 360
        )  # Default to 360 if not available
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_GEAR} Bittensor epoch length (tempo):{ANSI_RESET} "
            f"{ANSI_BOLD}{bittensor_epoch_length}{ANSI_RESET} blocks"
        )

        while True:
            try:
                current_block = subtensor.get_current_block()

                # Sync metagraph periodically
                if current_block - last_metagraph_sync >= metagraph_sync_interval:
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_NETWORK} resync_metagraph(){ANSI_RESET}"
                    )
                    metagraph.sync(subtensor=subtensor)
                    last_metagraph_sync = current_block
                    # Update tempo in case it changed
                    new_tempo = getattr(metagraph, "tempo", bittensor_epoch_length)
                    if new_tempo != bittensor_epoch_length:
                        bt.logging.info(
                            f"{ANSI_BOLD}{ANSI_YELLOW} Tempo changed:{ANSI_RESET} "
                            f"{bittensor_epoch_length} → {new_tempo}"
                        )
                        bittensor_epoch_length = new_tempo
                    network_name = (
                        config.subtensor.network
                        if hasattr(config.subtensor, "network")
                        else subtensor.network
                    )
                    # Convert block to scalar if it's an array
                    block_val = (
                        int(metagraph.block)
                        if hasattr(metagraph.block, "__iter__")
                        and not isinstance(metagraph.block, str)
                        else metagraph.block
                    )
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Metagraph updated{ANSI_RESET} "
                        f"metagraph(netuid:{ANSI_BOLD}{args.netuid}{ANSI_RESET}, "
                        f"n:{ANSI_BOLD}{metagraph.n}{ANSI_RESET}, "
                        f"block:{ANSI_BOLD}{block_val}{ANSI_RESET}, "
                        f"tempo:{ANSI_BOLD}{bittensor_epoch_length}{ANSI_RESET}, "
                        f"network:{ANSI_BOLD}{network_name}{ANSI_RESET})"
                    )

                # Check current weekly epoch (Friday 00:00 UTC → Thursday 23:59 UTC)
                current_epoch_start = epoch_start()
                current_weekly_epoch_version = current_epoch_start.strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

                # Check if this is a new weekly epoch or a restart - fetch frozen list and calculate weights
                if last_weekly_epoch_version != current_weekly_epoch_version:
                    # This could be:
                    # 1. A new weekly epoch (Friday 00:00 UTC)
                    # 2. A validator restart during an ongoing weekly epoch
                    # In both cases, we need to fetch the frozen list for the current weekly epoch
                    if last_weekly_epoch_version is None:
                        # Validator restart - fetch frozen list for current weekly epoch
                        bt.logging.info(
                            f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_ROCKET} Validator restart detected{ANSI_RESET} "
                            f"during weekly epoch {ANSI_BOLD}{current_weekly_epoch_version}{ANSI_RESET}. "
                            f"{ANSI_DIM}Fetching frozen epoch list...{ANSI_RESET}"
                        )
                    else:
                        # New weekly epoch transition
                        bt.logging.info(
                            f"{ANSI_BOLD}{ANSI_MAGENTA}{EMOJI_COIN} New weekly epoch detected:{ANSI_RESET} "
                            f"{ANSI_BOLD}{current_weekly_epoch_version}{ANSI_RESET} "
                            f"{ANSI_DIM}(previous: {last_weekly_epoch_version}){ANSI_RESET}"
                        )
                    bt.logging.info(
                        f"{ANSI_DIM}step({step}) block({current_block}){ANSI_RESET}"
                    )

                    # Fetch frozen epoch list and calculate weights for this weekly epoch
                    # This will also publish weights once (via run_epoch -> process_entries -> publish)
                    result = run_epoch(
                        verifier_url=args.verifier_url,
                        epoch_version=current_weekly_epoch_version,
                        settings=settings,
                        timeout=args.timeout,
                        dry_run=args.dry_run,
                        use_verified_amounts=args.use_verified_amounts,
                        subtensor=subtensor,
                        wallet=wallet,
                        metagraph=metagraph,
                        validator_uid=validator_uid,
                        args=args,
                    )

                    # Cache the weights and scores for this weekly epoch
                    # These will be reused throughout the week for every Bittensor epoch
                    # Note: epoch_version may have been updated if verifier returned a fallback epoch
                    cached_weights = result.get("weights", {})
                    cached_scores = result.get("scores", {})
                    # Use the actual epoch version returned by verifier (may be different if fallback occurred)
                    cached_epoch_version = result.get(
                        "epoch_version", current_weekly_epoch_version
                    )
                    # Track the weekly epoch we're in (not necessarily the frozen epoch version)
                    last_weekly_epoch_version = current_weekly_epoch_version
                    last_weight_publish_block = current_block
                    step += 1
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Weekly epoch weights calculated and cached{ANSI_RESET} "
                        f"{ANSI_BOLD}{current_weekly_epoch_version}{ANSI_RESET}. "
                        f"{ANSI_DIM}Will publish these weights every Bittensor epoch (~{bittensor_epoch_length} blocks) throughout the week.{ANSI_RESET}"
                    )
                else:
                    # Same weekly epoch - check if we need to publish cached weights for this Bittensor epoch
                    if (
                        cached_weights is not None
                        and cached_scores is not None
                        and cached_epoch_version is not None
                    ):
                        # Check if enough blocks have passed since last weight update (Bittensor epoch)
                        should_publish = False
                        blocks_since_update = 0

                        if metagraph is not None and validator_uid is not None:
                            last_update = (
                                metagraph.last_update[validator_uid]
                                if hasattr(metagraph, "last_update")
                                and validator_uid < len(metagraph.last_update)
                                else 0
                            )
                            blocks_since_update = current_block - last_update

                            # Publish weights if Bittensor epoch has passed (tempo blocks)
                            if blocks_since_update >= bittensor_epoch_length:
                                should_publish = True
                        else:
                            # Fallback: check blocks since last publish
                            blocks_since_last_publish = (
                                current_block - last_weight_publish_block
                            )
                            if blocks_since_last_publish >= bittensor_epoch_length:
                                should_publish = True
                                blocks_since_update = blocks_since_last_publish

                        if should_publish:
                            bt.logging.info(
                                f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_ROCKET} Publishing cached weights{ANSI_RESET} "
                                f"for weekly epoch {ANSI_BOLD}{cached_epoch_version}{ANSI_RESET} "
                                f"{ANSI_DIM}(Bittensor epoch: {blocks_since_update}/{bittensor_epoch_length} blocks){ANSI_RESET}"
                            )

                            # Publish the cached weights (same weights throughout the week)
                            published_weights = publish(
                                cached_scores,
                                epoch_version=cached_epoch_version,
                                settings=settings,
                                subtensor=subtensor,
                                wallet=wallet,
                                metagraph=metagraph,
                                validator_uid=validator_uid,
                            )

                            if published_weights:
                                last_weight_publish_block = current_block
                                bt.logging.info(
                                    f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Cached weights published{ANSI_RESET} "
                                    f"{ANSI_DIM}({len(published_weights)} miners, weekly epoch {cached_epoch_version}){ANSI_RESET}"
                                )
                        else:
                            bt.logging.debug(
                                f"{ANSI_DIM}Waiting for Bittensor epoch: {blocks_since_update}/{bittensor_epoch_length} blocks "
                                f"(weekly epoch: {cached_epoch_version}){ANSI_RESET}"
                            )
                    else:
                        # No cached weights yet - this shouldn't happen but log it
                        bt.logging.warning(
                            f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} No cached weights available{ANSI_RESET} "
                            f"for weekly epoch {current_weekly_epoch_version}. "
                            f"{ANSI_DIM}Will fetch on next check.{ANSI_RESET}"
                        )

                    # Wait before next check
                    bt.logging.debug(
                        f"{ANSI_DIM}Validator running... weekly epoch: {current_weekly_epoch_version}, "
                        f"block: {current_block}{ANSI_RESET}"
                    )
                    time.sleep(args.poll_interval)

            except KeyboardInterrupt:
                bt.logging.info(
                    f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} Validator killed{ANSI_RESET} "
                    f"by keyboard interrupt."
                )
                break
            except Exception as exc:
                import traceback

                bt.logging.error(
                    f"{ANSI_BOLD}{ANSI_RED}[VALIDATOR LOOP ERROR]{ANSI_RESET} "
                    f"Unexpected error in validator main loop"
                )
                bt.logging.error(f"Error type: {type(exc).__name__}")
                bt.logging.error(f"Error message: {str(exc)}")
                bt.logging.error(
                    f"Current block: {current_block if 'current_block' in locals() else 'N/A'}"
                )
                bt.logging.error(
                    f"Weekly epoch: {current_weekly_epoch_version if 'current_weekly_epoch_version' in locals() else 'N/A'}"
                )
                bt.logging.error(
                    f"Cached epoch: {cached_epoch_version if 'cached_epoch_version' in locals() else 'N/A'}"
                )
                bt.logging.error(f"Traceback:\n{traceback.format_exc()}")
                bt.logging.info(f"Retrying in {args.poll_interval} seconds...")
                time.sleep(args.poll_interval)


if __name__ == "__main__":  # pragma: no cover
    main()
