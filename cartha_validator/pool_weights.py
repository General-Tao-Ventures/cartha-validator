"""Pool weight querying from parent vault contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import bittensor as bt
import httpx

# Pool ID to Vault Address mapping (Base Sepolia testnet)
# These are the known vault addresses for each pool
POOL_ID_TO_VAULT: dict[str, str] = {
    "0xee62665949c883f9e0f6f002eac32e00bd59dfe6c34e92a91c37d6a8322d6489": "0x471D86764B7F99b894ee38FcD3cEFF6EAB321b69",  # BTCUSD
    "0x0b43555ace6b39aae1b894097d0a9fc17f504c62fea598fa206cc6f5088e6e45": "0xdB74B44957A71c95406C316f8d3c5571FA588248",  # ETHUSD
    "0xa9226449042e36bf6865099eec57482aa55e3ad026c315a0e4a692b776c318ca": "0x3C4dAfAC827140B8a031d994b7e06A25B9f27BAD",  # EURUSD
}

# Vault Address to Pool ID mapping (reverse lookup)
VAULT_TO_POOL_ID: dict[str, str] = {v.lower(): k for k, v in POOL_ID_TO_VAULT.items()}

# Function selector for getPools() - keccak256("getPools()")[:4]
GET_POOLS_SELECTOR = "0x673a2a1f"


def query_pool_weights(
    parent_vault_address: str,
    rpc_url: str,
    timeout: float = 15.0,
) -> dict[str, float]:
    """Query pool weights from parent vault contract.
    
    Args:
        parent_vault_address: Address of the parent vault contract
        rpc_url: RPC endpoint URL
        timeout: Request timeout in seconds
        
    Returns:
        Dictionary mapping pool_id (hex string) to weight (float, as percentage)
        Example: {"0xee62...": 50.0, "0x0b43...": 30.0}
        
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
        "params": [{"to": parent_vault_address, "data": GET_POOLS_SELECTOR}, "latest"],
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
        
        return _decode_pools_response(hex_result)


def _decode_pools_response(hex_result: str) -> dict[str, float]:
    """Decode ABI-encoded PoolConfig[] array.
    
    Args:
        hex_result: Hex-encoded ABI response
        
    Returns:
        Dictionary mapping pool_id to weight (as percentage)
    """
    hex_str = hex_result[2:]  # Remove 0x prefix
    
    # Parse array structure
    # Offset (first 64 chars): points to array data
    offset = int(hex_str[0:64], 16)
    
    # Array length (next 64 chars after offset)
    array_len = int(hex_str[64:128], 16)
    
    # Each PoolConfig struct is 5 * 32 bytes = 160 bytes = 320 hex chars
    struct_size = 320
    start_idx = 128  # After offset and length
    
    weights: dict[str, float] = {}
    total_weight = 0.0
    
    for i in range(array_len):
        struct_start = start_idx + (i * struct_size)
        
        # Extract vault address (last 40 chars of first 64-char field = 20 bytes)
        vault_hex = hex_str[struct_start + 24 : struct_start + 64]
        vault_addr = "0x" + vault_hex.lower()
        
        # Extract weight (next 64 chars = 32 bytes uint256)
        weight_hex = hex_str[struct_start + 64 : struct_start + 128]
        weight = int(weight_hex, 16)
        
        # Map vault address to pool ID
        pool_id = VAULT_TO_POOL_ID.get(vault_addr)
        if pool_id:
            weights[pool_id] = float(weight)
            total_weight += weight
            bt.logging.debug(
                f"[POOL WEIGHTS] Found pool {pool_id[:20]}... "
                f"vault {vault_addr} weight={weight}%"
            )
        else:
            bt.logging.warning(
                f"[POOL WEIGHTS] Unknown vault address {vault_addr}, skipping"
            )
    
    # Find all pool IDs that don't have weights set on chain
    all_pool_ids = set(POOL_ID_TO_VAULT.keys())
    pools_without_weights = all_pool_ids - set(weights.keys())
    
    # Calculate remaining percentage and split evenly among pools without weights
    remaining_percentage = 100.0 - total_weight
    
    if pools_without_weights and remaining_percentage > 0:
        num_pools_without_weights = len(pools_without_weights)
        weight_per_pool = remaining_percentage / num_pools_without_weights
        
        for pool_id in pools_without_weights:
            weights[pool_id] = weight_per_pool
            bt.logging.info(
                f"[POOL WEIGHTS] Pool {pool_id[:20]}... not found in contract, "
                f"assigned {weight_per_pool:.2f}% (split from remaining {remaining_percentage:.2f}%)"
            )
    elif remaining_percentage > 0:
        bt.logging.warning(
            f"[POOL WEIGHTS] Remaining {remaining_percentage:.2f}% unallocated "
            f"(all known pools have weights set)"
        )
    elif remaining_percentage < 0:
        bt.logging.warning(
            f"[POOL WEIGHTS] Total weights exceed 100%: {total_weight:.2f}%"
        )
    
    bt.logging.info(
        f"[POOL WEIGHTS] Retrieved {len(weights)} pool weights: "
        f"{', '.join(f'{pid[:20]}...={w:.2f}%' for pid, w in sorted(weights.items()))}"
    )
    
    return weights


def get_pool_weights_for_scoring(
    parent_vault_address: str,
    rpc_url: str,
    timeout: float = 15.0,
    fallback_weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Get pool weights for scoring, querying from chain.
    
    Args:
        parent_vault_address: Parent vault contract address (required)
        rpc_url: RPC endpoint URL (required)
        timeout: Request timeout in seconds
        fallback_weights: Fallback weights if query fails
        
    Returns:
        Dictionary mapping pool_id to weight (float, as percentage/100 for scoring)
        Example: {"0xee62...": 0.5, "0x0b43...": 0.3}
        
    Note:
        Weights are converted from percentage (50, 30) to decimal (0.5, 0.3)
        for use in scoring calculations.
    """
    try:
        weights = query_pool_weights(parent_vault_address, rpc_url, timeout)
        # Convert from percentage (50, 30) to decimal (0.5, 0.3) for scoring
        return {pid: w / 100.0 for pid, w in weights.items()}
    except Exception as exc:
        bt.logging.error(
            f"[POOL WEIGHTS] Failed to query weights from chain: {exc}. "
            "Using fallback weights."
        )
        if fallback_weights:
            return {
                pid: w / 100.0 if w > 1.0 else w
                for pid, w in fallback_weights.items()
            }
        # If no fallback and query failed, raise error
        raise RuntimeError(
            f"Failed to query pool weights from chain and no fallback weights provided: {exc}"
        ) from exc

