"""
Strategy execution service for one-time LLM analysis and execution.
No chat history, no session management - just execute the given task with tools.
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.tools.portfolio_tool import create_portfolio_tool
from src.utils.defi_tools import create_defi_langchain_tools
from src.utils.aave_yields_utils import get_simplified_aave_yields, get_available_tokens_and_chains
from src.utils.ai_router_tools import create_tools_agent
from src.utils.json_parser import extract_json_content
from src.config import logger
from src.utils.mongo_connection import mongo_connection
from src.utils.prompt_utils import get_prompt
from dotenv import load_dotenv

load_dotenv()


class StrategyExecutor:
    """Execute one-time strategy tasks using LLM and tools."""
    
    def __init__(self, vault_address: str, model: str = "google/gemini-2.5-pro"):
        """Initialize the executor with a vault address."""
        self.vault_address = vault_address
        self.model = model
        self.tools = None  # Will be created on first use
        self.agent = None  # Will be created on first use
    
    def _create_langchain_tools(self):
        """Create LangChain tool wrappers using shared utilities."""
        if self.tools is None:
            # Create tools without portfolio (since it's passed as context)
            self.tools = create_defi_langchain_tools(
                vault_address=self.vault_address,
                include_portfolio=False
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
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for strategy execution."""
        prompt_data = {
            "identity": "You are a DeFi strategy execution agent. Your sole purpose is to analyze the given task and execute it using available tools.",
            
            "execution_mode": "You operate in one-shot execution mode - no conversation, no follow-up questions. You must complete the given task autonomously.",
            
            "core_capabilities": {
                "yield_optimization": "Use provided yield data to execute deposits based on portfolio data",
                "token_swapping": "Execute token swaps on Core chain via Akka Finance",
                "lending_operations": "Supply or withdraw tokens on Aave/Colend",
                "portfolio_rebalancing": "Analyze portfolio and execute rebalancing strategies"
            },
            
            "available_tools": [
                {
                    "name": "research",
                    "description": "Get additional information if needed (NOTE: current yields are already provided in context)"
                },
                {
                    "name": "aave_lending",
                    "description": "Supply or withdraw tokens on lending protocols"
                },
                {
                    "name": "akka_swap",
                    "description": "Swap tokens on Core chain"
                }
            ],
            
            "execution_guidelines": [
                "Analyze the task and portfolio data to determine required actions",
                "Execute all necessary steps to complete the task",
                "Use the yield data provided in context for lending decisions (no need to research current rates)",
                "Calculate exact amounts for percentage-based requests",
                "Chain multiple operations together as needed",
                "Complete the entire task without asking for clarification",
                "Create a brief, user-friendly memo summarizing key actions and amounts for SMS notification"
            ],
            
            "response_format": {
                "instructions": "Return a JSON report of your execution",
                "format": {
                    "task": "The task that was executed",
                    "status": "success or failed",
                    "actions_taken": ["List of actions performed"],
                    "transactions": ["List of transaction hashes with chain info"],
                    "result": "Summary of what was accomplished",
                    "memo": "Brief SMS-friendly summary (max 160 chars) of key action taken and outcome. Example: 'Swapped 500 USDT to USDC and deposited at 5.2% APY on Core chain'",
                    "error": "Error message if failed (optional)"
                }
            }
        }
        
        return get_prompt(prompt_data, wrapper_tag="system_prompt")
    
    async def _get_portfolio_data(self) -> Dict[str, Any]:
        """Get current portfolio data."""
        portfolio_tool_config = create_portfolio_tool(vault_address=self.vault_address)
        portfolio_func = portfolio_tool_config["tool"]
        
        # Call portfolio tool to get current state
        portfolio_data = await portfolio_func(force_long_refresh=False)
        return portfolio_data
    
    
    async def _build_execution_context(self, task: str, portfolio_data: Dict[str, Any]) -> str:
        """Build context for execution including task and portfolio."""
        # Get tokens and chains info
        tokens_and_chains = get_available_tokens_and_chains()
        available_tokens = tokens_and_chains["available_tokens"]
        available_chains = tokens_and_chains["available_chains"]
        
        # Get AAVE yields
        aave_yields = await get_simplified_aave_yields()
        
        context_data = {
            "execution_task": {
                "task": task,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "mode": "One-time autonomous execution"
            },
            
            "portfolio_context": {
                "current_portfolio": portfolio_data,
                "analysis": "Use this portfolio data to calculate amounts and make decisions"
            },
            
            "available_resources": {
                "chains": available_chains,
                "tokens_by_chain": available_tokens,
                "current_yields": {
                    "data": aave_yields,
                    "instruction": "Use these pre-fetched yields for lending decisions - no need to research current rates"
                }
            },
            
            "execution_requirements": [
                "Complete the entire task autonomously",
                "Calculate exact amounts from portfolio percentages",
                "Execute all necessary swaps and deposits",
                "Return detailed execution report"
            ]
        }
        
        return get_prompt(context_data, wrapper_tag="execution_context")
    
    async def execute_strategy(self, task: str) -> Dict[str, Any]:
        """Execute a one-time strategy task.
        
        Args:
            task: The strategy task to execute (e.g., "move 50% to best yield")
            
        Returns:
            Execution result with status, actions taken, and transactions
        """
        try:
            # Initialize agent
            await self._init_agent()
            
            # Get current portfolio data
            logger.info("Fetching portfolio data...")
            portfolio_data = await self._get_portfolio_data()
            
            # Build system prompt
            system_message = self._build_system_prompt()
            
            # Build execution context with task and portfolio
            context_message = await self._build_execution_context(task, portfolio_data)
            
            # Combine context and task
            full_message = f"{context_message}\n\nExecute this task: {task}"
            
            # Execute the strategy
            logger.info(f"Executing strategy: {task}")
            result = await self.agent.execute(
                user_instructions=full_message,
                system_message=system_message,
                chat_history=None  # No chat history for one-time execution
            )
            
            if result["error"]:
                return {
                    "task": task,
                    "status": "failed",
                    "error": result["error"],
                    "actions_taken": [],
                    "transactions": []
                }
            
            # Extract and parse response
            response = result["final_output"]
            execution_report = extract_json_content(response)
            
            if not execution_report:
                # Try to construct report from response
                execution_report = {
                    "task": task,
                    "status": "completed",
                    "result": response,
                    "actions_taken": [],
                    "transactions": []
                }
            
            # Log intermediate steps if available
            if result.get("intermediate_steps"):
                actions = []
                for action, observation in result["intermediate_steps"]:
                    actions.append(f"{action.tool}: {action.tool_input}")
                    logger.info(f"Tool '{action.tool}' executed with result: {observation}")
                
                if "actions_taken" not in execution_report:
                    execution_report["actions_taken"] = actions
            
            return execution_report
            
        except Exception as e:
            logger.error(f"Strategy execution error: {e}")
            return {
                "task": task,
                "status": "failed",
                "error": str(e),
                "actions_taken": [],
                "transactions": []
            }


# Convenience function for strategy execution
async def execute_defi_strategy(task: str, vault_address: str, model: str = "google/gemini-2.5-flash") -> Dict[str, Any]:
    """Execute a DeFi strategy task.
    
    Args:
        task: The strategy to execute
        vault_address: The vault address for portfolio context
        model: The AI model to use
        
    Returns:
        Execution report with results
    """
    executor = StrategyExecutor(vault_address=vault_address, model=model)
    return await executor.execute_strategy(task)