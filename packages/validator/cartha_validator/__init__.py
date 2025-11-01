"""Validator tooling for Cartha."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("cartha-validator")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = ["__version__"]
