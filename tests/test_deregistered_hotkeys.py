"""Tests for validator deregistered hotkeys handling."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from cartha_validator.config import DEFAULT_SETTINGS
from cartha_validator.processor import process_entries


class DummyWeb3:
    class HTTPProvider:  # type: ignore[assignment]
        def __init__(self, url: str) -> None:
            self.url = url

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.eth = type("Eth", (), {"block_number": 500})()


@pytest.fixture(autouse=True)
def patch_web3(monkeypatch):
    monkeypatch.setattr("cartha_validator.processor.Web3", DummyWeb3)
    yield


def _replay_stub(chain_id: int, vault: str, owner: str, at_block: int, web3=None):
    return {"default": {"amount": 1_000_000_000, "lockDays": 180}}


def test_process_entries_with_deregistered_hotkey_scores_zero(monkeypatch):
    """Test that validator scores all positions for deregistered hotkeys as 0."""
    publish_calls: list = []

    def publish_stub(*args, **kwargs):
        publish_calls.append((args, kwargs))
        return {1: 0.0}

    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
            "score_temperature": 1000.0,
        }
    )
    entries = [
        {
            "hotkey": "bt1-hk1",
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
        },
        {
            "hotkey": "bt1-hk1",  # Same hotkey, different pool
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault2",
            "evm": "0xOwner2",
            "pool_id": "pool2",
            "snapshotBlock": 100,
            "amount": 2000,
            "lock_days": 60,
        },
    ]

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            assert hotkey_ss58 == "bt1-hk1"
            return 1

    # Test with deregistered hotkey
    deregistered_hotkeys = {"bt1-hk1"}
    
    result = process_entries(
        entries,
        settings,
        epoch_version="2024-11-08T00:00:00Z",
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=publish_stub,
        subtensor=SubtensorStub(),
        use_verified_amounts=True,
        deregistered_hotkeys=deregistered_hotkeys,
    )

    # Should score 0 for deregistered hotkey
    weights = result["weights"]
    assert weights[1] == 0.0
    
    # Should have skipped both entries
    summary = result["summary"]
    assert summary["skipped"] == 2
    assert summary["expired_pools"] == 2  # Counted as expired pools
    assert summary["scored"] == 0


def test_process_entries_without_deregistered_hotkeys_scores_normally(monkeypatch):
    """Test that validator scores normally when no deregistered hotkeys."""
    publish_calls: list = []

    def publish_stub(*args, **kwargs):
        publish_calls.append((args, kwargs))
        return {1: 1.0}

    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
            "score_temperature": 1000.0,
        }
    )
    entries = [
        {
            "hotkey": "bt1-hk1",
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
        }
    ]

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            assert hotkey_ss58 == "bt1-hk1"
            return 1

    # Test without deregistered hotkeys
    deregistered_hotkeys = set()
    
    result = process_entries(
        entries,
        settings,
        epoch_version="2024-11-08T00:00:00Z",
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=publish_stub,
        subtensor=SubtensorStub(),
        use_verified_amounts=True,
        deregistered_hotkeys=deregistered_hotkeys,
    )

    # Should score normally (not 0)
    weights = result["weights"]
    assert weights[1] > 0.0
    
    summary = result["summary"]
    assert summary["scored"] == 1
    assert summary["skipped"] == 0


def test_process_entries_partial_deregistered_hotkeys(monkeypatch):
    """Test that only deregistered hotkeys score 0, others score normally."""
    publish_calls: list = []

    def publish_stub(*args, **kwargs):
        publish_calls.append((args, kwargs))
        scores = kwargs.get("scores", args[0])
        return {uid: score for uid, score in scores.items()}

    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
            "score_temperature": 1000.0,
        }
    )
    entries = [
        {
            "hotkey": "bt1-hk1",  # Deregistered
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
        },
        {
            "hotkey": "bt1-hk2",  # Not deregistered
            "slot_uid": "2",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner2",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
        },
    ]

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            if hotkey_ss58 == "bt1-hk1":
                return 1
            elif hotkey_ss58 == "bt1-hk2":
                return 2
            return -1

    # Only hotkey1 is deregistered
    deregistered_hotkeys = {"bt1-hk1"}
    
    result = process_entries(
        entries,
        settings,
        epoch_version="2024-11-08T00:00:00Z",
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=publish_stub,
        subtensor=SubtensorStub(),
        use_verified_amounts=True,
        deregistered_hotkeys=deregistered_hotkeys,
    )

    weights = result["weights"]
    # Hotkey1 (deregistered) should score 0
    assert weights[1] == 0.0
    # Hotkey2 (not deregistered) should score normally
    assert weights[2] > 0.0
    
    summary = result["summary"]
    assert summary["scored"] == 1  # Only hotkey2 scored
    assert summary["skipped"] == 1  # Hotkey1 skipped


def test_process_entries_deregistered_hotkeys_none_handles_gracefully(monkeypatch):
    """Test that None deregistered_hotkeys is handled gracefully."""
    publish_calls: list = []

    def publish_stub(*args, **kwargs):
        publish_calls.append((args, kwargs))
        return {1: 1.0}

    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
            "score_temperature": 1000.0,
        }
    )
    entries = [
        {
            "hotkey": "bt1-hk1",
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
        }
    ]

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            assert hotkey_ss58 == "bt1-hk1"
            return 1

    # Test with None (should be normalized to empty set)
    result = process_entries(
        entries,
        settings,
        epoch_version="2024-11-08T00:00:00Z",
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=publish_stub,
        subtensor=SubtensorStub(),
        use_verified_amounts=True,
        deregistered_hotkeys=None,  # None should be handled
    )

    # Should score normally
    weights = result["weights"]
    assert weights[1] > 0.0
    
    summary = result["summary"]
    assert summary["scored"] == 1
    assert summary["skipped"] == 0
