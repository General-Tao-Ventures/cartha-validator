"""Validator entrypoint."""

from __future__ import annotations

import httpx

import bittensor as bt

from .scoring import score_entry
from .weights import publish_weights


def run_epoch(verifier_url: str, epoch: str, netuid: int) -> None:
    """Fetch verified miners, score, and publish weights (stub)."""
    bt.logging.info("Starting validator run for epoch %s", epoch)
    with httpx.Client(base_url=verifier_url) as client:
        response = client.get("/v1/verified-miners", params={"epoch": epoch})
        response.raise_for_status()
        entries = response.json()

    scores: dict[int, float] = {}
    for index, entry in enumerate(entries):
        position = entry.get("positions", {})
        scores[index] = score_entry(position)

    publish_weights(scores, netuid)


def main() -> None:
    run_epoch(verifier_url="http://localhost:8000", epoch="0", netuid=35)


if __name__ == "__main__":  # pragma: no cover
    main()
