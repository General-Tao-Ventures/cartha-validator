"""Validator tooling for Cartha."""

__version__ = "1.1.1"

# Convert version string (e.g., "1.0.0") to spec_version integer (e.g., 1000)
# Format: 1000 * major + 10 * minor + 1 * patch
# This matches Bittensor's version_key format used in set_weights()
version_split = __version__.split(".")
if len(version_split) == 3:
    # Standard semantic version format: "major.minor.patch"
    __spec_version__ = (
        (1000 * int(version_split[0]))
        + (10 * int(version_split[1]))
        + (1 * int(version_split[2]))
    )
elif len(version_split) == 1:
    # Single integer format: "100" should be treated as "1.0.0"
    # Parse as: major = num // 100, minor = (num % 100) // 10, patch = num % 10
    num = int(version_split[0])
    major = num // 100
    minor = (num % 100) // 10
    patch = num % 10
    __spec_version__ = (
        (1000 * major)
        + (10 * minor)
        + (1 * patch)
    )
else:
    # Fallback: pad with zeros if missing components
    major = int(version_split[0]) if len(version_split) > 0 else 0
    minor = int(version_split[1]) if len(version_split) > 1 else 0
    patch = int(version_split[2]) if len(version_split) > 2 else 0
    __spec_version__ = (
        (1000 * major)
        + (10 * minor)
        + (1 * patch)
    )

__all__ = ["__version__", "__spec_version__"]
