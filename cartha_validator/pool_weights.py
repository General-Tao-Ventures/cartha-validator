"""Pool weight querying from parent vault contract."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import bittensor as bt
import httpx

# Pool ID to Vault Address mapping (Base Mainnet)
# Pool IDs are keccak256 hashes of the pool names (e.g., keccak256("BTC/USD"))
# Vault addresses are from the mainnet deployment manifest (8453-manifest.json)
POOL_ID_TO_VAULT: dict[str, str] = {
    # Cryptos (parent: 0x7c5fAc6A0295663686873E418406cf540c45CCF3)
    "0xee62665949c883f9e0f6f002eac32e00bd59dfe6c34e92a91c37d6a8322d6489": "0xD090239EaE0d756726b6afd57E0b23A24FCABe86",  # BTC/USD
    "0x0b43555ace6b39aae1b894097d0a9fc17f504c62fea598fa206cc6f5088e6e45": "0x47EbDBE398733664250356F7F19fd516a5f1Dd0a",  # ETH/USD
    # Currencies (parent: 0xf69eeDf403C9DB553E1d1DCC29B31d0c3e7c58F3)
    "0xa9226449042e36bf6865099eec57482aa55e3ad026c315a0e4a692b776c318ca": "0x8AE6DDb449b3D8d1fE961483Fbe1329b5e4cbD86",  # EUR/USD
    "0xfd121bde813a3463e16ad2a4ea4103a6a122fbe2cdb07a80d4d293be07bb29fa": "0x9Eed917485e08FdFee977629bf933E8C0B33e539",  # GBP/USD
    "0xf9e627ddbdb060c1c9126daeb9addcd1d1ce7d49dbb540e2677f1c572bc8d195": "0xf2e3f581A7dE8B055c0122E3bFb445A67b485831",  # JPY/USD
    # Commodities (parent: 0xa265777B6241143C752d37025Bb4dE4B3E311A19)
    "0x5656b83664973a9b4e2c18d45b7578e6746ee4a565da62e3ac579fb9e05acc55": "0xabc777A16E41CF6E2F02A768D1f9f4d8aa68e58F",  # GOLD/USD
}

# Vault Address to Pool ID mapping (reverse lookup)
VAULT_TO_POOL_ID: dict[str, str] = {v.lower(): k for k, v in POOL_ID_TO_VAULT.items()}

# Parent vault addresses (Base Mainnet)
PARENT_VAULT_ADDRESSES = {
    "cryptos": "0x7c5fAc6A0295663686873E418406cf540c45CCF3",
    "currencies": "0xf69eeDf403C9DB553E1d1DCC29B31d0c3e7c58F3",
    "commodities": "0xa265777B6241143C752d37025Bb4dE4B3E311A19",
}

# Function selector for calculateTargetAllocations() - keccak256("calculateTargetAllocations()")[:4]
CALCULATE_TARGET_ALLOCATIONS_SELECTOR = "0x5f04c044"

# Cache configuration
CACHE_DIR = Path.home() / ".cartha_validator"
CACHE_FILE = CACHE_DIR / "pool_weights_cache.json"
CACHE_TTL_HOURS = 24  # Cache validity: 24 hours


def _load_cache() -> dict[str, Any] | None:
    """Load cached pool weights from disk.
    
    Returns:
        Cache data containing weights and timestamp, or None if cache doesn't exist or is invalid
    """
    try:
        if not CACHE_FILE.exists():
            bt.logging.debug("[POOL WEIGHTS CACHE] No cache file found")
            return None
        
        with CACHE_FILE.open("r") as f:
            cache_data = json.load(f)
        
        # Validate cache structure
        if not isinstance(cache_data, dict) or "weights" not in cache_data or "timestamp" not in cache_data:
            bt.logging.warning("[POOL WEIGHTS CACHE] Invalid cache structure, ignoring")
            return None
        
        bt.logging.debug(
            f"[POOL WEIGHTS CACHE] Loaded cache from {CACHE_FILE} "
            f"(timestamp: {cache_data.get('timestamp')})"
        )
        return cache_data
        
    except Exception as exc:
        bt.logging.error(f"[POOL WEIGHTS CACHE] Failed to load cache: {exc}")
        return None


def _save_cache(weights: dict[str, float]) -> None:
    """Save pool weights to disk cache.
    
    Args:
        weights: Dictionary mapping pool_id to weight (basis points)
    """
    try:
        # Ensure cache directory exists
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        cache_data = {
            "weights": weights,
            "timestamp": datetime.utcnow().isoformat(),
            "cache_ttl_hours": CACHE_TTL_HOURS,
        }
        
        with CACHE_FILE.open("w") as f:
            json.dump(cache_data, f, indent=2)
        
        bt.logging.info(
            f"[POOL WEIGHTS CACHE] Saved {len(weights)} pool weights to cache "
            f"(valid for {CACHE_TTL_HOURS}h)"
        )
        
    except Exception as exc:
        bt.logging.error(f"[POOL WEIGHTS CACHE] Failed to save cache: {exc}")


def _is_cache_valid(cache_data: dict[str, Any] | None) -> bool:
    """Check if cached weights are still valid (within TTL).
    
    Args:
        cache_data: Cache data containing timestamp
        
    Returns:
        True if cache is valid and within TTL, False otherwise
    """
    if cache_data is None:
        return False
    
    try:
        cached_time = datetime.fromisoformat(cache_data["timestamp"])
        now = datetime.utcnow()
        age = now - cached_time
        
        is_valid = age < timedelta(hours=CACHE_TTL_HOURS)
        
        if is_valid:
            remaining = timedelta(hours=CACHE_TTL_HOURS) - age
            hours_remaining = remaining.total_seconds() / 3600
            bt.logging.info(
                f"[POOL WEIGHTS CACHE] Using cached weights "
                f"(age: {age.total_seconds() / 3600:.1f}h, valid for {hours_remaining:.1f}h more)"
            )
        else:
            bt.logging.info(
                f"[POOL WEIGHTS CACHE] Cache expired "
                f"(age: {age.total_seconds() / 3600:.1f}h > TTL: {CACHE_TTL_HOURS}h)"
            )
        
        return is_valid
        
    except Exception as exc:
        bt.logging.error(f"[POOL WEIGHTS CACHE] Failed to validate cache timestamp: {exc}")
        return False


def query_pool_weights(
    parent_vault_address: str,
    rpc_url: str,
    timeout: float = 15.0,
) -> dict[str, float]:
    """Query pool weights from parent vault contract using calculateTargetAllocations().
    
    Args:
        parent_vault_address: Address of the parent vault contract
        rpc_url: RPC endpoint URL
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary mapping pool_id (hex string) to weight (float, as basis points)
        Example: {"0xee62...": 4000, "0x0b43...": 3500} (where 4000 = 40.00%)
        
    Raises:
        httpx.HTTPError: If RPC request fails
        ValueError: If response cannot be decoded
    """
    bt.logging.debug(
        f"[POOL WEIGHTS] Querying weights from parent vault {parent_vault_address}"
    )
    
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": parent_vault_address, "data": CALCULATE_TARGET_ALLOCATIONS_SELECTOR}, "latest"],
        "id": 1,
    }
    
    with httpx.Client(timeout=timeout) as client:
        response = client.post(rpc_url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        if "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            raise ValueError(f"RPC error: {error_msg}")
        
        hex_result = result.get("result", "")
        if not hex_result or hex_result == "0x":
            raise ValueError("Empty response from contract")
        
        return _decode_target_allocations_response(hex_result)


def _decode_target_allocations_response(hex_result: str) -> dict[str, float]:
    """Decode ABI-encoded calculateTargetAllocations() response.
    
    Returns (address[] vaults, uint256[] targetWeights)
    
    Args:
        hex_result: Hex-encoded ABI response
        
    Returns:
        Dictionary mapping pool_id to weight (as basis points, e.g., 4000 = 40%)
    """
    hex_str = hex_result[2:]  # Remove 0x prefix
    
    # Parse tuple structure: (address[], uint256[])
    # First 32 bytes: offset to vaults array
    # Next 32 bytes: offset to targetWeights array
    vaults_offset = int(hex_str[0:64], 16) * 2  # Convert to hex chars
    weights_offset = int(hex_str[64:128], 16) * 2  # Convert to hex chars
    
    # Parse vaults array
    vaults_len = int(hex_str[vaults_offset:vaults_offset + 64], 16)
    vaults = []
    for i in range(vaults_len):
        # Each address is 32 bytes (64 hex chars), last 20 bytes are the address
        addr_start = vaults_offset + 64 + (i * 64)
        addr_hex = hex_str[addr_start + 24:addr_start + 64]
        vaults.append("0x" + addr_hex.lower())
    
    # Parse targetWeights array
    weights_len = int(hex_str[weights_offset:weights_offset + 64], 16)
    target_weights = []
    for i in range(weights_len):
        weight_start = weights_offset + 64 + (i * 64)
        weight = int(hex_str[weight_start:weight_start + 64], 16)
        target_weights.append(weight)
    
    # Map vault addresses to pool IDs
    weights: dict[str, float] = {}
    
    for vault_addr, weight in zip(vaults, target_weights):
        pool_id = VAULT_TO_POOL_ID.get(vault_addr)
        if pool_id:
            weights[pool_id] = float(weight)
            bt.logging.debug(
                f"[POOL WEIGHTS] Found pool {pool_id[:20]}... "
                f"vault {vault_addr} weight={weight} bps"
            )
        else:
            bt.logging.warning(
                f"[POOL WEIGHTS] Unknown vault address {vault_addr} (weight={weight}), skipping"
            )
    
    bt.logging.info(
        f"[POOL WEIGHTS] Retrieved {len(weights)} pool weights: "
        f"{', '.join(f'{pid[:20]}...={w:.0f}bps' for pid, w in sorted(weights.items()))}"
    )
    
    return weights


def query_all_parent_vaults(
    rpc_url: str,
    timeout: float = 15.0,
    retry_attempts: int = 3,
    delay_between_vaults: float = 1.0,
) -> dict[str, float]:
    """Query pool weights from all parent vaults on mainnet with retry logic.
    
    Args:
        rpc_url: RPC endpoint URL for Base mainnet
        timeout: Request timeout in seconds
        retry_attempts: Number of retry attempts per vault on failure
        delay_between_vaults: Delay in seconds between querying different vaults (to avoid rate limiting)
        
    Returns:
        Dictionary mapping pool_id to weight (as basis points)
        Combined weights from all parent vaults
    """
    combined_weights: dict[str, float] = {}
    
    for idx, (category, parent_address) in enumerate(PARENT_VAULT_ADDRESSES.items()):
        # Add delay between vault queries to avoid rate limiting (skip for first vault)
        if idx > 0 and delay_between_vaults > 0:
            bt.logging.debug(
                f"[POOL WEIGHTS] Waiting {delay_between_vaults}s before next vault query..."
            )
            time.sleep(delay_between_vaults)
        
        # Retry logic for each vault
        for attempt in range(retry_attempts):
            try:
                bt.logging.info(
                    f"[POOL WEIGHTS] Querying {category} parent vault: {parent_address}"
                    + (f" (attempt {attempt + 1}/{retry_attempts})" if attempt > 0 else "")
                )
                weights = query_pool_weights(parent_address, rpc_url, timeout)
                combined_weights.update(weights)
                break  # Success, exit retry loop
                
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:  # Rate limit
                    if attempt < retry_attempts - 1:
                        # Exponential backoff: 2s, 4s, 8s...
                        backoff_delay = 2 ** (attempt + 1)
                        bt.logging.warning(
                            f"[POOL WEIGHTS] Rate limited on {category} vault. "
                            f"Retrying in {backoff_delay}s... (attempt {attempt + 1}/{retry_attempts})"
                        )
                        time.sleep(backoff_delay)
                    else:
                        bt.logging.error(
                            f"[POOL WEIGHTS] Failed to query {category} parent vault {parent_address} "
                            f"after {retry_attempts} attempts (rate limited): {exc}"
                        )
                else:
                    bt.logging.error(
                        f"[POOL WEIGHTS] HTTP error querying {category} parent vault {parent_address}: {exc}"
                    )
                    break  # Don't retry on non-rate-limit errors
                    
            except Exception as exc:
                bt.logging.error(
                    f"[POOL WEIGHTS] Failed to query {category} parent vault {parent_address}: {exc}"
                )
                break  # Don't retry on unexpected errors
    
    return combined_weights


def get_pool_weights_for_scoring(
    parent_vault_address: str,
    rpc_url: str,
    timeout: float = 15.0,
    fallback_weights: Mapping[str, float] | None = None,
    force_refresh: bool = False,
) -> dict[str, float]:
    """Get pool weights for scoring, with 24-hour caching to avoid rate limiting.
    
    Args:
        parent_vault_address: Legacy parameter (ignored, kept for backward compatibility)
        rpc_url: RPC endpoint URL (required, should be Base mainnet)
        timeout: Request timeout in seconds
        fallback_weights: Fallback weights if query fails
        force_refresh: Force cache refresh even if cache is valid (default: False)
        
    Returns:
        Dictionary mapping pool_id to weight (float, as decimal for scoring)
        Weights are normalized to sum to 1.0 across all pools.
        
    Note:
        - Weights are cached for 24 hours to avoid rate limiting
        - Cache is checked first, only queries chain if cache is stale or missing
        - Each parent vault has 10,000 basis points (100%) distributed among its child vaults
        - With 3 parent vaults, total = 30,000 basis points
        - Weights are normalized by dividing by the total sum (e.g., 6000/30000 = 0.2 = 20%)
    """
    # Try to load from cache first (unless force refresh)
    if not force_refresh:
        cache_data = _load_cache()
        if _is_cache_valid(cache_data):
            # Use cached weights
            weights = cache_data["weights"]
            bt.logging.info(
                f"[POOL WEIGHTS] Using cached weights ({len(weights)} pools)"
            )
            
            # Normalize cached weights
            total_weight = sum(weights.values())
            if total_weight > 0:
                normalized_weights = {pid: w / total_weight for pid, w in weights.items()}
                
                bt.logging.debug(
                    f"[POOL WEIGHTS] Cached weights normalized: "
                    f"Total raw: {total_weight:.0f} bps, "
                    f"Normalized sum: {sum(normalized_weights.values()):.4f}"
                )
                
                return normalized_weights
            else:
                bt.logging.warning("[POOL WEIGHTS] Cached weights have zero total, refreshing...")
    
    # Cache is stale, missing, or force refresh - query from chain
    try:
        bt.logging.info("[POOL WEIGHTS] Querying fresh weights from chain...")
        
        # Query all parent vaults with rate limiting protection
        weights = query_all_parent_vaults(
            rpc_url,
            timeout=timeout,
            retry_attempts=3,
            delay_between_vaults=2.0,  # 2 second delay to avoid rate limiting
        )
        
        if not weights:
            raise ValueError("No weights retrieved from any parent vault")
        
        # Save to cache for future use
        _save_cache(weights)
        
        # Calculate total weight across all parent vaults
        # Each parent vault has 10,000 bps (100%), so with 3 parents total should be ~30,000
        total_weight = sum(weights.values())
        
        if total_weight == 0:
            raise ValueError("Total weight is zero - cannot normalize")
        
        # Normalize weights to sum to 1.0 across all pools
        # Example: 6000 bps / 30000 total = 0.2 (20% of all pools)
        normalized_weights = {pid: w / total_weight for pid, w in weights.items()}
        
        bt.logging.info(
            f"[POOL WEIGHTS] Total pools weighted: {len(normalized_weights)}, "
            f"Total raw weight: {total_weight:.0f} bps, "
            f"Normalized weight sum: {sum(normalized_weights.values()):.4f}"
        )
        
        return normalized_weights
        
    except Exception as exc:
        bt.logging.error(
            f"[POOL WEIGHTS] Failed to query weights from chain: {exc}."
        )
        
        # Try to use cached weights even if expired, as a last resort
        cache_data = _load_cache()
        if cache_data and "weights" in cache_data:
            bt.logging.warning(
                "[POOL WEIGHTS] Using expired cache as fallback due to query failure"
            )
            weights = cache_data["weights"]
            total_weight = sum(weights.values())
            if total_weight > 0:
                normalized_weights = {pid: w / total_weight for pid, w in weights.items()}
                return normalized_weights
        
        # Last resort: use fallback weights
        if fallback_weights:
            bt.logging.warning("[POOL WEIGHTS] Using fallback weights")
            return {
                pid: w / 100.0 if w > 1.0 else w
                for pid, w in fallback_weights.items()
            }
        
        # If no fallback and query failed, raise error
        raise RuntimeError(
            f"Failed to query pool weights from chain and no fallback weights provided: {exc}"
        ) from exc

