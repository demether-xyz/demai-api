"""
Yield Optimizer Strategy for automatic token switching based on highest yield

This strategy monitors the yields of specified tokens on Aave and automatically
switches between them to maximize returns.
"""
from typing import Optional, Dict, Any, Tuple, List
import asyncio
import logging
import json
import os

from ..tools.aave_tool import (
    get_aave_current_yield,
    get_atoken_address,
    supply_to_aave,
    withdraw_from_aave,
    _get_atoken_balance_async
)
from ..tools.akka_tool import execute_akka_swap

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_CONFIG = {
    "min_yield_difference": 0.5,  # Minimum yield difference (in percentage points) to trigger a switch
    "min_balance_usd": 10.0,      # Minimum balance (in USD) to consider for switching
    "tokens": ["USDT", "USDC"]     # Default tokens to optimize between
}

async def get_current_positions(
    web3_instances: Dict,
    vault_address: str,
    chain_id: int,
    supported_tokens: Dict,
    token_list: List[str]
) -> Dict[str, Dict[str, Any]]:
    """
    Get current token positions in Aave
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        vault_address: Vault contract address
        chain_id: Chain ID to check
        supported_tokens: Dictionary of supported tokens from config
        token_list: List of token symbols to check
        
    Returns:
        Dictionary with token position information
    """
    positions = {}
    
    for token_symbol in token_list:
        if token_symbol not in supported_tokens:
            logger.warning(f"Token {token_symbol} not in supported tokens")
            continue
            
        token_config = supported_tokens[token_symbol]
        if chain_id not in token_config["addresses"]:
            logger.warning(f"Token {token_symbol} not available on chain {chain_id}")
            continue
            
        # Get aToken address
        atoken_address = get_atoken_address(token_symbol, chain_id)
        if not atoken_address:
            logger.warning(f"No aToken address for {token_symbol} on chain {chain_id}")
            continue
            
        # Get balance
        balance = await _get_atoken_balance_async(
            web3_instances[chain_id],
            vault_address,
            atoken_address,
            token_config["decimals"]
        )
        
        # Get current yield
        yield_info = await get_aave_current_yield(
            web3_instances,
            token_symbol,
            chain_id,
            supported_tokens
        )
        
        positions[token_symbol] = {
            "balance": balance,
            "decimals": token_config["decimals"],
            "token_address": token_config["addresses"][chain_id],
            "atoken_address": atoken_address,
            "yield_apy": yield_info.get("supply_apy", 0) if "error" not in yield_info else 0,
            "yield_info": yield_info
        }
        
    return positions

async def compare_yields_and_positions(
    positions: Dict[str, Dict[str, Any]],
    min_yield_difference: float = 0.5,
    min_balance_usd: float = 10.0
) -> Tuple[Optional[str], Optional[str], float, bool]:
    """
    Compare yields and determine if switching is beneficial
    
    Args:
        positions: Current positions dictionary
        min_yield_difference: Minimum yield difference to trigger switch
        min_balance_usd: Minimum balance to consider for switching
        
    Returns:
        Tuple of (current_best_token, target_best_token, yield_difference, should_switch)
    """
    if not positions:
        return None, None, 0, False
    
    # Find token with highest balance (current position)
    current_token = None
    max_balance = 0
    
    for token, data in positions.items():
        balance = data.get("balance", 0)
        if balance > max_balance:
            max_balance = balance
            current_token = token
    
    # Find token with highest yield
    target_token = None
    max_yield = -1
    
    for token, data in positions.items():
        yield_apy = data.get("yield_apy", 0)
        if yield_apy > max_yield:
            max_yield = yield_apy
            target_token = token
    
    if not current_token or not target_token:
        return None, None, 0, False
    
    # Calculate yield difference
    current_yield = positions[current_token].get("yield_apy", 0)
    target_yield = positions[target_token].get("yield_apy", 0)
    yield_difference = abs(target_yield - current_yield)
    
    # Check if we should switch
    should_switch = (
        current_token != target_token and
        yield_difference >= min_yield_difference and
        positions[current_token]["balance"] > min_balance_usd
    )
    
    # Log comparison for all tokens
    yield_info = ", ".join([f"{token}: {data.get('yield_apy', 0):.2f}%" for token, data in positions.items()])
    logger.info(
        f"Yield comparison - {yield_info}. "
        f"Current: {current_token} ({current_yield:.2f}%), Target: {target_token} ({target_yield:.2f}%), "
        f"Difference: {yield_difference:.2f}%, Should switch: {should_switch}"
    )
    
    return current_token, target_token, yield_difference, should_switch

