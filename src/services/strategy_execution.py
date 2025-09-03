"""
Strategy execution service for one-time LLM analysis and execution.
No chat history, no session management - just execute the given task with tools.
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from tools.portfolio_tool import create_portfolio_tool
from utils.defi_tools import create_defi_langchain_tools
from utils.aave_yields_utils import get_simplified_aave_yields, get_available_tokens_and_yield_assets
from utils.morpho_yields_utils import get_simplified_morpho_yields
from utils.ai_router_tools import create_tools_agent
from utils.json_parser import extract_json_content
from config import logger
from utils.mongo_connection import mongo_connection
from utils.prompt_utils import get_prompt
from dotenv import load_dotenv

load_dotenv()


class StrategyExecutor:
    """Execute one-time strategy tasks using LLM and tools."""
    
    def __init__(self, vault_address: str, model: str = "openai/gpt-oss-120b"):
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
                "yield_optimization": "Use provided yield data from ALL protocols (Aave/Colend AND Morpho) to execute deposits to the highest yielding options",
                "token_swapping": "Execute token swaps on Core chain via Akka Finance or Katana chain via Sushi",
                "lending_operations": "Supply or withdraw tokens on Aave/Colend (Arbitrum/Core) or Morpho vaults (Katana)",
                "portfolio_rebalancing": "Analyze portfolio and execute rebalancing strategies across all supported chains and protocols"
            },
            
            "available_tools": [
                {
                    "name": "research",
                    "description": "Get additional information if needed (NOTE: current yields are already provided in context)"
                },
                {
                    "name": "aave_lending",
                    "description": "Supply or withdraw tokens on Aave V3 (Arbitrum) or Colend (Core chain) lending protocols"
                },
                {
                    "name": "morpho_lending",
                    "description": "Supply or withdraw tokens on Morpho Blue markets or MetaMorpho vaults (Katana chain) for advanced yield opportunities"
                },
                {
                    "name": "akka_swap",
                    "description": "Swap tokens using Akka Finance DEX aggregator on Core chain"
                },
                {
                    "name": "sushi_swap",
                    "description": "Swap tokens using Sushi router on Katana chain"
                }
            ],
            
            "execution_guidelines": [
                "Analyze the task and portfolio data to determine required actions",
                "Execute all necessary steps to complete the task",
                "Use the yield data provided in context for lending decisions - compare ALL protocols (Aave/Colend AND Morpho) to select the highest yield option",
                "Calculate exact amounts for percentage-based requests based on current portfolio balances",
                "Chain multiple operations together as needed (view portfolio → calculate amounts → swap if needed → deposit to best yield)",
                "For Morpho vaults on Katana: use specific vault addresses (Steakhouse Prime: 0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD, Gauntlet: 0x9540441C503D763094921dbE4f13268E6d1d3B56)",
                "Complete the entire task without asking for clarification",
                "Create a brief, user-friendly memo summarizing key actions and amounts for a notification"
            ],
            
            "response_format": {
                "instructions": "Return a JSON report of your execution",
                "format": {
                    "task": "The task that was executed",
                    "status": "success or failed",
                    "actions_taken": ["List of actions performed"],
                    "transactions": ["List of transaction hashes with chain info"],
                    "result": "Summary of what was accomplished",
                    "memo": "Brief message friendly summary (max 160 chars) of key action taken and outcome.",
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
        # Get tokens, yield-bearing assets, and chains info
        tokens_and_assets = get_available_tokens_and_yield_assets()
        available_tokens = tokens_and_assets["available_tokens"]
        yield_bearing_assets = tokens_and_assets["yield_bearing_assets"]
        available_chains = tokens_and_assets["available_chains"]
        
        # Get yields from both protocols
        aave_yields = await get_simplified_aave_yields()
        morpho_yields = await get_simplified_morpho_yields()
        
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
                "base_tokens": available_tokens,
                "yield_bearing_assets": yield_bearing_assets,
                "current_yields": {
                    "aave_colend": {
                        "description": "Current borrow APY rates for tokens on Aave/Colend",
                        "data": aave_yields,
                        "note": "Traditional lending yields on Aave V3 (Arbitrum) and Colend (Core)"
                    },
                    "morpho": {
                        "description": "Current supply APY rates for tokens on Morpho markets and MetaMorpho vaults",
                        "data": morpho_yields,
                        "note": "Advanced lending yields through Morpho Blue protocol and managed MetaMorpho vaults"
                    },
                    "instruction": "CRITICAL: Compare ALL yield options across both Aave/Colend AND Morpho to select the highest APY for deposits. Use this pre-fetched data - no need to research current rates."
                },
                "morpho_vault_addresses": {
                    "steakhouse_prime": "0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD",
                    "gauntlet": "0x9540441C503D763094921dbE4f13268E6d1d3B56",
                    "note": "Use these exact addresses when depositing to Morpho vaults on Katana"
                }
            },
            
            "execution_requirements": [
                "Complete the entire task autonomously",
                "Calculate exact amounts from portfolio percentages", 
                "Compare yields across ALL protocols (Aave, Colend, AND Morpho) to find the best option",
                "Execute all necessary swaps and deposits to achieve the highest yields",
                "For yield optimization tasks, select the protocol/vault with the highest APY",
                "Return detailed execution report with transaction hashes"
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
async def execute_defi_strategy(task: str, vault_address: str, model: str = "openai/gpt-oss-120b") -> Dict[str, Any]:
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