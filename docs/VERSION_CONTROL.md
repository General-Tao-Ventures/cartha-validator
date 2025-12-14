# Version Control

## Quick Reference

When merging `staging` → `main`, you must bump the version in **both** files:

1. **`pyproject.toml`**:
   ```toml
   [project]
   version = "1.0.1"  # Increment this
   ```

2. **`cartha_validator/__init__.py`**:
   ```python
   __version__ = "1.0.1"  # Update fallback to match
   ```

**Both versions must match exactly.**

## Version Bump Requirements

The CI/CD workflow automatically checks:
- ✅ Versions match between `pyproject.toml` and `__init__.py`
- ✅ Staging version > main version
- ✅ Repository `version_key >= subnet weights_version` (ensures validators can publish weights)

## Version Key Calculation

The `version_key` is calculated as:
```
version_key = 1000 * major + 10 * minor + 1 * patch
```

Examples:
- `1.0.0` → `1000`
- `1.0.1` → `1001`
- `1.0.10` → `1010`
- `1.1.0` → `1010`
- `2.0.0` → `2000`

## Troubleshooting

### Version Check Fails

**Error**: Version mismatch or version not bumped

**Fix**: Update **both** files with the same version:
```bash
# Edit pyproject.toml: version = "1.0.1"
# Edit __init__.py: __version__ = "1.0.1"
git add pyproject.toml cartha_validator/__init__.py
git commit -m "Bump version to 1.0.1"
git push
```

### Weights Version Too Low

**Error**: `Repository version_key (X) < subnet weights_version (Y)`

**Fix**: Bump version so `version_key >= weights_version`:
```bash
# Check subnet requirement:
btcli s hyperparameters --netuid 35 | grep weights_version

# If weights_version = 1010, you need version >= 1.0.10 or >= 1.1.0
# Update both files accordingly
```

## Semantic Versioning

Use format: `MAJOR.MINOR.PATCH`
- **PATCH** (1.0.0 → 1.0.1): Bug fixes
- **MINOR** (1.0.0 → 1.1.0): New features (backward compatible)
- **MAJOR** (1.0.0 → 2.0.0): Breaking changes
