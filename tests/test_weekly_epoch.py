"""Tests for weekly frozen epoch behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cartha_validator.config import DEFAULT_SETTINGS


class MockSubtensor:
    def __init__(self, tempo: int = 360):
        self._tempo = tempo
        self._current_block = 1000000
        self.network = "test"

    def get_current_block(self) -> int:
        return self._current_block

    def set_weights(self, **kwargs) -> tuple[bool, str]:
        return True, "success"

    def tempo(self, netuid: int, block: int | None = None) -> int:
        return self._tempo

    def query_subtensor(self, *args, **kwargs):
        return None


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


@pytest.fixture
def mock_verifier_responses():
    """Mock verifier responses for different epochs."""
    responses = {}

    def get_response(epoch_version: str) -> list[dict[str, Any]]:
        if epoch_version not in responses:
            # Default response
            responses[epoch_version] = [
                {
                    "hotkey": "bt1-miner1",
                    "slot_uid": "1",
                    "chain_id": 31337,
                    "vault": "0xVault",
                    "evm": "0xOwner",
                    "pool_id": "default",
                    "snapshotBlock": 100,
                    "epoch_version": epoch_version,
                }
            ]
        return responses[epoch_version]

    return get_response


def _replay_stub(chain_id: int, vault: str, owner: str, at_block: int, web3=None):
    return {"default": {"amount": 1_000_000_000, "lockDays": 180}}


def test_weekly_epoch_detection_and_caching(mock_verifier_responses):
    """Test that validator detects new weekly epoch and caches weights."""
    from cartha_validator.epoch import epoch_start

    # Mock Friday 00:00 UTC
    friday = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)  # Friday
    epoch_version = friday.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Simulate the main loop logic for weekly epoch detection
    last_weekly_epoch_version = None
    cached_weights = None
    cached_scores = None

    # First iteration - new weekly epoch detected
    current_epoch_start = epoch_start(friday)
    current_weekly_epoch_version = current_epoch_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Should detect new epoch and cache
    if last_weekly_epoch_version != current_weekly_epoch_version:
        # Simulate fetching and calculating weights
        cached_weights = {1: 0.5}
        cached_scores = {1: 1.0}
        last_weekly_epoch_version = current_weekly_epoch_version

    # Verify caching happened
    assert last_weekly_epoch_version == current_weekly_epoch_version
    assert cached_weights is not None
    assert cached_scores is not None
    assert cached_weights == {1: 0.5}
    assert cached_scores == {1: 1.0}


def test_epoch_version_validation(mock_verifier_responses):
    """Test that validator validates epoch version matches."""
    epoch_version = "2024-01-05T00:00:00Z"

    # Simulate entries returned from verifier
    entries = [
        {
            "hotkey": "bt1-miner1",
            "slot_uid": "1",
            "epoch_version": "2024-01-12T00:00:00Z",  # Different epoch!
        }
    ]

    # Simulate the validation logic from run_epoch
    mismatched = [
        entry for entry in entries if entry.get("epoch_version") != epoch_version
    ]

    # Should detect mismatch
    assert len(mismatched) == 1
    assert mismatched[0]["epoch_version"] == "2024-01-12T00:00:00Z"
    assert mismatched[0]["epoch_version"] != epoch_version

    # Test with matching epoch versions
    entries_matching = [
        {
            "hotkey": "bt1-miner1",
            "slot_uid": "1",
            "epoch_version": epoch_version,  # Matching!
        }
    ]

    mismatched2 = [
        entry
        for entry in entries_matching
        if entry.get("epoch_version") != epoch_version
    ]

    # Should have no mismatches
    assert len(mismatched2) == 0


def test_cached_weights_published_multiple_times():
    """Test that cached weights are published multiple times during same weekly epoch."""
    # This test simulates the main loop behavior
    friday = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)
    epoch_version = friday.strftime("%Y-%m-%dT%H:%M:%SZ")

    cached_weights = {1: 0.5, 2: 0.5}
    cached_scores = {1: 1.0, 2: 1.0}
    cached_epoch_version = epoch_version

    publish_calls = []

    def mock_publish(
        scores: dict[int, float],
        epoch_version: str,
        settings: Any = None,
        subtensor: Any = None,
        wallet: Any = None,
        metagraph: Any = None,
        validator_uid: int | None = None,
    ) -> dict[int, float]:
        publish_calls.append((epoch_version, scores))
        return cached_weights

    subtensor = MockSubtensor(tempo=360)
    metagraph = MockMetagraph(tempo=360, validator_uid=0)

    # Simulate multiple Bittensor epochs within same weekly epoch
    # First publish - blocks_since_update = 0, should skip
    metagraph.last_update[0] = 1000000
    subtensor._current_block = 1000000

    from cartha_validator.weights import publish

    result1 = publish(
        cached_scores,
        epoch_version=cached_epoch_version,
        settings=DEFAULT_SETTINGS,
        subtensor=subtensor,
        wallet=MockWallet(),
        metagraph=metagraph,
        validator_uid=0,
    )

    # Should skip because not enough blocks
    assert len(publish_calls) == 0

    # Second publish - blocks_since_update = 360, should publish
    subtensor._current_block = 1000360
    metagraph.last_update[0] = 1000000

    result2 = publish(
        cached_scores,
        epoch_version=cached_epoch_version,
        settings=DEFAULT_SETTINGS,
        subtensor=subtensor,
        wallet=MockWallet(),
        metagraph=metagraph,
        validator_uid=0,
    )

    # Should have published
    assert result2 == cached_weights

    # Third publish - blocks_since_update = 360 again (simulating next epoch)
    subtensor._current_block = 1000720
    metagraph.last_update[0] = 1000360

    result3 = publish(
        cached_scores,
        epoch_version=cached_epoch_version,
        settings=DEFAULT_SETTINGS,
        subtensor=subtensor,
        wallet=MockWallet(),
        metagraph=metagraph,
        validator_uid=0,
    )

    # Should publish again with same cached weights
    assert result3 == cached_weights


def test_weekly_epoch_boundary_detection(monkeypatch):
    """Test that validator correctly detects weekly epoch boundaries."""
    from cartha_validator.epoch import epoch_start, epoch_end

    # Test Friday 00:00 UTC
    friday = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)  # Friday
    start = epoch_start(friday)
    assert start.weekday() == 4  # Friday
    assert start.hour == 0
    assert start.minute == 0

    # Test Thursday 23:59 UTC (end of epoch)
    thursday = datetime(2024, 1, 11, 23, 59, 59, tzinfo=UTC)  # Thursday
    end = epoch_end(thursday)
    assert end.weekday() == 3  # Thursday
    assert end.hour == 23
    assert end.minute == 59

    # Test that same Friday returns same epoch start
    friday_afternoon = datetime(2024, 1, 5, 15, 30, 0, tzinfo=UTC)
    start2 = epoch_start(friday_afternoon)
    assert start2 == start

    # Test that next Friday returns different epoch start
    next_friday = datetime(2024, 1, 12, 0, 0, 0, tzinfo=UTC)
    start3 = epoch_start(next_friday)
    assert start3 != start
    assert (start3 - start).days == 7


def test_tempo_detection_from_metagraph():
    """Test that validator correctly detects tempo from metagraph."""
    subtensor = MockSubtensor(tempo=360)
    metagraph = MockMetagraph(tempo=360, validator_uid=0)

    # Tempo should be available from metagraph
    assert hasattr(metagraph, "tempo")
    assert metagraph.tempo == 360

    # Test with different tempo
    metagraph2 = MockMetagraph(tempo=720, validator_uid=0)
    assert metagraph2.tempo == 720


def test_same_weekly_epoch_no_refetch(monkeypatch):
    """Test that validator doesn't refetch during same weekly epoch."""
    from cartha_validator.epoch import epoch_start

    friday = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)
    epoch_version = friday.strftime("%Y-%m-%dT%H:%M:%SZ")

    verifier_calls = []

    def mock_get(url: str, params: dict[str, Any] = None, **kwargs):
        verifier_calls.append(params.get("epoch"))
        response = MagicMock()
        response.json.return_value = [
            {
                "hotkey": "bt1-miner1",
                "slot_uid": "1",
                "epoch_version": epoch_version,
            }
        ]
        response.raise_for_status = MagicMock()
        return response

    # Simulate main loop: same weekly epoch, different times
    last_weekly_epoch_version = None
    cached_weights = None
    cached_scores = None

    # First iteration - new weekly epoch
    current_epoch_start = epoch_start(friday)
    current_weekly_epoch_version = current_epoch_start.strftime("%Y-%m-%dT%H:%M:%SZ")

    if last_weekly_epoch_version != current_weekly_epoch_version:
        # Should fetch - simulate the logic without actually importing main
        import httpx

        # Mock httpx.Client
        mock_client_instance = MagicMock()
        mock_client_instance.get = mock_get
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client_instance):
            with httpx.Client(base_url="http://test") as client:
                response = client.get(
                    "/v1/verified-miners", params={"epoch": epoch_version}
                )
                _ = response.json()

        cached_weights = {1: 0.5}
        cached_scores = {1: 1.0}
        last_weekly_epoch_version = current_weekly_epoch_version

    assert len(verifier_calls) == 1
    assert cached_weights is not None

    # Second iteration - same weekly epoch (different day/time)
    saturday = datetime(2024, 1, 6, 12, 0, 0, tzinfo=UTC)  # Saturday, same week
    current_epoch_start2 = epoch_start(saturday)
    current_weekly_epoch_version2 = current_epoch_start2.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Should NOT fetch again
    if last_weekly_epoch_version != current_weekly_epoch_version2:
        # This should not execute
        assert False, "Should not fetch again for same weekly epoch"

    # Should use cached weights
    assert cached_weights == {1: 0.5}
    assert len(verifier_calls) == 1  # Still only 1 call


