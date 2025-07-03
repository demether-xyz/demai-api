"""
Test file for Uniswap strategy execution
"""
import asyncio
import os
from strategies.strategies import StrategyExecutor
from strategies.uniswap_strategy import execute_uniswap_swap
from config import SUPPORTED_TOKENS


def create_strategy_executor(chain_id: int = 42161) -> StrategyExecutor:
    """
    Create a strategy executor from environment variables
    
    Args:
        chain_id: Chain ID (default: 42161 for Arbitrum)
        
    Returns:
        StrategyExecutor instance
    """
    if chain_id == 42161:
        rpc_url = os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc")
    elif chain_id == 1116:
        rpc_url = os.getenv("CORE_RPC_URL", "https://rpc.coredao.org")
    else:
        raise ValueError(f"Unsupported chain ID: {chain_id}")
    
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable not set")
    
    return StrategyExecutor(rpc_url=rpc_url, private_key=private_key)


async def example_usage():
    """Example of how to use the Uniswap swap execution system"""
    
    # --- Configuration ---
    chain_id = 42161 # Arbitrum
    vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92" # Replace with your vault address
    
    token_in_symbol = "USDC"
    token_out_symbol = "WBTC"
    swap_amount = 0.001 # Amount of token_in to swap
    # -------------------

    # Create executor
    executor = create_strategy_executor(chain_id=chain_id)
    
    # Get token details from config
    token_in_address = SUPPORTED_TOKENS[token_in_symbol]["addresses"][chain_id]
    token_in_decimals = SUPPORTED_TOKENS[token_in_symbol]["decimals"]
    token_out_address = SUPPORTED_TOKENS[token_out_symbol]["addresses"][chain_id]

    amount_in_wei = int(swap_amount * (10**token_in_decimals))

    print(f"Attempting to swap {swap_amount} {token_in_symbol} for {token_out_symbol} on chain {chain_id}...")
    
    try:
        tx_hash = await execute_uniswap_swap(
            executor=executor,
            chain_id=chain_id,
            vault_address=vault_address,
            token_in_address=token_in_address,
            token_out_address=token_out_address,
            amount_in=amount_in_wei,
            fee=2000 # USDC/WBTC on Arbitrum is typically 0.05%
        )
        print(f"Successfully sent swap transaction: {tx_hash}")
        
    except Exception as e:
        print(f"Error executing swap: {e}")


if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage())
