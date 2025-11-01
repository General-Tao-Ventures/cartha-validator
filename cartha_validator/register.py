"""Registration helpers shared across services."""

from __future__ import annotations

import bittensor as bt


def ensure_registered(wallet_name: str, hotkey_name: str, netuid: int, network: str = "finney") -> int:
    """Ensure the given wallet is registered on the subnet and return the UID."""
    bt.logging.info("Ensuring registration for wallet=%s hotkey=%s netuid=%s", wallet_name, hotkey_name, netuid)
    subtensor = bt.subtensor(network=network)
    wallet = bt.wallet(name=wallet_name, hotkey=hotkey_name)
    hotkey = wallet.hotkey.ss58_address

    if not subtensor.is_hotkey_registered(hotkey, netuid):
        bt.logging.warning("Hotkey not registered; performing registration")
        ok = subtensor.register(wallet=wallet, netuid=netuid, wait_for_finalization=True, cuda=True)
        if not ok:
            bt.logging.error("Registration failed for hotkey %s", hotkey)
            raise RuntimeError("Registration failed")

    neuron = subtensor.get_neuron_for_pubkey_and_subnet(hotkey, netuid)
    bt.logging.info("Registration complete uid=%s", neuron.uid)
    return neuron.uid
