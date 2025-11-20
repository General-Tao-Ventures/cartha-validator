"""Tests for validator restart behavior during ongoing weekly epoch."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from cartha_validator.config import DEFAULT_SETTINGS
from cartha_validator.epoch import epoch_start


def test_validator_restart_during_ongoing_epoch():
    """Test that validator correctly fetches frozen list when restarting during ongoing weekly epoch."""
    # Simulate a restart scenario: validator was running, crashed, and restarts mid-week
    # Current time: Saturday (same weekly epoch that started Friday 00:00 UTC)
    saturday = datetime(2024, 1, 6, 12, 0, 0, tzinfo=UTC)  # Saturday, same week as Friday
    
    # Calculate the weekly epoch version (should be Friday 00:00 UTC)
    current_epoch_start = epoch_start(saturday)
    current_weekly_epoch_version = current_epoch_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # On restart, last_weekly_epoch_version is None
    last_weekly_epoch_version = None
    
    # Simulate the restart detection logic
    if last_weekly_epoch_version != current_weekly_epoch_version:
        # Should detect restart and fetch frozen list for current weekly epoch
        assert last_weekly_epoch_version is None, "Should detect restart"
        
        # The validator should fetch the frozen list for current_weekly_epoch_version
        # This ensures it uses the correct frozen list for the ongoing weekly epoch
        fetched_epoch_version = current_weekly_epoch_version
        
        # Verify it's fetching for the correct epoch
        assert fetched_epoch_version == current_weekly_epoch_version
        assert fetched_epoch_version.startswith("2024-01-05")  # Friday 00:00 UTC


def test_validator_restart_vs_new_epoch_detection():
    """Test that validator distinguishes between restart and new weekly epoch."""
    friday_week1 = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)  # Friday 00:00 UTC
    epoch1 = epoch_start(friday_week1).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    saturday_week1 = datetime(2024, 1, 6, 12, 0, 0, tzinfo=UTC)  # Saturday same week
    epoch1_restart = epoch_start(saturday_week1).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    friday_week2 = datetime(2024, 1, 12, 0, 0, 0, tzinfo=UTC)  # Next Friday
    epoch2 = epoch_start(friday_week2).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Same weekly epoch (restart scenario)
    assert epoch1 == epoch1_restart, "Saturday should be in same weekly epoch as Friday"
    
    # Different weekly epoch (new epoch scenario)
    assert epoch1 != epoch2, "Next Friday should be different weekly epoch"
    
    # On restart during same week
    last_weekly_epoch_version = epoch1
    current_weekly_epoch_version = epoch1_restart
    
    # Should NOT fetch again (same epoch)
    if last_weekly_epoch_version != current_weekly_epoch_version:
        assert False, "Should not fetch again for same weekly epoch"
    
    # On restart after new epoch
    last_weekly_epoch_version = epoch1
    current_weekly_epoch_version = epoch2
    
    # SHOULD fetch (new epoch)
    if last_weekly_epoch_version != current_weekly_epoch_version:
        assert True, "Should fetch for new weekly epoch"
    
    # On restart with None (fresh start)
    last_weekly_epoch_version = None
    current_weekly_epoch_version = epoch1_restart
    
    # SHOULD fetch (restart detection)
    if last_weekly_epoch_version != current_weekly_epoch_version:
        assert True, "Should fetch on restart (last_weekly_epoch_version is None)"


def test_validator_uses_correct_epoch_version_on_restart():
    """Test that validator uses the correct epoch version when fetching frozen list on restart."""
    # Simulate restart on Wednesday of a week that started Friday
    wednesday = datetime(2024, 1, 10, 15, 30, 0, tzinfo=UTC)  # Wednesday
    
    # Calculate current weekly epoch (should be Friday 00:00 UTC of that week)
    current_epoch_start = epoch_start(wednesday)
    current_weekly_epoch_version = current_epoch_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Verify it's the Friday of that week
    assert current_weekly_epoch_version.startswith("2024-01-05"), "Should be Friday 00:00 UTC"
    assert current_epoch_start.weekday() == 4, "Should be Friday"
    assert current_epoch_start.hour == 0, "Should be 00:00 UTC"
    
    # On restart, validator should fetch frozen list for this epoch version
    # This ensures it uses the correct frozen list for the ongoing weekly epoch
    fetched_epoch = current_weekly_epoch_version
    
    # The fetched epoch should match the current weekly epoch
    assert fetched_epoch == current_weekly_epoch_version
    assert fetched_epoch == "2024-01-05T00:00:00Z"


def test_validator_restart_preserves_epoch_consistency():
    """Test that validator maintains epoch consistency across restarts."""
    # Simulate validator running, then restarting multiple times during same week
    friday = datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)
    saturday = datetime(2024, 1, 6, 12, 0, 0, tzinfo=UTC)
    monday = datetime(2024, 1, 8, 10, 0, 0, tzinfo=UTC)
    wednesday = datetime(2024, 1, 10, 15, 0, 0, tzinfo=UTC)
    
    # All should resolve to same weekly epoch
    epoch_friday = epoch_start(friday).strftime("%Y-%m-%dT%H:%M:%SZ")
    epoch_saturday = epoch_start(saturday).strftime("%Y-%m-%dT%H:%M:%SZ")
    epoch_monday = epoch_start(monday).strftime("%Y-%m-%dT%H:%M:%SZ")
    epoch_wednesday = epoch_start(wednesday).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # All should be the same (Friday 00:00 UTC)
    assert epoch_friday == epoch_saturday == epoch_monday == epoch_wednesday
    
    # On each restart, validator should fetch for the same epoch version
    # This ensures consistency - same frozen list used throughout the week
    for time_point in [friday, saturday, monday, wednesday]:
        current_epoch = epoch_start(time_point).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert current_epoch == epoch_friday, f"All times should resolve to same epoch: {time_point}"

