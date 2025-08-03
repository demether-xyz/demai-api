"""
Define available DeFi strategies that users can subscribe to.
"""
from typing import Dict, Any, List


# Define available strategies with minimal fields
STRATEGIES: Dict[str, Dict[str, Any]] = {
    "core_stablecoin_optimizer": {
        "id": "core_stablecoin_optimizer",
        "name": "Core Stablecoin Yield Optimizer",
        "description": "Optimizes best yield between USDT and USDC on Core chain daily",
        "task": "Analyze yields for USDT and USDC on Core chain, swap {percentage}% of Core funds to the higher yielding stablecoin, and deposit into the best lending protocol",
        "frequency": "daily",
        "chain": "Core",
        "tokens": ["USDT", "USDC"],
        "protocols": ["Colend"]  # Colend for lendings
    }
}

# Note: {percentage} will be replaced with the user-defined percentage when the strategy is executed


def get_strategy(strategy_id: str) -> Dict[str, Any]:
    """Get a specific strategy by ID.
    
    Args:
        strategy_id: The strategy ID
        
    Returns:
        Strategy configuration dict
        
    Raises:
        ValueError: If strategy not found
    """
    if strategy_id not in STRATEGIES:
        raise ValueError(f"Strategy '{strategy_id}' not found")
    return STRATEGIES[strategy_id].copy()


def get_all_strategies() -> List[Dict[str, Any]]:
    """Get all strategies.
    
    Returns:
        List of all strategy configurations
    """
    return [strategy.copy() for strategy in STRATEGIES.values()]


def format_strategy_task(strategy_id: str, user_params: Dict[str, Any]) -> str:
    """Format a strategy task with user-defined parameters.
    
    Args:
        strategy_id: The strategy ID
        user_params: User-defined parameters (e.g., {"percentage": 50})
        
    Returns:
        Formatted task string
        
    Raises:
        ValueError: If strategy not found
    """
    strategy = get_strategy(strategy_id)
    task = strategy["task"]
    
    # Replace placeholders with user parameters
    for key, value in user_params.items():
        placeholder = "{" + key + "}"
        task = task.replace(placeholder, str(value))
    
    return task