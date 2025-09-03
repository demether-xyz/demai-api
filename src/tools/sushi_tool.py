"""
SushiSwap swap tool for Katana via vault executeStrategy

This module mirrors the structure of akka_tool.py but targets Sushi's
router directly (Uniswap V2-style) on Katana. It builds calldata for
`swapExactTokensForTokens` and executes through the Vault's
`executeStrategy` with inline approvals.

Optionally, you can set the router address via env var:
- `SUSHI_ROUTER_KATANA`

Notes:
- This implementation assumes a V2-style router that exposes
  `getAmountsOut(uint256,address[])` and
  `swapExactTokensForTokens(uint256,uint256,address[],address,uint256)`.
- Multi-hop routes are supported by providing an address path; by default
  we attempt a single-hop `[src, dst]` path.
"""
from typing import Optional, List, Dict, Any
from web3 import Web3
from eth_abi import encode
import asyncio
import logging
import json
import os
import time

logger = logging.getLogger(__name__)

# Default slippage tolerance (3%)
DEFAULT_SLIPPAGE = 0.03

# Default gas limit for swap operations
DEFAULT_SWAP_GAS_LIMIT = 1_200_000

# Sushi router contract addresses
# Provide router address via env var to avoid hardcoding unknowns.
SUSHI_ROUTER_CONTRACTS: Dict[int, Dict[str, Optional[str]]] = {
    747474: {  # Katana
        "router": os.getenv("SUSHI_ROUTER_KATANA"),
    }
}

# Minimal ABI for read-only quote
SUSHI_ROUTER_READ_ABI = [
    {
        "name": "getAmountsOut",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "path", "type": "address[]"},
        ],
        "outputs": [
            {"name": "amounts", "type": "uint256[]"}
        ],
    }
]


def _build_swap_exact_tokens_calldata(
    amount_in: int,
    amount_out_min: int,
    path: List[str],
    to: str,
    deadline: int,
) -> bytes:
    """
    Encode calldata for UniswapV2-style `swapExactTokensForTokens`.
    """
    try:
        selector = Web3.keccak(
            text="swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"
        )[:4]
        encoded = encode(
            ["uint256", "uint256", "address[]", "address", "uint256"],
            [
                int(amount_in),
                int(amount_out_min),
                [Web3.to_checksum_address(a) for a in path],
                Web3.to_checksum_address(to),
                int(deadline),
            ],
        )
        return selector + encoded
    except Exception as e:
        logger.error(f"Error encoding swap calldata: {e}")
        raise


async def _get_amounts_out(
    executor,  # ToolExecutor
    router: str,
    amount_in: int,
    path: List[str],
) -> Optional[List[int]]:
    """
    Call router.getAmountsOut to estimate outputs for the path.
    """
    try:
        contract = executor.w3.eth.contract(
            address=Web3.to_checksum_address(router),
            abi=SUSHI_ROUTER_READ_ABI,
        )
        amounts: List[int] = await contract.functions.getAmountsOut(
            int(amount_in),
            [Web3.to_checksum_address(a) for a in path],
        ).call()
        return [int(a) for a in amounts]
    except Exception as e:
        logger.error(f"Error calling getAmountsOut: {e}")
        return None


async def execute_sushi_swap(
    executor,  # ToolExecutor instance
    chain_id: int,
    vault_address: str,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = DEFAULT_SLIPPAGE,
    path: Optional[List[str]] = None,
    gas_limit: Optional[int] = None,
) -> str:
    """
    Execute a Sushi router swap on Katana via the vault strategy call.
    - Encodes swapExactTokensForTokens calldata
    - Adds inline approval for `src_token` and `amount`
    """
    if chain_id not in SUSHI_ROUTER_CONTRACTS:
        raise ValueError(f"Sushi router not configured for chain {chain_id}")

    router = SUSHI_ROUTER_CONTRACTS[chain_id].get("router")
    if not router:
        raise ValueError(
            "Sushi router address not set. Provide env var SUSHI_ROUTER_KATANA"
        )

    # Default path is single-hop [src, dst]
    if not path:
        path = [src_token, dst_token]

    # Estimate outputs to compute amountOutMin
    amounts = await _get_amounts_out(
        executor=executor,
        router=router,
        amount_in=amount,
        path=path,
    )
    if not amounts or len(amounts) != len(path):
        raise ValueError("Failed to getAmountsOut for provided path")

    amount_out = int(amounts[-1])
    amount_out_min = int(amount_out * (1 - float(slippage)))

    # Encode calldata for swap
    deadline = int(time.time()) + 600  # 10 minutes
    calldata = _build_swap_exact_tokens_calldata(
        amount_in=int(amount),
        amount_out_min=amount_out_min,
        path=path,
        to=vault_address,
        deadline=deadline,
    )

    # Approvals (vault -> router for src token)
    approvals = [(Web3.to_checksum_address(src_token), int(amount))]

    if gas_limit is None:
        gas_limit = DEFAULT_SWAP_GAS_LIMIT

    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=router,
        call_data=calldata,
        approvals=approvals,
        gas_limit=gas_limit,
    )


