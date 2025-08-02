"""
Strategy configuration file containing contract addresses and function definitions
"""
from tools.aave_tool import AAVE_STRATEGY_CONTRACTS, AAVE_STRATEGY_FUNCTIONS, get_aave_strategy_balances
from src.archive.btc_core_strategy import BTCCoreStrategy

# Create BTC Core strategy instance for balance checking
_btc_core_strategy = BTCCoreStrategy()

# Combined strategy contract addresses from all protocol implementations
STRATEGY_CONTRACTS = {
    **AAVE_STRATEGY_CONTRACTS,
    # Future protocol contracts can be added here
}

# Combined strategy function signatures from all protocol implementations
STRATEGY_FUNCTIONS = {
    **AAVE_STRATEGY_FUNCTIONS,
    # Future protocol functions can be added here
}

# Strategy balance checkers - maps strategy names to their balance checking functions
STRATEGY_BALANCE_CHECKERS = {
    "aave_v3": get_aave_strategy_balances,
    "btc_core_yield": _btc_core_strategy.get_strategy_balances,
    # Future strategy balance checkers can be added here
} 