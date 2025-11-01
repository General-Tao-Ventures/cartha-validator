"""Weight publishing helpers."""

from __future__ import annotations

from typing import Mapping

import bittensor as bt


def publish_weights(weights: Mapping[int, float], netuid: int, subtensor: bt.Subtensor | None = None) -> None:
    """Publish weights to the Bittensor subnet."""
    if subtensor is None:
        subtensor = bt.subtensor()
    wallet = bt.wallet()
    uids = list(weights.keys())
    values = list(weights.values())
    bt.logging.info("Publishing weights for %s UIDs on netuid %s", len(uids), netuid)
    subtensor.set_weights(wallet=wallet, netuid=netuid, uids=uids, weights=values)
