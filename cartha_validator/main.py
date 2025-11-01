"""Validator cron entrypoint."""

from __future__ import annotations

import argparse
import json
from statistics import mean
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, List, Mapping

import httpx
from web3 import Web3

import bittensor as bt

from .config import DEFAULT_SETTINGS, ValidatorSettings
from .epoch import epoch_start
from .indexer import replay_owner
from .scoring import score_entry
from .weights import _normalize, publish

ReplayFn = Callable[[int, str, str, int, Web3 | None], Mapping[str, Mapping[str, int]]]
PublishFn = Callable[[Mapping[int, float], str, ValidatorSettings, Any | None, Any | None], Mapping[int, float]]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cartha subnet validator cron runner")
    parser.add_argument("--verifier-url", default=str(DEFAULT_SETTINGS.verifier_url), help="Verifier base URL.")
    parser.add_argument("--netuid", type=int, default=DEFAULT_SETTINGS.netuid, help="Subnet netuid.")
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
    return parser.parse_args()


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


def _format_positions(positions: Mapping[str, Mapping[str, int]], unit: float) -> Dict[str, Dict[str, Any]]:
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
            bt.logging.error("Failed to resolve UID for hotkey %s: %s", hotkey, exc)
            metrics["failures"] += 1
            continue

        if uid is None or uid < 0:
            bt.logging.warning("Hotkey %s not registered on netuid %s; skipping.", hotkey, settings.netuid)
            metrics["missing_uid"] += 1
            metrics["skipped"] += 1
            continue

        uid = int(uid)
        grouped.setdefault(uid, {"hotkey": hotkey, "slot_uid": entry.get("slot_uid") or entry.get("slotUID")})
        sources.setdefault(uid, []).append(entry)

    metrics["total_miners"] = len(grouped)

    for uid, miner_entries in sources.items():
        combined_positions: Dict[str, Dict[str, int]] = {}
        per_miner_replay: List[float] = []
        miner_failed = False

        for entry in miner_entries:
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
                bt.logging.error("Failed to initialise Web3 provider for chain %s: %s", chain_id, exc)
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
                    bt.logging.error("Unable to infer block for uid=%s chain=%s: %s", uid, chain_id, exc)
                    metrics["failures"] += 1
                    miner_failed = True
                    continue

            replay_start = perf_counter()
            try:
                positions = replay_fn(chain_id, vault, owner, int(at_block), web3=provider)
            except Exception as exc:  # pragma: no cover
                bt.logging.error("Replay failed for uid=%s chain=%s owner=%s: %s", uid, chain_id, owner, exc)
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
            bt.logging.info("Dry-run mode: computed weights for %s miners.", len(weights))
        else:
            weights = dict(publish_fn(scores, epoch_version=epoch_version, settings=settings))
    else:
        weights = {}
        bt.logging.warning("No scores computed; emitting empty weight vector.")

    for item in details:
        item["weight"] = weights.get(item["uid"], 0.0)

    details.sort(key=lambda item: item["score"], reverse=True)

    summary = {
        **metrics,
        "elapsed_ms": (perf_counter() - start_time) * 1000,
        "avg_replay_ms": mean(metrics["replay_ms"]) if metrics["replay_ms"] else 0.0,
        "max_rpc_lag": max(metrics["rpc_lag_blocks"]) if metrics["rpc_lag_blocks"] else 0,
        "dry_run": dry_run,
    }
    return {"scores": scores, "weights": weights, "ranking": details, "summary": summary, "unit": unit}


def run_epoch(
    verifier_url: str,
    epoch_version: str,
    settings: ValidatorSettings,
    *,
    timeout: float = 15.0,
    dry_run: bool = False,
    replay_fn: ReplayFn = replay_owner,
    publish_fn: PublishFn = publish,
) -> Dict[str, Any]:
    bt.logging.info("Starting validator run for epoch %s (dry_run=%s)", epoch_version, dry_run)
    with httpx.Client(base_url=verifier_url, timeout=timeout) as client:
        response = client.get("/v1/verified-miners", params={"epoch": epoch_version})
        response.raise_for_status()
        entries = response.json()

    subtensor = bt.subtensor()

    result = process_entries(
        entries,
        settings,
        epoch_version,
        dry_run=dry_run,
        replay_fn=replay_fn,
        publish_fn=publish_fn,
        subtensor=subtensor,
    )

    summary = result["summary"]
    bt.logging.info(
        (
            "Epoch %s summary: rows=%s miners=%s scored=%s skipped=%s failures=%s "
            "missingUid=%s inferredBlocks=%s avgReplay=%.2fms maxLag=%s dryRun=%s"
        ),
        epoch_version,
        summary["total_rows"],
        summary["total_miners"],
        summary["scored"],
        summary["skipped"],
        summary["failures"],
        summary["missing_uid"],
        summary["inferred_blocks"],
        summary["avg_replay_ms"],
        summary["max_rpc_lag"],
        dry_run,
    )

    if dry_run:
        unit = result["unit"]
        ranking_payload = [
            {
                "uid": item["uid"],
                "hotkey": item["hotkey"],
                "score": round(item["score"], 6),
                "weight": round(item["weight"], 6),
                "positions": _format_positions(item["positions"], unit),
            }
            for item in result["ranking"]
        ]
        json_blob = json.dumps(ranking_payload, indent=2)
        bt.logging.info("Dry-run weight vector:\n%s", json_blob)
        print(json_blob)

    return result


def main() -> None:
    args = _parse_args()
    epoch_version = _epoch_version(args.epoch)
    settings = DEFAULT_SETTINGS.model_copy(
        update={"verifier_url": args.verifier_url, "netuid": args.netuid},
    )
    run_epoch(
        verifier_url=args.verifier_url,
        epoch_version=epoch_version,
        settings=settings,
        timeout=args.timeout,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
