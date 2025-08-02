"""
Test file for Akka tool execution examples.

This script demonstrates how to use the Akka tool functions directly
for swap, quote, and approve operations.
"""
import os
import logging
# Import config first to load environment variables
from config import CHAIN_CONFIG, SUPPORTED_TOKENS
from tools.akka_tool import create_swap_tool

# --- Test Configuration ---
# Set the vault address for Core chain (Akka only supports Core)
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
TEST_CHAIN_NAME = "Core"

# Operations to perform
ENABLE_SWAP = True  # Set to True to actually execute a swap

# Swap parameters for the test
TEST_SRC_TOKEN = "USDC"
TEST_DST_TOKEN = "USDT"
TEST_AMOUNT = 0.001  # Human-readable format (0.001 USDC)

# --- End Test Configuration ---


async def test_swap_tool():
    """Test the simplified swap tool."""
    
    logging.info("--- Testing Swap Tool on Core ---")
    
    try:
        # Create the swap tool
        tool_config = create_swap_tool(
            vault_address=TEST_VAULT_ADDRESS
        )
        
        swap_tool = tool_config["tool"]
        metadata = tool_config["metadata"]
        
        logging.info(f"Created swap tool: {metadata['name']}")
        logging.info(f"Description: {metadata['description']}")
        logging.info(f"Parameters: {metadata['parameters']}")
        
        # Test swap operation if enabled
        if ENABLE_SWAP:
            logging.info(f"\nExecuting swap of {TEST_AMOUNT} {TEST_SRC_TOKEN} -> {TEST_DST_TOKEN}...")
            result = await swap_tool(
                chain_name=TEST_CHAIN_NAME,
                src_token=TEST_SRC_TOKEN,
                dst_token=TEST_DST_TOKEN,
                amount=TEST_AMOUNT
            )
            logging.info(f"Swap result: {result}")
        else:
            logging.info(f"\nSwap execution disabled. Set ENABLE_SWAP=True to execute.")
            
    except Exception as e:
        logging.error(f"Error in test: {e}")


if __name__ == "__main__":
    import asyncio
    
    # Configure logging for better output
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Check for private key
    if not os.getenv("PRIVATE_KEY"):
        logging.error("PRIVATE_KEY environment variable not set!")
        logging.info("Please set it in your .env file or environment.")
        exit(1)
    
    # Run tests
    logging.info("Testing Swap Tool\n")
    
    # Test the tool
    asyncio.run(test_swap_tool())
    
    logging.info("\n--- All Tests Completed ---")