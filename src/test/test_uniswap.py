"""
Test file for Uniswap strategy execution through the vault
"""
import asyncio
import os
import logging
from strategies.strategies import StrategyExecutor
from strategies.uniswap_strategy import execute_uniswap_swap
from config import SUPPORTED_TOKENS, CHAIN_CONFIG

# --- Test Configuration ---
# Set the chain ID for the test.
TEST_CHAIN_ID = 42161  # Arbitrum
# TEST_CHAIN_ID = 1116 # Core

# Set the vault address for the selected chain.
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

# Token pair and amount for the test
TOKEN_IN_SYMBOL = "USDC"
TOKEN_OUT_SYMBOL = "WBTC" 
SWAP_AMOUNT = 0.01  # Amount of TOKEN_IN to swap
FEE_TIER = 500  # Fee tier (500 = 0.05% for USDC/WBTC)

# --- End Test Configuration ---


def create_strategy_executor(chain_id: int) -> StrategyExecutor:
    """
    Create a strategy executor for a given chain using settings from config.py.
    
    Args:
        chain_id: The chain ID to create the executor for.
        
    Returns:
        An instance of StrategyExecutor.
        
    Raises:
        ValueError: If the chain ID is not supported, RPC URL is missing, or
                    the private key environment variable is not set.
    """
    if chain_id not in CHAIN_CONFIG:
        raise ValueError(f"Unsupported chain ID: {chain_id}")
        
    rpc_url = CHAIN_CONFIG[chain_id].get("rpc_url")
    if not rpc_url:
        raise ValueError(f"RPC URL not configured for chain ID: {chain_id}")

    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable not set. Please set it in your .env file or environment.")
    
    return StrategyExecutor(rpc_url=rpc_url, private_key=private_key)


async def example_usage():
    """Example of how to use the Uniswap swap execution system through the vault."""
    
    logging.info(f"--- Starting Uniswap Strategy Test on Chain ID: {TEST_CHAIN_ID} ---")
    
    # Create executor for the configured test chain
    try:
        executor = create_strategy_executor(chain_id=TEST_CHAIN_ID)
    except ValueError as e:
        logging.error(f"Failed to create strategy executor: {e}")
        return
    
    # Get the token addresses and decimals for the selected chain
    token_in_info = SUPPORTED_TOKENS.get(TOKEN_IN_SYMBOL, {})
    token_in_address = token_in_info.get("addresses", {}).get(TEST_CHAIN_ID)
    token_in_decimals = token_in_info.get("decimals", 6)
    
    token_out_info = SUPPORTED_TOKENS.get(TOKEN_OUT_SYMBOL, {})
    token_out_address = token_out_info.get("addresses", {}).get(TEST_CHAIN_ID)

    if not token_in_address:
        logging.warning(f"Token {TOKEN_IN_SYMBOL} is not supported on chain ID: {TEST_CHAIN_ID}. Skipping test.")
        return
        
    if not token_out_address:
        logging.warning(f"Token {TOKEN_OUT_SYMBOL} is not supported on chain ID: {TEST_CHAIN_ID}. Skipping test.")
        return

    # Convert the human-readable amount to wei (smallest unit)
    amount_in_wei = int(SWAP_AMOUNT * (10**token_in_decimals))

    logging.info(f"=== Testing {TOKEN_IN_SYMBOL} → {TOKEN_OUT_SYMBOL} Swap ===")
    logging.info(f"Amount: {SWAP_AMOUNT} {TOKEN_IN_SYMBOL}")
    logging.info(f"Fee tier: {FEE_TIER} ({FEE_TIER/10000}%)")
    logging.info(f"Vault: {TEST_VAULT_ADDRESS}")

    try:
        tx_hash = await execute_uniswap_swap(
            executor=executor,
            chain_id=TEST_CHAIN_ID,
            vault_address=TEST_VAULT_ADDRESS,
            token_in_address=token_in_address,
            token_out_address=token_out_address,
            amount_in=amount_in_wei,
            fee=FEE_TIER
        )
        logging.info(f"✅ Swap transaction successful. Hash: {tx_hash}")
        
    except Exception as e:
        logging.error(f"❌ An error occurred during the Uniswap strategy execution: {e}", exc_info=True)

    logging.info("--- Uniswap Strategy Test Finished ---")


if __name__ == "__main__":
    # Configure logging for better output
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Run example
    asyncio.run(example_usage())
