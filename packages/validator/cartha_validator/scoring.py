"""Scoring helpers."""

from __future__ import annotations

from typing import Mapping

import bittensor as bt

from .config import DEFAULT_SETTINGS


def score_entry(position: Mapping[str, Mapping[str, int]]) -> float:
    """Score a single miner entry by applying pool weights and lock-day boost."""
    total = 0.0
    for pool_id, details in position.items():
        weight = DEFAULT_SETTINGS.pool_weights.get(pool_id, 1.0)
        amount = details.get("amount", 0)
        lock_days = details.get("lockDays", 0)
        boost = min(lock_days, DEFAULT_SETTINGS.max_lock_days) / DEFAULT_SETTINGS.max_lock_days
        subtotal = weight * amount * boost
        bt.logging.debug("pool=%s weight=%s amount=%s boost=%s subtotal=%s", pool_id, weight, amount, boost, subtotal)
        total += subtotal
    return total
