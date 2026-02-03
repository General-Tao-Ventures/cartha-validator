"""Epoch running logic for the validator."""

from __future__ import annotations

import json
import textwrap
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import bittensor as bt
import httpx

from .config import ValidatorSettings
from .indexer import replay_owner
from .logging import (
    ANSI_BOLD,
    ANSI_BRIGHT_CYAN,
    ANSI_BRIGHT_GREEN,
    ANSI_CYAN,
    ANSI_DIM,
    ANSI_GREEN,
    ANSI_MAGENTA,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
    EMOJI_BLOCK,
    EMOJI_CHART,
    EMOJI_INFO,
    EMOJI_ROCKET,
    EMOJI_SUCCESS,
    EMOJI_TROPHY,
    EMOJI_WARNING,
)
from .pool_weights import get_pool_weights_for_scoring
from .processor import PublishFn, ReplayFn, format_positions, process_entries
from .weights import publish
from .leaderboard_client import send_ranking_to_leaderboard

# Re-export types for convenience
__all__ = ["run_epoch"]


def _format_http_error(exc: httpx.HTTPStatusError) -> str:
    """Format HTTP error response for better readability.
    
    Args:
        exc: HTTPStatusError exception
        
    Returns:
        Formatted error message string
    """
    try:
        response_json = exc.response.json()
        # If response is a simple dict with "detail" key, return just the detail
        if isinstance(response_json, dict) and len(response_json) == 1 and "detail" in response_json:
            if isinstance(response_json["detail"], str):
                return textwrap.indent(response_json["detail"], "  ")
        # Otherwise, return formatted JSON
        return textwrap.indent(json.dumps(response_json, indent=2), "  ")
    except Exception:
        # Response is not JSON, return text (truncated)
        response_text = exc.response.text[:500] if exc.response.text else 'No response body'
        return textwrap.indent(response_text, "  ")


