"""Event replay helpers for validators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from hexbytes import HexBytes
from web3 import Web3

import bittensor as bt

from .config import DEFAULT_SETTINGS

_ABI_PATH = Path(__file__).resolve().parents[1] / "abis" / "vault.json"
try:
    _VAULT_ABI = json.loads(_ABI_PATH.read_text()).get("abi", [])
except FileNotFoundError:  # pragma: no cover
    _VAULT_ABI: List[Dict[str, Any]] = []


def lock_id(owner: str, pool_id: bytes) -> HexBytes:
    """Compute the deterministic lock identifier."""
    codec = Web3().codec
    return HexBytes(Web3.keccak(codec.encode(["address", "bytes32"], [owner, pool_id])))


def _decode_pool_id(raw: bytes) -> str:
    """Decode a bytes32 pool id into a human-readable string."""
    try:
        decoded = Web3.to_text(raw).rstrip("\x00")
        return decoded if decoded else Web3.to_hex(raw)
    except UnicodeDecodeError:
        return Web3.to_hex(raw)


def _get_web3(chain_id: int) -> Web3:
    """Lazy instantiate a Web3 provider using default settings."""
    rpc_url = DEFAULT_SETTINGS.rpc_urls.get(chain_id)
    if rpc_url is None:
        msg = f"No RPC URL configured for chain_id={chain_id}"
        bt.logging.error(msg)
        raise ValueError(msg)
    return Web3(Web3.HTTPProvider(rpc_url))


def _gather_events(
    contract: Any,
    lock: HexBytes,
    at_block: int,
) -> List[Dict[str, Any]]:
    """Collect all events for a given lock id up to a target block."""
    events: List[Dict[str, Any]] = []
    lock_filter = {"lockId": HexBytes(lock)}
    events.extend(
        contract.events.LockCreated().get_logs(
            fromBlock=0,
            toBlock=at_block,
            argument_filters=lock_filter,
        )
    )
    events.extend(
        contract.events.LockUpdated().get_logs(
            fromBlock=0,
            toBlock=at_block,
            argument_filters=lock_filter,
        )
    )
    events.extend(
        contract.events.LockReleased().get_logs(
            fromBlock=0,
            toBlock=at_block,
            argument_filters=lock_filter,
        )
    )
    events.sort(key=lambda ev: (ev["blockNumber"], ev["logIndex"]))
    return events


def replay_owner(
    chain_id: int,
    vault: str,
    owner: str,
    at_block: int,
    web3: Web3 | None = None,
) -> Dict[str, Dict[str, int]]:
    """Replay vault events for the owner and return Model-1 positions."""
    bt.logging.info(
        "Replaying events for owner=%s vault=%s chain=%s block=%s",
        owner,
        vault,
        chain_id,
        at_block,
    )

    provider = web3 or _get_web3(chain_id)
    contract = provider.eth.contract(
        address=Web3.to_checksum_address(vault),
        abi=_VAULT_ABI,
    )

    owner_checksum = Web3.to_checksum_address(owner)
    created_logs = contract.events.LockCreated().get_logs(
        fromBlock=0,
        toBlock=at_block,
        argument_filters={"owner": owner_checksum},
    )

    if not created_logs:
        bt.logging.debug("No LockCreated events found for owner %s", owner_checksum)
        return {}

    locks: Dict[HexBytes, Dict[str, Any]] = {}
    for created in created_logs:
        lock = HexBytes(created["args"]["lockId"])
        pool_key = _decode_pool_id(created["args"]["poolId"])
        locks.setdefault(lock, {"pool": pool_key, "events": []})["events"].append(created)

    results: Dict[str, Dict[str, int]] = {}
    for lock, info in locks.items():
        events = info["events"]
        events.extend(_gather_events(contract, lock, at_block))

        # Deduplicate events that might have been added twice (e.g., LockCreated)
        seen = set()
        unique_events: List[Dict[str, Any]] = []
        for ev in events:
            key = (ev["event"], ev["blockNumber"], ev["logIndex"])
            if key not in seen:
                seen.add(key)
                unique_events.append(ev)
        unique_events.sort(key=lambda ev: (ev["blockNumber"], ev["logIndex"]))

        amount = 0
        lock_days = 0
        for ev in unique_events:
            name = ev["event"]
            args = ev["args"]
            if name == "LockCreated":
                amount = int(args["amount"])
                lock_days = int(args["lockDays"])
            elif name == "LockUpdated":
                amount += int(args["deltaAmount"])
                lock_days = max(lock_days, int(args["newLockDays"]))
            elif name == "LockReleased":
                amount -= int(args["amount"])
                if amount < 0:
                    amount = 0
            else:  # pragma: no cover
                bt.logging.debug("Ignoring unknown event %s for lock %s", name, lock.hex())

        if amount > 0:
            results[info["pool"]] = {"amount": amount, "lockDays": lock_days}
            bt.logging.debug(
                "Lock %s pool=%s amount=%s lockDays=%s",
                lock.hex(),
                info["pool"],
                amount,
                lock_days,
            )

    return results
