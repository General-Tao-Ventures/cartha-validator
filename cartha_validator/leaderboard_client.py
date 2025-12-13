"""Client for submitting rankings to leaderboard API."""

from __future__ import annotations

from typing import Any

import httpx
import bittensor as bt

from .logging import ANSI_BOLD, ANSI_GREEN, ANSI_RESET, ANSI_YELLOW


def send_ranking_to_leaderboard(
    leaderboard_url: str,
    validator_hotkey: str,
    epoch_version: str,
    ranking_data: list[dict[str, Any]],
) -> None:
    """
    Send ranking data to leaderboard API.
    
    Args:
        leaderboard_url: Base URL of leaderboard API
        validator_hotkey: Validator hotkey SS58 address
        epoch_version: Epoch version identifier
        ranking_data: List of ranking entries (from ranking_payload)
        
    Note:
        Errors are caught and logged, never raised (non-blocking).
    """
    try:
        url = f"{leaderboard_url.rstrip('/')}/v1/leaderboard/submit"
        
        payload = {
            "validator_hotkey": validator_hotkey,
            "epoch_version": epoch_version,
            "ranking": ranking_data,
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            bt.logging.info(
                f"{ANSI_BOLD}{ANSI_GREEN}[LEADERBOARD]{ANSI_RESET} "
                f"Ranking submitted successfully (submission_id={result.get('submission_id')}, "
                f"is_update={result.get('is_update', False)})"
            )
            
    except httpx.HTTPStatusError as e:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}[LEADERBOARD]{ANSI_RESET} "
            f"Failed to submit ranking: HTTP {e.response.status_code} - {e.response.text}"
        )
    except httpx.RequestError as e:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}[LEADERBOARD]{ANSI_RESET} "
            f"Failed to submit ranking: Network error - {e}"
        )
    except Exception as e:
        bt.logging.warning(
            f"{ANSI_BOLD}{ANSI_YELLOW}[LEADERBOARD]{ANSI_RESET} "
            f"Failed to submit ranking: {e}"
        )

