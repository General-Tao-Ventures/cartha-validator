#!/usr/bin/env python3
"""
Version Bump Helper Script

Helper script for developers to bump version in both pyproject.toml and __init__.py.
Supports major, minor, and patch version increments.
"""

import re
import sys
from pathlib import Path


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


def bump_version(version: str, bump_type: str) -> str:
    """
    Bump version by incrementing major, minor, or patch.

    Args:
        version: Current version string
        bump_type: Type of bump ('major', 'minor', 'patch')

    Returns:
        New version string
    """
    major, minor, patch = parse_version(version)

    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid bump type: {bump_type}. Must be 'major', 'minor', or 'patch'")

    return f"{major}.{minor}.{patch}"


def update_pyproject_version(pyproject_path: Path, new_version: str) -> None:
    """
    Update version in pyproject.toml.

    Args:
        pyproject_path: Path to pyproject.toml
        new_version: New version string
    """
    content = pyproject_path.read_text()
    # Replace version line
    content = re.sub(
        r'^version\s*=\s*["\'][^"\']+["\']',
        f'version = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    pyproject_path.write_text(content)


def update_init_version(init_path: Path, new_version: str) -> None:
    """
    Update version in __init__.py.

    Args:
        init_path: Path to __init__.py
        new_version: New version string
    """
    content = init_path.read_text()
    # Replace __version__ line
    content = re.sub(
        r'__version__\s*=\s*["\'][^"\']+["\']',
        f'__version__ = "{new_version}"',
        content,
    )
    init_path.write_text(content)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Bump version in pyproject.toml and __init__.py"
    )
    parser.add_argument(
        "bump_type",
        choices=["major", "minor", "patch"],
        help="Type of version bump",
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes",
    )

    args = parser.parse_args()

    # Determine file paths
    script_dir = Path(__file__).parent
    if args.pyproject_path:
        pyproject_path = args.pyproject_path
    else:
        pyproject_path = script_dir.parent / "pyproject.toml"

    if args.init_path:
        init_path = args.init_path
    else:
        init_path = script_dir.parent / "cartha_validator" / "__init__.py"

    # Read current version
    try:
        from get_version import get_version_from_pyproject, get_version_from_init

        current_pyproject_version = get_version_from_pyproject(pyproject_path)
        current_init_version = get_version_from_init(init_path)

        if current_pyproject_version != current_init_version:
            print(
                f"Warning: Version mismatch detected!\n"
                f"  pyproject.toml: {current_pyproject_version}\n"
                f"  __init__.py: {current_init_version}\n"
                f"Both will be updated to the same new version.",
                file=sys.stderr,
            )

        current_version = current_pyproject_version
    except Exception as e:
        print(f"Error reading current version: {e}", file=sys.stderr)
        sys.exit(1)

    # Calculate new version
    try:
        new_version = bump_version(current_version, args.bump_type)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Show what will be changed
    print(f"Current version: {current_version}")
    print(f"New version: {new_version}")
    print(f"Bump type: {args.bump_type}")
    print()

    if args.dry_run:
        print("Dry run - no changes made")
        print(f"Would update {pyproject_path}")
        print(f"Would update {init_path}")
        sys.exit(0)

    # Update files
    try:
        print(f"Updating {pyproject_path}...")
        update_pyproject_version(pyproject_path, new_version)
        print(f"✓ Updated pyproject.toml to version {new_version}")

        print(f"Updating {init_path}...")
        update_init_version(init_path, new_version)
        print(f"✓ Updated __init__.py to version {new_version}")

        print(f"\n✓ Version bumped successfully: {current_version} → {new_version}")
        print("\nNext steps:")
        print("  1. Review the changes")
        print("  2. Commit the version bump:")
        print(f"     git add {pyproject_path.relative_to(script_dir.parent)}")
        print(f"     git add {init_path.relative_to(script_dir.parent)}")
        print(f'     git commit -m "chore: bump version to {new_version}"')

    except Exception as e:
        print(f"Error updating files: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
