"""
Akka Finance strategy implementation for swapping tokens via the vault

This module provides integration with Akka Finance for token swaps using the 
Vault's executeStrategy function.
"""
from typing import Optional, List, Dict, Any
from web3 import Web3
from eth_abi import encode
import asyncio
import logging
import json
import os
import httpx

logger = logging.getLogger(__name__)

# Akka router contract addresses
AKKA_STRATEGY_CONTRACTS = {
    1116: {  # Core
        "router": "0x7C5Af181D9e9e91B15660830B52f7B7076Be0d64",
    }
}

# Akka API endpoints
AKKA_API_BASE = "https://routerv2.akka.finance/v2"

# Akka router function signatures
AKKA_STRATEGY_FUNCTIONS = {
    "multiPathSwap": {
        "function_name": "multiPathSwap",
        "function_signature": "multiPathSwap(uint256,uint256,(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[],address,uint256,uint8,bytes32,bytes32)",
        "requires_approval": True
    }
}

async def get_akka_quote(
    chain_id: int,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = 0.01
) -> Optional[Dict[str, Any]]:
    """
    Get swap quote from Akka API
    
    Args:
        chain_id: Chain ID
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        slippage: Slippage tolerance (default 1%)
        
    Returns:
        Quote data or None if error
    """
    try:
        url = f"{AKKA_API_BASE}/{chain_id}/pks-quote"
        params = {
            "src": src_token,
            "dst": dst_token,
            "amount": str(amount)
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                quote_data = response.json()
                logger.info(f"Got Akka quote: {amount} {src_token} -> {quote_data.get('outputAmount', {}).get('value', 'N/A')} {dst_token}")
                return quote_data
            else:
                logger.error(f"Failed to get Akka quote: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Error getting Akka quote: {e}")
        return None


async def get_akka_strategy_balances(web3_instances: Dict, vault_address: str, supported_tokens: Dict) -> List[Dict[str, Any]]:
    """
    Get Akka strategy balances (placeholder - Akka is a DEX aggregator, not a lending protocol)
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        vault_address: Vault contract address
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        Empty list as Akka doesn't hold balances
    """
    # Akka is a DEX aggregator, not a lending/yield protocol
    # It doesn't hold user funds, so there are no balances to retrieve
    return []

def _construct_akka_swap_calldata(
    quote_data: Dict[str, Any],
    receiver: str
) -> bytes:
    """
    Construct calldata for Akka multiPathSwap from quote data
    
    Args:
        quote_data: Quote data from Akka pks-quote API
        receiver: Address to receive swapped tokens (vault address)
        
    Returns:
        Encoded calldata for swap
    """
    try:
        swap_data = quote_data.get("swapData", {})
        
        # Extract parameters from swapData
        amount_in = int(swap_data.get("amountIn", "0"))
        amount_out_min = int(swap_data.get("amountOutMin", "0"))
        paths_data = swap_data.get("data", [])
        
        # Extract signature parameters from akkaFee
        akka_fee = swap_data.get("akkaFee", {})
        fee = int(akka_fee.get("fee", "0"))
        v = int(akka_fee.get("v", "0"))
        r = akka_fee.get("r", "0x" + "0" * 64)
        s = akka_fee.get("s", "0x" + "0" * 64)
        
        # Convert paths data to proper format
        paths = []
        for path_data in paths_data:
            if len(path_data) >= 5:
                src_amount = int(path_data[0])
                dst_min_amount = int(path_data[1])
                is_from_native = int(path_data[2])
                is_to_native = int(path_data[3])
                pools_data = path_data[4]
                
                # Convert pools
                pools = []
                for pool in pools_data:
                    if len(pool) >= 9:
                        pools.append((
                            Web3.to_checksum_address(pool[0]),  # srcToken
                            Web3.to_checksum_address(pool[1]),  # dstToken
                            Web3.to_checksum_address(pool[2]),  # pairAddr
                            int(pool[3]),  # fee
                            int(pool[4]),  # srcAmount
                            int(pool[5]),  # dstMinAmount
                            int(pool[6]),  # feeSrc
                            int(pool[7]),  # feeDst
                            int(pool[8])   # liquidityType
                        ))
                
                paths.append((
                    src_amount,
                    dst_min_amount,
                    is_from_native,
                    is_to_native,
                    pools
                ))
        
        # Encode multiPathSwap function call
        function_selector = Web3.keccak(text="multiPathSwap(uint256,uint256,(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[],address,uint256,uint8,bytes32,bytes32)")[:4]
        
        # Encode parameters
        encoded_params = encode(
            ['uint256', 'uint256', '(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[]', 'address', 'uint256', 'uint8', 'bytes32', 'bytes32'],
            [
                amount_in,  # amountIn
                amount_out_min,  # amountOutMin
                paths,  # paths
                Web3.to_checksum_address(receiver),  # to
                fee,  # fee
                v,  # v
                bytes.fromhex(r[2:]) if isinstance(r, str) and r.startswith("0x") else r,  # r
                bytes.fromhex(s[2:]) if isinstance(s, str) and s.startswith("0x") else s   # s
            ]
        )
        
        return function_selector + encoded_params
            
    except Exception as e:
        logger.error(f"Error constructing Akka swap calldata: {e}")
        raise


async def execute_akka_swap(
    executor,  # StrategyExecutor instance
    chain_id: int,
    vault_address: str,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = 0.01,
    gas_limit: Optional[int] = None
) -> str:
    """
    Execute token swap via Akka
    
    Args:
        executor: StrategyExecutor instance
        chain_id: Chain ID
        vault_address: Vault contract address
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        slippage: Slippage tolerance (default 1%)
        gas_limit: Optional gas limit override
        
    Returns:
        Transaction hash
    """
    # Get quote from Akka
    quote_data = await get_akka_quote(
        chain_id, src_token, dst_token, amount, slippage
    )
    if not quote_data:
        raise ValueError("Failed to get Akka quote")
    
    # Construct calldata from quote
    call_data = _construct_akka_swap_calldata(quote_data, vault_address)
    
    # Get the router address
    if chain_id not in AKKA_STRATEGY_CONTRACTS:
        raise ValueError(f"Akka strategy not supported on chain {chain_id}")
    target_contract = AKKA_STRATEGY_CONTRACTS[chain_id]["router"]
    
    # Construct approvals based on source token
    approvals = [(Web3.to_checksum_address(src_token), amount)]
    
    # Check if swap requires ETH
    value = int(quote_data.get("swapData", {}).get("value", 0))
    if value > 0:
        logger.warning(f"Akka swap requires {value} wei ETH value, but vault executeStrategy doesn't support ETH transfers")
    
    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=target_contract,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )

