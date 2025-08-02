"""
Simple chat assistant with portfolio viewing capabilities.
"""
import asyncio
import os
from src.tools.portfolio_tool import create_portfolio_tool
from src.utils.ai_router_tools import create_tools_agent
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, AIMessage
from src.utils.json_parser import extract_json_content
from src.config import logger
from src.services.chat_session_handler import ChatSessionHandler
from src.utils.mongo_connection import mongo_connection
from dotenv import load_dotenv

load_dotenv()


class SimpleAssistant:
    """Simple chat assistant with portfolio capabilities and session management."""
    
    def __init__(self, vault_address: str, model: str = "google/gemini-2.5-pro"):
        """Initialize the assistant with a vault address."""
        self.vault_address = vault_address
        self.model = model
        self.portfolio_tool = self._create_portfolio_tool()
        self.agent = None  # Will be created on first use
        self.session_handler = None  # Will be initialized when DB is available
        self.agent_id = "portfolio_assistant"  # Fixed agent ID for this assistant type
    
    def _create_portfolio_tool(self):
        """Create the portfolio tool."""
        portfolio_config = create_portfolio_tool(vault_address=self.vault_address)
        return portfolio_config["tool"]
    
    def _create_langchain_tool(self) -> StructuredTool:
        """Create LangChain tool wrapper."""
        portfolio_func = self.portfolio_tool
        
        # Sync wrapper for the async portfolio tool
        def sync_portfolio_tool(*args, **kwargs) -> str:
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
    
    async def _init_session_handler(self):
        """Initialize the session handler with database connection."""
        if self.session_handler is None:
            db = await mongo_connection.connect()
            self.session_handler = ChatSessionHandler(db)
            # Create indexes for better performance
            await self.session_handler.create_indexes()
    
    async def chat(self, message: str, user_id: str) -> str:
        """Process a chat message with session history and return response."""
        try:
            # Initialize agent and session handler if needed
            await self._init_agent()
            await self._init_session_handler()
            
            # Get or create session
            session_data = await self.session_handler.get_or_create_session(
                agent_id=self.agent_id,
                user_id=user_id,
                agent_name="Portfolio Assistant",
                maintain_global_history=True  # Use global history for portfolio context
            )
            
            # Build chat history from session
            chat_history = []
            messages = session_data.get("messages", [])
            
            # Convert to LangChain message format (last 20 messages for context)
            recent_messages = messages[-20:] if len(messages) > 20 else messages
            for msg in recent_messages:
                if msg.get("role") == "user":
                    chat_history.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    chat_history.append(AIMessage(content=msg.get("content", "")))
            
            # Get memory data from session
            memory_data = session_data.get("memory_data", {})
            
            # Build enhanced system message with memory context
            system_message = """You are a helpful DeFi portfolio assistant.

When the user asks about balances, holdings, or their portfolio in any way, use the view_portfolio tool to get their complete portfolio data.

Be proactive and helpful - provide the specific information they asked for along with relevant context from their portfolio.

IMPORTANT: Your responses should be in JSON format:
```json
{
  "reply": "your response to the user",
  "memory": {
    "key": "value to remember about this user/conversation"
  }
}
```

Only update memory when there's important information to remember about the user's preferences, goals, or context."""
            
            # Add memory context if available
            if memory_data:
                memory_context = "\n\nRemembered information about this user:\n"
                for key, value in memory_data.items():
                    memory_context += f"- {key}: {value}\n"
                system_message += memory_context
            
            # Execute with agent and chat history
            result = await self.agent.execute(
                user_instructions=message,
                system_message=system_message,
                chat_history=chat_history if chat_history else None
            )
            
            if result["error"]:
                error_response = f"Error: {result['error']}"
                # Save error message to history
                await self.session_handler.add_messages(
                    agent_id=self.agent_id,
                    user_id=user_id,
                    account_id=None,
                    maintain_global_history=True,
                    messages=[
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": error_response}
                    ]
                )
                return error_response
            
            # Extract response and handle JSON format
            assistant_response = result["final_output"]
            memory_updates = {}
            
            # Try to extract JSON from response
            extracted_json = extract_json_content(assistant_response)
            
            if extracted_json and "reply" in extracted_json:
                # Extract the actual reply from JSON
                actual_reply = extracted_json.get("reply", assistant_response)
                
                # Extract memory updates if present
                if "memory" in extracted_json and isinstance(extracted_json["memory"], dict):
                    memory_updates = extracted_json["memory"]
                    logger.info(f"Extracted memory updates: {len(memory_updates)} fields")
                    
                    # Update session with memory data
                    if memory_updates:
                        await self.session_handler.update_memory_data(
                            agent_id=self.agent_id,
                            user_id=user_id,
                            memory_updates=memory_updates,
                            maintain_global_history=True
                        )
            else:
                # If no valid JSON format, use the original response
                actual_reply = assistant_response
            
            # Save messages to history
            await self.session_handler.add_messages(
                agent_id=self.agent_id,
                user_id=user_id,
                account_id=None,
                maintain_global_history=True,
                messages=[
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": actual_reply}
                ]
            )
            
            return actual_reply
                
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return f"Error: {str(e)}"


# Convenience function for quick setup
async def create_assistant(vault_address: str, model: str = "google/gemini-2.5-flash") -> SimpleAssistant:
    """Create a simple assistant instance."""
    return SimpleAssistant(vault_address, model)


# Main chatbot function expected by main.py
async def run_chatbot(message: str, chat_id: str, vault_address: str = None) -> str:
    """
    Run the chatbot with a message and return the response.
    
    Args:
        message: User's message
        chat_id: Chat/user identifier (wallet address for chat history)
        vault_address: Vault address - the unique ID for portfolio context
    
    Returns:
        Assistant's response
    """
    try:
        # The vault address is the unique identifier for portfolio context
        # If no vault address provided, we can't provide portfolio functionality
        if not vault_address:
            return "Please provide a vault address to access portfolio features."
        
        # Create assistant instance with vault address as the unique ID
        assistant = SimpleAssistant(vault_address=vault_address)
        
        # Process the message with chat_id as user_id for session management
        response = await assistant.chat(message, user_id=chat_id)
        
        return response
        
    except Exception as e:
        logger.error(f"Error in run_chatbot: {e}")
        return f"Sorry, I encountered an error: {str(e)}"