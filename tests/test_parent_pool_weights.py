"""Tests for the parent-vault scoring path.

Covers:
- ``PARENT_VAULT_TO_CHILD_POOLS`` registry shape
- ``_augment_with_parent_weights`` arithmetic
- ``get_pool_weights_for_scoring`` (PRE-DEX) returns parent entries with the
  expected averaged weight
- Per-dollar scoring parity between a parent-vault lock and a single-child
  lock in PRE-DEX mode
- ``process_entries`` and ``format_positions`` pass ``vault_type`` through
"""

from __future__ import annotations

import pytest

from cartha_validator.config import DEFAULT_SETTINGS
from cartha_validator.pool_weights import (
    ALL_KNOWN_PARENT_VAULTS,
    ALL_KNOWN_POOLS,
    PARENT_VAULT_TO_CHILD_POOLS,
    _augment_with_parent_weights,
    get_pool_weights_for_scoring,
)
from cartha_validator.processor import format_positions, process_entries
from cartha_validator.scoring import score_entry


CRYPTO_PARENT = "0x7c5fac6a0295663686873e418406cf540c45ccf3"
CURRENCIES_PARENT = "0xf69eedf403c9db553e1d1dcc29b31d0c3e7c58f3"
COMMODITIES_PARENT = "0xa265777b6241143c752d37025bb4de4b3e311a19"

BTC_POOL = "0xee62665949c883f9e0f6f002eac32e00bd59dfe6c34e92a91c37d6a8322d6489"
ETH_POOL = "0x0b43555ace6b39aae1b894097d0a9fc17f504c62fea598fa206cc6f5088e6e45"
TAO_POOL = "0x92672906cbedad5b67ba80d7e4361725ef6b8fa45eb9dd04b335529420e01a7f"
GOLD_POOL = "0x5656b83664973a9b4e2c18d45b7578e6746ee4a565da62e3ac579fb9e05acc55"
SILVER_POOL = "0x3b66bf6918c0338548861fe0d3e82a1251710d12aa866a34d4bfc0a9b6a5d73c"


# ──────────────────────────────────────────────────────────────────────────────
# Registry shape
# ──────────────────────────────────────────────────────────────────────────────


def test_parent_registry_keys_lowercased() -> None:
    """Parent keys must be lowercased — that's how the verifier stores them
    on the verified_miners.pool_id column for parent rows."""
    for parent_addr in PARENT_VAULT_TO_CHILD_POOLS:
        assert parent_addr == parent_addr.lower(), parent_addr
    for parent_addr in ALL_KNOWN_PARENT_VAULTS:
        assert parent_addr == parent_addr.lower(), parent_addr


def test_parent_registry_covers_all_three_categories() -> None:
    assert set(PARENT_VAULT_TO_CHILD_POOLS) == {
        CRYPTO_PARENT,
        CURRENCIES_PARENT,
        COMMODITIES_PARENT,
    }
    assert len(PARENT_VAULT_TO_CHILD_POOLS[CRYPTO_PARENT]) == 3
    assert len(PARENT_VAULT_TO_CHILD_POOLS[CURRENCIES_PARENT]) == 3
    assert len(PARENT_VAULT_TO_CHILD_POOLS[COMMODITIES_PARENT]) == 2


def test_every_parents_children_are_in_all_known_pools() -> None:
    for parent_addr, children in PARENT_VAULT_TO_CHILD_POOLS.items():
        for child in children:
            assert child in ALL_KNOWN_POOLS, (
                f"{parent_addr}'s child {child} missing from ALL_KNOWN_POOLS"
            )


# ──────────────────────────────────────────────────────────────────────────────
# _augment_with_parent_weights — average rule
# ──────────────────────────────────────────────────────────────────────────────


def test_augment_pre_dex_equal_weights_keeps_parents_at_one() -> None:
    """In PRE-DEX every child is 1.0, so parent average is also 1.0."""
    child_weights = {pool_id: 1.0 for pool_id in ALL_KNOWN_POOLS}
    augmented = _augment_with_parent_weights(child_weights)
    for parent_addr in ALL_KNOWN_PARENT_VAULTS:
        assert augmented[parent_addr] == 1.0


