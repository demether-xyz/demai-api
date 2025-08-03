"""
Test file for LLM calling Portfolio tool autonomously.

This script demonstrates how to set up an LLM with the Portfolio tool
and let it decide when and how to call the tool based on user prompts.
"""
import asyncio
import os
import sys
import logging

# Add the parent directory to the Python path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import config first to load environment variables
from src.config import CHAIN_CONFIG
from src.tools.portfolio_tool import create_portfolio_tool
from src.utils.ai_router_tools import create_tools_agent
from langchain_core.tools import StructuredTool

# Configure logging with simplified format
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# --- Test Configuration ---
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
TEST_MODEL_ID = "google/gemini-2.5-pro"
VERBOSE = True 

# --- End Test Configuration ---


def create_langchain_portfolio_tool(vault_address: str) -> StructuredTool:
    """
    Create a LangChain StructuredTool wrapper for the Portfolio tool.
    
    This wraps the async Portfolio tool to work with LangChain agents.
    """
    # Create the Portfolio tool
    tool_config = create_portfolio_tool(
        vault_address=vault_address
    )
    
    portfolio_tool_func = tool_config["tool"]
    
    # Create a synchronous wrapper for LangChain
    def sync_portfolio_tool() -> str:
        """
        Get portfolio information showing all token balances and values.
        
        Returns:
            JSON string with portfolio data including total value, balances by chain, and DeFi positions
        """
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(portfolio_tool_func())
            return result
        finally:
            loop.close()
    
    # Create StructuredTool with proper schema
    return StructuredTool(
        name="portfolio_viewer",
        description="Get portfolio balances, token holdings, and total value across all chains. Use this tool when the user asks about their portfolio, balances, holdings, or wants to see what tokens they have.",
        func=sync_portfolio_tool,
        args_schema=None,  # No parameters needed
    )


async def test_llm_with_portfolio_tool():
    """Test the LLM's ability to use the Portfolio tool based on user prompts."""
    
    print(f"\n=== Testing LLM with Portfolio Tool ===\n")
    
    try:
        # Create the Portfolio tool as a LangChain tool
        portfolio_tool = create_langchain_portfolio_tool(
            vault_address=TEST_VAULT_ADDRESS
        )
        
        # Create the agent with the Portfolio tool
        agent = await create_tools_agent(
            tools=[portfolio_tool],
            model_id=TEST_MODEL_ID,
            verbose=VERBOSE
        )
        
        # Simple test prompt
        test_prompt = "What's in my portfolio? Show me all my token balances"
        
        # System message to guide the agent
        system_message = """You are a DeFi portfolio assistant that helps users view their token holdings and balances.

When a user asks about:
- Their portfolio, holdings, balances, tokens, or assets: use the portfolio_viewer tool
- How much they have, what tokens they own, or their total value: use the portfolio_viewer tool

The portfolio_viewer tool requires no parameters and returns:
- Total portfolio value in USD
- Token balances organized by blockchain (Core, Arbitrum, etc.)
- DeFi positions and strategies
- Summary of active chains and strategies

After calling the tool, provide a clear summary of:
1. Total portfolio value
2. Main holdings by chain
3. Any DeFi positions (like Aave deposits)"""
        
        print(f"User: {test_prompt}")
        
        # Execute the agent
        result = await agent.execute(
            user_instructions=test_prompt,
            system_message=system_message
        )
        
        if result["error"]:
            print(f"\n❌ Error: {result['error']}")
        else:
            print(f"\nAgent: {result['final_output']}")
            
            # Show tool calls if any
            if result["intermediate_steps"]:
                print(f"\n✅ Tool called successfully ({result['total_steps']} call{'s' if result['total_steps'] > 1 else ''})")
            else:
                print("\n⚠️  No tool calls were made")
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Suppress config.py logging
    logging.getLogger('root').setLevel(logging.WARNING)
    
    # Check for required environment variables
    if not os.getenv("OPENROUTER_API_KEY"):
        print("❌ OPENROUTER_API_KEY environment variable not set!")
        print("Please set it in your .env file or environment.")
        exit(1)
    
    # Run the test
    asyncio.run(test_llm_with_portfolio_tool())
    
    print("\n✅ Test completed successfully!")