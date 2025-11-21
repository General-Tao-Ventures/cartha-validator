"""Entry processing logic for the validator."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from statistics import mean
from time import perf_counter
from typing import Any

import bittensor as bt
from web3 import Web3

from .config import ValidatorSettings
from .indexer import replay_owner
from .logging import ANSI_BOLD, ANSI_RED, ANSI_YELLOW
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


def resolve_owner(entry: Mapping[str, Any]) -> str | None:
    """Extract owner EVM address from entry."""
    return entry.get("minerEvmAddress") or entry.get("miner_evm_address") or entry.get("evm")


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
    """Format position data for display."""
    formatted: dict[str, dict[str, Any]] = {}
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

    for uid, miner_entries in sources.items():
        combined_positions: dict[str, dict[str, int]] = {}
        per_miner_replay: list[float] = []
        miner_failed = False

        for entry in miner_entries:
            if use_verified_amounts:
                pool_id = "default"  # No longer exposed, use default
                amount = int(entry.get("amount", 0))
                lock_days = int(entry.get("lock_days", 0))
                existing = combined_positions.setdefault(
                    pool_id, {"amount": 0, "lockDays": 0}
                )
                existing["amount"] += amount
                existing["lockDays"] = max(existing["lockDays"], lock_days)
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
                bt.logging.error(f"RPC URL: {settings.rpc_urls.get(chain_id, 'NOT CONFIGURED')}")
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
                    bt.logging.error(f"RPC URL: {settings.rpc_urls.get(chain_id, 'NOT CONFIGURED')}")
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
                bt.logging.error(f"Chain: {chain_id}, Vault: {vault}, Owner: {owner}, Block: {at_block}")
                bt.logging.error(f"RPC URL: {settings.rpc_urls.get(chain_id, 'NOT CONFIGURED')}")
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
                existing = combined_positions.setdefault(
                    pool_id, {"amount": 0, "lockDays": 0}
                )
                existing["amount"] += int(data.get("amount", 0))
                existing["lockDays"] = max(
                    existing["lockDays"], int(data.get("lockDays", 0))
                )

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
                )
            )
    else:
        weights = {}
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW} No scores computed; emitting empty weight vector."
        )

    for item in details:
        item["weight"] = weights.get(item["uid"], 0.0)

    details.sort(key=lambda item: item["score"], reverse=True)

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

