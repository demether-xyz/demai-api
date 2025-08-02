"""
Test file for LLM calling Aave tool autonomously.

This script demonstrates how to set up an LLM with the Aave tool
and let it decide when and how to call the tool based on user prompts.
"""
import asyncio
import os
import sys
import logging

# Add the parent directory to the Python path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import config first to load environment variables
from src.config import CHAIN_CONFIG, SUPPORTED_TOKENS
from src.tools.aave_tool import create_aave_tool
from src.utils.ai_router_tools import create_tools_agent
from langchain_core.tools import StructuredTool

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Test Configuration ---
TEST_CHAIN_NAME = "Core"  # Can be "Core" or "Arbitrum"
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
TEST_MODEL_ID = "google/gemini-flash-1.5"  # You can change to other models
VERBOSE = True  # Enable verbose logging to see tool calls

# --- End Test Configuration ---


def create_langchain_aave_tool(chain_name: str, vault_address: str) -> StructuredTool:
    """
    Create a LangChain StructuredTool wrapper for the Aave tool.
    
    This wraps the async Aave tool to work with LangChain agents.
    """
    # Create the Aave tool
    tool_config = create_aave_tool(
        chain_name=chain_name,
        vault_address=vault_address
    )
    
    aave_tool_func = tool_config["tool"]
    
    # Create a synchronous wrapper for LangChain that handles different parameter formats
    def sync_aave_tool(**kwargs) -> str:
        """
        Execute Aave lending operation (supply or withdraw).
        
        Args:
            token_symbol or token: Symbol of the token (e.g., "USDC", "USDT")
            amount: Amount in human-readable format (e.g., 100.5)
            action: Operation to perform - "supply" or "withdraw"
            
        Returns:
            JSON string with operation result
        """
        # Handle different parameter formats from Gemini
        if 'kwargs' in kwargs:
            # Gemini sometimes wraps parameters in kwargs
            params = kwargs['kwargs']
        else:
            params = kwargs
            
        # Extract parameters (handle both token_symbol and token)
        token_symbol = params.get('token_symbol') or params.get('token')
        amount = float(params.get('amount', 0))
        action = params.get('action', 'supply')
        
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(aave_tool_func(
                token_symbol=token_symbol,
                amount=amount,
                action=action
            ))
            return result
        finally:
            loop.close()
    
    # Create StructuredTool with proper schema
    return StructuredTool(
        name="aave_lending",
        description=f"Supply or withdraw tokens on Aave V3 ({chain_name}). Use this tool when the user wants to lend tokens to Aave or withdraw tokens from Aave.",
        func=sync_aave_tool,
        args_schema=None,  # Let LangChain infer from function signature
    )


async def test_llm_with_aave_tool():
    """Test the LLM's ability to use the Aave tool based on user prompts."""
    
    logger.info(f"--- Testing LLM with Aave Tool on {TEST_CHAIN_NAME} ---")
    
    try:
        # Create the Aave tool as a LangChain tool
        aave_tool = create_langchain_aave_tool(
            chain_name=TEST_CHAIN_NAME,
            vault_address=TEST_VAULT_ADDRESS
        )
        
        # Create the agent with the Aave tool
        agent = await create_tools_agent(
            tools=[aave_tool],
            model_id=TEST_MODEL_ID,
            verbose=VERBOSE
        )
        
        # Simple test prompt
        test_prompt = "I want to supply 0.001 USDC to Aave for earning yield"
        
        # System message to guide the agent
        system_message = """You are a DeFi assistant that helps users interact with Aave V3 lending protocol.
        
When a user wants to:
- Supply, lend, deposit, or add tokens to Aave: use the aave_lending tool with action="supply"
- Withdraw, remove, or take out tokens from Aave: use the aave_lending tool with action="withdraw"

Always extract the token symbol and amount from the user's request.
After calling the tool, summarize the result for the user."""
        
        logger.info(f"User prompt: {test_prompt}")
        
        # Execute the agent
        result = await agent.execute(
            user_instructions=test_prompt,
            system_message=system_message
        )
        
        if result["error"]:
            logger.error(f"Error: {result['error']}")
        else:
            logger.info(f"Agent response: {result['final_output']}")
            logger.info(f"Number of tool calls: {result['total_steps']}")
            
            # Analyze tool calls
            if result["intermediate_steps"]:
                for step_idx, (action, observation) in enumerate(result["intermediate_steps"]):
                    logger.info(f"\nTool call {step_idx + 1}:")
                    logger.info(f"  Tool: {action.tool}")
                    logger.info(f"  Input: {action.tool_input}")
                    logger.info(f"  Result: {observation}")
            else:
                logger.warning("No tool calls were made!")
            
    except Exception as e:
        logger.error(f"Error in test: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Check for required environment variables
    if not os.getenv("PRIVATE_KEY"):
        logger.error("PRIVATE_KEY environment variable not set!")
        logger.info("Please set it in your .env file or environment.")
        exit(1)
    
    if not os.getenv("OPENROUTER_API_KEY"):
        logger.error("OPENROUTER_API_KEY environment variable not set!")
        logger.info("Please set it in your .env file or environment.")
        exit(1)
    
    logger.info("Testing LLM with Aave Tool\n")
    
    # Run the test
    asyncio.run(test_llm_with_aave_tool())
    
    logger.info("\n--- Test Completed ---")