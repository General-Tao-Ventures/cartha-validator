#!/usr/bin/env python3
"""
Version bump verification script for PR validation.
Ensures that staging -> main merges include a version bump.
Checks both pyproject.toml and __init__.py for consistency.
"""

import sys
import re
from pathlib import Path


def parse_version(version_string: str) -> tuple[int, int, int]:
    """Parse a semantic version string into (major, minor, patch)."""
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version_string)
    if not match:
        raise ValueError(f"Invalid version format: {version_string}")
    return tuple(map(int, match.groups()))


def extract_version_from_pyproject(file_path: Path) -> str:
    """Extract version from pyproject.toml file."""
    if not file_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found at {file_path}")
    
    content = file_path.read_text()
    match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find version in {file_path}")
    
    return match.group(1)


def extract_version_from_init(file_path: Path) -> str:
    """Extract fallback version from __init__.py file."""
    if not file_path.exists():
        raise FileNotFoundError(f"__init__.py not found at {file_path}")
    
    content = file_path.read_text()
    # Look for the fallback version: __version__ = "1.0.0"
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        raise ValueError(f"Could not find __version__ in {file_path}")
    
    return match.group(1)


def compare_versions(old_version: str, new_version: str) -> bool:
    """
    Compare two semantic versions.
    Returns True if new_version > old_version, False otherwise.
    """
    old = parse_version(old_version)
    new = parse_version(new_version)
    
    print(f"Old version: {old_version} -> {old}")
    print(f"New version: {new_version} -> {new}")
    
    return new > old


def check_version_consistency(branch_name: str, pyproject_path: Path, init_path: Path) -> str:
    """
    Check that versions in pyproject.toml and __init__.py are consistent.
    Returns the version if consistent, raises ValueError if not.
    """
    pyproject_version = extract_version_from_pyproject(pyproject_path)
    init_version = extract_version_from_init(init_path)
    
    if pyproject_version != init_version:
        raise ValueError(
            f"Version mismatch in {branch_name} branch!\n"
            f"  pyproject.toml: {pyproject_version}\n"
            f"  __init__.py fallback: {init_version}\n"
            f"Both versions must match. Please update both files."
        )
    
    return pyproject_version


def main():
    """Main entry point for version comparison."""
    if len(sys.argv) != 5:
        print("Usage: check_version_bump.py <main_pyproject> <main_init> <staging_pyproject> <staging_init>")
        sys.exit(1)
    
    main_pyproject = Path(sys.argv[1])
    main_init = Path(sys.argv[2])
    staging_pyproject = Path(sys.argv[3])
    staging_init = Path(sys.argv[4])
    
    try:
        # Check version consistency within each branch
        print(f"\n{'='*60}")
        print("Step 1: Checking version consistency within branches")
        print(f"{'='*60}\n")
        
        main_version = check_version_consistency("main", main_pyproject, main_init)
        print(f"✓ Main branch version is consistent: {main_version}")
        
        staging_version = check_version_consistency("staging", staging_pyproject, staging_init)
        print(f"✓ Staging branch version is consistent: {staging_version}")
        
        # Compare versions between branches
        print(f"\n{'='*60}")
        print("Step 2: Checking version bump between branches")
        print(f"{'='*60}\n")
        print(f"Checking version bump: {main_version} -> {staging_version}")
        
        if compare_versions(main_version, staging_version):
            print(f"\n✓ Version bump detected: {main_version} -> {staging_version}")
            print(f"✓ Staging version ({staging_version}) is greater than main ({main_version})")
            print(f"✓ Both pyproject.toml and __init__.py are consistent")
            sys.exit(0)
        else:
            print(f"\n✗ No version bump detected!")
            print(f"✗ Staging version ({staging_version}) must be greater than main ({main_version})")
            print(f"\nPlease update the version in BOTH files before merging to main:")
            print(f"  1. pyproject.toml (under [project] section)")
            print(f"  2. cartha_validator/__init__.py (fallback __version__)")
            print(f"\nUse semantic versioning: major.minor.patch")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
