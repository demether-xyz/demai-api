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

# Configure logging with simplified format
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# --- Test Configuration ---
TEST_CHAIN_NAME = "Core"  # Can be "Core" or "Arbitrum"
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
TEST_MODEL_ID = "google/gemini-2.5-pro"  # You can change to other models
VERBOSE = True 

# --- End Test Configuration ---


def create_langchain_aave_tool(vault_address: str) -> StructuredTool:
    """
    Create a LangChain StructuredTool wrapper for the Aave tool.
    
    This wraps the async Aave tool to work with LangChain agents.
    """
    # Create the Aave tool
    tool_config = create_aave_tool(
        vault_address=vault_address
    )
    
    aave_tool_func = tool_config["tool"]
    
    # Create a synchronous wrapper for LangChain that handles different parameter formats
    def sync_aave_tool(**kwargs) -> str:
        """
        Execute Aave lending operation (supply or withdraw).
        
        Args:
            chain_name or chain: Name of the blockchain network (e.g., "Core", "Arbitrum")
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
            
        # Extract parameters (handle both chain_name and chain)
        chain_name = params.get('chain_name') or params.get('chain')
        token_symbol = params.get('token_symbol') or params.get('token')
        amount = float(params.get('amount', 0))
        action = params.get('action', 'supply')
        
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(aave_tool_func(
                chain_name=chain_name,
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
        description="Supply or withdraw tokens on Aave V3 (supports Core and Arbitrum chains). Use this tool when the user wants to lend tokens to Aave or withdraw tokens from Aave.",
        func=sync_aave_tool,
        args_schema=None,  # Let LangChain infer from function signature
    )


async def test_llm_with_aave_tool():
    """Test the LLM's ability to use the Aave tool based on user prompts."""
    
    print(f"\n=== Testing LLM with Aave Tool ===\n")
    
    try:
        # Create the Aave tool as a LangChain tool
        aave_tool = create_langchain_aave_tool(
            vault_address=TEST_VAULT_ADDRESS
        )
        
        # Create the agent with the Aave tool
        agent = await create_tools_agent(
            tools=[aave_tool],
            model_id=TEST_MODEL_ID,
            verbose=VERBOSE
        )
        
        # Simple test prompt - now includes chain name
        test_prompt = "I want to supply 0.001 USDC to Aave on Core chain for earning yield"
        
        # System message to guide the agent
        system_message = """You are a DeFi assistant that helps users interact with Aave V3 lending protocol.
        
When a user wants to:
- Supply, lend, deposit, or add tokens to Aave: use the aave_lending tool with action="supply"
- Withdraw, remove, or take out tokens from Aave: use the aave_lending tool with action="withdraw"

The aave_lending tool requires these parameters:
- chain_name: The blockchain network ("Core" or "Arbitrum")
- token_symbol: The token to use (e.g., "USDC", "USDT")
- amount: The amount in decimal format
- action: Either "supply" or "withdraw"

Always extract the chain name, token symbol, and amount from the user's request.
If the user doesn't specify a chain, ask them which chain they want to use.
After calling the tool, summarize the result for the user."""
        
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
                # Extract transaction hash from result if available
                for action, observation in result["intermediate_steps"]:
                    if action.tool == "aave_lending":
                        try:
                            import json
                            obs_data = json.loads(observation)
                            if obs_data.get("status") == "success":
                                tx_hash = obs_data.get("data", {}).get("tx_hash")
                                if tx_hash:
                                    print(f"📝 Transaction: {tx_hash}")
                        except:
                            pass
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
    if not os.getenv("PRIVATE_KEY"):
        print("❌ PRIVATE_KEY environment variable not set!")
        print("Please set it in your .env file or environment.")
        exit(1)
    
    if not os.getenv("OPENROUTER_API_KEY"):
        print("❌ OPENROUTER_API_KEY environment variable not set!")
        print("Please set it in your .env file or environment.")
        exit(1)
    
    # Run the test
    asyncio.run(test_llm_with_aave_tool())
    
    print("\n✅ Test completed successfully!")