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
    ANSI_MAGENTA,
    ANSI_RED,
    ANSI_RESET,
    ANSI_YELLOW,
    EMOJI_ERROR,
    EMOJI_ROCKET,
    EMOJI_STOPWATCH,
    EMOJI_SUCCESS,
    EMOJI_WARNING,
)


def _normalize(
    scores: Mapping[int, float],
    trader_pool_uid: int | None = None,
    trader_pool_weight: float = 0.0,
) -> dict[int, float]:
    """Normalize scores into weights that sum to 1, with optional fixed trader pool allocation.
    
    Args:
        scores: Mapping of UID to score
        trader_pool_uid: Optional UID of trader rewards pool (receives fixed weight)
        trader_pool_weight: Fixed weight for trader pool (e.g., 0.243902 for 24.3902%)
    
    Returns:
        Normalized weights dict
    """
    # Validate trader pool weight
    if trader_pool_weight < 0 or trader_pool_weight >= 1:
        bt.logging.error(
            f"{ANSI_BOLD}{ANSI_RED}Invalid trader pool weight: {trader_pool_weight:.6f}{ANSI_RESET} "
            f"(must be >= 0 and < 1). Setting to 0."
        )
        trader_pool_weight = 0.0
    
    # Clamp negative scores
    positive = {uid: max(0.0, float(score)) for uid, score in scores.items()}
    
    # Calculate remaining weight for miners (after trader pool allocation)
    remaining_weight = 1.0 - trader_pool_weight
    
    # If trader pool is in the scores, we'll override its weight
    # Otherwise, we'll add it separately
    miner_scores = {uid: score for uid, score in positive.items() if uid != trader_pool_uid}
    
    # Normalize miner scores to fill remaining weight
    miner_total = sum(miner_scores.values())
    
    weights: dict[int, float] = {}
    
    if miner_total <= 0:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}Total miner score non-positive; "
            f"distributing remaining weight equally.{ANSI_RESET}"
        )
        # If no valid miner scores, distribute remaining weight equally
        if miner_scores:
            equal_weight = remaining_weight / len(miner_scores)
            weights = {uid: equal_weight for uid in miner_scores}
        else:
            weights = {}
    else:
        # Normalize miners to fill remaining weight (e.g., 75.6098% when trader pool takes 24.3902%)
        weights = {
            uid: (score / miner_total) * remaining_weight
            for uid, score in miner_scores.items()
        }
    
    # Add trader pool with fixed weight
    if trader_pool_uid is not None and trader_pool_weight > 0:
        weights[trader_pool_uid] = trader_pool_weight
        bt.logging.info(
            f"{ANSI_BOLD}{ANSI_CYAN}[TRADER POOL]{ANSI_RESET} "
            f"Allocated fixed weight: {ANSI_BOLD}{trader_pool_weight:.6f}{ANSI_RESET} "
            f"({trader_pool_weight * 100:.4f}%) to UID {ANSI_BOLD}{trader_pool_uid}{ANSI_RESET}"
        )
    
    # Verify weights sum to 1.0 (within floating point tolerance)
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}Weight sum verification failed:{ANSI_RESET} "
            f"total={total_weight:.10f} (expected 1.0, diff={abs(total_weight - 1.0):.10f})"
        )
    
    return weights


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

    # Initialize subtensor early to resolve trader pool UID
    subtensor = subtensor or bt.subtensor()
    
    # Resolve trader rewards pool UID from hotkey
    trader_pool_uid: int | None = None
    trader_pool_weight = settings.trader_rewards_pool_weight
    trader_pool_hotkey = settings.trader_rewards_pool_hotkey
    
    if trader_pool_hotkey and trader_pool_weight > 0:
        try:
            trader_pool_uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=trader_pool_hotkey,
                netuid=settings.netuid
            )
            if trader_pool_uid is None or trader_pool_uid < 0:
                bt.logging.warning(
                    f"{ANSI_BOLD}{ANSI_YELLOW}{EMOJI_WARNING} Trader Rewards Pool hotkey{ANSI_RESET} "
                    f"{trader_pool_hotkey} not registered on netuid {settings.netuid}. "
                    f"Skipping fixed weight allocation."
                )
                trader_pool_uid = None
            else:
                bt.logging.info(
                    f"{ANSI_BOLD}{ANSI_GREEN}[{settings.trader_rewards_pool_name}]{ANSI_RESET} "
                    f"Hotkey: {trader_pool_hotkey}, "
                    f"UID: {ANSI_BOLD}{trader_pool_uid}{ANSI_RESET}, "
                    f"Fixed Weight: {ANSI_BOLD}{trader_pool_weight:.6f}{ANSI_RESET} "
                    f"({trader_pool_weight * 100:.4f}%)"
                )
        except Exception as exc:
            bt.logging.error(
                f"{ANSI_BOLD}{ANSI_RED}{EMOJI_ERROR} Failed to resolve trader pool UID:{ANSI_RESET} {exc}"
            )
            trader_pool_uid = None

    # Normalize with trader pool allocation
    weights = _normalize(
        scores,
        trader_pool_uid=trader_pool_uid,
        trader_pool_weight=trader_pool_weight if trader_pool_uid is not None else 0.0,
    )
    
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
        if uid == trader_pool_uid:
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_MAGENTA}[{settings.trader_rewards_pool_name}]{ANSI_RESET} "
                f"UID {uid}: "
                f"score={score_val:.6f} → "
                f"weight={ANSI_BOLD}{weight_val:.6f}{ANSI_RESET} (FIXED)"
            )
        else:
            bt.logging.debug(
                f"UID {uid}: score={score_val:.6f} → normalized_weight={weight_val:.6f}"
            )
    
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
