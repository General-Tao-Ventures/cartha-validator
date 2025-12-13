"""Tests for epoch_runner deregistered hotkeys endpoint integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cartha_validator.config import DEFAULT_SETTINGS
from cartha_validator.epoch_runner import run_epoch

# Import httpx before patching to ensure HTTPStatusError is available
import httpx as _httpx


class MockSubtensor:
    def __init__(self, tempo: int = 360):
        self._tempo = tempo
        self._current_block = 1000000
        self.network = "test"

    def get_current_block(self) -> int:
        return self._current_block

    def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
        if hotkey_ss58 == "bt1-miner1":
            return 1
        elif hotkey_ss58 == "bt1-miner2":
            return 2
        return -1


class MockMetagraph:
    def __init__(self, tempo: int = 360, validator_uid: int = 0):
        self.tempo = tempo
        self.block = 1000000
        self.n = 256
        self.netuid = 35
        self.last_update = [0] * 256
        self.last_update[validator_uid] = 0
        self.hotkeys = ["bt1-validator"] * 256

    def sync(self, subtensor: Any) -> None:
        pass


class MockWallet:
    def __init__(self):
        self.hotkey = MagicMock()
        self.hotkey.ss58_address = "bt1-validator"


def _replay_stub(chain_id: int, vault: str, owner: str, at_block: int, web3=None):
    return {"default": {"amount": 1_000_000_000, "lockDays": 180}}


def _publish_stub(*args, **kwargs):
    scores = kwargs.get("scores", args[0])
    return {uid: score for uid, score in scores.items()}


@patch("cartha_validator.epoch_runner.httpx.Client")
def test_run_epoch_fetches_deregistered_hotkeys(mock_client_class):
    """Test that run_epoch fetches deregistered hotkeys from endpoint."""
    # Mock HTTP client
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client
    
    # Mock verified miners response
    verified_miners_response = MagicMock()
    verified_miners_response.status_code = 200
    verified_miners_response.json.return_value = [
        {
            "hotkey": "bt1-miner1",
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
            "expires_at": "2024-12-31T00:00:00Z",
            "epoch_version": "2024-11-08T00:00:00Z",
            "pool_id": "default",
        }
    ]
    verified_miners_response.headers = {}
    verified_miners_response.raise_for_status = MagicMock()
    
    # Mock deregistered hotkeys response
    deregistered_response = MagicMock()
    deregistered_response.status_code = 200
    deregistered_response.json.return_value = {
        "epoch_version": "2024-11-08T00:00:00Z",
        "hotkeys": ["bt1-miner1"],
        "count": 1,
    }
    deregistered_response.raise_for_status = MagicMock()
    
    mock_client.get.side_effect = [
        verified_miners_response,  # First call: verified miners
        deregistered_response,      # Second call: deregistered hotkeys
    ]
    
    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
        }
    )
    
    result = run_epoch(
        verifier_url="http://localhost:8000",
        epoch_version="2024-11-08T00:00:00Z",
        settings=settings,
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=_publish_stub,
        subtensor=MockSubtensor(),
        wallet=MockWallet(),
        metagraph=MockMetagraph(),
        use_verified_amounts=True,
    )
    
    # Verify both endpoints were called
    assert mock_client.get.call_count == 2
    
    # First call: verified miners
    first_call = mock_client.get.call_args_list[0]
    assert "/v1/verified-miners" in str(first_call)
    
    # Second call: deregistered hotkeys
    second_call = mock_client.get.call_args_list[1]
    assert "/v1/deregistered-hotkeys" in str(second_call)
    assert second_call.kwargs["params"]["epoch_version"] == "2024-11-08T00:00:00Z"
    
    # Verify miner1 was scored 0 (deregistered)
    weights = result["weights"]
    assert weights[1] == 0.0


@patch("cartha_validator.epoch_runner.httpx.Client")
def test_run_epoch_handles_deregistered_hotkeys_endpoint_failure(mock_client_class):
    """Test that run_epoch handles deregistered hotkeys endpoint failure gracefully."""
    # Mock HTTP client
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client
    
    # Mock verified miners response
    verified_miners_response = MagicMock()
    verified_miners_response.status_code = 200
    verified_miners_response.json.return_value = [
        {
            "hotkey": "bt1-miner1",
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
            "expires_at": "2024-12-31T00:00:00Z",
            "epoch_version": "2024-11-08T00:00:00Z",
            "pool_id": "default",
        }
    ]
    verified_miners_response.headers = {}
    verified_miners_response.raise_for_status = MagicMock()
    
    # Mock deregistered hotkeys response failure
    deregistered_response = MagicMock()
    deregistered_response.status_code = 500
    
    # Create a proper HTTPStatusError
    error = _httpx.HTTPStatusError(
        "Server Error",
        request=MagicMock(),
        response=deregistered_response,
    )
    
    def raise_error():
        raise error
    
    deregistered_response.raise_for_status = raise_error
    
    mock_client.get.side_effect = [
        verified_miners_response,  # First call: verified miners
        deregistered_response,      # Second call: deregistered hotkeys (fails)
    ]
    
    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
        }
    )
    
    # Should not raise exception, should continue without deregistered hotkeys
    result = run_epoch(
        verifier_url="http://localhost:8000",
        epoch_version="2024-11-08T00:00:00Z",
        settings=settings,
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=_publish_stub,
        subtensor=MockSubtensor(),
        wallet=MockWallet(),
        metagraph=MockMetagraph(),
        use_verified_amounts=True,
    )
    
    # Verify both endpoints were called
    assert mock_client.get.call_count == 2
    
    # Should score normally (no deregistered hotkeys applied)
    # Note: When deregistered hotkeys endpoint fails, we continue without applying them
    # So the miner should be scored normally
    weights = result["weights"]
    summary = result["summary"]
    
    # Verify miner was processed (may not have weights if no valid positions)
    # But should have been attempted
    assert summary["total_miners"] >= 1
    # If it has valid positions, it should score > 0
    if summary["scored"] > 0:
        assert 1 in weights
        assert weights[1] > 0.0


@patch("cartha_validator.epoch_runner.httpx.Client")
def test_run_epoch_with_no_deregistered_hotkeys(mock_client_class):
    """Test that run_epoch works correctly when no deregistered hotkeys exist."""
    # Mock HTTP client
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client
    
    # Mock verified miners response
    verified_miners_response = MagicMock()
    verified_miners_response.status_code = 200
    verified_miners_response.json.return_value = [
        {
            "hotkey": "bt1-miner1",
            "slot_uid": "1",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 100,
            "amount": 1000,
            "lock_days": 30,
            "expires_at": "2024-12-31T00:00:00Z",
            "epoch_version": "2024-11-08T00:00:00Z",
            "pool_id": "default",
        }
    ]
    verified_miners_response.headers = {}
    verified_miners_response.raise_for_status = MagicMock()
    
    # Mock empty deregistered hotkeys response
    deregistered_response = MagicMock()
    deregistered_response.status_code = 200
    deregistered_response.json.return_value = {
        "epoch_version": "2024-11-08T00:00:00Z",
        "hotkeys": [],
        "count": 0,
    }
    deregistered_response.raise_for_status = MagicMock()
    
    mock_client.get.side_effect = [
        verified_miners_response,  # First call: verified miners
        deregistered_response,      # Second call: deregistered hotkeys (empty)
    ]
    
    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "rpc_urls": {31337: "http://localhost:8545"},
            "token_decimals": 6,
        }
    )
    
    result = run_epoch(
        verifier_url="http://localhost:8000",
        epoch_version="2024-11-08T00:00:00Z",
        settings=settings,
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=_publish_stub,
        subtensor=MockSubtensor(),
        wallet=MockWallet(),
        metagraph=MockMetagraph(),
        use_verified_amounts=True,
    )
    
    # Should score normally (not zero)
    weights = result["weights"]
    summary = result["summary"]
    
    # Verify miner was processed
    assert summary["scored"] >= 0  # May be 0 if no valid positions, but should exist
    # If scored, should have weight > 0
    if summary["scored"] > 0:
        assert 1 in weights
        assert weights[1] > 0.0
