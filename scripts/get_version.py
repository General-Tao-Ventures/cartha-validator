#!/usr/bin/env python3
"""
Version Extraction Utility

Reads version from pyproject.toml and outputs it for use in scripts and CI/CD.
"""

import re
import sys
from pathlib import Path


def get_version_from_pyproject(pyproject_path: Path | None = None) -> str:
    """
    Extract version from pyproject.toml.

    Args:
        pyproject_path: Path to pyproject.toml (default: project root)

    Returns:
        Version string (e.g., "1.0.1")

    Raises:
        FileNotFoundError: If pyproject.toml not found
        ValueError: If version not found in pyproject.toml
    """
    if pyproject_path is None:
        # Try to find pyproject.toml relative to script location
        script_dir = Path(__file__).parent
        pyproject_path = script_dir.parent / "pyproject.toml"

    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")

    content = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find version in {pyproject_path}")

    return match.group(1)


def get_version_from_init(init_path: Path | None = None) -> str:
    """
    Extract version from __init__.py (fallback).

    Args:
        init_path: Path to __init__.py (default: cartha_validator/__init__.py)

    Returns:
        Version string (e.g., "1.0.1")

    Raises:
        FileNotFoundError: If __init__.py not found
        ValueError: If version not found in __init__.py
    """
    if init_path is None:
        script_dir = Path(__file__).parent
        init_path = script_dir.parent / "cartha_validator" / "__init__.py"

    if not init_path.exists():
        raise FileNotFoundError(f"__init__.py not found at {init_path}")

    content = init_path.read_text()
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        raise ValueError(f"Could not find __version__ in {init_path}")

    return match.group(1)


def main():
    """CLI entry point - outputs version to stdout."""
    import argparse

    parser = argparse.ArgumentParser(description="Extract version from project files")
    parser.add_argument(
        "--source",
        choices=["pyproject", "init", "both"],
        default="pyproject",
        help="Source file to read version from",
    )
    parser.add_argument(
        "--pyproject-path",
        type=Path,
        help="Path to pyproject.toml (default: auto-detect)",
    )
    parser.add_argument(
        "--init-path",
        type=Path,
        help="Path to __init__.py (default: auto-detect)",
    )

    args = parser.parse_args()

    try:
        if args.source == "pyproject":
            version = get_version_from_pyproject(args.pyproject_path)
            print(version)
        elif args.source == "init":
            version = get_version_from_init(args.init_path)
            print(version)
        elif args.source == "both":
            pyproject_version = get_version_from_pyproject(args.pyproject_path)
            init_version = get_version_from_init(args.init_path)
            if pyproject_version != init_version:
                print(
                    f"Version mismatch: pyproject.toml={pyproject_version}, __init__.py={init_version}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(pyproject_version)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
