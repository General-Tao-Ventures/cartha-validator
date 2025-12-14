#!/usr/bin/env python3
"""
Validator Manager Script (One-Stop Shop)

Main entry point for validator management:
- Manages validator process via PM2
- Checks GitHub releases for updates
- Handles automatic updates
- Resolves validator UID on startup

This script runs via PM2 and manages the validator process.
Both processes survive SSH disconnect and system restarts.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

try:
    import bittensor as bt
except ImportError:
    bt = None

from pm2_manager import PM2Manager
from validate_env import validate_required_vars, get_default_required_vars


def get_version_from_pyproject(pyproject_path: Path | None = None) -> str:
    """
    Extract version from pyproject.toml.

    Args:
        pyproject_path: Path to pyproject.toml (default: project root)

    Returns:
        Version string (e.g., "1.0.1")
    """
    if pyproject_path is None:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"

    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")

    content = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find version in {pyproject_path}")

    return match.group(1)


def parse_version(version_string: str) -> tuple[int, int, int]:
    """
    Parse semantic version string into (major, minor, patch).

    Args:
        version_string: Version string (e.g., "1.0.1")

    Returns:
        Tuple of (major, minor, patch)
    """
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version_string)
    if not match:
        raise ValueError(f"Invalid version format: {version_string}")
    return tuple(map(int, match.groups()))


def compare_versions(current: str, latest: str) -> bool:
    """
    Compare two semantic versions.

    Args:
        current: Current version string
        latest: Latest version string

    Returns:
        True if latest > current, False otherwise
    """
    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)

    return latest_tuple > current_tuple


def get_latest_github_release(repo: str, token: str | None = None) -> str | None:
    """
    Get latest release version from GitHub API.

    Args:
        repo: Repository in format "owner/repo"
        token: GitHub token for authentication (optional)

    Returns:
        Latest release tag/version, or None if not found
    """
    import urllib.request
    import urllib.error
    import json
    import ssl

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github.v3+json"}

    if token:
        headers["Authorization"] = f"token {token}"

    try:
        # Create SSL context that uses default certificates
        # This handles macOS and other systems where certificates might not be properly configured
        ssl_context = ssl.create_default_context()
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            tag = data.get("tag_name", "")
            # Remove 'v' prefix if present
            return tag.lstrip("v") if tag else None
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        print(f"Error fetching GitHub release: {e}", file=sys.stderr)
        return None


def resolve_validator_uid(
    hotkey_ss58: str, netuid: int, subtensor: Any | None = None
) -> int | None:
    """
    Resolve validator UID from hotkey.

    Args:
        hotkey_ss58: Hotkey SS58 address
        netuid: Subnet UID
        subtensor: Bittensor subtensor instance (optional, will create if None)

    Returns:
        Validator UID, or None if not found
    """
    if bt is None:
        print("Warning: bittensor not available, cannot resolve UID", file=sys.stderr)
        return None

    try:
        if subtensor is None:
            # Create subtensor instance
            config = bt.config()
            subtensor = bt.subtensor(config=config)

        # Try metagraph method first (more efficient)
        try:
            metagraph = subtensor.metagraph(netuid)
            metagraph.sync(subtensor=subtensor)
            if hotkey_ss58 in metagraph.hotkeys:
                return metagraph.hotkeys.index(hotkey_ss58)
        except Exception:
            pass

        # Fallback to direct query
        try:
            uid = subtensor.get_uid_for_hotkey_on_subnet(
                hotkey_ss58=hotkey_ss58, netuid=netuid
            )
            if uid is not None:
                return uid
        except Exception:
            pass

        return None
    except Exception as e:
        print(f"Error resolving validator UID: {e}", file=sys.stderr)
        return None


class ValidatorManager:
    """Main validator manager class."""

    def __init__(
        self,
        github_repo: str = "General-Tao-Ventures/cartha-validator",
        check_interval: int = 3600,
        pm2_app_name: str = "cartha-validator",
        validator_command: str = "uv run python -m cartha_validator.main",
        validator_args: list[str] | None = None,
    ):
        """
        Initialize validator manager.

        Args:
            github_repo: GitHub repository (owner/repo format)
            check_interval: Update check interval in seconds
            pm2_app_name: PM2 application name
            validator_command: Validator command to run
            validator_args: Validator command arguments
        """
        self.github_repo = github_repo
        self.check_interval = check_interval
        self.pm2_manager = PM2Manager(app_name=pm2_app_name)
        self.validator_command = validator_command
        self.validator_args = validator_args or []

        # Validator identification (resolved on startup)
        self.validator_uid: int | None = None
        self.hotkey_ss58: str | None = None
        self.netuid: int | None = None
        self.version: str | None = None

        # Project root directory
        self.project_root = Path(__file__).parent.parent

    def initialize_validator_uid(
        self, hotkey_ss58: str, netuid: int
    ) -> bool:
        """
        Resolve and cache validator UID on startup.

        Args:
            hotkey_ss58: Hotkey SS58 address
            netuid: Subnet UID

        Returns:
            True if UID resolved successfully, False otherwise
        """
        self.hotkey_ss58 = hotkey_ss58
        self.netuid = netuid

        print(f"Resolving validator UID for hotkey {hotkey_ss58} on netuid {netuid}...")
        self.validator_uid = resolve_validator_uid(hotkey_ss58, netuid)

        if self.validator_uid is not None:
            print(f"✓ Validator UID resolved: {self.validator_uid}")
            return True
        else:
            print(
                f"⚠ Warning: Could not resolve validator UID. Using hotkey as identifier.",
                file=sys.stderr,
            )
            return False

    def check_for_updates(self) -> tuple[bool, str | None]:
        """
        Check if a new release is available on GitHub.

        Returns:
            Tuple of (update_available, latest_version)
        """
        current_version = get_version_from_pyproject()
        latest_version = get_latest_github_release(self.github_repo)

        if not latest_version:
            return False, None

        if compare_versions(current_version, latest_version):
            return True, latest_version

        return False, latest_version

    def update_validator(self) -> bool:
        """
        Update validator by pulling latest code and restarting.

        Returns:
            True if update successful, False otherwise
        """
        print("Starting validator update...")

        # Validate environment before update
        env_file = self.project_root / ".env"
        is_valid, missing_vars = validate_required_vars(
            get_default_required_vars(),
            env_file_path=env_file if env_file.exists() else None,
        )

        if not is_valid:
            error_msg = (
                f"✗ Environment validation failed. Missing variables: {', '.join(missing_vars)}\n"
                f"Update aborted. Validator will continue running on current version."
            )
            print(error_msg, file=sys.stderr)
            return False

        try:
            # Git pull
            print("Pulling latest code...")
            result = subprocess.run(
                ["git", "pull"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"Git pull: {result.stdout}")

            # Install dependencies
            print("Installing dependencies...")
            result = subprocess.run(
                ["uv", "sync"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            print("Dependencies installed")

            # Restart validator via PM2
            print("Restarting validator...")
            self.pm2_manager.restart_validator()

            # Verify restart
            time.sleep(5)  # Wait a bit for restart
            if self.pm2_manager.is_running():
                new_version = get_version_from_pyproject()
                success_msg = (
                    f"✓ Validator updated and restarted successfully\n"
                    f"New version: {new_version}\n"
                    f"Validator UID: {self.validator_uid or 'Unknown'}"
                )
                print(success_msg)
                return True
            else:
                raise RuntimeError("Validator failed to start after restart")

        except subprocess.CalledProcessError as e:
            error_msg = (
                f"✗ Update failed: {e}\n"
                f"stdout: {e.stdout}\n"
                f"stderr: {e.stderr}\n"
                f"Validator will continue running on current version."
            )
            print(error_msg, file=sys.stderr)
            return False
        except Exception as e:
            error_msg = f"✗ Update failed with exception: {e}\nValidator will continue running on current version."
            print(error_msg, file=sys.stderr)
            return False

    def ensure_validator_running(self) -> bool:
        """
        Ensure validator is running via PM2.

        Returns:
            True if validator is running, False otherwise
        """
        if self.pm2_manager.is_running():
            return True

        print("Validator not running. Starting via PM2...")
        ecosystem_file = self.project_root / "scripts" / "ecosystem.config.js"
        try:
            self.pm2_manager.start_validator(ecosystem_file if ecosystem_file.exists() else None)
            time.sleep(3)  # Wait for startup
            return self.pm2_manager.is_running()
        except Exception as e:
            print(f"Failed to start validator: {e}", file=sys.stderr)
            return False

    def run_update_loop(self) -> None:
        """
        Main update checking loop.

        Runs continuously, checking for updates at specified intervals.
        """
        print("Starting validator manager update loop...")
        print(f"Check interval: {self.check_interval} seconds")
        print(f"GitHub repo: {self.github_repo}")

        # Get current version
        try:
            self.version = get_version_from_pyproject()
            print(f"Current version: {self.version}")
        except Exception as e:
            print(f"Warning: Could not get version: {e}", file=sys.stderr)

        # Ensure validator is running
        if not self.ensure_validator_running():
            print("Failed to start validator. Exiting.", file=sys.stderr)
            sys.exit(1)

        while True:
            try:
                # Check for updates
                update_available, latest_version = self.check_for_updates()

                if update_available:
                    current_version = get_version_from_pyproject()
                    print(
                        f"Update available: {current_version} -> {latest_version}"
                    )
                    self.update_validator()
                else:
                    current_version = get_version_from_pyproject()
                    print(
                        f"No update available. Current: {current_version}, Latest: {latest_version or 'Unknown'}"
                    )

                # Ensure validator is still running
                if not self.pm2_manager.is_running():
                    print("Validator stopped. Attempting restart...", file=sys.stderr)
                    self.ensure_validator_running()

                # Wait for next check
                time.sleep(self.check_interval)

            except KeyboardInterrupt:
                print("\nShutting down validator manager...")
                break
            except Exception as e:
                print(f"Error in update loop: {e}", file=sys.stderr)
                time.sleep(60)  # Wait before retrying on error


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validator manager - one-stop shop for validator management"
    )
    parser.add_argument(
        "--github-repo",
        default=os.environ.get("GITHUB_REPO", "General-Tao-Ventures/cartha-validator"),
        help="GitHub repository (owner/repo format)",
    )
    parser.add_argument(
        "--check-interval",
        type=int,
        default=int(os.environ.get("CHECK_INTERVAL", "3600")),
        help="Update check interval in seconds (default: 3600)",
    )
    parser.add_argument(
        "--pm2-app-name",
        default="cartha-validator",
        help="PM2 application name",
    )
    parser.add_argument(
        "--hotkey-ss58",
        help="Validator hotkey SS58 address (for UID resolution)",
    )
    parser.add_argument(
        "--netuid",
        type=int,
        help="Subnet UID (for UID resolution)",
    )

    args = parser.parse_args()

    # Create manager
    manager = ValidatorManager(
        github_repo=args.github_repo,
        check_interval=args.check_interval,
        pm2_app_name=args.pm2_app_name,
    )

    # Resolve validator UID if hotkey/netuid provided
    if args.hotkey_ss58 and args.netuid:
        manager.initialize_validator_uid(args.hotkey_ss58, args.netuid)
    else:
        print(
            "Warning: Hotkey and netuid not provided. UID resolution skipped.",
            file=sys.stderr,
        )

    # Run update loop
    manager.run_update_loop()


if __name__ == "__main__":
    main()
