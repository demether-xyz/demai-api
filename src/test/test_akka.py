"""
Test file for Akka strategy execution.

This script demonstrates how to use the StrategyExecutor to swap tokens via Akka Finance.
It can be configured to run on different chains by changing the `TEST_CHAIN_ID` and
`TEST_VAULT_ADDRESS` constants.
"""
import asyncio
import os
import logging
from strategies.strategies import StrategyExecutor
from strategies.akka_strategy import execute_akka_swap, get_akka_swap_estimate
from config import SUPPORTED_TOKENS, CHAIN_CONFIG

# --- Test Configuration ---
# Set the chain ID for the test.
TEST_CHAIN_ID = 1116  # Core

# Set the vault address for the selected chain.
# Make sure this address corresponds to a vault deployed on the TEST_CHAIN_ID.
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

# Swap parameters
TEST_SRC_TOKEN = "USDT"
TEST_DST_TOKEN = "SOLVBTC"
TEST_SWAP_AMOUNT = 0.1  # 0.1 USDT
TEST_SLIPPAGE = 0.01  # 1% slippage

# Operations to perform
ENABLE_QUOTE = True
ENABLE_SWAP = False  # Set to True to execute actual swap

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
    """Example of how to swap tokens using the Akka strategy."""
    
    logging.info(f"--- Starting Akka Strategy Test on Chain ID: {TEST_CHAIN_ID} ---")
    
    # Create executor for the configured test chain
    try:
        executor = create_strategy_executor(chain_id=TEST_CHAIN_ID)
    except ValueError as e:
        logging.error(f"Failed to create strategy executor: {e}")
        return
    
    # Get token info for source and destination tokens
    src_token_info = SUPPORTED_TOKENS.get(TEST_SRC_TOKEN, {})
    dst_token_info = SUPPORTED_TOKENS.get(TEST_DST_TOKEN, {})
    
    src_token_address = src_token_info.get("addresses", {}).get(TEST_CHAIN_ID)
    dst_token_address = dst_token_info.get("addresses", {}).get(TEST_CHAIN_ID)
    
    src_decimals = src_token_info.get("decimals", 6)
    dst_decimals = dst_token_info.get("decimals", 18)

    if not src_token_address:
        logging.error(f"Source token {TEST_SRC_TOKEN} is not supported on chain ID: {TEST_CHAIN_ID}")
        return
        
    if not dst_token_address:
        logging.error(f"Destination token {TEST_DST_TOKEN} is not supported on chain ID: {TEST_CHAIN_ID}")
        return

    # Convert the human-readable amount to wei (smallest unit)
    amount_in_wei = int(TEST_SWAP_AMOUNT * (10**src_decimals))

    try:
        if ENABLE_QUOTE:
            logging.info(f"\nGetting quote for swapping {TEST_SWAP_AMOUNT} {TEST_SRC_TOKEN} to {TEST_DST_TOKEN}...")
            
            estimate = await get_akka_swap_estimate(
                chain_id=TEST_CHAIN_ID,
                src_token=src_token_address,
                dst_token=dst_token_address,
                amount=amount_in_wei,
                slippage=TEST_SLIPPAGE
            )
            
            if "error" in estimate:
                logging.error(f"Failed to get quote: {estimate['error']}")
            else:
                dst_amount_human = float(estimate["dst_amount"]) / (10**dst_decimals)
                dst_min_human = float(estimate["dst_amount_min"]) / (10**dst_decimals)
                
                logging.info(f"Quote received:")
                logging.info(f"  Input: {TEST_SWAP_AMOUNT} {TEST_SRC_TOKEN}")
                logging.info(f"  Expected output: {dst_amount_human:.8f} {TEST_DST_TOKEN}")
                logging.info(f"  Minimum output (with {TEST_SLIPPAGE*100}% slippage): {dst_min_human:.8f} {TEST_DST_TOKEN}")
                
                if estimate.get("price_impact") is not None:
                    logging.info(f"  Price impact: {estimate['price_impact']}%")
                if estimate.get("gas_estimate"):
                    logging.info(f"  Gas estimate: {estimate['gas_estimate']}")

        if ENABLE_SWAP:
            logging.info(f"\nAttempting to swap {TEST_SWAP_AMOUNT} {TEST_SRC_TOKEN} to {TEST_DST_TOKEN}...")
            
            tx_hash = await execute_akka_swap(
                executor=executor,
                chain_id=TEST_CHAIN_ID,
                vault_address=TEST_VAULT_ADDRESS,
                src_token=src_token_address,
                dst_token=dst_token_address,
                amount=amount_in_wei,
                slippage=TEST_SLIPPAGE
            )
            
            logging.info(f"Swap transaction successful. Hash: {tx_hash}")
        else:
            logging.info("\nSwap execution disabled. Set ENABLE_SWAP=True to execute the swap.")
        
    except Exception as e:
        logging.error(f"An error occurred during the Akka strategy execution: {e}", exc_info=True)

    logging.info("\n--- Akka Strategy Test Finished ---")


if __name__ == "__main__":
    # Configure logging for better output
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Run example
    asyncio.run(example_usage())