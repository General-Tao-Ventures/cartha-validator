"""Epoch boundary helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bittensor as bt

EPOCH_LENGTH = timedelta(days=7)


def epoch_start(reference: datetime | None = None) -> datetime:
    """Return the start (Friday 00:00 UTC) of the epoch that contains reference."""
    reference = reference or datetime.now(tz=UTC)
    weekday = reference.weekday()  # Monday=0
    days_since_friday = (weekday - 4) % 7
    start = datetime(
        year=reference.year,
        month=reference.month,
        day=reference.day,
        hour=0,
        minute=0,
        tzinfo=UTC,
    ) - timedelta(days=days_since_friday)
    bt.logging.debug(f"Computed epoch start {start} from reference {reference}")
    return start


def epoch_end(reference: datetime | None = None) -> datetime:
    """Return the end timestamp (Thu 23:59 UTC) for the epoch containing reference."""
    start = epoch_start(reference)
    end = start + EPOCH_LENGTH - timedelta(minutes=1)
    bt.logging.debug(f"Computed epoch end {end}")
    return end
