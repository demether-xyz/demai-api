"""
Simple chat assistant with portfolio viewing capabilities.
"""
import asyncio
import os
from src.tools.portfolio_tool import create_portfolio_tool
from src.utils.ai_router_tools import create_tools_agent
from langchain_core.tools import StructuredTool
from src.utils.json_parser import extract_json_content
from src.config import logger
from dotenv import load_dotenv
import json

load_dotenv()


class SimpleAssistant:
    """Simple chat assistant with portfolio capabilities."""
    
    def __init__(self, vault_address: str, model: str = "google/gemini-2.5-flash"):
        """Initialize the assistant with a vault address."""
        self.vault_address = vault_address
        self.model = model
        self.portfolio_tool = self._create_portfolio_tool()
        self.agent = None  # Will be created on first use
    
    def _create_portfolio_tool(self):
        """Create the portfolio tool."""
        portfolio_config = create_portfolio_tool(vault_address=self.vault_address)
        return portfolio_config["tool"]
    
    def _create_langchain_tool(self) -> StructuredTool:
        """Create LangChain tool wrapper."""
        portfolio_func = self.portfolio_tool
        
        # Sync wrapper for the async portfolio tool
        def sync_portfolio_tool() -> str:
            """Get portfolio information."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(portfolio_func())
            finally:
                loop.close()
        
        return StructuredTool(
            name="view_portfolio",
            description="Get portfolio balances and holdings across all chains",
            func=sync_portfolio_tool,
            args_schema=None
        )
    
    async def _init_agent(self):
        """Initialize the agent if not already created."""
        if self.agent is None:
            portfolio_tool = self._create_langchain_tool()
            self.agent = await create_tools_agent(
                tools=[portfolio_tool],
                model_id=self.model,
                verbose=True
            )
    
    async def chat(self, message: str) -> str:
        """Process a chat message and return response."""
        try:
            # Initialize agent if needed
            await self._init_agent()
            
            # System message for the agent
            system_message = """You are a helpful DeFi portfolio assistant.

When the user asks about their portfolio, balances, holdings, or tokens, use the view_portfolio tool.

After getting the portfolio data, provide a clear summary of:
1. Total portfolio value
2. Main holdings by chain
3. Any notable positions"""

            # Execute with agent
            result = await self.agent.execute(
                user_instructions=message,
                system_message=system_message
            )
            
            if result["error"]:
                return f"Error: {result['error']}"
            
            return result["final_output"]
                
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return f"Error: {str(e)}"


# Convenience function for quick setup
async def create_assistant(vault_address: str, model: str = "google/gemini-2.5-flash") -> SimpleAssistant:
    """Create a simple assistant instance."""
    return SimpleAssistant(vault_address, model)