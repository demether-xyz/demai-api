"""
Test file for LLM calling Akka swap tool autonomously.

This script demonstrates how to set up an LLM with the Akka swap tool
and let it decide when and how to call the tool based on user prompts.
"""
import asyncio
import os
import sys
import logging

# Add the parent directory to the Python path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Import config first to load environment variables
from config import CHAIN_CONFIG, SUPPORTED_TOKENS
from tools.akka_tool import create_swap_tool
from utils.ai_router_tools import create_tools_agent
from langchain_core.tools import StructuredTool

# Configure logging with simplified format
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# --- Test Configuration ---
TEST_CHAIN_NAME = "Core"  # Akka only supports Core currently
TEST_VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
TEST_MODEL_ID = "openai/gpt-oss-120b"
VERBOSE = True 

# --- End Test Configuration ---


def create_langchain_akka_tool(vault_address: str) -> StructuredTool:
    """
    Create a LangChain StructuredTool wrapper for the Akka swap tool.
    
    This wraps the async Akka tool to work with LangChain agents.
    """
    # Create the Akka swap tool
    tool_config = create_swap_tool(
        vault_address=vault_address
    )
    
    akka_tool_func = tool_config["tool"]
    
    # Create a synchronous wrapper for LangChain that handles different parameter formats
    def sync_akka_tool(**kwargs) -> str:
        """
        Execute token swap using Akka Finance DEX aggregator.
        
        Args:
            chain_name or chain: Name of the blockchain network (e.g., "Core")
            src_token or source_token: Symbol of source token (e.g., "USDC", "USDT")
            dst_token or destination_token: Symbol of destination token
            amount: Amount to swap in human-readable format (e.g., 100.5)
            
        Returns:
            JSON string with swap result
        """
        # Handle different parameter formats from Gemini
        if 'kwargs' in kwargs:
            # Gemini sometimes wraps parameters in kwargs
            params = kwargs['kwargs']
        else:
            params = kwargs
            
        # Extract parameters (handle multiple naming conventions)
        chain_name = params.get('chain_name') or params.get('chain')
        src_token = params.get('src_token') or params.get('source_token')
        dst_token = params.get('dst_token') or params.get('destination_token')
        amount = float(params.get('amount', 0))
        
        # Run the async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(akka_tool_func(
                chain_name=chain_name,
                src_token=src_token,
                dst_token=dst_token,
                amount=amount
            ))
            return result
        finally:
            loop.close()
    
    # Create StructuredTool with proper schema
    return StructuredTool(
        name="akka_swap",
        description="Swap tokens using Akka Finance DEX aggregator on Core chain. Use this tool when the user wants to swap, exchange, convert, or trade one token for another.",
        func=sync_akka_tool,
        args_schema=None,  # Let LangChain infer from function signature
    )


async def test_llm_with_akka_tool():
    """Test the LLM's ability to use the Akka swap tool based on user prompts."""
    
    print(f"\n=== Testing LLM with Akka Swap Tool ===\n")
    
    try:
        # Create the Akka tool as a LangChain tool
        akka_tool = create_langchain_akka_tool(
            vault_address=TEST_VAULT_ADDRESS
        )
        
        # Create the agent with the Akka tool
        agent = await create_tools_agent(
            tools=[akka_tool],
            model_id=TEST_MODEL_ID,
            verbose=VERBOSE
        )
        
        # Simple test prompt - includes chain name
        test_prompt = "I want to swap 0.001 USDC to USDT on Core chain"
        
        # System message to guide the agent
        system_message = """You are a DeFi assistant that helps users swap tokens using Akka Finance DEX aggregator.
        
When a user wants to:
- Swap, exchange, convert, or trade tokens: use the akka_swap tool
- Get the best price for token swaps: use the akka_swap tool

The akka_swap tool requires these parameters:
- chain_name: The blockchain network (currently only "Core" is supported)
- src_token: The source token symbol (e.g., "USDC", "USDT")
- dst_token: The destination token symbol
- amount: The amount to swap in decimal format

Always extract the chain name, source token, destination token, and amount from the user's request.
If the user doesn't specify a chain, inform them that Akka currently only supports Core chain.
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
                    if action.tool == "akka_swap":
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
    asyncio.run(test_llm_with_akka_tool())
    
    print("\n✅ Test completed successfully!")