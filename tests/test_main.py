from __future__ import annotations

from typing import Any

import pytest

from cartha_validator.config import DEFAULT_SETTINGS
from cartha_validator.main import process_entries


class DummyWeb3:
    class HTTPProvider:  # type: ignore[assignment]
        def __init__(self, url: str) -> None:
            self.url = url

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.eth = type("Eth", (), {"block_number": 500})()


@pytest.fixture(autouse=True)
def patch_web3(monkeypatch):
    monkeypatch.setattr("cartha_validator.main.Web3", DummyWeb3)
    yield


def _replay_stub(chain_id: int, vault: str, owner: str, at_block: int, web3=None):
    return {"default": {"amount": 1_000_000_000, "lockDays": 180}}


def test_process_entries_dry_run(monkeypatch):
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
        }
    ]

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            assert hotkey_ss58 == "bt1-hk1"
            return 1

    result = process_entries(
        entries,
        settings,
        epoch_version="2024-11-08T00:00:00Z",
        dry_run=True,
        replay_fn=_replay_stub,
        publish_fn=publish_stub,
        subtensor=SubtensorStub(),
    )

    assert not publish_calls
    weights = result["weights"]
    assert pytest.approx(sum(weights.values()), rel=1e-9) == 1.0
    ranking = result["ranking"]
    assert ranking[0]["uid"] == 1
    assert ranking[0]["weight"] == pytest.approx(1.0)
    summary = result["summary"]
    assert summary["scored"] == 1
    assert summary["failures"] == 0


def test_process_entries_publishes(monkeypatch):
    published: dict[int, float] = {}

    def publish_stub(scores, epoch_version, settings, subtensor=None, wallet=None, metagraph=None, validator_uid=None):
        assert epoch_version == "2024-11-08T00:00:00Z"
        published.update({uid: 0.5 for uid in scores})
        return {uid: 0.5 for uid in scores}

    settings = DEFAULT_SETTINGS.model_copy(
        update={"rpc_urls": {31337: "http://localhost:8545"}, "token_decimals": 6}
    )
    entries = [
        {
            "hotkey": "bt1-hk2",
            "slot_uid": "2",
            "chain_id": 31337,
            "vault": "0xVault",
            "evm": "0xOwner",
            "pool_id": "default",
            "snapshotBlock": 200,
        }
    ]

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            assert hotkey_ss58 == "bt1-hk2"
            return 2

    result = process_entries(
        entries,
        settings,
        epoch_version="2024-11-08T00:00:00Z",
        dry_run=False,
        replay_fn=_replay_stub,
        publish_fn=publish_stub,
        subtensor=SubtensorStub(),
    )

    assert published == {2: 0.5}
    assert result["weights"][2] == pytest.approx(0.5)
    assert result["ranking"][0]["weight"] == pytest.approx(0.5)
    summary = result["summary"]
    assert summary["scored"] == 1
    assert summary["failures"] == 0
