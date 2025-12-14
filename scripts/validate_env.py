#!/usr/bin/env python3
"""
Environment Variable Validation Script

Validates that all required environment variables are set before restarting validator.
Checks .env file and environment variables.
"""

import os
import sys
from pathlib import Path
from typing import Any


def load_env_file(env_path: Path | None = None) -> dict[str, str]:
    """
    Load environment variables from .env file.

    Args:
        env_path: Path to .env file (default: .env in current directory)

    Returns:
        Dictionary of environment variables from .env file
    """
    if env_path is None:
        env_path = Path(".env")

    env_vars: dict[str, str] = {}

    if not env_path.exists():
        return env_vars

    with env_path.open() as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Parse KEY=VALUE format
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    env_vars[key] = value

    return env_vars


def get_env_value(key: str, env_file_vars: dict[str, str] | None = None) -> str | None:
    """
    Get environment variable value from environment or .env file.

    Args:
        key: Environment variable name
        env_file_vars: Pre-loaded .env file variables (optional)

    Returns:
        Environment variable value, or None if not set
    """
    # Check environment first (takes precedence)
    value = os.environ.get(key)
    if value:
        return value

    # Check .env file if provided
    if env_file_vars:
        return env_file_vars.get(key)

    return None


def validate_required_vars(
    required_vars: list[str],
    env_file_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """
    Validate that all required environment variables are set.

    Args:
        required_vars: List of required environment variable names
        env_file_path: Path to .env file (optional)

    Returns:
        Tuple of (is_valid, missing_vars)
    """
    env_file_vars = load_env_file(env_file_path) if env_file_path else None

    missing_vars: list[str] = []

    for var in required_vars:
        value = get_env_value(var, env_file_vars)
        if not value or value.strip() == "":
            missing_vars.append(var)

    return len(missing_vars) == 0, missing_vars


def get_default_required_vars() -> list[str]:
    """
    Get list of default required environment variables for validator.

    Returns:
        List of required environment variable names
    """
    return [
        "PARENT_VAULT_ADDRESS",
        "PARENT_VAULT_RPC_URL",
        # Note: VERIFIER_URL, WALLET_NAME, WALLET_HOTKEY, NETUID can come from
        # command-line args or config, so they're optional in .env
        # But we check for them if they're expected to be in .env
    ]


def main():
    """CLI interface for environment validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate environment variables for validator"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file (default: .env)",
    )
    parser.add_argument(
        "--required-vars",
        nargs="+",
        help="List of required environment variables (default: validator defaults)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed validation results",
    )

    args = parser.parse_args()

    # Determine required variables
    if args.required_vars:
        required_vars = args.required_vars
    else:
        required_vars = get_default_required_vars()

    # Validate
    is_valid, missing_vars = validate_required_vars(
        required_vars,
        env_file_path=args.env_file,
    )

    if args.verbose:
        print(f"Checking environment variables...")
        print(f"Environment file: {args.env_file}")
        print(f"Required variables: {', '.join(required_vars)}")
        print()

        env_file_vars = load_env_file(args.env_file)
        for var in required_vars:
            value = get_env_value(var, env_file_vars)
            if value:
                # Mask sensitive values
                if "KEY" in var.upper() or "SECRET" in var.upper() or "PASSWORD" in var.upper():
                    display_value = "***" if value else "NOT SET"
                else:
                    display_value = value[:50] + "..." if len(value) > 50 else value
                print(f"  ✓ {var}: {display_value}")
            else:
                print(f"  ✗ {var}: NOT SET")

        print()

    if is_valid:
        if args.verbose:
            print("✓ All required environment variables are set")
        sys.exit(0)
    else:
        print(
            f"✗ Missing required environment variables: {', '.join(missing_vars)}",
            file=sys.stderr,
        )
        print(
            f"\nPlease set these variables in {args.env_file} or as environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
