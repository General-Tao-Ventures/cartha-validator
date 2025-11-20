"""Scoring helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping

import bittensor as bt

from .config import DEFAULT_SETTINGS, ValidatorSettings


def score_entry(
    position: Mapping[str, Mapping[str, int]],
    settings: ValidatorSettings = DEFAULT_SETTINGS,
) -> float:
    """Score a single miner entry by applying pool weights and lock-day boost."""
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
            f"pool={pool_id} weight={weight} amount_raw={amount_raw} amount_tokens={amount_tokens} "
            f"lockDays={lock_days} boost={boost} raw_contrib={raw_contrib}"
        )
        raw_total += raw_contrib

    if raw_total <= 0:
        bt.logging.debug("Raw total score is non-positive; returning 0.")
        return 0.0

    temperature = settings.score_temperature
    if temperature <= 0:
        bt.logging.warning("score_temperature is non-positive; clamping raw total to [0,1].")
        return max(0.0, min(raw_total, 1.0))

    normalized = 1.0 - math.exp(-raw_total / temperature)
    normalized = max(0.0, min(normalized, 1.0))
    bt.logging.debug(
        f"raw_total={raw_total} temperature={temperature} normalized_score={normalized}"
    )
    return normalized
