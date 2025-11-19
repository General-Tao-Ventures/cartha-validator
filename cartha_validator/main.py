"""Validator cron entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, List, Mapping

import httpx
from web3 import Web3

import bittensor as bt

from .config import DEFAULT_SETTINGS, ValidatorSettings
from .epoch import epoch_start, epoch_end
from .indexer import replay_owner
from .logging import (
    ANSI_BOLD,
    ANSI_DIM,
    ANSI_GREEN,
    ANSI_YELLOW,
    ANSI_RED,
    ANSI_CYAN,
    ANSI_MAGENTA,
    ANSI_RESET,
    ANSI_BRIGHT_GREEN,
    ANSI_BRIGHT_YELLOW,
    ANSI_BRIGHT_CYAN,
    EMOJI_SUCCESS,
    EMOJI_ERROR,
    EMOJI_WARNING,
    EMOJI_INFO,
    EMOJI_ROCKET,
    EMOJI_CHART,
    EMOJI_TROPHY,
    EMOJI_COIN,
    EMOJI_GEAR,
    EMOJI_STOPWATCH,
    EMOJI_BLOCK,
    EMOJI_NETWORK,
)
from .scoring import score_entry
from .weights import _normalize, publish

ReplayFn = Callable[[int, str, str, int, Web3 | None], Mapping[str, Mapping[str, int]]]
PublishFn = Callable[
    [
        Mapping[int, float],
        str,
        ValidatorSettings,
        Any | None,
        Any | None,
        Any | None,
        int | None,
    ],
    dict[int, float],
]


def _parse_args() -> argparse.Namespace:
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


def _epoch_version(value: str | None) -> str:
    if value:
        return value
    start = epoch_start()
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_owner(entry: Mapping[str, Any]) -> str | None:
    return (
        entry.get("owner")
        or entry.get("evm")
        or entry.get("minerEvmAddress")
        or entry.get("minerEvm")
    )


def _resolve_block(entry: Mapping[str, Any]) -> int | None:
    for key in ("snapshotBlock", "blockNumber", "atBlock"):
        value = entry.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _format_positions(
    positions: Mapping[str, Mapping[str, int]], unit: float
) -> Dict[str, Dict[str, Any]]:
    formatted: Dict[str, Dict[str, Any]] = {}
    for pool_id, data in positions.items():
        amount_raw = int(data.get("amount", 0))
        amount_usdc = amount_raw / unit
        formatted[pool_id] = {
            "amountRaw": amount_raw,
            "amountUSDC": f"{amount_usdc:,.6f} USDC",
            "lockDays": int(data.get("lockDays", 0)),
        }
    return formatted


def process_entries(
    entries: Iterable[Mapping[str, Any]],
    settings: ValidatorSettings,
    epoch_version: str,
    *,
    dry_run: bool = False,
    replay_fn: ReplayFn = replay_owner,
    publish_fn: PublishFn = publish,
    subtensor: Any | None = None,
    wallet: Any | None = None,
    metagraph: Any | None = None,
    validator_uid: int | None = None,
    use_verified_amounts: bool = False,
) -> Dict[str, Any]:
    """Replay events, score miners, and optionally publish weights."""
    start_time = perf_counter()
    scores: Dict[int, float] = {}
    details: List[Dict[str, Any]] = []
    metrics = {
        "total_rows": 0,
        "total_miners": 0,
        "scored": 0,
        "skipped": 0,
        "failures": 0,
        "missing_uid": 0,
        "inferred_blocks": 0,
        "replay_ms": [],
        "rpc_lag_blocks": [],
    }
    unit = float(10**settings.token_decimals)
    web3_cache: Dict[int, Web3] = {}
    subtensor = subtensor or bt.subtensor()

    grouped: Dict[int, Dict[str, Any]] = {}
    sources: Dict[int, List[Mapping[str, Any]]] = {}

    for entry in entries:
        metrics["total_rows"] += 1
        hotkey = entry.get("hotkey")
        if not hotkey:
            bt.logging.warning("Skipping entry missing hotkey: %s", entry)
            metrics["skipped"] += 1
            continue

        try:
            uid = subtensor.get_uid_for_hotkey_on_subnet(hotkey_ss58=hotkey, netuid=settings.netuid)
        except Exception as exc:  # pragma: no cover
            bt.logging.error(f"Failed to resolve UID for hotkey {hotkey}: {exc}")
            metrics["failures"] += 1
            continue

        if uid is None or uid < 0:
            bt.logging.warning(
                "Hotkey %s not registered on netuid %s; skipping.",
                hotkey,
                settings.netuid,
            )
            metrics["missing_uid"] += 1
            metrics["skipped"] += 1
            continue

        uid = int(uid)
        grouped.setdefault(
            uid,
            {
                "hotkey": hotkey,
                "slot_uid": entry.get("slot_uid") or entry.get("slotUID"),
            },
        )
        sources.setdefault(uid, []).append(entry)

    metrics["total_miners"] = len(grouped)

    for uid, miner_entries in sources.items():
        combined_positions: Dict[str, Dict[str, int]] = {}
        per_miner_replay: List[float] = []
        miner_failed = False

        for entry in miner_entries:
            if use_verified_amounts:
                pool_id = entry.get("pool_id") or entry.get("poolId") or "default"
                amount = int(entry.get("amount", 0))
                lock_days = settings.max_lock_days
                existing = combined_positions.setdefault(pool_id, {"amount": 0, "lockDays": 0})
                existing["amount"] += amount
                existing["lockDays"] = max(existing["lockDays"], lock_days)
                continue

            chain_id = entry.get("chainId") or entry.get("chain_id")
            vault = entry.get("vault")
            owner = _resolve_owner(entry)
            if None in (chain_id, vault, owner):
                bt.logging.warning(
                    "Entry for uid=%s missing replay fields (chain=%s vault=%s owner=%s); skipping entry.",
                    uid,
                    chain_id,
                    vault,
                    owner,
                )
                metrics["skipped"] += 1
                miner_failed = True
                continue

            chain_id = int(chain_id)
            try:
                provider = web3_cache.get(chain_id)
                if provider is None:
                    rpc_url = settings.rpc_urls.get(chain_id)
                    if not rpc_url:
                        raise ValueError(f"No RPC configured for chain_id={chain_id}")
                    provider = Web3(Web3.HTTPProvider(rpc_url))
                    web3_cache[chain_id] = provider
            except Exception as exc:
                bt.logging.error(f"Failed to initialise Web3 provider for chain {chain_id}: {exc}")
                # If RPC is not available and we're not using verified amounts, suggest using the flag
                if not use_verified_amounts and "Connection refused" in str(exc):
                    bt.logging.warning(
                        f"{ANSI_BOLD}{ANSI_YELLOW}💡 Tip:{ANSI_RESET} "
                        f"RPC endpoint not available for chain {chain_id}. "
                        f"Use {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} to bypass RPC replay "
                        f"and use verifier-supplied amounts instead."
                    )
                metrics["failures"] += 1
                miner_failed = True
                continue

            at_block = _resolve_block(entry)
            if at_block is None:
                try:
                    at_block = int(provider.eth.block_number)
                    metrics["inferred_blocks"] += 1
                    bt.logging.debug(
                        "No snapshot block for uid=%s chain=%s; defaulting to latest block %s.",
                        uid,
                        chain_id,
                        at_block,
                    )
                except Exception as exc:  # pragma: no cover
                    bt.logging.error(f"Unable to infer block for uid={uid} chain={chain_id}: {exc}")
                    metrics["failures"] += 1
                    miner_failed = True
                    continue

            replay_start = perf_counter()
            try:
                positions = replay_fn(chain_id, vault, owner, int(at_block), web3=provider)
            except Exception as exc:  # pragma: no cover
                bt.logging.error(
                    f"Replay failed for uid={uid} chain={chain_id} owner={owner}: {exc}"
                )
                # If RPC connection failed and we're not using verified amounts, suggest using the flag
                if not use_verified_amounts and "Connection refused" in str(exc):
                    bt.logging.warning(
                        f"{ANSI_BOLD}{ANSI_YELLOW}💡 Tip:{ANSI_RESET} "
                        f"RPC endpoint not available. "
                        f"Use {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} to bypass RPC replay."
                    )
                metrics["failures"] += 1
                miner_failed = True
                continue
            duration_ms = (perf_counter() - replay_start) * 1000
            metrics["replay_ms"].append(duration_ms)
            per_miner_replay.append(duration_ms)

            try:
                current_block = provider.eth.block_number
                metrics["rpc_lag_blocks"].append(max(0, int(current_block) - int(at_block)))
            except Exception:  # pragma: no cover
                bt.logging.debug("Failed to compute RPC lag for chain %s", chain_id)

            for pool_id, data in positions.items():
                existing = combined_positions.setdefault(pool_id, {"amount": 0, "lockDays": 0})
                existing["amount"] += int(data.get("amount", 0))
                existing["lockDays"] = max(existing["lockDays"], int(data.get("lockDays", 0)))

        if not combined_positions:
            if miner_failed:
                bt.logging.warning("Skipping uid=%s after replay failures.", uid)
            continue

        score = score_entry(combined_positions, settings=settings)
        scores[uid] = score
        metrics["scored"] += 1
        grouped_entry = grouped[uid]
        details.append(
            {
                "uid": uid,
                "hotkey": grouped_entry.get("hotkey"),
                "slot_uid": grouped_entry.get("slot_uid"),
                "score": score,
                "positions": combined_positions,
                "sources": miner_entries,
                "avgReplayMs": mean(per_miner_replay) if per_miner_replay else 0.0,
            }
        )

    weights: Dict[int, float]
    if scores:
        if dry_run:
            weights = dict(_normalize(scores))
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_BRIGHT_CYAN}{EMOJI_GEAR} Dry-run mode:{ANSI_RESET} "
                f"computed weights for {ANSI_BOLD}{len(weights)}{ANSI_RESET} miners."
            )
        else:
            weights = dict(
                publish_fn(
                    scores,
                    epoch_version=epoch_version,
                    settings=settings,
                    subtensor=subtensor,
                    wallet=wallet,
                    metagraph=metagraph,
                    validator_uid=validator_uid,
                )
            )
    else:
        weights = {}
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} No scores computed;{ANSI_RESET} "
            f"emitting empty weight vector."
        )

    for item in details:
        item["weight"] = weights.get(item["uid"], 0.0)

    details.sort(key=lambda item: item["score"], reverse=True)

    summary = {
        **metrics,
        "elapsed_ms": (perf_counter() - start_time) * 1000,
        "avg_replay_ms": mean(metrics["replay_ms"]) if metrics["replay_ms"] else 0.0,
        "max_rpc_lag": (max(metrics["rpc_lag_blocks"]) if metrics["rpc_lag_blocks"] else 0),
        "dry_run": dry_run,
    }
    return {
        "scores": scores,
        "weights": weights,
        "ranking": details,
        "summary": summary,
        "unit": unit,
    }


def run_epoch(
    verifier_url: str,
    epoch_version: str,
    settings: ValidatorSettings,
    *,
    timeout: float = 15.0,
    dry_run: bool = False,
    replay_fn: ReplayFn = replay_owner,
    publish_fn: PublishFn = publish,
    use_verified_amounts: bool = False,
    subtensor: Any | None = None,
    wallet: Any | None = None,
    metagraph: Any | None = None,
    validator_uid: int | None = None,
    args: Any | None = None,
) -> Dict[str, Any]:
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_ROCKET} Starting validator run{ANSI_RESET} "
        f"for epoch {ANSI_BOLD}{ANSI_MAGENTA}{epoch_version}{ANSI_RESET} "
        f"{ANSI_DIM}(dry_run={dry_run}){ANSI_RESET}"
    )

    # SECURITY: Detect mainnet and enforce RPC validation (defense in depth)
    is_mainnet = False
    if subtensor is not None:
        network_name = getattr(subtensor, "network", None)
        if network_name == "finney":
            is_mainnet = True
    if metagraph is not None and hasattr(metagraph, "netuid"):
        if metagraph.netuid == 35:
            is_mainnet = True
    if settings.netuid == 35:
        is_mainnet = True

    # SECURITY: Block --use-verified-amounts on mainnet (defense in depth)
    if is_mainnet and use_verified_amounts:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}🚨 SECURITY ERROR:{ANSI_RESET} "
            f"--use-verified-amounts is FORBIDDEN on mainnet!"
        )
        raise RuntimeError(
            "Security violation: --use-verified-amounts cannot be used on mainnet. "
            "RPC validation is required for production security."
        )

    # Check if we're in testnet mode and warn about RPC requirements
    if not use_verified_amounts:
        # Check if RPC URLs are configured for the chains we might encounter
        # Common testnet chain ID is 31337
        testnet_chain_id = 31337
        if testnet_chain_id in settings.rpc_urls:
            rpc_url = settings.rpc_urls[testnet_chain_id]
            # Check if it's localhost (common testnet default that won't work)
            if "localhost" in rpc_url or "127.0.0.1" in rpc_url:
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}⚠️  RPC Configuration Warning:{ANSI_RESET}\n"
                    f"  You're running without {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} "
                    f"and have a localhost RPC configured ({rpc_url}).\n"
                    f"  {ANSI_DIM}If you're on testnet, RPC endpoints are not available.{ANSI_RESET}\n"
                    f"  {ANSI_BOLD}💡 Recommendation:{ANSI_RESET} Use {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} "
                    f"to bypass RPC replay and use verifier-supplied amounts.\n"
                    f"  {ANSI_DIM}Continuing with RPC replay attempt...{ANSI_RESET}"
                )
        elif not settings.rpc_urls:
            # No RPC URLs configured at all
            bt.logging.warning(
                f"{ANSI_BOLD}{ANSI_YELLOW}⚠️  No RPC Configuration:{ANSI_RESET}\n"
                f"  You're running without {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} "
                f"but no RPC URLs are configured.\n"
                f"  {ANSI_BOLD}💡 Recommendation:{ANSI_RESET} Use {ANSI_BOLD}--use-verified-amounts{ANSI_RESET} "
                f"to bypass RPC replay, or configure RPC URLs in config.py.\n"
                f"  {ANSI_DIM}Continuing with RPC replay attempt...{ANSI_RESET}"
            )

    with httpx.Client(base_url=verifier_url, timeout=timeout) as client:
        response = client.get("/v1/verified-miners", params={"epoch": epoch_version})
        response.raise_for_status()
        entries = response.json()

    if subtensor is None:
        subtensor = bt.subtensor()
    if wallet is None:
        wallet = bt.wallet()

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
    )

    summary = result["summary"]
    bt.logging.info(
        f"Epoch {epoch_version} summary: rows={summary['total_rows']} miners={summary['total_miners']} "
        f"scored={summary['scored']} skipped={summary['skipped']} failures={summary['failures']} "
        f"missingUid={summary['missing_uid']} inferredBlocks={summary['inferred_blocks']} "
        f"avgReplay={summary['avg_replay_ms']:.2f}ms maxLag={summary['max_rpc_lag']} dryRun={dry_run}"
    )

    # Save detailed ranking to log file
    log_dir_str = getattr(args, "log_dir", "validator_logs") if args else "validator_logs"
    log_dir = Path(log_dir_str)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = (
        log_dir
        / f"weights_{epoch_version.replace(':', '-').replace('T', '_').replace('Z', '')}_{timestamp}.json"
    )

    ranking_payload = [
        {
            "uid": item["uid"],
            "hotkey": item["hotkey"],
            "slot_uid": item.get("slot_uid"),
            "score": round(item["score"], 6),
            "weight": round(item["weight"], 6),
            "positions": _format_positions(item["positions"], result["unit"]),
        }
        for item in result["ranking"]
    ]

    log_entry = {
        "epoch_version": epoch_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
            medal = f"{EMOJI_TROPHY} " if i == 1 else f"{ANSI_BRIGHT_CYAN}#{i}{ANSI_RESET} "
            bt.logging.info(
                f"{medal}UID={ANSI_BOLD}{item['uid']}{ANSI_RESET} "
                f"score={ANSI_GREEN}{item['score']:.6f}{ANSI_RESET} "
                f"weight={ANSI_BRIGHT_GREEN}{item['weight']:.6f}{ANSI_RESET}"
            )
        if len(result["ranking"]) > 5:
            bt.logging.debug(f"Full ranking:\n{json.dumps(ranking_payload, indent=2)}")

    return result


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
        config.subtensor.network if hasattr(config.subtensor, "network") else subtensor.network
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
        last_processed_epoch = None
        step = 0
        last_metagraph_sync = 0
        metagraph_sync_interval = 100  # Sync metagraph every 100 blocks

        current_block = subtensor.get_current_block()
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_BLOCK} Validator starting{ANSI_RESET} "
            f"at block: {ANSI_BOLD}{current_block}{ANSI_RESET}"
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
                        f"network:{ANSI_BOLD}{network_name}{ANSI_RESET})"
                    )

                current_epoch_start = epoch_start()
                current_epoch_version = current_epoch_start.strftime("%Y-%m-%dT%H:%M:%SZ")

                # Check if this is a new epoch
                if last_processed_epoch != current_epoch_version:
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_MAGENTA}{EMOJI_COIN} New epoch detected:{ANSI_RESET} "
                        f"{ANSI_BOLD}{current_epoch_version}{ANSI_RESET}"
                    )
                    bt.logging.info(f"{ANSI_DIM}step({step}) block({current_block}){ANSI_RESET}")

                    run_epoch(
                        verifier_url=args.verifier_url,
                        epoch_version=current_epoch_version,
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

                    last_processed_epoch = current_epoch_version
                    step += 1
                    bt.logging.info(
                        f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Processed epoch{ANSI_RESET} "
                        f"{ANSI_BOLD}{current_epoch_version}{ANSI_RESET}. "
                        f"{ANSI_DIM}Next check in {args.poll_interval} seconds...{ANSI_RESET}"
                    )
                else:
                    # Same epoch, just wait and log heartbeat
                    bt.logging.info(f"{ANSI_DIM}Validator running... {time.time()}{ANSI_RESET}")

                    epoch_end_time = epoch_end(current_epoch_start)
                    now = datetime.now(timezone.utc)
                    time_until_next = (
                        epoch_end_time - now
                    ).total_seconds() + 60  # 1 minute after epoch ends

                    if time_until_next > 0:
                        wait_time = min(time_until_next, args.poll_interval)
                        bt.logging.debug(
                            f"Current epoch: {current_epoch_version} (ends {epoch_end_time}). Waiting {wait_time} seconds until next check..."
                        )
                        time.sleep(wait_time)
                    else:
                        # Should be a new epoch by now, but check in a short interval
                        bt.logging.debug(
                            f"Epoch should have ended, checking again in {args.poll_interval} seconds..."
                        )
                        time.sleep(args.poll_interval)

            except KeyboardInterrupt:
                bt.logging.info(
                    f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} Validator killed{ANSI_RESET} "
                    f"by keyboard interrupt."
                )
                break
            except Exception as exc:
                bt.logging.error(f"Error in validator loop: {exc}", exc_info=True)
                bt.logging.info(f"Retrying in {args.poll_interval} seconds...")
                time.sleep(args.poll_interval)


if __name__ == "__main__":  # pragma: no cover
    main()
