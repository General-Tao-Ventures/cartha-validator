"""Tests for auto-updater functionality."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from scripts.validator_manager import (
    compare_versions,
    get_latest_github_release,
    get_version_from_pyproject,
    parse_version,
    resolve_validator_uid,
)


class TestVersionComparison:
    """Test version comparison logic for auto-updater."""

    def test_compare_versions_newer(self) -> None:
        """Test comparing versions where latest is newer."""
        assert compare_versions("1.0.0", "1.0.1") is True
        assert compare_versions("1.0.0", "1.1.0") is True
        assert compare_versions("1.0.0", "2.0.0") is True
        assert compare_versions("1.2.3", "1.2.4") is True
        assert compare_versions("1.2.3", "1.3.0") is True

    def test_compare_versions_older(self) -> None:
        """Test comparing versions where latest is older or same."""
        assert compare_versions("1.0.1", "1.0.0") is False
        assert compare_versions("1.1.0", "1.0.0") is False
        assert compare_versions("2.0.0", "1.0.0") is False
        assert compare_versions("1.0.0", "1.0.0") is False

    def test_compare_versions_edge_cases(self) -> None:
        """Test edge cases in version comparison."""
        # Test with different patch levels
        assert compare_versions("0.0.1", "0.0.2") is True
        assert compare_versions("10.20.30", "10.20.31") is True

        # Test major version jumps
        assert compare_versions("1.9.9", "2.0.0") is True


class TestGetLatestGitHubRelease:
    """Test GitHub release fetching logic."""

    @patch("scripts.validator_manager.urllib.request.urlopen")
    def test_get_latest_release_success(self, mock_urlopen: MagicMock) -> None:
        """Test successfully fetching latest release."""
        # Mock response
        mock_response = MagicMock()
        mock_response.read.return_value.decode.return_value = json.dumps(
            {"tag_name": "v1.2.3"}
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version = get_latest_github_release("owner/repo")
        assert version == "1.2.3"

    @patch("scripts.validator_manager.urllib.request.urlopen")
    def test_get_latest_release_without_v_prefix(self, mock_urlopen: MagicMock) -> None:
        """Test release tag without 'v' prefix."""
        mock_response = MagicMock()
        mock_response.read.return_value.decode.return_value = json.dumps(
            {"tag_name": "1.2.3"}
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version = get_latest_github_release("owner/repo")
        assert version == "1.2.3"

    @patch("scripts.validator_manager.urllib.request.urlopen")
    def test_get_latest_release_with_token(self, mock_urlopen: MagicMock) -> None:
        """Test fetching release with authentication token."""
        mock_response = MagicMock()
        mock_response.read.return_value.decode.return_value = json.dumps(
            {"tag_name": "v2.0.0"}
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version = get_latest_github_release("owner/repo", token="test-token")
        assert version == "2.0.0"

        # Verify Authorization header was set
        call_args = mock_urlopen.call_args
        assert call_args is not None
        request = call_args[0][0]
        assert "Authorization" in request.headers
        assert request.headers["Authorization"] == "token test-token"

    @patch("scripts.validator_manager.urllib.request.urlopen")
    def test_get_latest_release_not_found(self, mock_urlopen: MagicMock) -> None:
        """Test when no releases are found."""
        mock_response = MagicMock()
        mock_response.read.return_value.decode.return_value = json.dumps({})
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version = get_latest_github_release("owner/repo")
        assert version is None

    @patch("scripts.validator_manager.urllib.request.urlopen")
    def test_get_latest_release_network_error(self, mock_urlopen: MagicMock) -> None:
        """Test handling network errors."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Network error")

        version = get_latest_github_release("owner/repo")
        assert version is None

    @patch("scripts.validator_manager.urllib.request.urlopen")
    def test_get_latest_release_invalid_json(self, mock_urlopen: MagicMock) -> None:
        """Test handling invalid JSON response."""
        mock_response = MagicMock()
        mock_response.read.return_value.decode.return_value = "invalid json"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version = get_latest_github_release("owner/repo")
        assert version is None


class TestResolveValidatorUID:
    """Test validator UID resolution."""

    @patch("scripts.validator_manager.bt")
    def test_resolve_uid_via_metagraph(self, mock_bt: MagicMock) -> None:
        """Test resolving UID via metagraph."""
        # Mock metagraph
        mock_metagraph = MagicMock()
        mock_metagraph.hotkeys = ["key1", "key2", "key3"]
        mock_metagraph.hotkeys.index = Mock(return_value=1)

        # Mock subtensor
        mock_subtensor = MagicMock()
        mock_subtensor.metagraph = Mock(return_value=mock_metagraph)
        mock_metagraph.sync = Mock()

        uid = resolve_validator_uid("key2", 35, subtensor=mock_subtensor)
        assert uid == 1
        mock_metagraph.sync.assert_called_once()

    @patch("scripts.validator_manager.bt")
    def test_resolve_uid_via_direct_query(self, mock_bt: MagicMock) -> None:
        """Test resolving UID via direct subtensor query."""
        # Mock metagraph failure
        mock_metagraph = MagicMock()
        mock_metagraph.hotkeys = []
        mock_metagraph.sync.side_effect = Exception("Metagraph error")

        # Mock subtensor with direct query success
        mock_subtensor = MagicMock()
        mock_subtensor.metagraph = Mock(return_value=mock_metagraph)
        mock_subtensor.get_uid_for_hotkey_on_subnet = Mock(return_value=42)

        uid = resolve_validator_uid("key1", 35, subtensor=mock_subtensor)
        assert uid == 42
        mock_subtensor.get_uid_for_hotkey_on_subnet.assert_called_once_with(
            hotkey_ss58="key1", netuid=35
        )

    @patch("scripts.validator_manager.bt")
    def test_resolve_uid_not_found(self, mock_bt: MagicMock) -> None:
        """Test when UID cannot be resolved."""
        mock_subtensor = MagicMock()
        mock_metagraph = MagicMock()
        mock_metagraph.hotkeys = []
        mock_metagraph.sync = Mock()
        mock_subtensor.metagraph = Mock(return_value=mock_metagraph)
        mock_subtensor.get_uid_for_hotkey_on_subnet = Mock(return_value=None)

        uid = resolve_validator_uid("nonexistent", 35, subtensor=mock_subtensor)
        assert uid is None

    def test_resolve_uid_no_bittensor(self) -> None:
        """Test when bittensor is not available."""
        with patch("scripts.validator_manager.bt", None):
            uid = resolve_validator_uid("key1", 35)
            assert uid is None


