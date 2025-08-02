"""
Portfolio Tool for LLM Integration

This module creates an LLM-friendly tool for getting portfolio information.
The tool allows LLMs to fetch portfolio balances and values across chains.
"""

import json
import logging
import os
from typing import Dict, Any, Optional
from services.portfolio_service import PortfolioService
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


def create_portfolio_tool(
    vault_address: str,
    mongodb_uri: Optional[str] = None,
    database_name: str = "demai-api"
) -> Dict[str, Any]:
    """
    Create a portfolio tool following the standard pattern.
    
    Args:
        vault_address: Vault contract address to query
        mongodb_uri: MongoDB connection string (defaults to MONGODB_URI env var)
        database_name: Name of the database to use
        
    Returns:
        Dictionary with "tool" function and "metadata"
    """
    # Handle MongoDB connection
    if not mongodb_uri:
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            logger.warning("MONGODB_URI not provided, portfolio caching will be disabled")
    
    # Create MongoDB client and database reference if URI is provided
    db = None
    if mongodb_uri:
        try:
            client = AsyncIOMotorClient(mongodb_uri)
            db = client[database_name]
            logger.info(f"MongoDB connected for portfolio tool")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            db = None
    
    # Create portfolio service instance
    portfolio_service = PortfolioService(db=db)
    
    # Create the LLM-callable function
    async def get_portfolio() -> str:
        """
        Get portfolio information for the configured vault.
        
        Returns:
            JSON string with portfolio data
        """
        try:
            # Get portfolio summary for the configured vault
            # Note: get_portfolio_for_llm defaults to refresh=False to use cached data when available
            portfolio_data = await portfolio_service.get_portfolio_for_llm(
                vault_address=vault_address
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
            "parameters": {}
        }
    }