from hexbytes import HexBytes
from web3 import Web3

from cartha_validator.indexer import lock_id, replay_owner
from cartha_validator.scoring import score_entry


class FakeEventStream:
    def __init__(self, logs):
        self._logs = logs

    def get_logs(self, fromBlock, toBlock, argument_filters=None):
        argument_filters = argument_filters or {}
        filtered = []
        for log in self._logs:
            if fromBlock is not None and log["blockNumber"] < fromBlock:
                continue
            if toBlock is not None and log["blockNumber"] > toBlock:
                continue
            include = True
            for key, value in argument_filters.items():
                log_value = log["args"].get(key)
                if isinstance(log_value, str) and isinstance(value, str):
                    if log_value.lower() != value.lower():
                        include = False
                        break
                else:
                    if log_value != value:
                        include = False
                        break
            if include:
                filtered.append(log.copy())
        return filtered


class FakeEvents:
    def __init__(self, lock_created, lock_updated, lock_released):
        self._lock_created = lock_created
        self._lock_updated = lock_updated
        self._lock_released = lock_released

    def LockCreated(self):
        return FakeEventStream(self._lock_created)

    def LockUpdated(self):
        return FakeEventStream(self._lock_updated)

    def LockReleased(self):
        return FakeEventStream(self._lock_released)


class FakeContract:
    def __init__(self, lock_created, lock_updated, lock_released):
        self.events = FakeEvents(lock_created, lock_updated, lock_released)


class FakeEth:
    def __init__(self, contract):
        self._contract = contract

    def contract(self, address, abi):
        return self._contract


class FakeWeb3:
    def __init__(self, contract):
        self.eth = FakeEth(contract)


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


def _build_event(
    event_name: str,
    block_number: int,
    log_index: int,
    **args,
):
    return {
        "event": event_name,
        "blockNumber": block_number,
        "logIndex": log_index,
        "args": args,
    }


def _default_addresses() -> tuple[str, str]:
    owner = Web3.to_checksum_address("0x00000000000000000000000000000000000000Aa")
    vault = Web3.to_checksum_address("0x00000000000000000000000000000000000000Bb")
    return owner, vault


def _pool_bytes(label: str) -> bytes:
    return label.encode("utf-8").ljust(32, b"\x00")


def _replay(
    lock_created,
    lock_updated,
    lock_released,
):
    contract = FakeContract(lock_created, lock_updated, lock_released)
    fake_web3 = FakeWeb3(contract)
    owner, vault = _default_addresses()
    return replay_owner(
        chain_id=31337,
        vault=vault,
        owner=owner,
        at_block=999,
        web3=fake_web3,
    )


def test_replay_owner_handles_topup_inheriting_lockdays() -> None:
    owner, _ = _default_addresses()
    pool = _pool_bytes("default")
    key = lock_id(owner, pool)
    created = [
        _build_event(
            "LockCreated",
            block_number=1,
            log_index=0,
            lockId=key,
            owner=owner,
            poolId=pool,
            vault="0xVault",
            amount=100,
            start=0,
            lockDays=30,
            maxLockDays=365,
        )
    ]
    updated = [
        _build_event(
            "LockUpdated",
            block_number=2,
            log_index=0,
            lockId=key,
            deltaAmount=50,
            newLockDays=30,
        )
    ]
    released = []

    result = _replay(created, updated, released)
    assert result == {"default": {"amount": 150, "lockDays": 30}}


def test_replay_owner_handles_lock_extension() -> None:
    owner, _ = _default_addresses()
    pool = _pool_bytes("default")
    key = lock_id(owner, pool)
    created = [
        _build_event(
            "LockCreated",
            block_number=5,
            log_index=0,
            lockId=key,
            owner=owner,
            poolId=pool,
            vault="0xVault",
            amount=200,
            start=0,
            lockDays=45,
            maxLockDays=365,
        )
    ]
    updated = [
        _build_event(
            "LockUpdated",
            block_number=6,
            log_index=0,
            lockId=key,
            deltaAmount=0,
            newLockDays=120,
        )
    ]

    result = _replay(created, updated, [])
    assert result == {"default": {"amount": 200, "lockDays": 120}}


def test_replay_owner_handles_partial_release() -> None:
    owner, _ = _default_addresses()
    pool = _pool_bytes("default")
    key = lock_id(owner, pool)
    created = [
        _build_event(
            "LockCreated",
            block_number=10,
            log_index=0,
            lockId=key,
            owner=owner,
            poolId=pool,
            vault="0xVault",
            amount=300,
            start=0,
            lockDays=90,
            maxLockDays=365,
        )
    ]
    updated = [
        _build_event(
            "LockUpdated",
            block_number=12,
            log_index=0,
            lockId=key,
            deltaAmount=-120,
            newLockDays=90,
        )
    ]
    released = [
        _build_event(
            "LockReleased",
            block_number=15,
            log_index=0,
            lockId=key,
            to=owner,
            amount=30,
        )
    ]

    result = _replay(created, updated, released)
    assert result == {"default": {"amount": 150, "lockDays": 90}}


def test_replay_owner_multi_pool_support() -> None:
    owner, _ = _default_addresses()
    pool_a = _pool_bytes("default")
    pool_b = _pool_bytes("oil")
    lock_a = lock_id(owner, pool_a)
    lock_b = lock_id(owner, pool_b)

    created = [
        _build_event(
            "LockCreated",
            block_number=1,
            log_index=0,
            lockId=lock_a,
            owner=owner,
            poolId=pool_a,
            vault="0xVault",
            amount=100,
            start=0,
            lockDays=30,
            maxLockDays=365,
        ),
        _build_event(
            "LockCreated",
            block_number=2,
            log_index=0,
            lockId=lock_b,
            owner=owner,
            poolId=pool_b,
            vault="0xVault",
            amount=500,
            start=0,
            lockDays=60,
            maxLockDays=365,
        ),
    ]
    updated = [
        _build_event(
            "LockUpdated",
            block_number=3,
            log_index=0,
            lockId=lock_a,
            deltaAmount=50,
            newLockDays=45,
        ),
        _build_event(
            "LockUpdated",
            block_number=4,
            log_index=0,
            lockId=lock_b,
            deltaAmount=-100,
            newLockDays=60,
        ),
    ]
    released = []

    result = _replay(created, updated, released)
    assert result == {
        "default": {"amount": 150, "lockDays": 45},
        "oil": {"amount": 400, "lockDays": 60},
    }
