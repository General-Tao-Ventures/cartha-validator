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
    metagraph: Any | None = None,
    validator_uid: int | None = None,
) -> dict[int, float]:
    """Normalize scores and publish weights to the subnet."""
    if not scores:
        bt.logging.warning("No scores to publish; skipping set_weights.")
        return {}

    weights = _normalize(scores)
    uids = list(weights.keys())
    values = list(weights.values())

    bt.logging.info(
        f"Publishing {len(uids)} weights for netuid={settings.netuid} epoch={epoch_version}"
    )
    subtensor = subtensor or bt.subtensor()
    wallet = wallet or bt.wallet()
    
    # Check if enough blocks have passed since last weight update (if metagraph available)
    if metagraph is not None and validator_uid is not None:
        current_block = subtensor.get_current_block()
        last_update = metagraph.last_update[validator_uid] if hasattr(metagraph, 'last_update') and validator_uid < len(metagraph.last_update) else 0
        blocks_since_update = current_block - last_update
        epoch_length = getattr(settings, 'epoch_length_blocks', 100)  # Default epoch length
        
        if blocks_since_update < epoch_length:
            bt.logging.info(
                f"Skipping set_weights: only {blocks_since_update} blocks since last update (need {epoch_length}). "
                "Will retry when cooldown expires."
            )
            return {}

    version_key = _query_version_key(subtensor, settings.netuid)
    if version_key is None:
        version_key = _version_key(epoch_version)
        bt.logging.debug(f"Falling back to derived version_key={version_key}")
    
    success, message = subtensor.set_weights(
        wallet=wallet,
        netuid=settings.netuid,
        uids=uids,
        weights=values,
        version_key=version_key,
        wait_for_inclusion=False,
        wait_for_finalization=False,
    )
    if not success:
        # Handle "too soon" error gracefully - this is expected during cooldown periods
        if "too soon" in str(message).lower() or "cooldown" in str(message).lower():
            bt.logging.warning(
                f"Cannot set weights yet (cooldown period): {message}. Will retry on next epoch."
            )
            # Return empty dict to indicate weights weren't published, but don't crash
            return {}
        bt.logging.error(f"Failed to publish weights: {message}")
        raise RuntimeError(f"set_weights failed: {message}")
    bt.logging.info(f"Weights published successfully (version_key={version_key}).")
    return weights


__all__ = ["publish"]
