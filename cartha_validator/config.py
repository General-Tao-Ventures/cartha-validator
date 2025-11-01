"""Configuration helpers for validator loop."""

from __future__ import annotations

from datetime import time
from typing import Mapping

from pydantic import BaseModel, Field, HttpUrl


class ValidatorSettings(BaseModel):
    """Typed configuration for validator components."""

    netuid: int = 35
    verifier_url: HttpUrl | str = "http://localhost:8000"
    rpc_urls: Mapping[int, str] = Field(default_factory=dict)
    pool_weights: Mapping[str, float] = Field(default_factory=dict)
    max_lock_days: int = 365
    token_decimals: int = 6
    score_temperature: float = 1000.0
    epoch_weekday: int = 4  # Friday
    epoch_time: time = time(hour=0, minute=0)
    epoch_timezone: str = "UTC"


DEFAULT_SETTINGS = ValidatorSettings(
    rpc_urls={31337: "http://localhost:8545"},
    pool_weights={"default": 1.0},
    max_lock_days=365,
)
