from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"
    FAILED = "failed"


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StrategyResult:
    def __init__(self, success: bool, data: Dict[str, Any] = None, error: str = None, tx_hash: str = None):
        self.success = success
        self.data = data or {}
        self.error = error
        self.tx_hash = tx_hash
        self.timestamp = datetime.utcnow()
    
    def to_dict(self):
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "tx_hash": self.tx_hash,
            "timestamp": self.timestamp.isoformat()
        }


class BaseStrategy(ABC):
    """Base class for all strategies"""
    def __init__(
        self, 
        strategy_id: str, 
        name: str, 
        description: str,
        detailed_description: str = None,
        chain_id: int = None,
        chain_name: str = None,
        chain_icon: str = None,
        primary_token: str = None,
        secondary_tokens: List[str] = None,
        apy: float = 0.0,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        update_frequency: str = "Daily",
        protocol: str = None,
        threshold_info: str = None
    ):
        self.strategy_id = strategy_id
        self.name = name
        self.description = description
        self.detailed_description = detailed_description or description
        self.chain_id = chain_id
        self.chain_name = chain_name
        self.chain_icon = chain_icon
        self.primary_token = primary_token
        self.secondary_tokens = secondary_tokens or []
        self.apy = apy
        self.risk_level = risk_level
        self.update_frequency = update_frequency
        self.protocol = protocol
        self.threshold_info = threshold_info
    
    @abstractmethod
    async def execute(self, task_data: Dict[str, Any]) -> StrategyResult:
        """
        Execute the strategy for a specific task
        
        Args:
            task_data: Dict containing:
                - user_address: str
                - vault_address: str
                - amount: str (in wei)
                - params: Dict[str, Any] (strategy-specific parameters)
                - chain_id: int
        
        Returns:
            StrategyResult indicating success/failure and any transaction data
        """
        pass
    
    @abstractmethod
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate strategy parameters
        
        Returns:
            (is_valid, error_message)
        """
        pass
    
    def get_default_interval_hours(self) -> int:
        """Default interval between runs in hours"""
        return 24
    
    def get_required_params(self) -> list[str]:
        """List of required parameter names"""
        return []
    
    def to_dict(self) -> Dict[str, Any]:
        """Return strategy information in format expected by frontend"""
        return {
            "id": self.strategy_id,
            "strategy_id": self.strategy_id,  # Keep for backward compatibility
            "name": self.name,
            "description": self.description,
            "detailedDescription": self.detailed_description,
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "chain_icon": self.chain_icon,
            "primaryToken": self.primary_token,
            "secondaryTokens": self.secondary_tokens,
            "apy": self.apy,
            "riskLevel": self.risk_level.value if self.risk_level else "medium",
            "updateFrequency": self.update_frequency,
            "protocol": self.protocol,
            "thresholdInfo": self.threshold_info,
            "default_interval_hours": self.get_default_interval_hours(),
            "required_params": self.get_required_params()
        }