"""
Asset configuration file containing asset balance checkers for DeFi protocols
"""
from tools.aave_tool import get_aave_strategy_balances

# Asset balance checkers - maps asset types to their balance checking functions
# These check for tokenized assets on DeFi protocols (like aTokens on Aave)
ASSET_BALANCE_CHECKERS = {
    "aave_v3": get_aave_strategy_balances,
    # Future protocol asset checkers can be added here
    # Examples: compound, yearn, etc.
}