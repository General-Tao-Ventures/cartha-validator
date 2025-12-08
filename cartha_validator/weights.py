"""Weight publishing helpers."""

from __future__ import annotations

import threading
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


def _normalize(scores: Mapping[int, float]) -> dict[int, float]:
    """Normalize scores into weights that sum to 1 and clamp negatives."""
    positive = {uid: max(0.0, float(score)) for uid, score in scores.items()}
    total = sum(positive.values())
    if total <= 0:
        bt.logging.warning("Total score non-positive; emitting zeroed weights.")
        return {uid: 0.0 for uid in positive}
    return {uid: value / total for uid, value in positive.items()}


class SetWeightsTimeoutError(Exception):
    """Raised when set_weights operation times out."""
    pass


def _set_weights_with_timeout(
    subtensor: Any,
    wallet: Any,
    netuid: int,
    uids: list[int],
    weights: list[float],
    version_key: int,
    timeout: float,
) -> tuple[bool, str]:
    """Set weights with a timeout using threading.
    
    Args:
        subtensor: Bittensor subtensor instance
        wallet: Bittensor wallet instance
        netuid: Subnet netuid
        uids: List of UIDs
        weights: List of weights
        version_key: Version key for weights
        timeout: Timeout in seconds
        
    Returns:
        Tuple of (success, message)
        
    Raises:
        SetWeightsTimeoutError: If operation exceeds timeout
    """
    result = [None]
    exception = [None]
    
    def set_weights():
        try:
            result[0] = subtensor.set_weights(
                wallet=wallet,
                netuid=netuid,
                uids=uids,
                weights=weights,
                version_key=version_key,
                wait_for_inclusion=False,
                wait_for_finalization=False,
            )
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=set_weights, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        # Thread is still running, operation timed out
        raise SetWeightsTimeoutError(f"set_weights operation timed out after {timeout} seconds")
    
    if exception[0]:
        raise exception[0]
    
    return result[0]


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
        # Use tempo (Bittensor epoch length) from metagraph, fallback to settings
        epoch_length = getattr(metagraph, "tempo", None) or settings.epoch_length_blocks

        if blocks_since_update < epoch_length:
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_STOPWATCH} Skipping set_weights:{ANSI_RESET} "
                f"only {ANSI_BOLD}{blocks_since_update}{ANSI_RESET} blocks since last update "
                f"{ANSI_DIM}(need {epoch_length}){ANSI_RESET}. "
                f"Will retry when cooldown expires."
            )
            # Return normalized weights even when skipping, so logging is accurate
            return weights

    # Use spec_version as the version_key (Bittensor chain will automatically reject if version is too low)
    version_key = __spec_version__
    bt.logging.info(
        f"{ANSI_BOLD}{ANSI_CYAN}Validator version:{ANSI_RESET} "
        f"{ANSI_BOLD}{__version__}{ANSI_RESET} "
        f"{ANSI_DIM}(version_key={version_key}){ANSI_RESET}"
    )

    # Set weights with timeout
    try:
        success, message = _set_weights_with_timeout(
            subtensor=subtensor,
            wallet=wallet,
            netuid=settings.netuid,
            uids=uids,
            weights=values,
            version_key=version_key,
            timeout=settings.set_weights_timeout,
        )
    except SetWeightsTimeoutError as e:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}{EMOJI_ERROR} Weight setting timed out:{ANSI_RESET} {e}"
        )
        raise RuntimeError(f"set_weights timed out after {settings.set_weights_timeout} seconds") from e
    except Exception as e:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}{EMOJI_ERROR} Unexpected error during set_weights:{ANSI_RESET} {e}"
        )
        raise RuntimeError(f"set_weights failed with exception: {e}") from e
    
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
