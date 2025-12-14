#!/usr/bin/env python3
"""
Check that the repository's version_key is >= subnet's weights_version hyperparameter.

This ensures validators can publish weights to the subnet.
"""

import sys
from pathlib import Path

try:
    import bittensor as bt
except ImportError:
    print("Error: bittensor library not found. Install with: pip install bittensor")
    sys.exit(1)


def get_repo_version_key(repo_path: Path | None = None) -> int:
    """Get the version_key from the repository's __spec_version__.
    
    Args:
        repo_path: Path to repository root (default: auto-detect from script location)
        
    Returns:
        The __spec_version__ integer value
    """
    if repo_path is None:
        # Auto-detect repo root: script is in .github/scripts/, so go up 2 levels
        repo_path = Path(__file__).parent.parent.parent
    
    # Add repo root to Python path so we can import cartha_validator
    repo_path_str = str(repo_path.resolve())
    if repo_path_str not in sys.path:
        sys.path.insert(0, repo_path_str)
    
    try:
        from cartha_validator import __spec_version__
        return __spec_version__
    except ImportError as e:
        print(f"Error: Could not import __spec_version__ from cartha_validator")
        print(f"  Repository path: {repo_path}")
        print(f"  Python path: {sys.path[:3]}...")
        print(f"  Import error: {e}")
        print(f"\n  Make sure you're running this from the repository root,")
        print(f"  or that cartha_validator package is installed.")
        sys.exit(1)


def get_subnet_weights_version(network: str = "finney", netuid: int = 35) -> int:
    """Query the Bittensor chain for subnet's weights_version hyperparameter.
    
    Args:
        network: Bittensor network name (default: "finney" for mainnet)
        netuid: Subnet UID (default: 35 for Cartha)
        
    Returns:
        The weights_version hyperparameter value
        
    Raises:
        RuntimeError: If unable to query the chain
    """
    try:
        # Connect to Bittensor network
        subtensor = bt.subtensor(network=network)
        
        # Method 1: Try metagraph.hparams (most reliable - confirmed working)
        try:
            metagraph = subtensor.metagraph(netuid=netuid)
            metagraph.sync(subtensor=subtensor)
            
            if hasattr(metagraph, "hparams") and hasattr(metagraph.hparams, "weights_version"):
                weights_version = metagraph.hparams.weights_version
                if weights_version is not None:
                    return int(weights_version)
        except Exception as e:
            # Continue to try other methods
            pass
        
        # Method 2: Try get_subnet_hyperparameters
        if hasattr(subtensor, "get_subnet_hyperparameters"):
            try:
                hyperparams = subtensor.get_subnet_hyperparameters(netuid=netuid)
                if hyperparams and hasattr(hyperparams, "weights_version"):
                    weights_version = hyperparams.weights_version
                    if weights_version is not None:
                        return int(weights_version)
            except Exception:
                pass
        
        # Method 3: Try get_hyperparameter (may not work for all parameters)
        if hasattr(subtensor, "get_hyperparameter"):
            try:
                weights_version = subtensor.get_hyperparameter("weights_version", netuid=netuid)
                if weights_version is not None:
                    return int(weights_version)
            except Exception:
                pass
        
        raise RuntimeError(
            f"Could not retrieve weights_version hyperparameter for netuid {netuid}. "
            f"Tried: metagraph.hparams, get_subnet_hyperparameters, and get_hyperparameter"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to query Bittensor chain: {e}") from e


def main():
    """Main entry point for weights version check."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Check repository version_key >= subnet weights_version"
    )
    parser.add_argument(
        "--network",
        type=str,
        default="finney",
        help="Bittensor network name (default: finney for mainnet)"
    )
    parser.add_argument(
        "--netuid",
        type=int,
        default=35,
        help="Subnet UID (default: 35 for Cartha)"
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip the check (useful for testing or when chain is unavailable)"
    )
    
    args = parser.parse_args()
    
    if args.skip_check:
        print("⚠️  Skipping weights_version check (--skip-check flag set)")
        sys.exit(0)
    
    try:
        # Get repository's version_key
        # When running from GitHub Actions, we're in the staging directory
        repo_path = Path.cwd()
        repo_version_key = get_repo_version_key(repo_path=repo_path)
        print(f"Repository version_key: {repo_version_key}")
        
        # Get subnet's weights_version
        print(f"Querying Bittensor chain (network: {args.network}, netuid: {args.netuid})...")
        subnet_weights_version = get_subnet_weights_version(
            network=args.network,
            netuid=args.netuid
        )
        print(f"Subnet weights_version: {subnet_weights_version}")
        
        # Compare versions
        print(f"\n{'='*60}")
        print("Version Comparison")
        print(f"{'='*60}")
        print(f"Repository version_key:  {repo_version_key}")
        print(f"Subnet weights_version:  {subnet_weights_version}")
        print(f"Required: version_key >= weights_version")
        
        if repo_version_key >= subnet_weights_version:
            print(f"\n✅ Version check PASSED")
            print(f"✅ Repository version_key ({repo_version_key}) >= subnet weights_version ({subnet_weights_version})")
            print(f"✅ Validators can publish weights to subnet {args.netuid}")
            sys.exit(0)
        else:
            print(f"\n❌ Version check FAILED")
            print(f"❌ Repository version_key ({repo_version_key}) < subnet weights_version ({subnet_weights_version})")
            print(f"❌ Validators cannot publish weights with current version")
            print(f"\n⚠️  Action Required:")
            print(f"   Bump the version in both files:")
            print(f"   1. pyproject.toml")
            print(f"   2. cartha_validator/__init__.py")
            print(f"\n   The version_key must be >= {subnet_weights_version}")
            print(f"   Current version_key: {repo_version_key}")
            print(f"   Required minimum: {subnet_weights_version}")
            print(f"   Difference needed: {subnet_weights_version - repo_version_key}")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print(f"\n⚠️  This check requires:")
        print(f"   1. Network access to Bittensor chain ({args.network})")
        print(f"   2. bittensor library installed")
        print(f"   3. Valid netuid ({args.netuid})")
        print(f"\n   If this is a temporary network issue, you can:")
        print(f"   - Retry the workflow")
        print(f"   - Use --skip-check flag (for testing only)")
        sys.exit(1)


if __name__ == "__main__":
    main()