class TestPM2ManagerIntegration:
    """Test PM2 manager integration."""

    def test_pm2_manager_initialization(self) -> None:
        """Test PM2 manager initialization."""
        from scripts.pm2_manager import PM2Manager

        manager = PM2Manager(app_name="test-validator")
        assert manager.app_name == "test-validator"

    @patch("scripts.pm2_manager.subprocess.run")
    def test_pm2_is_running(self, mock_run: MagicMock) -> None:
        """Test checking if validator is running."""
        from scripts.pm2_manager import PM2Manager

        # Mock PM2 jlist output with running process
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            [
                {
                    "name": "cartha-validator",
                    "pm2_env": {"status": "online", "restart_time": 0},
                    "pid": 12345,
                }
            ]
        )
        mock_run.return_value = mock_result

        manager = PM2Manager(app_name="cartha-validator")
        assert manager.is_running() is True

    @patch("scripts.pm2_manager.subprocess.run")
    def test_pm2_not_running(self, mock_run: MagicMock) -> None:
        """Test when validator is not running."""
        from scripts.pm2_manager import PM2Manager

        # Mock PM2 jlist output with no matching process
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps([{"name": "other-app", "pm2_env": {"status": "online"}}])
        mock_run.return_value = mock_result

        manager = PM2Manager(app_name="cartha-validator")
        assert manager.is_running() is False

    @patch("scripts.pm2_manager.subprocess.run")
    def test_pm2_get_status(self, mock_run: MagicMock) -> None:
        """Test getting validator status."""
        from scripts.pm2_manager import PM2Manager

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            [
                {
                    "name": "cartha-validator",
                    "pm2_env": {
                        "status": "online",
                        "restart_time": 2,
                        "pm_uptime": 3600000,
                    },
                    "pid": 12345,
                    "monit": {"memory": 1000000, "cpu": 5.0},
                }
            ]
        )
        mock_run.return_value = mock_result

        manager = PM2Manager(app_name="cartha-validator")
        status = manager.get_status()
        assert status is not None
        assert status["name"] == "cartha-validator"
        assert status["status"] == "online"
        assert status["pid"] == 12345
        assert status["restarts"] == 2

    def test_pm2_log_paths(self) -> None:
        """Test PM2 log path generation."""
        from scripts.pm2_manager import PM2Manager

        manager = PM2Manager(app_name="cartha-validator")
        error_log = manager.get_error_log_path()
        stdout_log = manager.get_stdout_log_path()

        assert "cartha-validator-error.log" in str(error_log)
        assert "cartha-validator-out.log" in str(stdout_log)
        assert ".pm2" in str(error_log)
        assert ".pm2" in str(stdout_log)


class TestUpdateProcess:
    """Test update process flow."""

    @patch("subprocess.run")
    def test_update_process_git_pull(self, mock_run: MagicMock) -> None:
        """Test git pull during update."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Already up to date"
        mock_run.return_value = mock_result

        result = subprocess.run(
            ["git", "pull"], capture_output=True, text=True, check=True
        )
        assert result.returncode == 0
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_update_process_uv_sync(self, mock_run: MagicMock) -> None:
        """Test uv sync during update."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Installed dependencies"
        mock_run.return_value = mock_result

        result = subprocess.run(
            ["uv", "sync"], capture_output=True, text=True, check=True
        )
        assert result.returncode == 0
        mock_run.assert_called_once()

    def test_version_extraction_from_pyproject(self) -> None:
        """Test extracting version from pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\n'
                'name = "test"\n'
                'version = "1.2.3"\n'
            )

            version = get_version_from_pyproject(pyproject_path)
            assert version == "1.2.3"


class TestErrorHandling:
    """Test error handling in auto-updater."""

    def test_parse_version_invalid_format(self) -> None:
        """Test parsing invalid version format."""
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_version("invalid")

    def test_get_version_file_not_found(self) -> None:
        """Test handling missing pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "nonexistent.toml"
            with pytest.raises(FileNotFoundError):
                get_version_from_pyproject(pyproject_path)

    def test_get_version_missing_version_field(self) -> None:
        """Test handling missing version field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text('[project]\nname = "test"\n')

            with pytest.raises(ValueError, match="Could not find version"):
                get_version_from_pyproject(pyproject_path)
