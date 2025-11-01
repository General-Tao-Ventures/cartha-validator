"""Weight publishing helpers."""

from __future__ import annotations

from typing import Any, Mapping

import bittensor as bt

from .config import DEFAULT_SETTINGS, ValidatorSettings


def _version_key(epoch_version: str) -> int:
    """Create a deterministic positive version key from the epoch identifier."""
    return abs(hash(epoch_version)) % (2**31)


def _query_version_key(subtensor: Any, netuid: int) -> int | None:
    """Fetch the current version key from chain if available."""
    try:
        response = subtensor.query_subtensor("WeightsVersionKey", params=[netuid])
    except Exception as exc:  # pragma: no cover - network failure
        bt.logging.warning("Failed to query WeightsVersionKey: %s", exc)
        return None

    value = getattr(response, "value", response)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        bt.logging.warning("Unexpected WeightsVersionKey response: %r", value)
        return None


def _normalize(scores: Mapping[int, float]) -> dict[int, float]:
    """Normalize scores into weights that sum to 1 and clamp negatives."""
    positive = {uid: max(0.0, float(score)) for uid, score in scores.items()}
    total = sum(positive.values())
    if total <= 0:
        bt.logging.warning("Total score non-positive; emitting zeroed weights.")
        return {uid: 0.0 for uid in positive}
    return {uid: value / total for uid, value in positive.items()}


def publish(
    scores: Mapping[int, float],
    epoch_version: str,
    settings: ValidatorSettings = DEFAULT_SETTINGS,
    subtensor: Any | None = None,
    wallet: Any | None = None,
) -> dict[int, float]:
    """Normalize scores and publish weights to the subnet."""
    if not scores:
        bt.logging.warning("No scores to publish; skipping set_weights.")
        return {}

    weights = _normalize(scores)
    uids = list(weights.keys())
    values = list(weights.values())

    bt.logging.info(
        "Publishing %s weights for netuid=%s epoch=%s",
        len(uids),
        settings.netuid,
        epoch_version,
    )
    subtensor = subtensor or bt.subtensor()
    wallet = wallet or bt.wallet()
    version_key = _query_version_key(subtensor, settings.netuid)
    if version_key is None:
        version_key = _version_key(epoch_version)
        bt.logging.debug("Falling back to derived version_key=%s", version_key)
    success, message = subtensor.set_weights(
        wallet=wallet,
        netuid=settings.netuid,
        uids=uids,
        weights=values,
        version_key=version_key,
    )
    if not success:
        bt.logging.error("Failed to publish weights: %s", message)
        raise RuntimeError(f"set_weights failed: {message}")
    bt.logging.info("Weights published (version_key=%s).", version_key)
    return weights


__all__ = ["publish"]
