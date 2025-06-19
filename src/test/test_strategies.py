"""
Test file for strategy execution examples
"""
import asyncio
import os
from strategies import StrategyExecutor
from backend.strategies.aave_strategy import supply_to_aave, withdraw_from_aave


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
    else:
        raise ValueError(f"Unsupported chain ID: {chain_id}")
    
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable not set")
    
    return StrategyExecutor(rpc_url=rpc_url, private_key=private_key)


async def example_usage():
    """Example of how to use the strategy execution system"""
    
    # Create executor
    executor = create_strategy_executor(chain_id=42161)
    
    # Example vault and token addresses (replace with actual)
    vault_address = "0xdBFCBEDe24F05a7d4EaeD44C115F0Fa7803F5e49"
    usdc_address = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # USDC on Arbitrum
    
    try:
        # Supply 1000 USDC to Aave (1000 * 10^6 because USDC has 6 decimals)
        amount = int(0.001 * 10**6)
        
        tx_hash = await supply_to_aave(
            executor=executor,
            vault_address=vault_address,
            asset_address=usdc_address,
            amount=amount
        )
        
        # Later, withdraw from Aave
        # tx_hash = await withdraw_from_aave(
        #     executor=executor,
        #     vault_address=vault_address,
        #     asset_address=usdc_address,
        #     amount=amount
        # )
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Run example
    asyncio.run(example_usage()) 