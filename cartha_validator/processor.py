"""Entry processing logic for the validator."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from statistics import mean
from time import perf_counter
from typing import Any

import bittensor as bt
from web3 import Web3

from .config import ValidatorSettings
from .indexer import replay_owner
from .logging import ANSI_BOLD, ANSI_RED, ANSI_RESET, ANSI_YELLOW
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
        bool,
    ],
    dict[int, float],
]


def resolve_owner(entry: Mapping[str, Any]) -> str | None:
    """Extract owner EVM address from entry."""
    return (
        entry.get("minerEvmAddress")
        or entry.get("miner_evm_address")
        or entry.get("evm")
    )


def resolve_block(entry: Mapping[str, Any]) -> int | None:
    """Extract block number from entry."""
    block = entry.get("block") or entry.get("atBlock") or entry.get("at_block")
    if block is not None:
        try:
            return int(block)
        except (ValueError, TypeError):
            return None
    return None


def format_positions(
    positions: Mapping[str, Mapping[str, int]], unit: float
) -> dict[str, dict[str, Any]]:
    """Format position data for display.
    
    Supports per-position keys (e.g. "pool_id#0") by reading the actual
    pool_id from the position data when available.
    """
    formatted: dict[str, dict[str, Any]] = {}
    for pos_key, data in positions.items():
        # Use stored pool_id if available (per-position scoring),
        # otherwise fall back to the dict key (legacy combined format)
        actual_pool_id = data.get("pool_id", pos_key)
        amount_raw = int(data.get("amount", 0))
        amount_usdc = amount_raw / unit
        formatted[pos_key] = {
            "pool_id": actual_pool_id,
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
    force: bool = False,
    deregistered_hotkeys: set[str] | None = None,
) -> dict[str, Any]:
    """Replay events, score miners, and optionally publish weights."""
    start_time = perf_counter()
    scores: dict[int, float] = {}
    details: list[dict[str, Any]] = []
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
        "expired_pools": 0,
    }
    unit = float(10**settings.token_decimals)
    web3_cache: dict[int, Web3] = {}
    subtensor = subtensor or bt.subtensor()

    grouped: dict[int, dict[str, Any]] = {}
    sources: dict[int, list[Mapping[str, Any]]] = {}

    for entry in entries:
        metrics["total_rows"] += 1
        hotkey = entry.get("hotkey")
        if not hotkey:
            bt.logging.warning("Skipping entry missing hotkey: %s", entry)
            metrics["skipped"] += 1
            continue

        try:
            uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=hotkey, netuid=settings.netuid
            )
        except Exception as exc:  # pragma: no cover
            import traceback

            bt.logging.error(
                f"{ANSI_BOLD}{ANSI_RED}[UID RESOLUTION ERROR]{ANSI_RESET} "
                f"Failed to resolve UID for hotkey"
            )
            bt.logging.error(f"Error type: {type(exc).__name__}")
            bt.logging.error(f"Error message: {str(exc)}")
            bt.logging.error(f"Hotkey: {hotkey}")
            bt.logging.error(f"Netuid: {settings.netuid}")
            bt.logging.debug(f"Traceback:\n{traceback.format_exc()}")
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

    # Normalize deregistered_hotkeys set (handle None)
    if deregistered_hotkeys is None:
        deregistered_hotkeys = set()
    
    for uid, miner_entries in sources.items():
        combined_positions: dict[str, dict[str, int]] = {}
        per_miner_replay: list[float] = []
        miner_failed = False
        
        # Check if this hotkey is deregistered - if so, score all positions as 0
        hotkey = grouped.get(uid, {}).get("hotkey")
        if hotkey and hotkey in deregistered_hotkeys:
            bt.logging.warning(
                f"{ANSI_BOLD}{ANSI_YELLOW}[DEREGISTERED HOTKEY]{ANSI_RESET} "
                f"Hotkey {hotkey} (UID {uid}) is deregistered - scoring all positions as 0"
            )
            # Set score to 0 for this UID (all positions)
            scores[uid] = 0.0
            metrics["skipped"] += len(miner_entries)
            metrics["expired_pools"] = metrics.get("expired_pools", 0) + len(miner_entries)
            continue  # Skip processing this miner entirely

        for entry in miner_entries:
            if use_verified_amounts:
                # Use pool_id from verifier (now included in VerifiedMinerEntry)
                pool_id = entry.get("pool_id", "default")

                # Check if this pool has expired, been released, or miner was deregistered
                current_time = datetime.now(UTC)
                
                # Check if miner was deregistered mid-epoch
                deregistered_at_str = entry.get("deregistered_at")
                if deregistered_at_str:
                    try:
                        # Parse deregistered_at - handle both ISO format strings and datetime objects
                        if isinstance(deregistered_at_str, str):
                            # Handle ISO format with or without timezone
                            if deregistered_at_str.endswith("Z"):
                                deregistered_at = datetime.fromisoformat(
                                    deregistered_at_str.replace("Z", "+00:00")
                                )
                            else:
                                deregistered_at = datetime.fromisoformat(deregistered_at_str)
                            # Ensure timezone-aware
                            if deregistered_at.tzinfo is None:
                                deregistered_at = deregistered_at.replace(tzinfo=UTC)
                        else:
                            deregistered_at = deregistered_at_str
                            if deregistered_at.tzinfo is None:
                                deregistered_at = deregistered_at.replace(tzinfo=UTC)

                        if deregistered_at <= current_time:
                            # Miner was deregistered mid-epoch - skip this pool (don't add to combined_positions)
                            hotkey = grouped.get(uid, {}).get("hotkey", "unknown")
                            bt.logging.debug(
                                f"Miner deregistered for uid={uid} hotkey={hotkey}: "
                                f"deregistered_at={deregistered_at} <= current_time={current_time}"
                            )
                            metrics["expired_pools"] = (
                                metrics.get("expired_pools", 0) + 1
                            )
                            continue
                    except (ValueError, TypeError) as exc:
                        bt.logging.warning(
                            f"Failed to parse deregistered_at for uid={uid} pool={pool_id}: {deregistered_at_str}, error: {exc}"
                        )
                        # Continue processing if we can't parse deregistered_at (don't skip the pool)
                
                # Check if pool has expired
                expires_at_str = entry.get("expires_at")
                if expires_at_str:
                    try:
                        # Parse expires_at - handle both ISO format strings and datetime objects
                        if isinstance(expires_at_str, str):
                            # Handle ISO format with or without timezone
                            if expires_at_str.endswith("Z"):
                                expires_at = datetime.fromisoformat(
                                    expires_at_str.replace("Z", "+00:00")
                                )
                            else:
                                expires_at = datetime.fromisoformat(expires_at_str)
                            # Ensure timezone-aware
                            if expires_at.tzinfo is None:
                                expires_at = expires_at.replace(tzinfo=UTC)
                        else:
                            expires_at = expires_at_str
                            if expires_at.tzinfo is None:
                                expires_at = expires_at.replace(tzinfo=UTC)

                        if expires_at < current_time:
                            # Pool has expired - skip this pool (don't add to combined_positions)
                            hotkey = grouped.get(uid, {}).get("hotkey", "unknown")
                            bt.logging.debug(
                                f"Pool {pool_id} expired for uid={uid} hotkey={hotkey}: "
                                f"expires_at={expires_at} < current_time={current_time}"
                            )
                            metrics["expired_pools"] = (
                                metrics.get("expired_pools", 0) + 1
                            )
                            continue
                    except (ValueError, TypeError) as exc:
                        bt.logging.warning(
                            f"Failed to parse expires_at for uid={uid} pool={pool_id}: {expires_at_str}, error: {exc}"
                        )
                        # Continue processing if we can't parse expires_at (don't skip the pool)

                amount = int(entry.get("amount", 0))
                lock_days = int(entry.get("lock_days", 0))
                # Score each position individually (don't combine by pool_id)
                # Each position keeps its own lock_days for accurate boost calculation
                pos_key = f"{pool_id}#{len(combined_positions)}"
                combined_positions[pos_key] = {
                    "amount": amount,
                    "lockDays": lock_days,
                    "pool_id": pool_id,
                }
                continue

            # Note: chain_id, vault, and owner are no longer exposed in API
            # Validators must use --use-verified-amounts or have their own data source
            chain_id = entry.get("chainId") or entry.get("chain_id")
            vault = entry.get("vault")
            owner = resolve_owner(entry)
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
                import traceback

                bt.logging.error(
                    f"{ANSI_BOLD}{ANSI_RED}[RPC INIT ERROR]{ANSI_RESET} "
                    f"Failed to initialise Web3 provider for chain {chain_id}"
                )
                bt.logging.error(f"Error type: {type(exc).__name__}")
                bt.logging.error(f"Error message: {str(exc)}")
                bt.logging.error(f"UID: {uid}, Chain: {chain_id}, Vault: {vault}")
                bt.logging.error(
                    f"RPC URL: {settings.rpc_urls.get(chain_id, 'NOT CONFIGURED')}"
                )
                bt.logging.debug(f"Traceback:\n{traceback.format_exc()}")
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

            at_block = resolve_block(entry)
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
                    import traceback

                    bt.logging.error(
                        f"{ANSI_BOLD}{ANSI_RED}[BLOCK INFERENCE ERROR]{ANSI_RESET} "
                        f"Unable to infer block for uid={uid}"
                    )
                    bt.logging.error(f"Error type: {type(exc).__name__}")
                    bt.logging.error(f"Error message: {str(exc)}")
                    bt.logging.error(f"Chain: {chain_id}, Vault: {vault}")
                    bt.logging.error(
                        f"RPC URL: {settings.rpc_urls.get(chain_id, 'NOT CONFIGURED')}"
                    )
                    bt.logging.debug(f"Traceback:\n{traceback.format_exc()}")
                    metrics["failures"] += 1
                    miner_failed = True
                    continue

            replay_start = perf_counter()
            try:
                positions = replay_fn(
                    chain_id, vault, owner, int(at_block), web3=provider
                )
            except Exception as exc:  # pragma: no cover
                import traceback

                bt.logging.error(
                    f"{ANSI_BOLD}{ANSI_RED}[REPLAY ERROR]{ANSI_RESET} "
                    f"Replay failed for uid={uid}"
                )
                bt.logging.error(f"Error type: {type(exc).__name__}")
                bt.logging.error(f"Error message: {str(exc)}")
                bt.logging.error(
                    f"Chain: {chain_id}, Vault: {vault}, Owner: {owner}, Block: {at_block}"
                )
                bt.logging.error(
                    f"RPC URL: {settings.rpc_urls.get(chain_id, 'NOT CONFIGURED')}"
                )
                bt.logging.debug(f"Traceback:\n{traceback.format_exc()}")
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
                metrics["rpc_lag_blocks"].append(
                    max(0, int(current_block) - int(at_block))
                )
            except Exception:  # pragma: no cover
                bt.logging.debug("Failed to compute RPC lag for chain %s", chain_id)

            for pool_id, data in positions.items():
                # Score each position individually (don't combine by pool_id)
                pos_key = f"{pool_id}#{len(combined_positions)}"
                combined_positions[pos_key] = {
                    "amount": int(data.get("amount", 0)),
                    "lockDays": int(data.get("lockDays", 0)),
                    "pool_id": pool_id,
                }

        if not combined_positions:
            if miner_failed:
                bt.logging.warning("Skipping uid=%s after replay failures.", uid)
            else:
                # All pools expired - log this case
                hotkey = grouped.get(uid, {}).get("hotkey", "unknown")
                bt.logging.debug(
                    f"[SCORING] uid={uid} hotkey={hotkey}: All pools expired, score=0"
                )
            continue

        # Log scoring details for this miner
        hotkey = grouped.get(uid, {}).get("hotkey", "unknown")
        pool_count = len(combined_positions)
        total_amount = sum(pos.get("amount", 0) for pos in combined_positions.values())
        total_amount_usdc = total_amount / unit
        bt.logging.debug(
            f"[SCORING] uid={uid} hotkey={hotkey}: Scoring {pool_count} pool(s), "
            f"total_amount={total_amount} base_units ({total_amount_usdc:.2f} USDC)"
        )
        
        # Log each pool being scored
        for pool_id, pool_data in combined_positions.items():
            pool_amount = pool_data.get("amount", 0)
            pool_lock_days = pool_data.get("lockDays", 0)
            bt.logging.debug(
                f"[SCORING] uid={uid} pool={pool_id}: "
                f"amount={pool_amount} ({pool_amount / unit:.2f} USDC), "
                f"lock_days={pool_lock_days}"
            )

        # Check minimum total assets threshold
        min_threshold = settings.min_total_assets_usdc
        if total_amount_usdc < min_threshold:
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_YELLOW}[MIN ASSETS]{ANSI_RESET} "
                f"uid={uid} hotkey={hotkey}: Total assets {total_amount_usdc:,.2f} USDC "
                f"< minimum threshold {min_threshold:,.2f} USDC → score=0"
            )
            score = 0.0
        else:
            score = score_entry(combined_positions, settings=settings)
        scores[uid] = score
        
        # Log final score for this miner
        bt.logging.debug(
            f"[SCORING] uid={uid} hotkey={hotkey}: "
            f"final_score={score:.6f} (from {pool_count} pool(s))"
        )
        
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

    weights: dict[int, float]
    if scores:
        if dry_run:
            weights = dict(_normalize(scores))
            bt.logging.info(
                f"{ANSI_BOLD} Dry-run mode: computed weights for {len(weights)} miners."
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
                    force=force,
                )
            )
    else:
        weights = {}
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW} No scores computed; emitting empty weight vector."
        )

    for item in details:
        item["weight"] = weights.get(item["uid"], 0.0)
        # Log final weight assignment
        uid = item["uid"]
        hotkey = item.get("hotkey", "unknown")
        score = item["score"]
        weight = item["weight"]
        pool_count = len(item.get("positions", {}))
        bt.logging.debug(
            f"[WEIGHT] uid={uid} hotkey={hotkey}: "
            f"score={score:.6f} → weight={weight:.6f} ({pool_count} pool(s))"
        )

    details.sort(key=lambda item: item["score"], reverse=True)
    
    # Calculate display scores (normalized to 0-1000 for frontend display)
    # Raw scores are preserved for weight calculation, display_score is just for UI
    if details:
        max_raw_score = max(item["score"] for item in details)
        if max_raw_score > 0:
            for item in details:
                # Normalize to 0-1000 scale for display
                item["display_score"] = round((item["score"] / max_raw_score) * 1000, 2)
        else:
            for item in details:
                item["display_score"] = 0.0
    else:
        # No details, nothing to do
        pass

    summary = {
        **metrics,
        "elapsed_ms": (perf_counter() - start_time) * 1000,
        "avg_replay_ms": mean(metrics["replay_ms"]) if metrics["replay_ms"] else 0.0,
        "max_rpc_lag": (
            max(metrics["rpc_lag_blocks"]) if metrics["rpc_lag_blocks"] else 0
        ),
        "dry_run": dry_run,
    }
    return {
        "scores": scores,
        "weights": weights,
        "ranking": details,
        "summary": summary,
        "unit": unit,
    }