async def execute_yield_optimization(
    executor,  # StrategyExecutor instance
    chain_id: int,
    vault_address: str,
    web3_instances: Dict,
    supported_tokens: Dict,
    token_list: List[str] = None,
    min_yield_difference: float = None,
    min_balance_usd: float = None,
    slippage: float = 0.01,
    gas_limit: Optional[int] = None
) -> Dict[str, Any]:
    """
    Execute yield optimization strategy
    
    Args:
        executor: StrategyExecutor instance
        chain_id: Chain ID
        vault_address: Vault contract address
        web3_instances: Dictionary of Web3 instances by chain_id
        supported_tokens: Dictionary of supported tokens from config
        token_list: List of tokens to optimize between (default: ["USDT", "USDC"])
        min_yield_difference: Minimum yield difference to trigger switch
        min_balance_usd: Minimum balance to consider for switching
        slippage: Slippage tolerance for swaps (default 1%)
        gas_limit: Optional gas limit override
        
    Returns:
        Dictionary with execution results
    """
    try:
        # Use defaults if not provided
        if token_list is None:
            token_list = DEFAULT_CONFIG["tokens"]
        if min_yield_difference is None:
            min_yield_difference = DEFAULT_CONFIG["min_yield_difference"]
        if min_balance_usd is None:
            min_balance_usd = DEFAULT_CONFIG["min_balance_usd"]
            
        # Step 1: Get current positions
        positions = await get_current_positions(
            web3_instances,
            vault_address,
            chain_id,
            supported_tokens,
            token_list
        )
        
        # Step 2: Compare yields and determine if switching is needed
        current_token, target_token, yield_difference, should_switch = await compare_yields_and_positions(
            positions,
            min_yield_difference,
            min_balance_usd
        )
        
        if not should_switch:
            return {
                "status": "no_action",
                "message": f"No switch needed. Current position in {current_token} is optimal.",
                "current_token": current_token,
                "current_yield": positions[current_token]["yield_apy"],
                "target_token": target_token,
                "target_yield": positions[target_token]["yield_apy"],
                "yield_difference": yield_difference
            }
        
        # Step 3: Execute the switch
        transactions = []
        current_position = positions[current_token]
        target_position = positions[target_token]
        
        # Convert balance to wei
        amount_to_switch = int(current_position["balance"] * (10 ** current_position["decimals"]))
        
        # Step 3a: Withdraw from current position
        logger.info(f"Withdrawing {current_position['balance']} {current_token} from Aave")
        withdraw_tx = await withdraw_from_aave(
            executor=executor,
            chain_id=chain_id,
            vault_address=vault_address,
            asset_address=current_position["token_address"],
            amount=amount_to_switch,
            gas_limit=gas_limit
        )
        transactions.append({"action": "withdraw", "token": current_token, "tx_hash": withdraw_tx})
        
        # Wait for withdrawal to be mined
        await executor.w3.eth.wait_for_transaction_receipt(withdraw_tx)
        
        # Step 3b: Swap tokens using Akka
        logger.info(f"Swapping {current_token} to {target_token} via Akka")
        swap_tx = await execute_akka_swap(
            executor=executor,
            chain_id=chain_id,
            vault_address=vault_address,
            src_token=current_position["token_address"],
            dst_token=target_position["token_address"],
            amount=amount_to_switch,
            slippage=slippage,
            gas_limit=gas_limit
        )
        transactions.append({"action": "swap", "from": current_token, "to": target_token, "tx_hash": swap_tx})
        
        # Wait for swap to be mined
        await executor.w3.eth.wait_for_transaction_receipt(swap_tx)
        
        # Step 3c: Get the swapped amount (approximate for now)
        # In production, you'd parse the swap events to get exact amount
        swapped_amount = int(amount_to_switch * (10 ** target_position["decimals"]) / (10 ** current_position["decimals"]))
        
        # Step 3d: Supply to Aave
        logger.info(f"Supplying {target_token} to Aave")
        supply_tx = await supply_to_aave(
            executor=executor,
            chain_id=chain_id,
            vault_address=vault_address,
            asset_address=target_position["token_address"],
            amount=swapped_amount,
            gas_limit=gas_limit
        )
        transactions.append({"action": "supply", "token": target_token, "tx_hash": supply_tx})
        
        return {
            "status": "success",
            "message": f"Successfully switched from {current_token} to {target_token}",
            "from_token": current_token,
            "to_token": target_token,
            "yield_improvement": yield_difference,
            "transactions": transactions,
            "new_yield": target_position["yield_apy"]
        }
        
    except Exception as e:
        logger.error(f"Error executing yield optimization: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

def optimize_yield(
    chain_name: str,
    vault_address: str,
    token_list: List[str] = None,
    min_yield_difference: float = None,
    min_balance_usd: float = None,
    slippage: float = 0.01
) -> str:
    """
    Optimize yield between specified tokens by automatically switching to the higher yield.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        chain_name: Name of the blockchain network (e.g., "Arbitrum", "Core")
        vault_address: Address of the vault to optimize
        token_list: List of tokens to optimize between (default: ["USDT", "USDC"])
        min_yield_difference: Minimum yield difference to trigger switch (default: 0.5%)
        min_balance_usd: Minimum balance to consider for switching (default: $10)
        slippage: Slippage tolerance for swaps (default 1%)
        
    Returns:
        JSON string with optimization results
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from tools.strategy_executor import StrategyExecutor
        from web3 import Web3
        
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
        
        # Get RPC URL and initialize Web3 instances
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        web3_instances = {chain_id: Web3(Web3.HTTPProvider(rpc_url))}
        executor = StrategyExecutor(rpc_url, PRIVATE_KEY)
        
        # Run the async optimization function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(execute_yield_optimization(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                web3_instances=web3_instances,
                supported_tokens=SUPPORTED_TOKENS,
                token_list=token_list,
                min_yield_difference=min_yield_difference,
                min_balance_usd=min_balance_usd,
                slippage=slippage
            ))
        finally:
            loop.close()
        
        # Format the result
        if result["status"] == "success":
            return json.dumps({
                "status": "success",
                "message": result["message"],
                "details": {
                    "from_token": result["from_token"],
                    "to_token": result["to_token"],
                    "yield_improvement": f"{result['yield_improvement']:.2f}%",
                    "new_yield": f"{result['new_yield']:.2f}%",
                    "transactions": [
                        f"{tx['action']}: {tx['tx_hash']}" for tx in result["transactions"]
                    ]
                }
            })
        elif result["status"] == "no_action":
            return json.dumps({
                "status": "success",
                "message": result["message"],
                "details": {
                    "current_token": result["current_token"],
                    "current_yield": f"{result['current_yield']:.2f}%",
                    "best_token": result["target_token"],
                    "best_yield": f"{result['target_yield']:.2f}%",
                    "yield_difference": f"{result['yield_difference']:.2f}%",
                    "action": "No switch needed"
                }
            })
        else:
            return json.dumps(result)
            
    except Exception as e:
        logger.error(f"Error in optimize_yield: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

def check_yield_optimization_status(
    chain_name: str,
    vault_address: str,
    token_list: List[str] = None,
    min_yield_difference: float = None,
    min_balance_usd: float = None
) -> str:
    """
    Check current yield optimization status without executing any changes.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        chain_name: Name of the blockchain network (e.g., "Arbitrum", "Core")
        vault_address: Address of the vault to check
        token_list: List of tokens to check (default: ["USDT", "USDC"])
        min_yield_difference: Minimum yield difference to trigger switch (default: 0.5%)
        min_balance_usd: Minimum balance to consider for switching (default: $10)
        
    Returns:
        JSON string with current status and recommendations
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from web3 import Web3
        
        # Find chain_id from chain_name
        chain_id = None
        for c_id, config in CHAIN_CONFIG.items():
            if config["name"].lower() == chain_name.lower():
                chain_id = c_id
                break
                
        if chain_id is None:
            return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})
        
        # Get RPC URL and initialize Web3 instances
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        web3_instances = {chain_id: Web3(Web3.HTTPProvider(rpc_url))}
        
        # Use defaults if not provided
        if token_list is None:
            token_list = DEFAULT_CONFIG["tokens"]
        if min_yield_difference is None:
            min_yield_difference = DEFAULT_CONFIG["min_yield_difference"]
        if min_balance_usd is None:
            min_balance_usd = DEFAULT_CONFIG["min_balance_usd"]
        
        # Get current positions
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            positions = loop.run_until_complete(get_current_positions(
                web3_instances,
                vault_address,
                chain_id,
                SUPPORTED_TOKENS,
                token_list
            ))
            
            current_token, target_token, yield_difference, should_switch = loop.run_until_complete(
                compare_yields_and_positions(positions, min_yield_difference, min_balance_usd)
            )
        finally:
            loop.close()
        
        # Format response
        current_positions = {}
        for token in token_list:
            position = positions.get(token, {})
            current_positions[token] = {
                "balance": f"{position.get('balance', 0):.6f}",
                "yield_apy": f"{position.get('yield_apy', 0):.2f}%"
            }
        
        return json.dumps({
            "status": "success",
            "data": {
                "current_positions": current_positions,
                "recommendation": {
                    "current_best": current_token,
                    "optimal_token": target_token,
                    "should_switch": should_switch,
                    "yield_difference": f"{yield_difference:.2f}%",
                    "reason": (
                        f"Switch to {target_token} for {yield_difference:.2f}% higher yield" 
                        if should_switch 
                        else f"Stay in {current_token} - yield difference too small or no position to switch"
                    )
                },
                "chain": chain_name,
                "vault": vault_address
            }
        })
        
    except Exception as e:
        logger.error(f"Error in check_yield_optimization_status: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

# Backward compatibility functions
def optimize_yield_usdt_usdc(chain_name: str, vault_address: str, slippage: float = 0.01) -> str:
    """Backward compatibility wrapper for USDT/USDC optimization"""
    return optimize_yield(chain_name, vault_address, ["USDT", "USDC"], slippage=slippage)