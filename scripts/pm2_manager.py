#!/usr/bin/env python3
"""
PM2 Process Management Wrapper

Provides functions to manage validator process via PM2:
- Start/stop/restart validator
- Check validator status
- Get validator logs
- Setup PM2 startup script
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class PM2Manager:
    """Wrapper for PM2 process management commands."""

    def __init__(self, app_name: str = "cartha-validator"):
        """
        Initialize PM2 manager.

        Args:
            app_name: PM2 application name for the validator
        """
        self.app_name = app_name

    def _run_pm2_command(
        self, command: list[str], check: bool = True
    ) -> subprocess.CompletedProcess:
        """
        Run a PM2 command and return the result.

        Args:
            command: PM2 command to run (e.g., ['pm2', 'status'])
            check: Whether to raise exception on non-zero exit code

        Returns:
            CompletedProcess result

        Raises:
            subprocess.CalledProcessError: If check=True and command fails
            FileNotFoundError: If PM2 is not installed
        """
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=check,
            )
            return result
        except FileNotFoundError:
            raise FileNotFoundError(
                "PM2 is not installed. Install it with: npm install -g pm2"
            )

    def is_installed(self) -> bool:
        """
        Check if PM2 is installed.

        Returns:
            True if PM2 is installed, False otherwise
        """
        try:
            self._run_pm2_command(["pm2", "--version"], check=False)
            return True
        except FileNotFoundError:
            return False

    def is_running(self) -> bool:
        """
        Check if validator is running via PM2.

        Returns:
            True if validator is running, False otherwise
        """
        try:
            result = self._run_pm2_command(["pm2", "jlist"], check=False)
            if result.returncode != 0:
                return False

            processes = json.loads(result.stdout)
            return any(
                proc.get("name") == self.app_name
                and proc.get("pm2_env", {}).get("status") == "online"
                for proc in processes
            )
        except (json.JSONDecodeError, subprocess.CalledProcessError):
            return False

    def get_status(self) -> dict[str, Any] | None:
        """
        Get validator status from PM2.

        Returns:
            Dictionary with status info, or None if not running
        """
        try:
            result = self._run_pm2_command(["pm2", "jlist"], check=False)
            if result.returncode != 0:
                return None

            processes = json.loads(result.stdout)
            for proc in processes:
                if proc.get("name") == self.app_name:
                    pm2_env = proc.get("pm2_env", {})
                    return {
                        "name": proc.get("name"),
                        "status": pm2_env.get("status"),
                        "pid": proc.get("pid"),
                        "uptime": proc.get("pm2_env", {}).get("pm_uptime"),
                        "restarts": pm2_env.get("restart_time", 0),
                        "memory": proc.get("monit", {}).get("memory", 0),
                        "cpu": proc.get("monit", {}).get("cpu", 0),
                    }
            return None
        except (json.JSONDecodeError, subprocess.CalledProcessError):
            return None

    def start_validator(
        self, ecosystem_file: Path | None = None
    ) -> subprocess.CompletedProcess:
        """
        Start validator via PM2.

        Args:
            ecosystem_file: Path to PM2 ecosystem config file (optional)

        Returns:
            CompletedProcess result

        Raises:
            subprocess.CalledProcessError: If start fails
        """
        if ecosystem_file and ecosystem_file.exists():
            return self._run_pm2_command(
                ["pm2", "start", str(ecosystem_file)]
            )
        else:
            # Start individual app (if already configured in PM2)
            return self._run_pm2_command(["pm2", "start", self.app_name])

    def stop_validator(self) -> subprocess.CompletedProcess:
        """
        Stop validator via PM2.

        Returns:
            CompletedProcess result

        Raises:
            subprocess.CalledProcessError: If stop fails
        """
        return self._run_pm2_command(["pm2", "stop", self.app_name])

    def restart_validator(self) -> subprocess.CompletedProcess:
        """
        Restart validator via PM2.

        Returns:
            CompletedProcess result

        Raises:
            subprocess.CalledProcessError: If restart fails
        """
        return self._run_pm2_command(["pm2", "restart", self.app_name])

    def get_logs(self, lines: int = 100) -> str:
        """
        Get recent validator logs from PM2.

        Args:
            lines: Number of lines to retrieve

        Returns:
            Log output as string
        """
        try:
            result = self._run_pm2_command(
                ["pm2", "logs", self.app_name, "--lines", str(lines), "--nostream"],
                check=False,
            )
            return result.stdout if result.returncode == 0 else ""
        except subprocess.CalledProcessError:
            return ""

    def get_error_log_path(self) -> Path:
        """
        Get path to PM2 error log file for validator.

        Returns:
            Path to error log file
        """
        # PM2 stores logs in ~/.pm2/logs/{app-name}-error.log
        home = Path.home()
        return home / ".pm2" / "logs" / f"{self.app_name}-error.log"

    def get_stdout_log_path(self) -> Path:
        """
        Get path to PM2 stdout log file for validator.

        Returns:
            Path to stdout log file
        """
        # PM2 stores logs in ~/.pm2/logs/{app-name}-out.log
        home = Path.home()
        return home / ".pm2" / "logs" / f"{self.app_name}-out.log"

    def setup_startup(self) -> subprocess.CompletedProcess:
        """
        Setup PM2 to start on system boot.

        Returns:
            CompletedProcess result

        Raises:
            subprocess.CalledProcessError: If setup fails
        """
        # Generate startup script
        result = self._run_pm2_command(["pm2", "startup"], check=False)
        if result.returncode == 0:
            # Save PM2 process list
            self._run_pm2_command(["pm2", "save"], check=False)
        return result

    def save_process_list(self) -> subprocess.CompletedProcess:
        """
        Save current PM2 process list.

        Returns:
            CompletedProcess result
        """
        return self._run_pm2_command(["pm2", "save"], check=False)


def main():
    """CLI interface for PM2 manager."""
    import argparse

    parser = argparse.ArgumentParser(description="PM2 process manager for validator")
    parser.add_argument(
        "--app-name",
        default="cartha-validator",
        help="PM2 application name",
    )
    parser.add_argument(
        "action",
        choices=["status", "start", "stop", "restart", "logs", "setup-startup"],
        help="Action to perform",
    )
    parser.add_argument(
        "--ecosystem-file",
        type=Path,
        help="Path to PM2 ecosystem config file (for start action)",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=100,
        help="Number of log lines to retrieve (for logs action)",
    )

    args = parser.parse_args()

    manager = PM2Manager(app_name=args.app_name)

    try:
        if args.action == "status":
            if not manager.is_installed():
                print("PM2 is not installed")
                sys.exit(1)

            if manager.is_running():
                status = manager.get_status()
                if status:
                    print(f"Validator '{args.app_name}' is running:")
                    print(json.dumps(status, indent=2))
                else:
                    print(f"Validator '{args.app_name}' status unknown")
            else:
                print(f"Validator '{args.app_name}' is not running")

        elif args.action == "start":
            if not manager.is_installed():
                print("PM2 is not installed. Install with: npm install -g pm2")
                sys.exit(1)

            result = manager.start_validator(args.ecosystem_file)
            print(f"Started validator: {result.stdout}")

        elif args.action == "stop":
            result = manager.stop_validator()
            print(f"Stopped validator: {result.stdout}")

        elif args.action == "restart":
            result = manager.restart_validator()
            print(f"Restarted validator: {result.stdout}")

        elif args.action == "logs":
            logs = manager.get_logs(args.lines)
            print(logs)

        elif args.action == "setup-startup":
            result = manager.setup_startup()
            print(result.stdout)
            print("\nPM2 startup configured. Run 'pm2 save' to save current process list.")

    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
