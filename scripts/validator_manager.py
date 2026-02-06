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
            subtensor = bt.subtensor()

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

    def get_running_validator_version(self) -> str | None:
        """
        Extract the running validator version from its logs.
        
        Returns:
            Version string if found, None otherwise
        """
        try:
            # Get recent logs from PM2
            logs = self.pm2_manager.get_logs(lines=200)
            
            # Look for version pattern: "Validator version: 1.0.1" or "__version__ = 1.0.1"
            import re
            patterns = [
                r'Validator version:\s*([\d.]+)',
                r'__version__\s*=\s*["\']([\d.]+)["\']',
                r'version_key=(\d+)',  # Fallback: extract from version_key
            ]
            
            for pattern in patterns:
                match = re.search(pattern, logs)
                if match:
                    version = match.group(1)
                    # If we got version_key, convert it back (e.g., 1001 -> 1.0.1)
                    if pattern == patterns[2] and len(version) == 4:
                        major = int(version[0])
                        minor = int(version[1:3])
                        patch = int(version[3])
                        return f"{major}.{minor}.{patch}"
                    return version
            
            return None
        except Exception as e:
            print(f"Warning: Could not extract running validator version: {e}", file=sys.stderr)
            return None

    def check_running_version_mismatch(self) -> bool:
        """
        Check if running validator version differs from local code version.
        This handles cases where code was updated but validator wasn't restarted.
        
        Returns:
            True if versions don't match and restart is needed, False otherwise
        """
        try:
            local_version = get_version_from_pyproject()
            running_version = self.get_running_validator_version()
            
            if running_version is None:
                # Can't determine running version, assume it's fine
                return False
            
            if local_version != running_version:
                print(
                    f"⚠ Version mismatch detected!\n"
                    f"  Local code version: {local_version}\n"
                    f"  Running validator version: {running_version}\n"
                    f"  Restarting validator to sync versions...",
                    file=sys.stderr
                )
                return True
            
            return False
        except Exception as e:
            print(f"Warning: Could not check version mismatch: {e}", file=sys.stderr)
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

    def _get_current_commit(self) -> str | None:
        """Get the current git commit SHA."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except Exception as e:
            print(f"Warning: Could not get current commit: {e}", file=sys.stderr)
            return None

    def _rollback_to_commit(self, commit_sha: str) -> bool:
        """
        Rollback to a specific git commit.
        
        Args:
            commit_sha: The git commit SHA to rollback to
            
        Returns:
            True if rollback successful, False otherwise
        """
        print(f"🔄 Rolling back to commit {commit_sha[:8]}...")
        
        try:
            # Backup ecosystem.config.js before rollback
            ecosystem_file = self.project_root / "scripts" / "ecosystem.config.js"
            ecosystem_backup = self.project_root / "scripts" / ".ecosystem.config.js.local"
            if ecosystem_file.exists():
                import shutil
                shutil.copy2(ecosystem_file, ecosystem_backup)
            
            # Reset to the previous commit
            result = subprocess.run(
                ["git", "reset", "--hard", commit_sha],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"Git reset: {result.stdout}")
            
            # Restore ecosystem.config.js
            if ecosystem_backup.exists():
                import shutil
                shutil.copy2(ecosystem_backup, ecosystem_file)
                print("Restored ecosystem.config.js")
            
            # Re-sync dependencies for the rolled-back version
            subprocess.run(
                ["uv", "sync"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            
            # Restart validator
            self.pm2_manager.restart_validator()
            time.sleep(5)
            
            if self.pm2_manager.is_running():
                print(f"✓ Rollback successful - now running commit {commit_sha[:8]}")
                return True
            else:
                print("✗ Rollback completed but validator failed to start", file=sys.stderr)
                return False
                
        except Exception as e:
            print(f"✗ Rollback failed: {e}", file=sys.stderr)
            return False

    def _health_check(self, wait_seconds: int = 30) -> bool:
        """
        Perform a health check on the validator after update.
        
        Checks:
        1. Is the process running?
        2. Has it stayed running for at least wait_seconds?
        3. No crash loops detected?
        
        Args:
            wait_seconds: How long to wait and monitor for stability
            
        Returns:
            True if validator appears healthy, False otherwise
        """
        print(f"🏥 Running health check (monitoring for {wait_seconds}s)...")
        
        # Initial check
        if not self.pm2_manager.is_running():
            print("✗ Health check failed: Validator not running")
            return False
        
        # Monitor for stability (check every 5 seconds)
        check_interval = 5
        checks = wait_seconds // check_interval
        consecutive_running = 0
        
        for i in range(checks):
            time.sleep(check_interval)
            if self.pm2_manager.is_running():
                consecutive_running += 1
                print(f"  ✓ Check {i+1}/{checks}: Running")
            else:
                print(f"  ✗ Check {i+1}/{checks}: Not running (crash detected)")
                return False
        
        # Check PM2 restart count to detect crash loops
        try:
            result = subprocess.run(
                ["pm2", "jlist"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                import json
                processes = json.loads(result.stdout)
                for proc in processes:
                    if proc.get("name") == "cartha-validator":
                        restart_count = proc.get("pm2_env", {}).get("restart_time", 0)
                        if restart_count > 3:
                            print(f"⚠ Warning: Validator has restarted {restart_count} times")
                            # Don't fail on this, just warn
        except Exception:
            pass  # Non-fatal, continue
        
        print("✓ Health check passed")
        return True

    def update_validator(self) -> bool:
        """
        Update validator by pulling latest code and restarting.
        
        Features:
        - Auto-rollback if update fails or validator crashes
        - Health check after update to verify stability
        - Preserves ecosystem.config.js

        Uses the update.sh script which handles:
        - Backing up ecosystem.config.js
        - Git pull with conflict resolution
        - Restoring ecosystem.config.js
        - uv sync
        - PM2 restart

        Returns:
            True if update successful, False otherwise
        """
        print("Starting validator update...")
        
        # Save current commit for potential rollback
        rollback_commit = self._get_current_commit()
        if rollback_commit:
            print(f"📍 Rollback point saved: {rollback_commit[:8]}")
        
        old_version = get_version_from_pyproject()

        try:
            # Use update.sh script if available (preferred method)
            update_script = self.project_root / "scripts" / "update.sh"
            if update_script.exists():
                print("Using update.sh script...")
                result = subprocess.run(
                    ["bash", str(update_script)],
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                )
                print(result.stdout)
                if result.returncode != 0:
                    print(f"Update script stderr: {result.stderr}", file=sys.stderr)
                    # Don't fail completely - the validator might still be running
                    if self.pm2_manager.is_running():
                        print("⚠ Update had issues but validator is still running")
                        return False
                    # Try rollback
                    if rollback_commit:
                        print("Update failed, attempting rollback...")
                        if self._rollback_to_commit(rollback_commit):
                            print(f"Rolled back to version {old_version}")
                        else:
                            print("Rollback also failed!", file=sys.stderr)
                    return False
                
                # Health check after update
                if not self._health_check(wait_seconds=30):
                    print("⚠ Health check failed after update")
                    if rollback_commit:
                        print("Attempting rollback due to failed health check...")
                        if self._rollback_to_commit(rollback_commit):
                            print(f"✓ Rolled back to version {old_version}")
                            return False
                        else:
                            print("Rollback also failed!", file=sys.stderr)
                    return False
                
                new_version = get_version_from_pyproject()
                success_msg = (
                    f"✓ Validator updated successfully\n"
                    f"Version: {old_version} → {new_version}\n"
                    f"Validator UID: {self.validator_uid or 'Unknown'}"
                )
                print(success_msg)
                return True
            
            # Fallback: manual update if update.sh doesn't exist
            print("update.sh not found, using fallback method...")
            
            # Backup ecosystem.config.js
            ecosystem_file = self.project_root / "scripts" / "ecosystem.config.js"
            ecosystem_backup = self.project_root / "scripts" / ".ecosystem.config.js.local"
            if ecosystem_file.exists():
                import shutil
                shutil.copy2(ecosystem_file, ecosystem_backup)
                print("Backed up ecosystem.config.js")
            
            # Git pull
            print("Pulling latest code...")
            result = subprocess.run(
                ["git", "pull"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                # Try reset if pull fails
                print("Git pull failed, attempting reset...")
                subprocess.run(
                    ["git", "fetch", "origin"],
                    cwd=self.project_root,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "reset", "--hard", "origin/main"],
                    cwd=self.project_root,
                    capture_output=True,
                )
            print(f"Git: {result.stdout}")
            
            # Restore ecosystem.config.js if needed
            if ecosystem_backup.exists():
                if not ecosystem_file.exists():
                    import shutil
                    shutil.copy2(ecosystem_backup, ecosystem_file)
                    print("Restored ecosystem.config.js from backup")

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

            # Health check
            if not self._health_check(wait_seconds=30):
                print("⚠ Health check failed after update")
                if rollback_commit:
                    print("Attempting rollback...")
                    if self._rollback_to_commit(rollback_commit):
                        print(f"✓ Rolled back to version {old_version}")
                    else:
                        print("Rollback also failed!", file=sys.stderr)
                return False

            new_version = get_version_from_pyproject()
            success_msg = (
                f"✓ Validator updated and restarted successfully\n"
                f"Version: {old_version} → {new_version}\n"
                f"Validator UID: {self.validator_uid or 'Unknown'}"
            )
            print(success_msg)
            return True

        except subprocess.CalledProcessError as e:
            error_msg = (
                f"✗ Update failed: {e}\n"
                f"stdout: {e.stdout}\n"
                f"stderr: {e.stderr}"
            )
            print(error_msg, file=sys.stderr)
            
            # Attempt rollback
            if rollback_commit:
                print("Attempting rollback...")
                if self._rollback_to_commit(rollback_commit):
                    print(f"✓ Rolled back to version {old_version}")
                else:
                    print("Rollback also failed!", file=sys.stderr)
            return False
        except Exception as e:
            error_msg = f"✗ Update failed with exception: {e}"
            print(error_msg, file=sys.stderr)
            
            # Attempt rollback
            if rollback_commit:
                print("Attempting rollback...")
                if self._rollback_to_commit(rollback_commit):
                    print(f"✓ Rolled back to version {old_version}")
                else:
                    print("Rollback also failed!", file=sys.stderr)
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
                # First, check if running validator version matches local code version
                # This handles cases where code was updated but validator wasn't restarted
                if self.check_running_version_mismatch():
                    print("Restarting validator to sync with local code version...")
                    self.pm2_manager.restart_validator()
                    time.sleep(5)  # Wait for restart
                    if not self.pm2_manager.is_running():
                        print("Warning: Validator failed to restart after version sync", file=sys.stderr)
                
                # Check for updates from GitHub
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
