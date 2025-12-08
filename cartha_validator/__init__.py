"""Validator tooling for Cartha."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cartha-subnet-validator")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "1.0.0"

# Convert version string (e.g., "1.0.0") to spec_version integer (e.g., 1000)
# Format: 1000 * major + 10 * minor + 1 * patch
version_split = __version__.split(".")
__spec_version__ = (
    (1000 * int(version_split[0]))
    + (10 * int(version_split[1]))
    + (1 * int(version_split[2]))
)

__all__ = ["__version__", "__spec_version__"]
