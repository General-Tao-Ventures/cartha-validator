"""Epoch boundary helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bittensor as bt

EPOCH_LENGTH = timedelta(days=7)


def epoch_start(reference: datetime | None = None) -> datetime:
    """Return the start (Friday 00:00 UTC) of the epoch that contains reference."""
    reference = reference or datetime.now(tz=timezone.utc)
    weekday = reference.weekday()  # Monday=0
    days_since_friday = (weekday - 4) % 7
    start = datetime(
        year=reference.year,
        month=reference.month,
        day=reference.day,
        hour=0,
        minute=0,
        tzinfo=timezone.utc,
    ) - timedelta(days=days_since_friday)
    bt.logging.debug("Computed epoch start %s from reference %s", start, reference)
    return start


def epoch_end(reference: datetime | None = None) -> datetime:
    """Return the end timestamp (Thu 23:59 UTC) for the epoch containing reference."""
    start = epoch_start(reference)
    end = start + EPOCH_LENGTH - timedelta(minutes=1)
    bt.logging.debug("Computed epoch end %s", end)
    return end
