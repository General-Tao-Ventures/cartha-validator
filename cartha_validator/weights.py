"""Weight publishing helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import bittensor as bt

from .config import DEFAULT_SETTINGS, ValidatorSettings
from .logging import (
    ANSI_BOLD,
    ANSI_CYAN,
    ANSI_DIM,
    ANSI_GREEN,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
    EMOJI_ERROR,
    EMOJI_ROCKET,
    EMOJI_STOPWATCH,
    EMOJI_SUCCESS,
    EMOJI_WARNING,
)


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
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} No scores to publish;{ANSI_RESET} "
            f"skipping set_weights."
        )
        return {}

    weights = _normalize(scores)
    uids = list(weights.keys())
    values = list(weights.values())

    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}{EMOJI_ROCKET} Publishing{ANSI_RESET} "
        f"{ANSI_BOLD}{len(uids)}{ANSI_RESET} weights "
        f"for netuid={ANSI_BOLD}{settings.netuid}{ANSI_RESET} "
        f"{ANSI_DIM}(epoch {epoch_version}){ANSI_RESET}"
    )
    # Log actual normalized weights being published
    for uid, weight_val in zip(uids, values):
        score_val = scores.get(uid, 0.0)
        bt.logging.debug(f"UID {uid}: score={score_val:.6f} -> normalized_weight={weight_val:.6f}")
    subtensor = subtensor or bt.subtensor()
    wallet = wallet or bt.wallet()

    # Check if enough blocks have passed since last weight update (if metagraph available)
    if metagraph is not None and validator_uid is not None:
        current_block = subtensor.get_current_block()
        last_update = (
            metagraph.last_update[validator_uid]
            if hasattr(metagraph, "last_update") and validator_uid < len(metagraph.last_update)
            else 0
        )
        blocks_since_update = current_block - last_update
        # Use tempo (Bittensor epoch length) from metagraph, fallback to default
        epoch_length = getattr(metagraph, "tempo", None) or getattr(settings, "epoch_length_blocks", 360)  # Default to 360 (typical tempo)

        if blocks_since_update < epoch_length:
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_STOPWATCH} Skipping set_weights:{ANSI_RESET} "
                f"only {ANSI_BOLD}{blocks_since_update}{ANSI_RESET} blocks since last update "
                f"{ANSI_DIM}(need {epoch_length}){ANSI_RESET}. "
                f"Will retry when cooldown expires."
            )
            # Return normalized weights even when skipping, so logging is accurate
            return weights

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
                f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_STOPWATCH} Cannot set weights yet{ANSI_RESET} "
                f"{ANSI_DIM}(cooldown period){ANSI_RESET}: {message}. "
                f"Will retry on next epoch."
            )
            # Return normalized weights even when skipping, so logging shows what would be published
            return weights
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}{EMOJI_ERROR} Failed to publish weights:{ANSI_RESET} {message}"
        )
        raise RuntimeError(f"set_weights failed: {message}")
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Weights published successfully{ANSI_RESET} "
        f"{ANSI_DIM}(version_key={version_key}){ANSI_RESET}"
    )
    return weights


__all__ = ["publish"]
