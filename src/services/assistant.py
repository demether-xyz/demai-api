"""
Simple chat assistant with portfolio viewing capabilities.
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Union
from utils.defi_tools import create_defi_langchain_tools
from utils.aave_yields_utils import get_simplified_aave_yields, get_available_tokens_and_chains
from utils.ai_router_tools import create_tools_agent
from langchain_core.messages import HumanMessage, AIMessage
from utils.json_parser import extract_json_content
from config import logger
from services.chat_session_handler import ChatSessionHandler
from utils.mongo_connection import mongo_connection
from utils.prompt_utils import get_prompt
from dotenv import load_dotenv

load_dotenv()


class SimpleAssistant:
    """Simple chat assistant with portfolio capabilities and session management."""
    
    def __init__(self, vault_address: str, model: str = "openai/gpt-oss-120b"):
        """Initialize the assistant with a vault address."""
        self.vault_address = vault_address
        self.model = model
        self.tools = None  # Will be created on first use
        self.agent = None  # Will be created on first use
        self.session_handler = None  # Will be initialized when DB is available
        self.agent_id = "portfolio_assistant"  # Fixed agent ID for this assistant type
    
    def _create_langchain_tools(self):
        """Create LangChain tool wrappers using shared utilities."""
        if self.tools is None:
            self.tools = create_defi_langchain_tools(
                vault_address=self.vault_address,
                include_portfolio=True
            )
        return self.tools
    
    async def _init_agent(self):
        """Initialize the agent if not already created."""
        if self.agent is None:
            tools = self._create_langchain_tools()
            self.agent = await create_tools_agent(
                tools=tools,
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
    
    def _build_system_prompt(self) -> str:
        """Build the base system prompt using prompt_utils."""
        prompt_data = {
            "identity": "You are demAI, an advanced AI-powered assistant designed to revolutionize decentralized finance (DeFi) by providing intelligent, personalized, and automated portfolio management.",
            
            "core_capabilities": {
                "portfolio_analysis": "View and analyze current token balances and positions across all chains",
                "yield_optimization": "Find the best lending yields available on Aave/Colend and execute deposits. When asked to 'deposit X% into best yield', I will: 1) Check portfolio balances, 2) Identify highest yield opportunities from context data, 3) Calculate amounts and determine required swaps, 4) Execute swaps if needed, 5) Deposit into the best yield protocol",
                "token_swapping": "Execute token swaps on Core chain via Akka Finance to rebalance portfolios or prepare for lending deposits. NOTE: Cross-chain transfers are NOT supported - only swaps within Core chain",
                "lending_operations": "Supply tokens to Aave (Arbitrum) or Colend (Core) to earn yield, or withdraw to access liquidity. Each chain operates independently",
                "market_research": "Research current DeFi conditions, protocol information, and market opportunities to inform decisions",
                "strategy_execution": "Execute complex multi-step strategies like 'convert 50% of stablecoins to highest yield' by combining portfolio analysis, swaps, and lending in a structured plan. Limited to operations within each chain"
            },
            
            "available_tools": [
                {
                    "name": "view_portfolio",
                    "description": "Analyze the user's current DeFi positions, balances, and performance metrics across all supported chains. Uses cached data for fast response. Only use force_long_refresh=true for major transactions or when explicitly requested."
                },
                {
                    "name": "research", 
                    "description": "Get real-time information about DeFi protocols, market conditions, yield opportunities, and educational content"
                },
                {
                    "name": "aave_lending",
                    "description": "Supply or withdraw tokens on Aave V3 (Arbitrum) or Colend (Core chain) lending protocols to earn yield or access liquidity"
                },
                {
                    "name": "akka_swap",
                    "description": "Swap tokens using Akka Finance DEX aggregator on Core chain for best execution prices"
                }
            ],
            
            "key_principles": [
                "Execute actions directly when requested - don't just suggest, DO",
                "When asked about yields or optimization, use the yield data in context to make decisions",
                "Develop complete implementation plans for complex requests before executing",
                "Chain multiple tools together to achieve user goals (view portfolio → calculate amounts → swap → deposit)",
                "Always show transaction results and provide clickable links for executed transactions"
            ],
            
            "action_guidelines": [
                "CRITICAL VERIFICATION: Before ANY deposit/lending operation, ALWAYS check portfolio balance first and verify the user has sufficient tokens. If the requested amount exceeds their balance, ask: 'I notice you want to deposit X TOKEN but you only have Y TOKEN available. Would you like to: 1) Deposit your full balance of Y TOKEN instead, or 2) Deposit a different amount?'",
                "For yield optimization requests: First check portfolio, then use context yield data (not research) to identify best opportunities, calculate exact amounts, execute swaps if needed, then deposit",
                "For percentage-based requests: Calculate exact token amounts based on current portfolio balances",
                "For 'best yield' requests: Use the current_aave_lending_rates in context to identify highest APY opportunities",
                "SAFETY CHECKS: Before executing potentially risky operations (depositing >80% of balance, swapping all tokens, withdrawing large amounts), confirm with user: 'This will [describe action]. Are you sure you want to proceed?'",
                "Always develop a clear step-by-step plan before executing complex strategies",
                "Research tool is for validation or additional info only - primary decisions should use context data",
                "IMPORTANT: Cross-chain transfers are NOT supported. You can only: 1) Swap tokens on Core chain via Akka, 2) Lend on Arbitrum via Aave, 3) Lend on Core via Colend. To optimize yields across chains, work with existing balances on each chain"
            ],
            
            "transaction_formatting": {
                "Core": "When returning transaction hashes on Core chain, format as: https://scan.coredao.org/tx/{tx_hash}",
                "Arbitrum": "When returning transaction hashes on Arbitrum, format as: https://arbiscan.io/tx/{tx_hash}"
            },
            
            "response_format": {
                "instructions": "IMPORTANT: Your responses must be in JSON format",
                "example": {
                    "reply": "your response to the user",
                    "memory": {
                        "key": "value to remember about this user/conversation"
                    }
                }
            },
            
            "memory_guidelines": [
                "Risk tolerance (conservative/moderate/aggressive)",
                "Experience level with DeFi",
                "Financial goals and time horizons",
                "Preferred protocols or strategies",
                "Past interactions and preferences"
            ]
        }
        
        return get_prompt(prompt_data, wrapper_tag="system_prompt")
    
    
    async def _build_context_prompt(self, memory_data: dict = None) -> str:
        """Build a context prompt with current date and memory to append before user message."""
        # Get tokens and chains info
        tokens_and_chains = get_available_tokens_and_chains()
        available_tokens = tokens_and_chains["available_tokens"]
        available_chains = tokens_and_chains["available_chains"]
        
        # Get simplified AAVE yields
        aave_yields = await get_simplified_aave_yields()
        
        context_data = {
            "current_context": {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "date": datetime.now().strftime("%A, %B %d, %Y"),
                "user_memory": memory_data if memory_data else {"status": "No previous context stored"},
                "available_defi_assets": {
                    "chains": available_chains,
                    "tokens_by_chain": available_tokens,
                    "aave_tool_info": "For Aave/Colend operations, use these exact chain names and token symbols",
                    "akka_tool_info": "Akka Finance DEX aggregator is currently only available on Core chain",
                    "cross_chain_note": "IMPORTANT: Cross-chain transfers are NOT supported. You must work with existing token balances on each chain. Swaps are only available on Core chain via Akka"
                },
                "current_aave_lending_rates": {
                    "description": "Current borrow APY rates for tokens on Aave/Colend - USE THIS DATA for yield decisions",
                    "yields": aave_yields,
                    "note": "This is your PRIMARY source for yield optimization. When users ask about best yields or where to deposit, use these rates directly without needing research tool"
                }
            }
        }
        
        return get_prompt(context_data, wrapper_tag="context_update")
    
    async def chat(self, message: str, user_id: str, return_intermediate_steps: bool = False) -> Union[str, Dict[str, Any]]:
        """Process a chat message with session history and return response.
        
        Args:
            message: The user's message
            user_id: The user/session ID
            return_intermediate_steps: If True, returns a dict with intermediate steps instead of just the response
            
        Returns:
            Either a string response or a dict with 'response' and 'intermediate_steps'
        """
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
            
            # Build base system message
            system_message = self._build_system_prompt()
            
            # Build context prompt with current date and memory
            context_prompt = await self._build_context_prompt(memory_data)
            
            # Combine context with user message for better memory retention
            enhanced_message = f"{context_prompt}\n\nUser request: {message}"
            
            # Execute with agent and chat history
            result = await self.agent.execute(
                user_instructions=enhanced_message,
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
            
            # Format intermediate steps if requested
            intermediate_messages = []
            if return_intermediate_steps and result.get("intermediate_steps"):
                for i, (action, observation) in enumerate(result["intermediate_steps"]):
                    # Format tool invocation
                    tool_msg = f"Invoking: `{action.tool}` with `{action.tool_input}`"
                    intermediate_messages.append({
                        "type": "tool_invocation",
                        "step": i + 1,
                        "tool": action.tool,
                        "input": action.tool_input,
                        "message": tool_msg
                    })
                    
                    # Format tool response
                    intermediate_messages.append({
                        "type": "tool_response",
                        "step": i + 1,
                        "tool": action.tool,
                        "output": observation,
                        "message": str(observation)
                    })
                    
                    logger.info(f"Step {i+1}: Tool '{action.tool}' called with input: {action.tool_input}")
            
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
            
            # Return based on requested format
            if return_intermediate_steps:
                return {
                    "response": actual_reply,
                    "intermediate_steps": intermediate_messages,
                    "total_steps": result.get("total_steps", 0)
                }
            else:
                return actual_reply
                
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return f"Error: {str(e)}"


# Convenience function for quick setup
async def create_assistant(vault_address: str, model: str = "google/gemini-2.5-pro") -> SimpleAssistant:
    """Create a simple assistant instance."""
    return SimpleAssistant(vault_address, model)


# Main chatbot function expected by main.py
async def run_chatbot(message: str, chat_id: str, vault_address: str = None, return_intermediate_steps: bool = False) -> Union[str, Dict[str, Any]]:
    """
    Run the chatbot with a message and return the response.
    
    Args:
        message: User's message
        chat_id: Chat/user identifier (wallet address for chat history)
        vault_address: Vault address - the unique ID for portfolio context
        return_intermediate_steps: If True, returns dict with response and intermediate steps
    
    Returns:
        Either assistant's response string or dict with response and intermediate steps
    """
    try:
        # The vault address is the unique identifier for portfolio context
        # If no vault address provided, we can't provide portfolio functionality
        if not vault_address:
            return "Please provide a vault address to access portfolio features."
        
        # Create assistant instance with vault address as the unique ID
        assistant = SimpleAssistant(vault_address=vault_address)
        
        # Process the message with chat_id as user_id for session management
        response = await assistant.chat(message, user_id=chat_id, return_intermediate_steps=return_intermediate_steps)
        
        return response
        
    except Exception as e:
        logger.error(f"Error in run_chatbot: {e}")
        return f"Sorry, I encountered an error: {str(e)}"