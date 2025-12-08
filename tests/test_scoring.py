from __future__ import annotations

import json
import math
from typing import Any

import bittensor as bt
import pytest

from cartha_validator.config import DEFAULT_SETTINGS
from cartha_validator.scoring import score_entry
from cartha_validator import __spec_version__
from cartha_validator.weights import _normalize, publish


class DummySubtensor:
    def __init__(self, version_key: int = 1234) -> None:
        self.calls: list[dict[str, Any]] = []
        self.version_key = version_key

    def set_weights(
        self,
        wallet: Any,
        netuid: int,
        uids,
        weights,
        version_key: int,
        **kwargs,
    ):
        self.calls.append(
            {
                "wallet": wallet,
                "netuid": netuid,
                "uids": list(uids),
                "weights": list(weights),
                "version_key": version_key,
                "kwargs": kwargs,
            }
        )
        return True, "ok"

    def query_subtensor(self, key: str, params: list[Any]):
        if key == "WeightsVersionKey":
            return type("Resp", (), {"value": self.version_key})()
        raise KeyError(key)


class DummyWallet:
    pass


def test_score_entry_applies_weight_and_boost() -> None:
    settings = DEFAULT_SETTINGS.model_copy(update={
        "pool_weights": {"default": 2.0},
        "max_lock_days": 365,
        "score_temperature": 1000.0,
    })
    unit = 10 ** settings.token_decimals
    entry = {"default": {"amount": 1000 * unit, "lockDays": 180}}
    score = score_entry(entry, settings=settings)
    amount_tokens = 1000
    raw = 2.0 * amount_tokens * (180 / 365)
    expected = 1 - math.exp(-raw / settings.score_temperature)
    assert pytest.approx(score, rel=1e-6) == expected


def test_score_entry_clamps_lock_days() -> None:
    settings = DEFAULT_SETTINGS.model_copy(update={"max_lock_days": 90, "score_temperature": 1000.0})
    unit = 10 ** settings.token_decimals
    entry = {"default": {"amount": 500 * unit, "lockDays": 180}}
    score = score_entry(entry, settings=settings)
    raw = 500 * (90 / 90)
    expected = 1 - math.exp(-raw / settings.score_temperature)
    assert score == pytest.approx(expected)


def test_normalize_clamps_negative_scores() -> None:
    weights = _normalize({1: -5, 2: 5})
    assert weights[1] == 0.0
    assert pytest.approx(weights[2]) == 1.0


def test_publish_normalizes_and_calls_subtensor() -> None:
    subtensor = DummySubtensor(version_key=98765)
    wallet = DummyWallet()
    settings = DEFAULT_SETTINGS.model_copy(update={"netuid": 99})
    scores = {1: 10.0, 10: 30.0}
    epoch_version = "2024-10-18T00:00:00Z"

    weights = publish(
        scores,
        epoch_version=epoch_version,
        settings=settings,
        subtensor=subtensor,
        wallet=wallet,
    )

    expected_weights = {
        1: pytest.approx(0.25),
        10: pytest.approx(0.75),
    }
    for uid, value in expected_weights.items():
        assert weights[uid] == value

    assert len(subtensor.calls) == 1
    call = subtensor.calls[0]
    assert call["netuid"] == 99
    assert call["uids"] == [1, 10]
    assert call["weights"] == [pytest.approx(0.25), pytest.approx(0.75)]
    # Should use __spec_version__ directly (Bittensor chain will enforce version requirements)
    assert call["version_key"] == __spec_version__


def test_publish_raises_on_failure() -> None:
    class FailingSubtensor(DummySubtensor):
        def set_weights(self, *args, **kwargs):
            return False, "failed"

    with pytest.raises(RuntimeError):
        publish(
            {0: 1.0},
            epoch_version="2024-10-18T00:00:00Z",
            subtensor=FailingSubtensor(),
            force=False,
        )

def test_publish_uses_spec_version() -> None:
    """Test that publish uses __spec_version__ as version_key."""
    subtensor = DummySubtensor()
    wallet = DummyWallet()
    epoch_version = "2024-11-01T00:00:00Z"
    settings = DEFAULT_SETTINGS
    weights = publish(
        {0: 1.0},
        epoch_version=epoch_version,
        settings=settings,
        subtensor=subtensor,
        wallet=wallet,
        force=False,
    )
    assert weights[0] == 1.0
    call = subtensor.calls[0]
    # Should use __spec_version__ directly (Bittensor chain will enforce version requirements)
    assert call["version_key"] == __spec_version__


