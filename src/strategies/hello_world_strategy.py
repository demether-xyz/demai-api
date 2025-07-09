import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .base_strategy import BaseStrategy, StrategyResult, RiskLevel

logger = logging.getLogger(__name__)


class HelloWorldStrategy(BaseStrategy):
    """
    A simple hello world strategy for testing the framework.
    This strategy just logs a message and returns success.
    """
    
    def __init__(self):
        super().__init__(
            strategy_id="hello_world",
            name="Hello World Strategy",
            description="A simple test strategy that logs messages",
            detailed_description="This is a test strategy that demonstrates the framework. It logs a custom message and returns success. Perfect for testing the strategy execution pipeline without any real blockchain interactions.",
            chain_id=42161,  # Arbitrum
            chain_name="Arbitrum",
            chain_icon="⚡",
            primary_token="USDC",
            secondary_tokens=["USDC", "USDT"],
            apy=5.0,
            risk_level=RiskLevel.LOW,
            update_frequency="Every hour",
            protocol="Hello Protocol",
            threshold_info="No minimum required for testing"
        )
    
    async def execute(self, task_data: Dict[str, Any]) -> StrategyResult:
        """
        Execute the hello world strategy
        """
        try:
            user_address = task_data["user_address"]
            vault_address = task_data["vault_address"]
            amount = task_data["amount"]
            params = task_data.get("params", {})
            chain_id = task_data["chain_id"]
            
            # Get custom message from params or use default
            message = params.get("message", "Hello World!")
            
            # Log the execution
            logger.info(f"Executing HelloWorld strategy for user {user_address}")
            logger.info(f"Vault: {vault_address}, Amount: {amount}, Chain: {chain_id}")
            logger.info(f"Message: {message}")
            
            # Simulate some work
            result_data = {
                "message": message,
                "user": user_address,
                "vault": vault_address,
                "amount": amount,
                "chain_id": chain_id,
                "executed_at": datetime.utcnow().isoformat(),
                "strategy_info": {
                    "name": self.name,
                    "protocol": self.protocol,
                    "primary_token": self.primary_token,
                    "apy": self.apy
                }
            }
            
            # Return success
            return StrategyResult(
                success=True,
                data=result_data
            )
            
        except Exception as e:
            logger.error(f"Error in HelloWorld strategy: {str(e)}")
            return StrategyResult(
                success=False,
                error=str(e)
            )
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate parameters for the hello world strategy
        """
        # Optional message parameter
        if "message" in params and not isinstance(params["message"], str):
            return False, "Message must be a string"
        
        # All params are valid
        return True, None
    
    def get_default_interval_hours(self) -> int:
        """Run every hour by default"""
        return 1
    
    def get_required_params(self) -> list[str]:
        """No required params for hello world"""
        return []