def test_augment_post_dex_parent_is_arithmetic_mean() -> None:
    """When children have varying weights, parent = mean(children)."""
    # Synthetic POST-DEX-like weights — Crypto children at 0.20/0.10/0.30,
    # Commodities at 0.40/0.20.
    child_weights = {
        BTC_POOL: 0.20,
        ETH_POOL: 0.10,
        TAO_POOL: 0.30,
        GOLD_POOL: 0.40,
        SILVER_POOL: 0.20,
    }
    augmented = _augment_with_parent_weights(child_weights)
    assert augmented[CRYPTO_PARENT] == pytest.approx((0.20 + 0.10 + 0.30) / 3)
    assert augmented[COMMODITIES_PARENT] == pytest.approx((0.40 + 0.20) / 2)


def test_augment_falls_back_when_parent_has_no_children_in_input() -> None:
    """If we somehow have no child weights for a parent, default to 1.0 so the
    parent row still scores rather than getting 0.0."""
    augmented = _augment_with_parent_weights({})
    for parent_addr in ALL_KNOWN_PARENT_VAULTS:
        assert augmented[parent_addr] == 1.0


def test_augment_does_not_mutate_input() -> None:
    child_weights = {BTC_POOL: 1.0}
    _augment_with_parent_weights(child_weights)
    assert child_weights == {BTC_POOL: 1.0}


# ──────────────────────────────────────────────────────────────────────────────
# get_pool_weights_for_scoring (PRE-DEX path)
# ──────────────────────────────────────────────────────────────────────────────


def test_pre_dex_weights_include_parents() -> None:
    weights = get_pool_weights_for_scoring(
        parent_vault_address="ignored",
        rpc_url="http://localhost:8545",
    )
    assert len(weights) == len(ALL_KNOWN_POOLS) + len(ALL_KNOWN_PARENT_VAULTS)
    for parent_addr in ALL_KNOWN_PARENT_VAULTS:
        assert weights[parent_addr] == 1.0
    for child_pool in ALL_KNOWN_POOLS:
        assert weights[child_pool] == 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Scoring — per-dollar parity between parent and child locks in PRE-DEX
# ──────────────────────────────────────────────────────────────────────────────


def test_parent_lock_scores_same_as_child_lock_in_pre_dex() -> None:
    """A $1000 lock to the Crypto parent should score the same as a $1000
    lock to cvBTC in PRE-DEX mode (both pool_weights = 1.0)."""
    pool_weights = get_pool_weights_for_scoring(
        parent_vault_address="ignored",
        rpc_url="http://localhost:8545",
    )
    settings = DEFAULT_SETTINGS.model_copy(update={
        "pool_weights": pool_weights,
        "max_lock_days": 365,
    })
    unit = 10 ** settings.token_decimals
    amount = 1000 * unit
    lock_days = 180

    parent_entry = {
        f"{CRYPTO_PARENT}#0": {
            "amount": amount,
            "lockDays": lock_days,
            "pool_id": CRYPTO_PARENT,
        }
    }
    child_entry = {
        f"{BTC_POOL}#0": {
            "amount": amount,
            "lockDays": lock_days,
            "pool_id": BTC_POOL,
        }
    }
    parent_score = score_entry(parent_entry, settings=settings)
    child_score = score_entry(child_entry, settings=settings)

    assert pytest.approx(parent_score, rel=1e-9) == child_score
    # And both should equal the formula: 1000 * 180/365 with weight 1.0
    assert pytest.approx(parent_score, rel=1e-9) == 1000 * (180 / 365)


