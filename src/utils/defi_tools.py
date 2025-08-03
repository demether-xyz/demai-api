"""
Shared DeFi tools utilities for creating LangChain tools.
"""
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from utils.ai_router_tools import create_langchain_tool
from tools.portfolio_tool import create_portfolio_tool
from tools.research_tool import create_research_tool
from tools.aave_tool import create_aave_tool
from tools.akka_tool import create_swap_tool
from config import logger


# Input schemas for tools
class PortfolioInput(BaseModel):
    force_long_refresh: bool = Field(
        default=False, 
        description="Force a complete refresh of portfolio data. This is a slow operation - only use after major transactions or when explicitly requested. Normally, cached data is sufficient."
    )


class ResearchInput(BaseModel):
    query: str = Field(description="The research query or question to investigate")


class AaveLendingInput(BaseModel):
    chain_name: str = Field(description="The blockchain network - 'Core' or 'Arbitrum'")
    token_symbol: str = Field(description="The token symbol (e.g., 'USDC', 'USDT')")
    amount: float = Field(description="The amount to supply or withdraw")
    action: str = Field(description="The operation - 'supply' or 'withdraw'")


class AkkaSwapInput(BaseModel):
    chain_name: str = Field(description="The blockchain network - currently only 'Core' is supported")
    src_token: str = Field(description="The source token symbol to swap from (e.g., 'USDC', 'USDT')")
    dst_token: str = Field(description="The destination token symbol to swap to")
    amount: float = Field(description="The amount of source token to swap")


def create_defi_langchain_tools(vault_address: str, include_portfolio: bool = True) -> List[StructuredTool]:
    """Create all DeFi LangChain tools.
    
    Args:
        vault_address: The vault address for portfolio and transaction tools
        include_portfolio: Whether to include the portfolio tool (default True)
        
    Returns:
        List of LangChain StructuredTool objects
    """
    tools = []
    
    # Portfolio tool (optional)
    if include_portfolio:
        portfolio_config = create_portfolio_tool(vault_address=vault_address)
        portfolio_func = portfolio_config["tool"]
        
        tools.append(create_langchain_tool(
            func=portfolio_func,
            name="view_portfolio",
            description="Get portfolio balances and holdings across all chains",
            args_schema=PortfolioInput
        ))
    
    # Research tool
    research_config = create_research_tool()
    research_func = research_config["tool"]
    
    tools.append(create_langchain_tool(
        func=research_func,
        name="research",
        description="Perform web research and get real-time information on any topic",
        args_schema=ResearchInput
    ))
    
    # Aave tool
    aave_config = create_aave_tool(vault_address=vault_address)
    aave_func = aave_config["tool"]
    
    tools.append(create_langchain_tool(
        func=aave_func,
        name="aave_lending",
        description="Supply or withdraw tokens on Aave V3 (Arbitrum) or Colend (Core chain). Use this tool when the user wants to lend tokens to Aave/Colend or withdraw tokens from Aave/Colend.",
        args_schema=AaveLendingInput
    ))
    
    # Akka swap tool
    akka_config = create_swap_tool(vault_address=vault_address)
    akka_func = akka_config["tool"]
    
    tools.append(create_langchain_tool(
        func=akka_func,
        name="akka_swap",
        description="Swap tokens using Akka Finance DEX aggregator on Core chain. Use this tool when the user wants to swap, exchange, convert, or trade one token for another.",
        args_schema=AkkaSwapInput
    ))
    
    logger.info(f"Created {len(tools)} DeFi tools for vault {vault_address}")
    return tools