async def get_sushi_swap_estimate(
    executor,  # ToolExecutor instance
    chain_id: int,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = DEFAULT_SLIPPAGE,
    path: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Get a quote via router.getAmountsOut for a path and slippage.
    """
    if chain_id not in SUSHI_ROUTER_CONTRACTS:
        return {"error": f"Sushi router not configured for chain {chain_id}"}

    router = SUSHI_ROUTER_CONTRACTS[chain_id].get("router")
    if not router:
        return {"error": "Sushi router address not set (SUSHI_ROUTER_KATANA)"}

    if not path:
        path = [src_token, dst_token]

    amounts = await _get_amounts_out(executor, router, amount, path)
    if not amounts or len(amounts) != len(path):
        return {"error": "Failed to getAmountsOut"}

    dst_amount = int(amounts[-1])
    dst_amount_min = int(dst_amount * (1 - float(slippage)))

    return {
        "src_amount": int(amount),
        "dst_amount": dst_amount,
        "dst_amount_min": dst_amount_min,
        "path": [Web3.to_checksum_address(a) for a in path],
    }


def create_sushi_tool(
    vault_address: str,
    private_key: Optional[str] = None,
):
    """
    Create an LLM-callable Sushi swap tool for Katana.
    Mirrors the pattern used in akka_tool.create_swap_tool.
    """
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
    from tools.tool_executor import ToolExecutor

    if not private_key:
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise ValueError("PRIVATE_KEY not provided and not found in environment")

    async def sushi_swap_operation(
        chain_name: str,
        src_token: str,
        dst_token: str,
        amount: float,
    ) -> str:
        try:
            # Only Katana supported here
            chain_id = None
            for c_id, cfg in CHAIN_CONFIG.items():
                if cfg["name"].lower() == chain_name.lower():
                    chain_id = c_id
                    break

            if chain_id != 747474:
                return json.dumps({
                    "status": "error",
                    "message": "Sushi swap currently supported only on Katana",
                })

            rpc_url = RPC_ENDPOINTS.get(chain_id)
            if not rpc_url:
                return json.dumps({
                    "status": "error",
                    "message": f"RPC URL not found for chain: {chain_name}",
                })

            src_cfg = SUPPORTED_TOKENS.get(src_token.upper())
            dst_cfg = SUPPORTED_TOKENS.get(dst_token.upper())
            if not src_cfg or not dst_cfg:
                return json.dumps({"status": "error", "message": "Unsupported token symbol"})

            src_addr = src_cfg["addresses"].get(chain_id)
            dst_addr = dst_cfg["addresses"].get(chain_id)
            if not src_addr or not dst_addr:
                return json.dumps({
                    "status": "error",
                    "message": f"Token not available on {chain_name}",
                })

            # Convert to base units
            amount_wei = int(amount * (10 ** int(src_cfg["decimals"])) )

            executor = ToolExecutor(rpc_url, private_key)

            tx_hash = await execute_sushi_swap(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                src_token=src_addr,
                dst_token=dst_addr,
                amount=amount_wei,
                slippage=DEFAULT_SLIPPAGE,
            )

            return json.dumps({
                "status": "success",
                "message": f"Swapped {amount} {src_token} -> {dst_token} on {chain_name}",
                "data": {
                    "src_token": src_token,
                    "dst_token": dst_token,
                    "amount": amount,
                    "chain": chain_name,
                    "vault": vault_address,
                    "tx_hash": tx_hash,
                },
            })
        except Exception as e:
            logger.error(f"Error in sushi_swap_operation: {e}")
            return json.dumps({"status": "error", "message": str(e)})

    return {
        "tool": sushi_swap_operation,
        "metadata": {
            "name": "sushi_swap",
            "description": "Swap tokens on Katana via Sushi router",
            "vault": vault_address,
            "parameters": {
                "chain_name": "Blockchain network (only 'Katana')",
                "src_token": "Source token symbol",
                "dst_token": "Destination token symbol",
                "amount": "Amount to swap (human-readable)",
            },
        },
    }

