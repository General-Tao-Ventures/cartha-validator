"""Weight publishing helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import bittensor as bt

from . import __spec_version__, __version__
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


def _query_weight_versions(subtensor: Any, netuid: int) -> int | None:
    """Query the weight_versions hyperparameter from the subnet.
    
    This is the minimum required version that validators must meet.
    Returns None if the query fails.
    """
    try:
        # Try get_hyperparameter method first (synchronous)
        if hasattr(subtensor, "get_hyperparameter"):
            weight_versions = subtensor.get_hyperparameter("WeightVersions", netuid=netuid)
            if weight_versions is not None:
                return int(weight_versions)
        
        # Fallback to query_subtensor
        response = subtensor.query_subtensor("WeightVersions", params=[netuid])
        value = getattr(response, "value", response)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            bt.logging.warning("Unexpected WeightVersions response: %r", value)
            return None
    except Exception as exc:  # pragma: no cover - network failure
        bt.logging.warning("Failed to query WeightVersions hyperparameter: %s", exc)
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
    force: bool = False,
) -> dict[int, float]:
    """Normalize scores and publish weights to the subnet.
    
    Args:
        scores: Mapping of UID to score
        epoch_version: Epoch version identifier
        settings: Validator settings
        subtensor: Bittensor subtensor instance
        wallet: Bittensor wallet instance
        metagraph: Bittensor metagraph instance
        validator_uid: Validator UID
        force: If True, bypass cooldown check and always attempt to set weights (e.g., on startup)
    """
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
    # Skip this check if force=True (e.g., on validator startup)
    if not force and metagraph is not None and validator_uid is not None:
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

    # Query the subnet's weight_versions hyperparameter (minimum required version)
    required_version = _query_weight_versions(subtensor, settings.netuid)
    if required_version is not None:
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_CYAN}Version check:{ANSI_RESET} "
            f"validator version {ANSI_BOLD}{__version__}{ANSI_RESET} "
            f"(spec_version={ANSI_BOLD}{__spec_version__}{ANSI_RESET}) "
            f"vs subnet requirement {ANSI_BOLD}{required_version}{ANSI_RESET}"
        )
        if __spec_version__ < required_version:
            error_msg = (
                f"{ANSI_BOLD}{ANSI_RED}{EMOJI_ERROR} Version mismatch:{ANSI_RESET} "
                f"Validator version {ANSI_BOLD}{__version__}{ANSI_RESET} "
                f"(spec_version={ANSI_BOLD}{__spec_version__}{ANSI_RESET}) "
                f"is below subnet requirement {ANSI_BOLD}{required_version}{ANSI_RESET}. "
                f"{ANSI_DIM}Please update the validator code.{ANSI_RESET}"
            )
            bt.logging.error(error_msg)
            raise RuntimeError(
                f"Validator version {__version__} (spec_version={__spec_version__}) "
                f"is below subnet requirement {required_version}"
            )
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_GREEN}{EMOJI_SUCCESS} Version check passed{ANSI_RESET} "
            f"{ANSI_DIM}({__spec_version__} >= {required_version}){ANSI_RESET}"
        )
    else:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} Could not query WeightVersions hyperparameter{ANSI_RESET}. "
            f"{ANSI_DIM}Proceeding with validator version {__version__} (spec_version={__spec_version__}){ANSI_RESET}"
        )

    # Use spec_version as the version_key (like logicnet)
    version_key = __spec_version__

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
