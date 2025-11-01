import sys
from pathlib import Path

from hexbytes import HexBytes
from web3 import Web3

sys.path.append(str(Path(__file__).resolve().parents[1]))

from cartha_validator.indexer import lock_id
from cartha_validator.scoring import score_entry


def test_lock_id_deterministic() -> None:
    owner = "0x0000000000000000000000000000000000000001"
    pool = b"default".ljust(32, b"\x00")
    codec = Web3().codec
    expected = Web3.keccak(codec.encode(["address", "bytes32"], [owner, pool]))
    assert lock_id(owner, pool) == HexBytes(expected)


def test_score_entry_basic() -> None:
    position = {"default": {"amount": 1000, "lockDays": 180}}
    score = score_entry(position)
    assert score > 0