def test_parent_lock_in_post_dex_scores_average() -> None:
    """In POST-DEX-like settings, a parent lock scores at the children's
    average — not the sum."""
    # Synthetic Crypto children weights (sum to ~1.0 within parent for
    # demonstration; exact normalisation depends on POST-DEX query).
    child_weights = {
        BTC_POOL: 0.40,
        ETH_POOL: 0.30,
        TAO_POOL: 0.30,
    }
    weights = _augment_with_parent_weights(child_weights)
    assert weights[CRYPTO_PARENT] == pytest.approx((0.40 + 0.30 + 0.30) / 3)

    settings = DEFAULT_SETTINGS.model_copy(update={
        "pool_weights": weights,
        "max_lock_days": 365,
    })
    unit = 10 ** settings.token_decimals
    amount = 1000 * unit
    lock_days = 365

    parent_entry = {
        f"{CRYPTO_PARENT}#0": {
            "amount": amount,
            "lockDays": lock_days,
            "pool_id": CRYPTO_PARENT,
        }
    }
    score = score_entry(parent_entry, settings=settings)
    expected = ((0.40 + 0.30 + 0.30) / 3) * 1000 * (365 / 365)
    assert pytest.approx(score, rel=1e-9) == expected


def test_parent_lock_does_not_get_summed_weight() -> None:
    """Regression guard: parent must not get sum(children) weight."""
    child_weights = {
        BTC_POOL: 1.0,
        ETH_POOL: 1.0,
        TAO_POOL: 1.0,
    }
    weights = _augment_with_parent_weights(child_weights)
    # If we summed, parent weight would be 3.0; we want 1.0.
    assert weights[CRYPTO_PARENT] != pytest.approx(3.0)
    assert weights[CRYPTO_PARENT] == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────────────
# vault_type pass-through (processor → format_positions)
# ──────────────────────────────────────────────────────────────────────────────


def test_format_positions_emits_vault_type_default_child() -> None:
    positions = {f"{BTC_POOL}#0": {"amount": 1_000_000, "lockDays": 30, "pool_id": BTC_POOL}}
    formatted = format_positions(positions, unit=1_000_000.0)
    assert formatted[f"{BTC_POOL}#0"]["vaultType"] == "child"


def test_format_positions_emits_vault_type_parent() -> None:
    positions = {
        f"{CRYPTO_PARENT}#0": {
            "amount": 1_000_000,
            "lockDays": 30,
            "pool_id": CRYPTO_PARENT,
            "vault_type": "parent",
        }
    }
    formatted = format_positions(positions, unit=1_000_000.0)
    assert formatted[f"{CRYPTO_PARENT}#0"]["vaultType"] == "parent"
    assert formatted[f"{CRYPTO_PARENT}#0"]["pool_id"] == CRYPTO_PARENT


def test_process_entries_passes_vault_type_into_combined_positions() -> None:
    """When the verifier API returns vault_type='parent', it should appear in
    the combined_positions entry that downstream scoring/leaderboards see."""

    class SubtensorStub:
        def get_uid_for_hotkey_on_subnet(self, hotkey_ss58: str, netuid: int) -> int:
            return 7

    settings = DEFAULT_SETTINGS.model_copy(update={
        "pool_weights": {CRYPTO_PARENT: 1.0},
        "max_lock_days": 365,
    })
    entry = {
        "hotkey": "5xxx",
        "slot_uid": "7",
        "amount": 5_000_000,
        "lock_days": 90,
        "pool_id": CRYPTO_PARENT,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "epoch_version": "test",
        "vault_type": "parent",
    }
    result = process_entries(
        [entry],
        settings,
        epoch_version="test",
        use_verified_amounts=True,
        subtensor=SubtensorStub(),
        dry_run=True,
        publish_fn=lambda *a, **kw: {},
    )
    ranking = result["ranking"]
    assert len(ranking) == 1
    # `process_entries` returns the raw combined_positions dict; format_positions
    # is applied later by epoch_runner.py when it builds the leaderboard JSON.
    raw_positions = ranking[0]["positions"]
    pos_key = next(iter(raw_positions))
    assert raw_positions[pos_key]["vault_type"] == "parent"
    assert raw_positions[pos_key]["pool_id"] == CRYPTO_PARENT
    # And once format_positions runs, the vault_type pass-through becomes
    # `vaultType` (camelCase) on the leaderboard payload.
    formatted = format_positions(raw_positions, unit=10 ** settings.token_decimals)
    assert formatted[pos_key]["vaultType"] == "parent"