def run_epoch(
    verifier_url: str,
    epoch_version: str,
    settings: ValidatorSettings,
    *,
    timeout: float | None = None,
    dry_run: bool = False,
    replay_fn: ReplayFn = replay_owner,
    publish_fn: PublishFn = publish,
    use_verified_amounts: bool = False,
    subtensor: Any | None = None,
    wallet: Any | None = None,
    metagraph: Any | None = None,
    validator_uid: int | None = None,
    args: Any | None = None,
    force: bool = False,
    hotkey_ss58: str | None = None,
) -> dict[str, Any]:
    """Run a single epoch: fetch entries, process, score, and publish weights.

    Args:
        verifier_url: Base URL of the verifier service
        epoch_version: Epoch version identifier (ISO8601 format)
        settings: Validator settings
        timeout: HTTP timeout for verifier requests (defaults to settings.timeout if None)
        dry_run: If True, don't publish weights
        replay_fn: Function to replay on-chain events
        publish_fn: Function to publish weights
        use_verified_amounts: Use verifier amounts (default: True). Set to False to use on-chain replay instead.
        subtensor: Bittensor subtensor instance (created if None)
        wallet: Bittensor wallet instance (created if None)
        metagraph: Bittensor metagraph instance (optional)
        validator_uid: Validator UID (optional)
        args: Command-line arguments (for log_dir)
        force: If True, bypass cooldown check and always attempt to set weights (e.g., on startup)
        hotkey_ss58: Hotkey SS58 address (optional, derived from wallet if not provided)

    Returns:
        Dictionary with scores, weights, ranking, and summary
    """
    # Use settings.timeout if timeout not provided
    if timeout is None:
        timeout = settings.timeout
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_ROCKET} Starting validator run{ANSI_RESET} "
        f"for epoch {ANSI_BOLD}{ANSI_MAGENTA}{epoch_version}{ANSI_RESET} "
        f"{ANSI_DIM}(dry_run={dry_run}){ANSI_RESET}"
    )

    # Get validator hotkey for server-side whitelist check
    # Use provided hotkey_ss58 if available, otherwise derive from wallet
    if hotkey_ss58:
        validator_hotkey = hotkey_ss58
    elif wallet is not None:
        validator_hotkey = wallet.hotkey.ss58_address
    else:
        # Create default wallet as fallback
        wallet = bt.wallet()
        validator_hotkey = wallet.hotkey.ss58_address
    
    # Detect if we're on testnet (for demo mode detection)
    is_testnet = False
    if subtensor is not None and hasattr(subtensor, "network"):
        is_testnet = subtensor.network == "test"
    elif metagraph is not None and hasattr(metagraph, "netuid"):
        is_testnet = metagraph.netuid == settings.testnet_netuid
    
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}[VALIDATOR]{ANSI_RESET} "
        f"Validator hotkey: {ANSI_BOLD}{validator_hotkey}{ANSI_RESET}"
    )
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}[WHITELIST CHECK]{ANSI_RESET} "
        f"Checking validator whitelist status with verifier..."
    )

    try:
        with httpx.Client(base_url=verifier_url, timeout=timeout) as client:
            # Build query parameters - always include validator_hotkey for server-side whitelist check
            # Also include network/netuid for testnet detection on verifier side
            params = {
                "epoch": epoch_version,
                "validator_hotkey": validator_hotkey,
            }
            # Add network/netuid if available (for testnet/mainnet detection)
            if metagraph is not None and hasattr(metagraph, "netuid"):
                params["netuid"] = metagraph.netuid
            if subtensor is not None and hasattr(subtensor, "network"):
                params["network"] = subtensor.network
            
            bt.logging.debug(
                f"{ANSI_DIM}Fetching verified miners from {verifier_url}/v1/verified-miners?epoch={epoch_version}&validator_hotkey={validator_hotkey}{ANSI_RESET}"
            )
            bt.logging.debug(
                f"{ANSI_DIM}Request params: {params}{ANSI_RESET}"
            )
            response = client.get("/v1/verified-miners", params=params)
            response.raise_for_status()
            entries = response.json()
            
            # Check for warning headers from verifier (if any)
            warning_header = response.headers.get("X-Verifier-Warning")
            if warning_header:
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}[VERIFIER WARNING]{ANSI_RESET} {warning_header}"
                )
                # If on testnet and we got a warning, it likely means whitelist is empty
                if is_testnet:
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_CYAN}[WHITELIST CHECK]{ANSI_RESET} "
                        f"{ANSI_DIM}Testnet mode: Whitelist is empty, allowing all validators. "
                        f"If this was mainnet, your validator would have been rejected.{ANSI_RESET}"
                    )
            else:
                # Success without warning - validator is whitelisted (or whitelist is empty on mainnet)
                if is_testnet:
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_GREEN}[WHITELIST CHECK]{ANSI_RESET} "
                        f"Validator whitelist check passed (testnet mode)"
                    )
                else:
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_GREEN}[WHITELIST CHECK]{ANSI_RESET} "
                        f"Validator whitelist check passed - hotkey is whitelisted"
                    )
            
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_GREEN}[VERIFIER REQUEST]{ANSI_RESET} "
                f"Successfully fetched {len(entries)} verified miner entries"
            )
            
            # Fetch deregistered hotkeys list for the epoch
            deregistered_hotkeys: set[str] = set()
            try:
                dereg_response = client.get("/v1/deregistered-hotkeys", params={"epoch_version": epoch_version})
                dereg_response.raise_for_status()
                dereg_data = dereg_response.json()
                deregistered_hotkeys = set(dereg_data.get("hotkeys", []))
                if deregistered_hotkeys:
                    bt.logging.warning(
                        f"{ANSI_BOLD}{ANSI_YELLOW}[DEREGISTERED HOTKEYS]{ANSI_RESET} "
                        f"Found {len(deregistered_hotkeys)} deregistered hotkeys - all positions will be scored 0"
                    )
                else:
                    bt.logging.debug(
                        f"{ANSI_DIM}No deregistered hotkeys found for epoch {epoch_version}{ANSI_RESET}"
                    )
            except httpx.HTTPStatusError as exc:
                # Non-fatal: log warning but continue
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}[DEREGISTERED HOTKEYS]{ANSI_RESET} "
                    f"Failed to fetch deregistered hotkeys: HTTP {exc.response.status_code}. "
                    f"Continuing without hotkey-level deregistration checks."
                )
            except Exception as exc:
                # Non-fatal: log warning but continue
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}[DEREGISTERED HOTKEYS]{ANSI_RESET} "
                    f"Failed to fetch deregistered hotkeys: {exc}. "
                    f"Continuing without hotkey-level deregistration checks."
                )
    except httpx.HTTPStatusError as exc:
        # Format HTTP error for better readability
        error_detail = _format_http_error(exc)
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}[VERIFIER HTTP ERROR]{ANSI_RESET} "
            f"HTTP {exc.response.status_code} {exc.response.reason_phrase} during GET {exc.request.url}"
        )
        if error_detail:
            bt.logging.error(f"Response:\n{ANSI_DIM}{error_detail}{ANSI_RESET}")
        if exc.response.status_code == 403:
            bt.logging.error(
                f"{ANSI_BOLD}{ANSI_RED}🚨 VALIDATOR REJECTED BY VERIFIER:{ANSI_RESET}\n"
                f"  The verifier has rejected your request. This usually means your hotkey is not whitelisted.\n"
                f"  {ANSI_BOLD}Your hotkey:{ANSI_RESET} {validator_hotkey}\n"
            )
            if is_testnet:
                bt.logging.error(
                    f"  {ANSI_BOLD}{ANSI_YELLOW}Note:{ANSI_RESET} You are on testnet, but the verifier rejected you.\n"
                    f"  This suggests the whitelist is configured and your hotkey is not in it.\n"
                    f"  {ANSI_BOLD}Action Required:{ANSI_RESET} Contact the subnet owner to add your hotkey to the validator whitelist.\n"
                )
            else:
                bt.logging.error(
                    f"  {ANSI_BOLD}Action Required:{ANSI_RESET} Contact the subnet owner to add your hotkey to the validator whitelist.\n"
                )
            bt.logging.error(f"  {ANSI_DIM}Response: {error_detail}{ANSI_RESET}")
        raise RuntimeError(
            f"Verifier HTTP error {exc.response.status_code}: {error_detail[:200]}"
        ) from exc
    except httpx.RequestError as exc:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}[VERIFIER REQUEST ERROR]{ANSI_RESET} "
            f"Failed to connect to verifier: {exc}"
        )
        bt.logging.error(f"URL: {verifier_url}/v1/verified-miners")
        bt.logging.error(f"Error type: {type(exc).__name__}")
        raise RuntimeError(f"Failed to connect to verifier at {verifier_url}: {exc}") from exc
    except Exception as exc:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}[VERIFIER ERROR]{ANSI_RESET} "
            f"Unexpected error fetching verified miners: {exc}"
        )
        bt.logging.error(f"Error type: {type(exc).__name__}")
        bt.logging.error(f"URL: {verifier_url}/v1/verified-miners?epoch={epoch_version}")
        import traceback
        bt.logging.error(f"Traceback:\n{traceback.format_exc()}")
        raise

    # Confirm epoch version: verify all entries match the requested epoch
    # Note: Verifier may return a different epoch (last frozen) if current epoch is not frozen yet
    # This is expected behavior and ensures validators only use frozen epoch data
    actual_epoch_version = None
    if entries:
        # Check if all entries have the same epoch_version
        epoch_versions = {
            entry.get("epoch_version")
            for entry in entries
            if entry.get("epoch_version")
        }
        if len(epoch_versions) == 1:
            actual_epoch_version = epoch_versions.pop()
        elif len(epoch_versions) > 1:
            # Multiple different epochs - this is unexpected
            bt.logging.warning(
                f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} Multiple epoch versions in response:{ANSI_RESET} "
                f"{epoch_versions}. {ANSI_DIM}This may indicate a verifier issue.{ANSI_RESET}"
            )
            # Use the most common epoch version
            epoch_counts = Counter(
                entry.get("epoch_version")
                for entry in entries
                if entry.get("epoch_version")
            )
            actual_epoch_version = epoch_counts.most_common(1)[0][0]

        if actual_epoch_version and actual_epoch_version != epoch_version:
            # Verifier returned a different epoch (likely last frozen epoch fallback)
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_INFO} Epoch fallback:{ANSI_RESET} "
                f"Requested {epoch_version} (not frozen yet), "
                f"verifier returned {actual_epoch_version} (last frozen epoch). "
                f"{ANSI_DIM}Using frozen epoch data for consistency.{ANSI_RESET}"
            )
            # Update epoch_version to match what was actually returned
            epoch_version = actual_epoch_version
        elif actual_epoch_version == epoch_version:
            bt.logging.debug(
                f"{ANSI_DIM}Epoch version confirmed: all {len(entries)} entries match {epoch_version}{ANSI_RESET}"
            )
        else:
            # No entries or no epoch_version in entries
            bt.logging.debug(
                f"{ANSI_DIM}No entries returned for epoch {epoch_version}{ANSI_RESET}"
            )

    if subtensor is None:
        subtensor = bt.subtensor()
    if wallet is None:
        wallet = bt.wallet()

    # Query pool weights from parent vault contract before scoring
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}[POOL WEIGHTS]{ANSI_RESET} "
        f"Querying pool weights from parent vault contract..."
    )
    queried_weights = get_pool_weights_for_scoring(
        parent_vault_address=settings.parent_vault_address,
        rpc_url=settings.parent_vault_rpc_url,
        timeout=timeout,
        fallback_weights=settings.pool_weights,
    )
    
    # Update settings with queried weights (create a copy to avoid mutating original)
    if queried_weights:
        # Create a new settings object with updated pool_weights
        settings_dict = settings.model_dump()
        settings_dict["pool_weights"] = queried_weights
        settings = ValidatorSettings(**settings_dict)
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_GREEN}[POOL WEIGHTS]{ANSI_RESET} "
            f"Updated pool weights from chain: {len(queried_weights)} pools"
        )
    else:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}[POOL WEIGHTS]{ANSI_RESET} "
            f"No weights queried, using fallback/default weights"
        )

    result = process_entries(
        entries,
        settings,
        epoch_version,
        dry_run=dry_run,
        replay_fn=replay_fn,
        publish_fn=publish_fn,
        subtensor=subtensor,
        wallet=wallet,
        metagraph=metagraph,
        validator_uid=validator_uid,
        use_verified_amounts=use_verified_amounts,
        deregistered_hotkeys=deregistered_hotkeys,
        force=force,
    )

    # Include the actual epoch version used (may differ from requested if fallback occurred)
    result["epoch_version"] = epoch_version

    summary = result["summary"]
    expired_pools = summary.get("expired_pools", 0)
    bt.logging.info(
        f"Epoch {epoch_version} summary: rows={summary['total_rows']} miners={summary['total_miners']} "
        f"scored={summary['scored']} skipped={summary['skipped']} failures={summary['failures']} "
        f"missingUid={summary['missing_uid']} inferredBlocks={summary['inferred_blocks']} "
        f"expiredPools={expired_pools} avgReplay={summary['avg_replay_ms']:.2f}ms maxLag={summary['max_rpc_lag']} dryRun={dry_run}"
    )

    # Save detailed ranking to log file
    log_dir_str = (
        getattr(args, "log_dir", settings.log_dir) if args else settings.log_dir
    )
    log_dir = Path(log_dir_str)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log_file = (
        log_dir
        / f"weights_{epoch_version.replace(':', '-').replace('T', '_').replace('Z', '')}_{timestamp}.json"
    )

    # Calculate emissions per day for each miner (weight * daily total emissions)
    daily_emissions = settings.daily_alpha_emissions
    
    ranking_payload = [
        {
            "uid": item["uid"],
            "hotkey": item["hotkey"],
            "slot_uid": str(item.get("slot_uid") or item["uid"]),  # Convert to string for API
            "score": round(item["score"], 6),  # Raw score (for weight calculation)
            "display_score": item.get("display_score", round(item["score"], 2)),  # Normalized 0-1000 for display
            "weight": round(item["weight"], 6),
            "emissions_per_day": round(item["weight"] * daily_emissions, 6),  # Alpha emissions per day
            "positions": format_positions(item["positions"], result["unit"]),
        }
        for item in result["ranking"]
    ]
    
    # Add trader rewards pool to ranking if it received weight but isn't in ranking
    # (happens when trader pool has no verified positions/score=0)
    trader_pool_hotkey = settings.trader_rewards_pool_hotkey
    trader_pool_weight = settings.trader_rewards_pool_weight
    
    if trader_pool_hotkey and trader_pool_weight > 0:
        # Check if trader pool is already in ranking
        trader_in_ranking = any(
            item.get("hotkey") == trader_pool_hotkey for item in ranking_payload
        )
        
        if not trader_in_ranking and result.get("weights"):
            # Try to find trader pool UID in weights
            try:
                trader_pool_uid = subtensor.get_uid_for_hotkey_on_subnet(
                    hotkey_ss58=trader_pool_hotkey,
                    netuid=settings.netuid
                )
                
                if trader_pool_uid is not None and trader_pool_uid in result["weights"]:
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_MAGENTA}[{settings.trader_rewards_pool_name}]{ANSI_RESET} "
                        f"Adding to leaderboard ranking (UID {trader_pool_uid}, weight={trader_pool_weight:.6f})"
                    )
                    trader_weight = result["weights"][trader_pool_uid]
                    ranking_payload.append({
                        "uid": trader_pool_uid,
                        "hotkey": trader_pool_hotkey,
                        "slot_uid": str(trader_pool_uid),  # Convert to string for API
                        "score": 0.0,
                        "display_score": 0.0,
                        "weight": round(trader_weight, 6),
                        "emissions_per_day": round(trader_weight * daily_emissions, 6),
                        "positions": {},
                    })
            except Exception as e:
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}[TRADER POOL]{ANSI_RESET} "
                    f"Failed to add to leaderboard ranking: {e}"
                )

    log_entry = {
        "epoch_version": epoch_version,
        "timestamp": datetime.now(UTC).isoformat(),
        "dry_run": dry_run,
        "summary": summary,
        "ranking": ranking_payload,
    }

    log_file.write_text(json.dumps(log_entry, indent=2))
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_BLOCK} Weight vector saved{ANSI_RESET} "
        f"to {ANSI_DIM}{log_file}{ANSI_RESET}"
    )

    if dry_run:
        # In dry-run, also print a summary to console
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_BRIGHT_CYAN}{EMOJI_CHART} Dry-run summary:{ANSI_RESET} "
            f"{ANSI_BOLD}{summary['scored']}{ANSI_RESET} miners scored, weights computed "
            f"{ANSI_DIM}(see log file for details){ANSI_RESET}"
        )
        # Print only top 5 at info level, full list at debug level
        for i, item in enumerate(result["ranking"][:5], 1):
            medal = EMOJI_TROPHY if i == 1 else f"#{i}"
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_CYAN}{medal}{ANSI_RESET} "
                f"UID={ANSI_BOLD}{item['uid']}{ANSI_RESET} "
                f"score={ANSI_GREEN}{item['score']:.6f}{ANSI_RESET} "
                f"weight={ANSI_BRIGHT_GREEN}{item['weight']:.6f}{ANSI_RESET}"
            )
        bt.logging.debug(f"Full ranking:\n{json.dumps(ranking_payload, indent=2)}")
    else:
        # In production mode, log summary with top miners
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Published weights{ANSI_RESET} "
            f"for {ANSI_BOLD}{summary['scored']}{ANSI_RESET} miners "
            f"{ANSI_DIM}(epoch {epoch_version}){ANSI_RESET}\n"
            f"{ANSI_DIM}Full details saved to {log_file}{ANSI_RESET}"
        )
        # Show top 5 miners at info level, full list at debug level
        for i, item in enumerate(result["ranking"][:5], 1):
            medal = (
                f"{EMOJI_TROPHY} " if i == 1 else f"{ANSI_BRIGHT_CYAN}#{i}{ANSI_RESET} "
            )
            bt.logging.info(
                f"{medal}UID={ANSI_BOLD}{item['uid']}{ANSI_RESET} "
                f"score={ANSI_GREEN}{item['score']:.6f}{ANSI_RESET} "
                f"weight={ANSI_BRIGHT_GREEN}{item['weight']:.6f}{ANSI_RESET}"
            )
        if len(result["ranking"]) > 5:
            bt.logging.debug(f"Full ranking:\n{json.dumps(ranking_payload, indent=2)}")
        
        # Send ranking to leaderboard API (only if not dry-run and weights published successfully)
        if not dry_run and settings.leaderboard_api_url:
            try:
                send_ranking_to_leaderboard(
                    leaderboard_url=settings.leaderboard_api_url,
                    validator_hotkey=validator_hotkey,
                    epoch_version=epoch_version,
                    ranking_data=ranking_payload,
                )
            except Exception as e:
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}[LEADERBOARD]{ANSI_RESET} "
                    f"Failed to send ranking to leaderboard: {e}"
                )

    return result