async def get_akka_swap_estimate(
    chain_id: int,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = 0.01
) -> Dict[str, Any]:
    """
    Get swap estimate from Akka without executing
    
    Args:
        chain_id: Chain ID
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        slippage: Slippage tolerance (default 1%)
        
    Returns:
        Dictionary with swap estimate details
    """
    quote_data = await get_akka_quote(chain_id, src_token, dst_token, amount, slippage)
    
    if not quote_data:
        return {"error": "Failed to get quote from Akka"}
    
    try:
        input_amount = quote_data["inputAmount"]
        output_amount = quote_data["outputAmount"]
        
        # Calculate price impact if available
        price_impact = None
        if "priceImpact" in quote_data:
            price_impact = float(quote_data["priceImpact"])
        
        return {
            "src_token": src_token,
            "dst_token": dst_token,
            "src_amount": input_amount["value"],
            "dst_amount": output_amount["value"],
            "dst_amount_min": int(int(output_amount["value"]) * (1 - slippage)),
            "price_impact": price_impact,
            "route": quote_data.get("route", "Unknown"),
            "gas_estimate": quote_data.get("estimatedGas", 0)
        }
        
    except Exception as e:
        logger.error(f"Error parsing Akka quote: {e}")
        return {"error": str(e)}

def swap_tokens_via_akka(
    src_token_symbol: str,
    dst_token_symbol: str,
    amount: float,
    chain_name: str,
    vault_address: str,
    slippage: float = 0.01
) -> str:
    """
    Swap tokens using Akka Finance on a specified chain.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        src_token_symbol: Symbol of source token (e.g., "USDC")
        dst_token_symbol: Symbol of destination token (e.g., "USDT")
        amount: Amount to swap (human-readable format)
        chain_name: Name of the blockchain network (e.g., "Arbitrum")
        vault_address: Address of the vault initiating the swap
        slippage: Slippage tolerance (default 1%)
        
    Returns:
        JSON string indicating success or failure with transaction hash
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from strategies.strategies import StrategyExecutor
        
        # Get private key from environment variable
        PRIVATE_KEY = os.getenv("PRIVATE_KEY")
        if not PRIVATE_KEY:
            return json.dumps({"status": "error", "message": "PRIVATE_KEY environment variable not set"})
        
        # Find chain_id from chain_name
        chain_id = None
        for c_id, config in CHAIN_CONFIG.items():
            if config["name"].lower() == chain_name.lower():
                chain_id = c_id
                break
                
        if chain_id is None:
            return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})
        
        # Get token details
        src_token_config = SUPPORTED_TOKENS.get(src_token_symbol.upper())
        dst_token_config = SUPPORTED_TOKENS.get(dst_token_symbol.upper())
        
        if not src_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported source token: {src_token_symbol}"})
        if not dst_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported destination token: {dst_token_symbol}"})
        
        src_address = src_token_config["addresses"].get(chain_id)
        dst_address = dst_token_config["addresses"].get(chain_id)
        
        if not src_address:
            return json.dumps({"status": "error", "message": f"Source token {src_token_symbol} not available on {chain_name}"})
        if not dst_address:
            return json.dumps({"status": "error", "message": f"Destination token {dst_token_symbol} not available on {chain_name}"})
        
        # Convert amount to smallest unit
        decimals = src_token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get RPC URL and initialize executor
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        executor = StrategyExecutor(rpc_url, PRIVATE_KEY)
        
        # Run the async swap function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tx_hash = loop.run_until_complete(execute_akka_swap(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                src_token=src_address,
                dst_token=dst_address,
                amount=amount_wei,
                slippage=slippage
            ))
        finally:
            loop.close()
            
        if tx_hash:
            return json.dumps({
                "status": "success",
                "message": "Swap transaction sent!",
                "tx_hash": tx_hash,
                "details": {
                    "src_token": src_token_symbol,
                    "dst_token": dst_token_symbol,
                    "amount": amount,
                    "chain": chain_name
                }
            })
        else:
            return json.dumps({"status": "error", "message": "Failed to send swap transaction"})
            
    except Exception as e:
        logger.error(f"Error in swap_tokens_via_akka: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

def get_akka_swap_quote(
    src_token_symbol: str,
    dst_token_symbol: str,
    amount: float,
    chain_name: str
) -> str:
    """
    Get a swap quote from Akka Finance without executing.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        src_token_symbol: Symbol of source token (e.g., "USDC")
        dst_token_symbol: Symbol of destination token (e.g., "USDT")
        amount: Amount to swap (human-readable format)
        chain_name: Name of the blockchain network (e.g., "Arbitrum")
        
    Returns:
        JSON string with quote details
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG
        
        # Find chain_id from chain_name
        chain_id = None
        for c_id, config in CHAIN_CONFIG.items():
            if config["name"].lower() == chain_name.lower():
                chain_id = c_id
                break
                
        if chain_id is None:
            return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})
        
        # Get token details
        src_token_config = SUPPORTED_TOKENS.get(src_token_symbol.upper())
        dst_token_config = SUPPORTED_TOKENS.get(dst_token_symbol.upper())
        
        if not src_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported source token: {src_token_symbol}"})
        if not dst_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported destination token: {dst_token_symbol}"})
        
        src_address = src_token_config["addresses"].get(chain_id)
        dst_address = dst_token_config["addresses"].get(chain_id)
        
        if not src_address:
            return json.dumps({"status": "error", "message": f"Source token {src_token_symbol} not available on {chain_name}"})
        if not dst_address:
            return json.dumps({"status": "error", "message": f"Destination token {dst_token_symbol} not available on {chain_name}"})
        
        # Convert amount to smallest unit
        decimals = src_token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get quote synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            estimate = loop.run_until_complete(get_akka_swap_estimate(
                chain_id=chain_id,
                src_token=src_address,
                dst_token=dst_address,
                amount=amount_wei
            ))
        finally:
            loop.close()
            
        if "error" in estimate:
            return json.dumps({"status": "error", "message": estimate["error"]})
            
        # Convert amounts back to human-readable format
        dst_decimals = dst_token_config["decimals"]
        
        return json.dumps({
            "status": "success",
            "data": {
                "src_token": src_token_symbol,
                "dst_token": dst_token_symbol,
                "src_amount": amount,
                "dst_amount": float(estimate["dst_amount"]) / (10 ** dst_decimals),
                "dst_amount_min": float(estimate["dst_amount_min"]) / (10 ** dst_decimals),
                "price_impact": estimate.get("price_impact"),
                "route": estimate.get("route"),
                "gas_estimate": estimate.get("gas_estimate"),
                "chain": chain_name
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_akka_swap_quote: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})