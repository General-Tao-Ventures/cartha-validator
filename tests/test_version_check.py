"""Tests for version checking and comparison logic."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.get_version import (
    get_version_from_init,
    get_version_from_pyproject,
)
from scripts.bump_version import bump_version, parse_version


class TestParseVersion:
    """Test version parsing logic."""

    def test_parse_valid_version(self) -> None:
        """Test parsing valid semantic versions."""
        assert parse_version("1.0.0") == (1, 0, 0)
        assert parse_version("1.2.3") == (1, 2, 3)
        assert parse_version("10.20.30") == (10, 20, 30)
        assert parse_version("0.0.1") == (0, 0, 1)

    def test_parse_version_with_extra_chars(self) -> None:
        """Test parsing version with extra characters (should still work)."""
        # parse_version uses regex that matches from start
        assert parse_version("1.0.0-beta") == (1, 0, 0)
        assert parse_version("2.3.4+dev") == (2, 3, 4)

    def test_parse_invalid_version(self) -> None:
        """Test parsing invalid version formats."""
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_version("1.0")
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_version("1")
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_version("invalid")
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_version("")


class TestBumpVersion:
    """Test version bumping logic."""

    def test_bump_patch(self) -> None:
        """Test patch version bump."""
        assert bump_version("1.0.0", "patch") == "1.0.1"
        assert bump_version("1.2.3", "patch") == "1.2.4"
        assert bump_version("10.20.30", "patch") == "10.20.31"

    def test_bump_minor(self) -> None:
        """Test minor version bump."""
        assert bump_version("1.0.0", "minor") == "1.1.0"
        assert bump_version("1.2.3", "minor") == "1.3.0"
        assert bump_version("10.20.30", "minor") == "10.21.0"

    def test_bump_major(self) -> None:
        """Test major version bump."""
        assert bump_version("1.0.0", "major") == "2.0.0"
        assert bump_version("1.2.3", "major") == "2.0.0"
        assert bump_version("10.20.30", "major") == "11.0.0"

    def test_bump_invalid_type(self) -> None:
        """Test invalid bump type."""
        with pytest.raises(ValueError, match="Invalid bump type"):
            bump_version("1.0.0", "invalid")


class TestGetVersionFromPyproject:
    """Test extracting version from pyproject.toml."""

    def test_get_version_from_pyproject(self) -> None:
        """Test extracting version from valid pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\n'
                'name = "test"\n'
                'version = "1.2.3"\n'
            )
            version = get_version_from_pyproject(pyproject_path)
            assert version == "1.2.3"

    def test_get_version_with_single_quotes(self) -> None:
        """Test extracting version with single quotes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\n'
                'name = "test"\n'
                "version = '2.3.4'\n"
            )
            version = get_version_from_pyproject(pyproject_path)
            assert version == "2.3.4"

    def test_get_version_not_found(self) -> None:
        """Test when version is not found in pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "pyproject.toml"
            pyproject_path.write_text(
                '[project]\n'
                'name = "test"\n'
            )
            with pytest.raises(ValueError, match="Could not find version"):
                get_version_from_pyproject(pyproject_path)

    def test_get_version_file_not_found(self) -> None:
        """Test when pyproject.toml doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pyproject_path = Path(tmpdir) / "nonexistent.toml"
            with pytest.raises(FileNotFoundError):
                get_version_from_pyproject(pyproject_path)


class TestGetVersionFromInit:
    """Test extracting version from __init__.py."""

    def test_get_version_from_init(self) -> None:
        """Test extracting version from valid __init__.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_path = Path(tmpdir) / "__init__.py"
            init_path.write_text('__version__ = "1.2.3"\n')
            version = get_version_from_init(init_path)
            assert version == "1.2.3"

    def test_get_version_with_single_quotes(self) -> None:
        """Test extracting version with single quotes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_path = Path(tmpdir) / "__init__.py"
            init_path.write_text("__version__ = '2.3.4'\n")
            version = get_version_from_init(init_path)
            assert version == "2.3.4"

    def test_get_version_not_found(self) -> None:
        """Test when version is not found in __init__.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_path = Path(tmpdir) / "__init__.py"
            init_path.write_text('"""Module docstring"""\n')
            with pytest.raises(ValueError, match="Could not find __version__"):
                get_version_from_init(init_path)

    def test_get_version_file_not_found(self) -> None:
        """Test when __init__.py doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            init_path = Path(tmpdir) / "nonexistent.py"
            with pytest.raises(FileNotFoundError):
                get_version_from_init(init_path)


class TestVersionComparison:
    """Test version comparison logic."""

    def test_version_comparison(self) -> None:
        """Test comparing versions."""
        # Test patch increments
        assert parse_version("1.0.1") > parse_version("1.0.0")
        assert parse_version("1.0.0") < parse_version("1.0.1")

        # Test minor increments
        assert parse_version("1.1.0") > parse_version("1.0.0")
        assert parse_version("1.0.0") < parse_version("1.1.0")

        # Test major increments
        assert parse_version("2.0.0") > parse_version("1.0.0")
        assert parse_version("1.0.0") < parse_version("2.0.0")

        # Test equal versions
        assert parse_version("1.0.0") == parse_version("1.0.0")

        # Test complex comparisons
        assert parse_version("1.2.3") > parse_version("1.2.2")
        assert parse_version("1.2.3") < parse_version("1.3.0")
        assert parse_version("1.2.3") < parse_version("2.0.0")