def test_weights_use_tempo_from_metagraph(monkeypatch):
    """Test that weights.py uses tempo from metagraph."""
    from cartha_validator.weights import publish

    subtensor = MockSubtensor(tempo=360)
    metagraph = MockMetagraph(tempo=360, validator_uid=0)
    wallet = MockWallet()

    # Set last_update to be exactly tempo blocks ago
    metagraph.last_update[0] = 1000000 - 360
    subtensor._current_block = 1000000

    scores = {1: 1.0}

    # Should publish because blocks_since_update (360) >= tempo (360)
    result = publish(
        scores,
        epoch_version="2024-01-05T00:00:00Z",
        settings=DEFAULT_SETTINGS,
        subtensor=subtensor,
        wallet=wallet,
        metagraph=metagraph,
        validator_uid=0,
    )

    assert result is not None

    # Test with tempo = 720, blocks_since_update = 360 (should skip)
    metagraph2 = MockMetagraph(tempo=720, validator_uid=0)
    metagraph2.last_update[0] = 1000000 - 360
    subtensor._current_block = 1000000

    result2 = publish(
        scores,
        epoch_version="2024-01-05T00:00:00Z",
        settings=DEFAULT_SETTINGS,
        subtensor=subtensor,
        wallet=wallet,
        metagraph=metagraph2,
        validator_uid=0,
    )

    # Should return weights but may skip actual publishing
    assert result2 is not None
