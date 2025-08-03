"""
Portfolio Tool for LLM Integration

This module creates an LLM-friendly tool for getting portfolio information.
The tool allows LLMs to fetch portfolio balances and values across chains.
"""

import asyncio
import json
import logging
from typing import Dict, Any
from services.portfolio_service import PortfolioService
from utils.mongo_connection import mongo_connection

logger = logging.getLogger(__name__)


def create_portfolio_tool(
    vault_address: str
) -> Dict[str, Any]:
    """
    Create a portfolio tool following the standard pattern.
    
    Args:
        vault_address: Vault contract address to query
        
    Returns:
        Dictionary with "tool" function and "metadata"
    """
    # MongoDB connection will be handled inside the tool function
    # This allows the tool creation to be synchronous while execution is async
    
    # Create the LLM-callable function
    async def get_portfolio(force_long_refresh: bool = False) -> str:
        """
        Get portfolio information for the configured vault.
        
        Args:
            force_long_refresh: Force a complete refresh of portfolio data (slow operation - only use after major transactions)
        
        Returns:
            JSON string with portfolio data
        """
        try:
            # Initialize MongoDB connection
            db = await mongo_connection.connect()
            
            # Create portfolio service instance with db
            portfolio_service = PortfolioService(db)
            # Get portfolio summary for the configured vault
            # Note: get_portfolio_for_llm defaults to refresh=False to use cached data when available
            portfolio_data = await portfolio_service.get_portfolio_for_llm(
                vault_address=vault_address,
                refresh=force_long_refresh
            )
            
            # Check for errors
            if portfolio_data.get("error"):
                return json.dumps({
                    "status": "error",
                    "message": portfolio_data["error"]
                })
            
            # Return structured response
            return json.dumps({
                "status": "success",
                "message": f"Successfully retrieved portfolio for vault {vault_address}",
                "data": {
                    "vault_address": vault_address,
                    "total_value_usd": portfolio_data.get("total_value_usd", 0),
                    "chains": portfolio_data.get("chains", {}),
                    "strategies": portfolio_data.get("strategies", {}),
                    "summary": portfolio_data.get("summary", {})
                }
            })
            
        except Exception as e:
            logger.error(f"Error in get_portfolio: {e}")
            return json.dumps({
                "status": "error",
                "message": f"Failed to get portfolio: {str(e)}"
            })
    
    # Return tool configuration
    return {
        "tool": get_portfolio,
        "metadata": {
            "name": "portfolio_viewer",
            "description": f"Get portfolio balances and values for vault {vault_address}",
            "vault": vault_address,
            "parameters": {
                "force_long_refresh": {
                    "type": "boolean",
                    "description": "Force a complete refresh of portfolio data. This is a slow operation - only use after major transactions or when explicitly requested by the user. Normally, cached data is sufficient.",
                    "default": False
                }
            }
        }
    }