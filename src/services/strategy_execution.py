"""
Strategy execution service for one-time LLM analysis and execution.
No chat history, no session management - just execute the given task with tools.
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.tools.portfolio_tool import create_portfolio_tool
from src.tools.research_tool import create_research_tool
from src.tools.aave_tool import create_aave_tool, get_all_aave_yields
from src.tools.akka_tool import create_swap_tool
from src.utils.ai_router_tools import create_tools_agent
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
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
        self.research_tool = self._create_research_tool()
        self.aave_tool = self._create_aave_tool()
        self.akka_tool = self._create_akka_tool()
        self.agent = None  # Will be created on first use
    
    def _create_research_tool(self):
        """Create the research tool."""
        research_config = create_research_tool()
        return research_config["tool"]
    
    def _create_aave_tool(self):
        """Create the Aave tool."""
        aave_config = create_aave_tool(vault_address=self.vault_address)
        return aave_config["tool"]
    
    def _create_akka_tool(self):
        """Create the Akka swap tool."""
        akka_config = create_swap_tool(vault_address=self.vault_address)
        return akka_config["tool"]
    
    def _create_langchain_tool(self, func, name: str, description: str, args_schema):
        """Helper to create a LangChain tool with async support."""
        if asyncio.iscoroutinefunction(func):
            # Wrap async function
            def sync_wrapper(**kwargs):
                return asyncio.run(func(**kwargs))
            
            return StructuredTool(
                name=name,
                description=description,
                func=sync_wrapper,
                args_schema=args_schema,
                coroutine=func
            )
        else:
            # Regular sync function
            return StructuredTool(
                name=name,
                description=description,
                func=func,
                args_schema=args_schema
            )
    
    def _create_langchain_tools(self) -> list[StructuredTool]:
        """Create LangChain tool wrappers (no portfolio tool since it's in context)."""
        tools = []
        
        # Research tool
        research_func = self.research_tool
        
        class ResearchInput(BaseModel):
            query: str = Field(description="The research query or question to investigate")
        
        tools.append(self._create_langchain_tool(
            func=research_func,
            name="research",
            description="Perform web research and get real-time information on any topic",
            args_schema=ResearchInput
        ))
        
        # Aave tool
        aave_func = self.aave_tool
        
        class AaveLendingInput(BaseModel):
            chain_name: str = Field(description="The blockchain network - 'Core' or 'Arbitrum'")
            token_symbol: str = Field(description="The token symbol (e.g., 'USDC', 'USDT')")
            amount: float = Field(description="The amount to supply or withdraw")
            action: str = Field(description="The operation - 'supply' or 'withdraw'")
        
        tools.append(self._create_langchain_tool(
            func=aave_func,
            name="aave_lending",
            description="Supply or withdraw tokens on Aave V3 (Arbitrum) or Colend (Core chain)",
            args_schema=AaveLendingInput
        ))
        
        # Akka swap tool
        akka_func = self.akka_tool
        
        class AkkaSwapInput(BaseModel):
            chain_name: str = Field(description="The blockchain network - currently only 'Core' is supported")
            src_token: str = Field(description="The source token symbol to swap from (e.g., 'USDC', 'USDT')")
            dst_token: str = Field(description="The destination token symbol to swap to")
            amount: float = Field(description="The amount of source token to swap")
        
        tools.append(self._create_langchain_tool(
            func=akka_func,
            name="akka_swap",
            description="Swap tokens using Akka Finance DEX aggregator on Core chain",
            args_schema=AkkaSwapInput
        ))
        
        return tools
    
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
                "yield_optimization": "Find best lending yields and execute deposits based on portfolio data",
                "token_swapping": "Execute token swaps on Core chain via Akka Finance",
                "lending_operations": "Supply or withdraw tokens on Aave/Colend",
                "portfolio_rebalancing": "Analyze portfolio and execute rebalancing strategies"
            },
            
            "available_tools": [
                {
                    "name": "research",
                    "description": "Get additional information if needed for decision making"
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
                "Use yield data from context for optimization decisions",
                "Calculate exact amounts for percentage-based requests",
                "Chain multiple operations together as needed",
                "Complete the entire task without asking for clarification"
            ],
            
            "response_format": {
                "instructions": "Return a JSON report of your execution",
                "format": {
                    "task": "The task that was executed",
                    "status": "success or failed",
                    "actions_taken": ["List of actions performed"],
                    "transactions": ["List of transaction hashes with chain info"],
                    "result": "Summary of what was accomplished",
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
    
    async def _get_simplified_aave_yields(self) -> List[Dict[str, Any]]:
        """Get simplified AAVE yields data."""
        try:
            from src.config import CHAIN_CONFIG
            
            # Connect to database
            db = await mongo_connection.connect()
            
            # Fetch all yields
            yields = await get_all_aave_yields(db=db)
            
            # Simplify the data
            simplified_yields = []
            for token_symbol, chain_yields in yields.items():
                for yield_data in chain_yields:
                    chain_id = yield_data.get('chain_id')
                    chain_name = CHAIN_CONFIG.get(chain_id, {}).get('name', f'Chain {chain_id}')
                    
                    simplified_yields.append({
                        'token': token_symbol,
                        'chain': chain_name,
                        'borrow_apy': round(yield_data.get('borrow_apy', 0), 2)
                    })
            
            return simplified_yields
        except Exception as e:
            logger.warning(f"Failed to fetch AAVE yields: {e}")
            return []
    
    async def _build_execution_context(self, task: str, portfolio_data: Dict[str, Any]) -> str:
        """Build context for execution including task and portfolio."""
        from src.config import SUPPORTED_TOKENS, CHAIN_CONFIG
        
        # Get available tokens and chains
        available_tokens = {}
        for token_symbol, token_info in SUPPORTED_TOKENS.items():
            chains = []
            for chain_id in token_info.get("addresses", {}):
                if chain_id in CHAIN_CONFIG:
                    chains.append(CHAIN_CONFIG[chain_id]["name"])
            if chains:
                available_tokens[token_symbol] = chains
        
        available_chains = [config["name"] for config in CHAIN_CONFIG.values()]
        
        # Get AAVE yields
        aave_yields = await self._get_simplified_aave_yields()
        
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
                    "instruction": "Use these yields for optimization decisions"
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