def test_multi_wallet_ranking_outputs_json(capfd) -> None:
    subtensor = DummySubtensor(version_key=22222)
    wallet = DummyWallet()
    settings = DEFAULT_SETTINGS.model_copy(
        update={
            "pool_weights": {"default": 1.0, "oil": 1.5},
            "max_lock_days": 365,
            "netuid": 77,
            "score_temperature": 1000.0,
        }
    )
    unit = 10 ** settings.token_decimals
    epoch_version = "2024-11-08T00:00:00Z"
    entries = [
        {
            "uid": 1,
            "hotkey": "bt1-hk1",
            "positions": {"default": {"amount": 1000 * unit, "lockDays": 180}},
        },
        {
            "uid": 10,
            "hotkey": "bt1-hk2",
            "positions": {
                "default": {"amount": 800 * unit, "lockDays": 365},
                "oil": {"amount": 500 * unit, "lockDays": 120},
            },
        },
        {
            "uid": 3,
            "hotkey": "bt1-hk3",
            "positions": {"default": {"amount": 400 * unit, "lockDays": 60}},
        },
    ]

    scores = {entry["uid"]: score_entry(entry["positions"], settings=settings) for entry in entries}
    raw_expectations = {
        1: 1.0 * 1000 * (180 / 365),
        10: (1.0 * 800 * (365 / 365)) + (1.5 * 500 * (120 / 365)),
        3: 1.0 * 400 * (60 / 365),
    }
    expected_scores = {
        uid: 1 - math.exp(-raw / settings.score_temperature) for uid, raw in raw_expectations.items()
    }
    for uid, expected_score in expected_scores.items():
        assert scores[uid] == pytest.approx(expected_score, rel=1e-9)

    weights = publish(
        scores,
        epoch_version=epoch_version,
        settings=settings,
        subtensor=subtensor,
        wallet=wallet,
        force=False,
    )

    expected_weights = _normalize(expected_scores)
    for uid, expected_weight in expected_weights.items():
        assert weights[uid] == pytest.approx(expected_weight, rel=1e-9)

    ranking = sorted(
        [
            {
                "uid": entry["uid"],
                "hotkey": entry["hotkey"],
                "score": scores[entry["uid"]],
                "weight": weights[entry["uid"]],
                "positions": entry["positions"],
            }
            for entry in entries
        ],
        key=lambda item: item["score"],
        reverse=True,
    )

    for index, item in enumerate(ranking, start=1):
        bt.logging.debug("Rank #%s => %s", index, item)

    def _format_positions(raw_positions):
        formatted: dict[str, dict[str, object]] = {}
        for pool_id, data in raw_positions.items():
            amount_raw = data.get("amount", 0)
            amount_tokens = amount_raw / unit
            formatted[pool_id] = {
                "amountRaw": amount_raw,
                "amountUSDC": f"{amount_tokens:,.6f} USDC",
                "lockDays": data.get("lockDays", 0),
            }
        return formatted

    json_output = json.dumps(
        [
            {
                **item,
                "score": round(item["score"], 6),
                "weight": round(item["weight"], 6),
                "positions": _format_positions(item["positions"]),
            }
            for item in ranking
        ],
        indent=2,
    )
    bt.logging.info("Ranking JSON:\n%s", json_output)
    print(json_output)

    assert ranking[0]["uid"] == 10
    assert ranking[1]["uid"] == 1
    assert ranking[2]["uid"] == 3
    assert ranking[0]["score"] == pytest.approx(expected_scores[10], rel=1e-9)
    assert ranking[1]["score"] == pytest.approx(expected_scores[1], rel=1e-9)
    assert ranking[2]["score"] == pytest.approx(expected_scores[3], rel=1e-9)
    assert ranking[0]["weight"] == pytest.approx(expected_weights[10], rel=1e-9)
    assert ranking[1]["weight"] == pytest.approx(expected_weights[1], rel=1e-9)
    assert ranking[2]["weight"] == pytest.approx(expected_weights[3], rel=1e-9)
    assert pytest.approx(sum(weights.values()), rel=1e-9) == 1.0

    out, _ = capfd.readouterr()
    assert '"uid": 10' in out
    assert '"weight":' in out
    # Re-emit captured output so it is visible when running with -s.
    print(out)
