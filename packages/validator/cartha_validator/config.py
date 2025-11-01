"""Configuration helpers for validator loop."""

from __future__ import annotations

from datetime import time
from typing import Mapping

from pydantic import BaseModel, Field


class PoolWeight(BaseModel):
    pool_id: str
    weight: float


class ValidatorSettings(BaseModel):
    rpc_urls: Mapping[int, str] = Field(default_factory=dict)
    pool_weights: Mapping[str, float] = Field(default_factory=dict)
    max_lock_days: int = 365
    epoch_start: time = time(hour=0, minute=0)


DEFAULT_SETTINGS = ValidatorSettings(
    rpc_urls={31337: "http://localhost:8545"},
    pool_weights={"default": 1.0},
    max_lock_days=365,
)
