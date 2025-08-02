"""
Test file for strategy execution examples.

This script demonstrates how to use the ToolExecutor to interact with DeFi protocols.
It can be configured to run on different chains by changing the `TEST_CHAIN_ID` and
`TEST_VAULT_ADDRESS` constants.
"""
import asyncio
import os
import logging
from tools.tool_executor import ToolExecutor
from tools.aave_tool import supply_to_aave, withdraw_from_aave
from config import SUPPORTED_TOKENS, CHAIN_CONFIG

# --- Test Configuration ---
# Set the chain ID for the test.
# Supported chains are defined in `config.py`.
TEST_CHAIN_ID = 1116  # Core
# TEST_CHAIN_ID = 42161 # Arbitrum

# Set the vault address for the selected chain.
# Make sure this address corresponds to a vault deployed on the TEST_CHAIN_ID.
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

# Operations to perform
ENABLE_SUPPLY = True
ENABLE_WITHDRAW = False

# Asset and amount for the test
TEST_TOKEN_SYMBOL = "USDC"
TEST_AMOUNT_TO_INTERACT = 0.001

# --- End Test Configuration ---


def create_strategy_executor(chain_id: int) -> ToolExecutor:
    """
    Create a strategy executor for a given chain using settings from config.py.
    
    Args:
        chain_id: The chain ID to create the executor for.
        
    Returns:
        An instance of ToolExecutor.
        
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
    
    return ToolExecutor(rpc_url=rpc_url, private_key=private_key)


async def example_usage():
    """Example of how to supply and withdraw assets using the Aave strategy."""
    
    logging.info(f"--- Starting Aave Strategy Test on Chain ID: {TEST_CHAIN_ID} ---")
    
    # Create executor for the configured test chain
    try:
        executor = create_strategy_executor(chain_id=TEST_CHAIN_ID)
    except ValueError as e:
        logging.error(f"Failed to create strategy executor: {e}")
        return
    
    # Get the token address and decimals for the selected chain
    token_info = SUPPORTED_TOKENS.get(TEST_TOKEN_SYMBOL, {})
    token_address = token_info.get("addresses", {}).get(TEST_CHAIN_ID)
    token_decimals = token_info.get("decimals", 6) # Default to 6 decimals if not specified

    if not token_address:
        logging.warning(f"Token {TEST_TOKEN_SYMBOL} is not supported on chain ID: {TEST_CHAIN_ID}. Skipping test.")
        return

    # Convert the human-readable amount to wei (smallest unit)
    amount_in_wei = int(TEST_AMOUNT_TO_INTERACT * (10**token_decimals))

    try:
        if ENABLE_SUPPLY:
            logging.info(f"Attempting to supply {TEST_AMOUNT_TO_INTERACT} {TEST_TOKEN_SYMBOL} to Aave...")
            tx_hash = await supply_to_aave(
                executor=executor,
                chain_id=TEST_CHAIN_ID,
                vault_address=TEST_VAULT_ADDRESS,
                asset_address=token_address,
                amount=amount_in_wei
            )
            logging.info(f"Supply transaction successful. Hash: {tx_hash}")
        else:
            logging.info("Supply operation disabled.")

        if ENABLE_WITHDRAW:
            logging.info(f"\nAttempting to withdraw {TEST_AMOUNT_TO_INTERACT} {TEST_TOKEN_SYMBOL} from Aave...")
            tx_hash_withdraw = await withdraw_from_aave(
                executor=executor,
                chain_id=TEST_CHAIN_ID,
                vault_address=TEST_VAULT_ADDRESS,
                asset_address=token_address,
                amount=amount_in_wei
            )
            logging.info(f"Withdraw transaction successful. Hash: {tx_hash_withdraw}")
        else:
            logging.info("Withdraw operation disabled.")
        
    except Exception as e:
        logging.error(f"An error occurred during the Aave strategy execution: {e}", exc_info=True)

    logging.info("--- Aave Strategy Test Finished ---")


if __name__ == "__main__":
    # Configure logging for better output
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Run example
    asyncio.run(example_usage()) 