"""
Sample Tool Pattern for LLM Integration

This module demonstrates the standard pattern for creating LLM-friendly tools.

Pattern Overview:
1. Builder function configures the tool with runtime parameters
2. Returns an async function with minimal LLM parameters
3. All configuration handled at creation time
4. Returns structured JSON responses

Example Usage:
    # Configuration (done once)
    tool_config = create_sample_tool(
        chain_name="Core",
        vault_address="0x123..."
    )
    
    # LLM usage (simple parameters)
    result = await tool_config["tool"](
        token="USDC",
        amount=100.5,
        action="process"
    )
"""

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def create_sample_tool(
    chain_name: str,
    vault_address: str,
    private_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a sample tool following the standard pattern.
    
    Args:
        chain_name: Blockchain network name (e.g., "Core", "Arbitrum")
        vault_address: Vault contract address
        private_key: Optional private key (defaults to PRIVATE_KEY env var)
        
    Returns:
        Dictionary with "tool" function and "metadata"
    """
    # Import configuration (loads environment)
    from config import CHAIN_CONFIG, RPC_ENDPOINTS
    from tools.tool_executor import ToolExecutor
    
    # Handle private key
    if not private_key:
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise ValueError("PRIVATE_KEY not provided and not found in environment")
    
    # Validate and get chain ID
    chain_id = None
    for c_id, config in CHAIN_CONFIG.items():
        if config["name"].lower() == chain_name.lower():
            chain_id = c_id
            break
    
    if chain_id is None:
        raise ValueError(f"Unknown chain name: {chain_name}")
    
    # Get RPC URL
    rpc_url = RPC_ENDPOINTS.get(chain_id)
    if not rpc_url:
        raise ValueError(f"RPC URL not found for chain ID: {chain_id}")
    
    # Create the LLM-callable function
    async def sample_operation(
        token: str,
        amount: float,
        action: str = "process"
    ) -> str:
        """
        Execute operation with minimal parameters for LLM use.
        
        Args:
            token: Token symbol (e.g., "USDC")
            amount: Amount to process
            action: Operation type (default: "process")
            
        Returns:
            JSON string with operation result
        """
        try:
            # Validate inputs
            if action not in ["process", "analyze"]:
                return json.dumps({
                    "status": "error",
                    "message": f"Invalid action: {action}"
                })
            
            # Create executor for blockchain operations
            executor = ToolExecutor(rpc_url, private_key)
            
            # Implement your logic here
            # This is just a placeholder
            result = f"Processed {amount} {token} with {action}"
            
            # Return structured response
            return json.dumps({
                "status": "success",
                "message": f"Successfully executed {action}",
                "data": {
                    "token": token,
                    "amount": amount,
                    "action": action,
                    "chain": chain_name,
                    "vault": vault_address,
                    "result": result
                }
            })
            
        except Exception as e:
            logger.error(f"Error in sample_operation: {e}")
            return json.dumps({
                "status": "error",
                "message": f"Failed to {action}: {str(e)}"
            })
    
    # Return tool configuration
    return {
        "tool": sample_operation,
        "metadata": {
            "name": "sample_tool",
            "description": f"Sample tool on {chain_name}",
            "chain": chain_name,
            "vault": vault_address,
            "parameters": {
                "token": "Token symbol (e.g., USDC)",
                "amount": "Amount to process",
                "action": "Operation type: process or analyze"
            }
        }
    }