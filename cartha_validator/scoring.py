"""Scoring helpers."""

from __future__ import annotations

from collections.abc import Mapping

import bittensor as bt

from .config import DEFAULT_SETTINGS, ValidatorSettings


def score_entry(
    position: Mapping[str, Mapping[str, int]],
    settings: ValidatorSettings = DEFAULT_SETTINGS,
) -> float:
    """Score a single miner entry by applying pool weights and lock-day boost.
    
    Returns the raw score directly, which will be normalized to weights later.
    This preserves the full competitive differences between miners.
    """
    raw_total = 0.0
    
    for pool_id, details in position.items():
        weight = settings.pool_weights.get(pool_id, 1.0)
        amount_raw = details.get("amount", 0)
        decimals = max(0, settings.token_decimals)
        scale = float(10**decimals) if decimals else 1.0
        amount_tokens = float(amount_raw) / scale
        lock_days = details.get("lockDays", 0)
        if settings.max_lock_days <= 0:
            bt.logging.warning("max_lock_days is non-positive; defaulting boost to 1.0")
            boost = 1.0
        else:
            boost = min(lock_days, settings.max_lock_days) / settings.max_lock_days
        raw_contrib = weight * amount_tokens * boost
        bt.logging.debug(
            f"[SCORE CALC] pool={pool_id[:20]}...: "
            f"pool_weight={weight:.4f} × amount={amount_tokens:.2f} USDC × "
            f"boost={boost:.4f} (lock_days={lock_days}/{settings.max_lock_days}) = "
            f"raw_contrib={raw_contrib:.6f}"
        )
        raw_total += raw_contrib

    if raw_total <= 0:
        bt.logging.debug("[SCORE CALC] Raw total is non-positive; returning score=0.0")
        return 0.0

    bt.logging.debug(
        f"[SCORE CALC] raw_total={raw_total:.6f} → score={raw_total:.6f} "
        f"(raw score used directly, will be normalized to weights)"
    )
    return raw_total
