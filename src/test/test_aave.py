"""
Test file for Aave tool execution examples.

This script demonstrates how to use the simplified Aave tool interface
for supply and withdraw operations.
"""
import asyncio
import os
import logging
# Import config first to load environment variables
from config import CHAIN_CONFIG, SUPPORTED_TOKENS
from tools.aave_tool import create_aave_tool

# --- Test Configuration ---
# Set the chain for the test
TEST_CHAIN_NAME = "Core"  # Can be "Core" or "Arbitrum"

# Set the vault address for the selected chain
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

# Operations to perform
ENABLE_SUPPLY = True
ENABLE_WITHDRAW = False

# Asset and amount for the test
TEST_TOKEN_SYMBOL = "USDC"
TEST_AMOUNT = 0.001  # Human-readable format (0.001 USDC)

# --- End Test Configuration ---


async def test_aave_interface():
    """Test the Aave interface with the subtool pattern."""
    
    logging.info(f"--- Testing Aave Interface on {TEST_CHAIN_NAME} ---")
    
    try:
        # Create the configured Aave tool
        tool_config = create_aave_tool(
            chain_name=TEST_CHAIN_NAME,
            vault_address=TEST_VAULT_ADDRESS
        )
        
        aave_tool = tool_config["tool"]
        metadata = tool_config["metadata"]
        
        logging.info(f"Created Aave tool: {metadata['name']}")
        logging.info(f"Description: {metadata['description']}")
        logging.info(f"Parameters: {metadata['parameters']}")
        
        # Test supply operation
        if ENABLE_SUPPLY:
            logging.info(f"\nSupplying {TEST_AMOUNT} {TEST_TOKEN_SYMBOL} to Aave...")
            result = await aave_tool(
                token_symbol=TEST_TOKEN_SYMBOL,
                amount=TEST_AMOUNT,
                action="supply"
            )
            logging.info(f"Supply result: {result}")
        
        # Test withdraw operation
        if ENABLE_WITHDRAW:
            logging.info(f"\nWithdrawing {TEST_AMOUNT} {TEST_TOKEN_SYMBOL} from Aave...")
            result = await aave_tool(
                token_symbol=TEST_TOKEN_SYMBOL,
                amount=TEST_AMOUNT,
                action="withdraw"
            )
            logging.info(f"Withdraw result: {result}")
            
    except Exception as e:
        logging.error(f"Error in test: {e}")


def demonstrate_llm_usage():
    """
    Demonstrate how an LLM would use the Aave tool.
    
    This shows the simple interface that requires minimal parameters:
    - token_symbol: The token to operate with
    - amount: The amount in human-readable format
    - action: Either "supply" or "withdraw"
    """
    logging.info("\n--- LLM Usage Example ---")
    logging.info("An LLM would use the async tool after it's configured:")
    logging.info("""
    # First, create the configured tool
    tool_config = create_aave_tool(
        chain_name="Core",
        vault_address="0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
    )
    aave_tool = tool_config["tool"]
    
    # Then use it with minimal parameters:
    
    # Example 1: Supply USDC
    result = await aave_tool(
        token_symbol="USDC",
        amount=100.5,
        action="supply"
    )
    
    # Example 2: Withdraw USDT
    result = await aave_tool(
        token_symbol="USDT",
        amount=50.0,
        action="withdraw"
    )
    """)


if __name__ == "__main__":
    # Configure logging for better output
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Check for private key
    if not os.getenv("PRIVATE_KEY"):
        logging.error("PRIVATE_KEY environment variable not set!")
        logging.info("Please set it in your .env file or environment.")
        exit(1)
    
    # Run tests
    logging.info("Testing Aave Tool Interface\n")
    
    # Test the interface
    asyncio.run(test_aave_interface())
    
    logging.info("\n" + "="*50 + "\n")
    
    # Show LLM usage examples
    demonstrate_llm_usage()
    
    logging.info("\n--- All Tests Completed ---")