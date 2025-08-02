"""
Aave V3 strategy implementation with contract definitions and helper functions
"""
from typing import Optional, List, Dict, Any
from web3 import Web3
from eth_abi import encode
import asyncio
import logging
import json
import os

logger = logging.getLogger(__name__)

# Aave V3 strategy contract addresses
AAVE_STRATEGY_CONTRACTS = {
    42161: {  # Arbitrum
        "aave_v3_supply": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",  # Aave V3 Pool on Arbitrum
        "aave_v3_withdraw": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",  # Same contract, different function
        "aave_protocol_data_provider": "0x69FA688f1Dc47d4B5d8029D5a35FB7a548310654",  # AaveProtocolDataProvider on Arbitrum
    },
    1116: { # Core
        "aave_v3_supply": "0x0CEa9F0F49F30d376390e480ba32f903B43B19C5", # Aave V3 Pool on Core
        "aave_v3_withdraw": "0x0CEa9F0F49F30d376390e480ba32f903B43B19C5", # Same contract, different function
        "aave_protocol_data_provider": "0x0CEa9F0F49F30d376390e480ba32f903B43B19C5",  # Use Pool as fallback for Core
    }
}

# Helper function to get aToken address from centralized config
def get_atoken_address(token_symbol: str, chain_id: int) -> str:
    """Get aToken address from SUPPORTED_TOKENS config"""
    try:
        from config import SUPPORTED_TOKENS
        return SUPPORTED_TOKENS[token_symbol]["aave_atokens"][chain_id]
    except KeyError:
        return None

# Aave V3 strategy function signatures
AAVE_STRATEGY_FUNCTIONS = {
    "aave_v3_supply": {
        "function_name": "supply",
        "function_signature": "supply(address,uint256,address,uint16)",
        "requires_approval": True
    },
    "aave_v3_withdraw": {
        "function_name": "withdraw", 
        "function_signature": "withdraw(address,uint256,address)",
        "requires_approval": False
    }
}

# ABI for Aave V3 Pool
AAVE_V3_POOL_ABI = [
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "onBehalfOf", "type": "address"},
            {"name": "referralCode", "type": "uint16"}
        ],
        "name": "supply",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "to", "type": "address"}
        ],
        "name": "withdraw",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "asset", "type": "address"}
        ],
        "name": "getReserveData",
        "outputs": [
            {
                "components": [
                    {"name": "configuration", "type": "uint256"},
                    {"name": "liquidityIndex", "type": "uint128"},
                    {"name": "currentLiquidityRate", "type": "uint128"},
                    {"name": "variableBorrowIndex", "type": "uint128"},
                    {"name": "currentVariableBorrowRate", "type": "uint128"},
                    {"name": "currentStableBorrowRate", "type": "uint128"},
                    {"name": "lastUpdateTimestamp", "type": "uint40"},
                    {"name": "id", "type": "uint16"},
                    {"name": "aTokenAddress", "type": "address"},
                    {"name": "stableDebtTokenAddress", "type": "address"},
                    {"name": "variableDebtTokenAddress", "type": "address"},
                    {"name": "interestRateStrategyAddress", "type": "address"},
                    {"name": "accruedToTreasury", "type": "uint128"},
                    {"name": "unbacked", "type": "uint128"},
                    {"name": "isolationModeTotalDebt", "type": "uint128"}
                ],
                "name": "",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# ABI for Aave aToken
AAVE_ATOKEN_ABI = [
    {
        "inputs": [
            {"name": "account", "type": "address"}
        ],
        "name": "balanceOf",
        "outputs": [
            {"name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# ABI for AaveProtocolDataProvider
AAVE_DATA_PROVIDER_ABI = [
    {
        "inputs": [
            {"name": "asset", "type": "address"}
        ],
        "name": "getReserveData",
        "outputs": [
            {"name": "unbacked", "type": "uint256"},
            {"name": "accruedToTreasuryScaled", "type": "uint256"},
            {"name": "totalAToken", "type": "uint256"},
            {"name": "totalStableDebt", "type": "uint256"},
            {"name": "totalVariableDebt", "type": "uint256"},
            {"name": "liquidityRate", "type": "uint256"},
            {"name": "variableBorrowRate", "type": "uint256"},
            {"name": "stableBorrowRate", "type": "uint256"},
            {"name": "averageStableBorrowRate", "type": "uint256"},
            {"name": "liquidityIndex", "type": "uint256"},
            {"name": "variableBorrowIndex", "type": "uint256"},
            {"name": "lastUpdateTimestamp", "type": "uint40"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "asset", "type": "address"}
        ],
        "name": "getUserReserveData",
        "outputs": [
            {"name": "currentATokenBalance", "type": "uint256"},
            {"name": "currentStableDebt", "type": "uint256"},
            {"name": "currentVariableDebt", "type": "uint256"},
            {"name": "principalStableDebt", "type": "uint256"},
            {"name": "scaledVariableDebt", "type": "uint256"},
            {"name": "stableBorrowRate", "type": "uint256"},
            {"name": "liquidityRate", "type": "uint256"},
            {"name": "stableRateLastUpdated", "type": "uint40"},
            {"name": "usageAsCollateralEnabled", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

def _encode_aave_supply(asset_address: str, amount: int, on_behalf_of: str, referral_code: int = 0) -> bytes:
    """Encode Aave V3 supply function call data."""
    function_selector = Web3.keccak(text="supply(address,uint256,address,uint16)")[:4]
    encoded_params = encode(
        ["address", "uint256", "address", "uint16"],
        [Web3.to_checksum_address(asset_address), amount, Web3.to_checksum_address(on_behalf_of), referral_code]
    )
    return function_selector + encoded_params

def _encode_aave_withdraw(asset_address: str, amount: int, to: str) -> bytes:
    """Encode Aave V3 withdraw function call data."""
    function_selector = Web3.keccak(text="withdraw(address,uint256,address)")[:4]
    encoded_params = encode(
        ["address", "uint256", "address"],
        [Web3.to_checksum_address(asset_address), amount, Web3.to_checksum_address(to)]
    )
    return function_selector + encoded_params

def get_aave_contracts(chain_id: int) -> dict:
    """Get Aave contract addresses for a given chain."""
    return AAVE_STRATEGY_CONTRACTS.get(chain_id, {})

def _ray_to_apy(ray_value: int) -> float:
    """Convert Aave ray format (27 decimals) to APY percentage"""
    # Convert from Ray (27 decimals) to decimal
    rate_decimal = ray_value / 10**27
    # Convert to percentage
    return rate_decimal * 100

async def _get_aave_reserve_data(web3_instance, pool_address: str, asset_address: str) -> Dict[str, Any]:
    """
    Get reserve data for an asset from Aave V3 Pool
    
    Args:
        web3_instance: Web3 instance (sync or async)
        pool_address: Aave V3 Pool contract address
        asset_address: Asset token address
        
    Returns:
        Dictionary with reserve data including APY rates
    """
    try:
        # Check if async Web3
        is_async = hasattr(web3_instance.eth, 'call') and asyncio.iscoroutinefunction(web3_instance.eth.call)
        
        pool_contract = web3_instance.eth.contract(
            address=Web3.to_checksum_address(pool_address),
            abi=AAVE_V3_POOL_ABI
        )
        
        # Call getReserveData
        if is_async:
            reserve_data = await pool_contract.functions.getReserveData(
                Web3.to_checksum_address(asset_address)
            ).call()
        else:
            reserve_data = pool_contract.functions.getReserveData(
                Web3.to_checksum_address(asset_address)
            ).call()
        
        # Extract relevant data
        liquidity_rate = reserve_data[2]  # currentLiquidityRate
        variable_borrow_rate = reserve_data[4]  # currentVariableBorrowRate
        stable_borrow_rate = reserve_data[5]  # currentStableBorrowRate
        last_update = reserve_data[6]  # lastUpdateTimestamp
        atoken_address = reserve_data[8]  # aTokenAddress
        
        return {
            "liquidity_rate": liquidity_rate,
            "variable_borrow_rate": variable_borrow_rate,
            "stable_borrow_rate": stable_borrow_rate,
            "last_update_timestamp": last_update,
            "atoken_address": atoken_address,
            "supply_apy": _ray_to_apy(liquidity_rate),
            "variable_borrow_apy": _ray_to_apy(variable_borrow_rate),
            "stable_borrow_apy": _ray_to_apy(stable_borrow_rate)
        }
        
    except Exception as e:
        logger.error(f"Error getting Aave reserve data: {e}")
        return {"error": str(e)}

async def _get_atoken_balance_async(web3_instance, user_address: str, atoken_address: str, decimals: int) -> float:
    """Get aToken balance for a user (async version)"""
    try:
        atoken_contract = web3_instance.eth.contract(
            address=Web3.to_checksum_address(atoken_address),
            abi=AAVE_ATOKEN_ABI
        )
        
        # Check if async Web3
        if hasattr(web3_instance.eth, 'call') and asyncio.iscoroutinefunction(web3_instance.eth.call):
            balance_wei = await atoken_contract.functions.balanceOf(
                Web3.to_checksum_address(user_address)
            ).call()
        else:
            balance_wei = atoken_contract.functions.balanceOf(
                Web3.to_checksum_address(user_address)
            ).call()
        
        # Convert to human-readable format
        return balance_wei / (10 ** decimals)
        
    except Exception as e:
        logger.error(f"Error getting aToken balance: {e}")
        return 0.0

def _get_atoken_balance_sync(web3_instance, user_address: str, atoken_address: str, decimals: int) -> float:
    """Get aToken balance for a user (sync version for compatibility)"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _get_atoken_balance_async(web3_instance, user_address, atoken_address, decimals)
            )
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error in sync aToken balance wrapper: {e}")
        return 0.0

async def get_aave_current_yield(
    web3_instances: Dict,
    token_symbol: str,
    chain_id: int,
    supported_tokens: Dict
) -> Dict[str, Any]:
    """
    Get current yield rates for a token on Aave V3
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        token_symbol: Token symbol (e.g., "USDC")
        chain_id: Chain ID
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        Dictionary with current yield information
    """
    try:
        # Get contract addresses
        contracts = get_aave_contracts(chain_id)
        if not contracts:
            return {"error": f"Aave not supported on chain {chain_id}"}
        
        pool_address = contracts.get("aave_v3_supply")
        if not pool_address:
            return {"error": f"Aave pool address not found for chain {chain_id}"}
        
        # Get token info
        token_info = supported_tokens.get(token_symbol)
        if not token_info:
            return {"error": f"Token {token_symbol} not supported"}
        
        asset_address = token_info["addresses"].get(chain_id)
        if not asset_address:
            return {"error": f"Token {token_symbol} not available on chain {chain_id}"}
        
        # Get Web3 instance for this chain
        w3 = web3_instances.get(chain_id)
        if not w3:
            return {"error": f"Web3 instance not available for chain {chain_id}"}
        
        # Get reserve data
        reserve_data = await _get_aave_reserve_data(w3, pool_address, asset_address)
        
        if "error" in reserve_data:
            return reserve_data
        
        # Calculate utilization rate
        try:
            if reserve_data["liquidity_rate"] > 0:
                # Utilization = Borrow Rate / Supply Rate (approximation)
                utilization = min(reserve_data["variable_borrow_rate"] / reserve_data["liquidity_rate"], 1.0)
            else:
                utilization = 0.0
        except:
            utilization = 0.0
        
        return {
            "token_symbol": token_symbol,
            "chain_id": chain_id,
            "supply_apy": reserve_data["supply_apy"],
            "borrow_apy": reserve_data["variable_borrow_apy"],
            "utilization_rate": utilization * 100,  # Convert to percentage
            "last_update_timestamp": reserve_data["last_update_timestamp"],
            "atoken_address": reserve_data["atoken_address"],
            "pool_address": pool_address
        }
        
    except Exception as e:
        logger.error(f"Error getting Aave yield for {token_symbol} on chain {chain_id}: {e}")
        return {"error": str(e)}

async def get_aave_strategy_balances(
    web3_instances: Dict,
    vault_address: str,
    supported_tokens: Dict
) -> List[Dict[str, Any]]:
    """
    Get Aave V3 balances for all supported tokens across all chains
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        vault_address: Vault address to check balances for
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        List of balance dictionaries for each token/chain combination
    """
    balances = []
    
    for token_symbol, token_info in supported_tokens.items():
        # Check if token has Aave aTokens configured
        if "aave_atokens" not in token_info:
            continue
            
        for chain_id, atoken_address in token_info["aave_atokens"].items():
            # Skip if no Web3 instance for this chain
            if chain_id not in web3_instances:
                continue
                
            try:
                # Get aToken balance
                balance = await _get_atoken_balance_async(
                    web3_instances[chain_id],
                    vault_address,
                    atoken_address,
                    token_info["decimals"]
                )
                
                # Skip if zero balance
                if balance == 0:
                    continue
                
                # Get current yield data
                yield_data = await get_aave_current_yield(
                    web3_instances,
                    token_symbol,
                    chain_id,
                    supported_tokens
                )
                
                balance_info = {
                    "token_symbol": token_symbol,
                    "chain_id": chain_id,
                    "protocol": "Aave V3",
                    "strategy": "aave_v3",
                    "balance": balance,
                    "decimals": token_info["decimals"],
                    "atoken_address": atoken_address,
                    "current_apy": yield_data.get("supply_apy", 0) if "error" not in yield_data else 0
                }
                
                balances.append(balance_info)
                
            except Exception as e:
                logger.error(f"Error getting Aave balance for {token_symbol} on chain {chain_id}: {e}")
                continue
    
    return balances

async def supply_to_aave(
    executor,  # ToolExecutor instance
    chain_id: int,
    vault_address: str,
    asset_address: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """
    Supply assets to Aave V3 through vault
    
    Args:
        executor: ToolExecutor instance
        chain_id: Chain ID
        vault_address: Vault contract address
        asset_address: Asset token address
        amount: Amount to supply (in wei)
        gas_limit: Optional gas limit override
        
    Returns:
        Transaction hash
    """
    contracts = get_aave_contracts(chain_id)
    if not contracts:
        raise ValueError(f"Aave not supported on chain {chain_id}")
    
    aave_pool = contracts["aave_v3_supply"]
    
    # Encode the supply function call
    call_data = _encode_aave_supply(
        asset_address=asset_address,
        amount=amount,
        on_behalf_of=vault_address,  # Supply on behalf of the vault
        referral_code=0
    )
    
    # Token approval for the vault to spend
    approvals = [(asset_address, amount)]
    
    # Execute through vault
    tx_hash = await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=aave_pool,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )
    
    return tx_hash

async def withdraw_from_aave(
    executor,  # ToolExecutor instance
    chain_id: int,
    vault_address: str,
    asset_address: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """
    Withdraw assets from Aave V3 through vault
    
    Args:
        executor: ToolExecutor instance
        chain_id: Chain ID
        vault_address: Vault contract address
        asset_address: Asset token address
        amount: Amount to withdraw (in wei)
        gas_limit: Optional gas limit override
        
    Returns:
        Transaction hash
    """
    contracts = get_aave_contracts(chain_id)
    if not contracts:
        raise ValueError(f"Aave not supported on chain {chain_id}")
    
    aave_pool = contracts["aave_v3_withdraw"]
    
    # Encode the withdraw function call
    call_data = _encode_aave_withdraw(
        asset_address=asset_address,
        amount=amount,
        to=vault_address  # Withdraw to the vault
    )
    
    # No approvals needed for withdrawal
    approvals = []
    
    # Execute through vault
    tx_hash = await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=aave_pool,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )
    
    return tx_hash

# Synchronous wrapper functions for LangChain compatibility

def supply_to_aave_sync(
    chain_name: str,
    vault_address: str,
    token_symbol: str,
    amount: float
) -> str:
    """
    Supply tokens to Aave V3 on the specified chain.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        chain_name: Name of the blockchain network (e.g., "Arbitrum", "Core")
        vault_address: Address of the vault to supply from
        token_symbol: Symbol of the token to supply (e.g., "USDC", "USDT")
        amount: Amount to supply in human-readable format (e.g., 100.5 for 100.5 USDC)
        
    Returns:
        JSON string with transaction result
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from tools.tool_executor import ToolExecutor
        
        # Get private key from environment variable
        PRIVATE_KEY = os.getenv("PRIVATE_KEY")
        if not PRIVATE_KEY:
            return json.dumps({"status": "error", "message": "PRIVATE_KEY environment variable not set"})
        
        # Find chain_id from chain_name
        chain_id = None
        for c_id, config in CHAIN_CONFIG.items():
            if config["name"].lower() == chain_name.lower():
                chain_id = c_id
                break
        
        if chain_id is None:
            return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})
        
        # Get token details from SUPPORTED_TOKENS
        token_config = SUPPORTED_TOKENS.get(token_symbol.upper())
        if not token_config:
            return json.dumps({"status": "error", "message": f"Unsupported token symbol: {token_symbol}"})
        
        asset_address = token_config["addresses"].get(chain_id)
        if not asset_address:
            return json.dumps({"status": "error", "message": f"Token {token_symbol} not available on {chain_name}"})
        
        decimals = token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get RPC URL and initialize executor
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        executor = ToolExecutor(rpc_url, PRIVATE_KEY)
        
        # Run the async supply_to_aave function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tx_hash = loop.run_until_complete(supply_to_aave(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                asset_address=asset_address,
                amount=amount_wei
            ))
        finally:
            loop.close()
        
        if tx_hash:
            return json.dumps({"status": "success", "message": "Supply transaction sent!", "tx_hash": tx_hash})
        else:
            return json.dumps({"status": "error", "message": "Failed to send supply transaction."})
    
    except Exception as e:
        logger.error(f"Error in supply_to_aave_sync: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

def withdraw_from_aave_sync(
    chain_name: str,
    vault_address: str,
    token_symbol: str,
    amount: float
) -> str:
    """
    Withdraw tokens from Aave V3 on the specified chain.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        chain_name: Name of the blockchain network (e.g., "Arbitrum", "Core")
        vault_address: Address of the vault to withdraw to
        token_symbol: Symbol of the token to withdraw (e.g., "USDC", "USDT")
        amount: Amount to withdraw in human-readable format (e.g., 100.5 for 100.5 USDC)
        
    Returns:
        JSON string with transaction result
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from tools.tool_executor import ToolExecutor
        
        # Get private key from environment variable
        PRIVATE_KEY = os.getenv("PRIVATE_KEY")
        if not PRIVATE_KEY:
            return json.dumps({"status": "error", "message": "PRIVATE_KEY environment variable not set"})
        
        # Find chain_id from chain_name
        chain_id = None
        for c_id, config in CHAIN_CONFIG.items():
            if config["name"].lower() == chain_name.lower():
                chain_id = c_id
                break
        
        if chain_id is None:
            return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})
        
        # Get token details from SUPPORTED_TOKENS
        token_config = SUPPORTED_TOKENS.get(token_symbol.upper())
        if not token_config:
            return json.dumps({"status": "error", "message": f"Unsupported token symbol: {token_symbol}"})
        
        asset_address = token_config["addresses"].get(chain_id)
        if not asset_address:
            return json.dumps({"status": "error", "message": f"Token {token_symbol} not available on {chain_name}"})
        
        decimals = token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get RPC URL and initialize executor
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        executor = ToolExecutor(rpc_url, PRIVATE_KEY)
        
        # Run the async withdraw_from_aave function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tx_hash = loop.run_until_complete(withdraw_from_aave(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                asset_address=asset_address,
                amount=amount_wei
            ))
        finally:
            loop.close()
        
        if tx_hash:
            return json.dumps({"status": "success", "message": "Withdrawal transaction sent!", "tx_hash": tx_hash})
        else:
            return json.dumps({"status": "error", "message": "Failed to send withdrawal transaction."})
    
    except Exception as e:
        logger.error(f"Error in withdraw_token_from_aave: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})


# ===========================================
# LLM-Friendly Interface with Subtool Pattern
# ===========================================

def create_aave_tool(
    chain_name: str,
    vault_address: str,
    private_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an Aave tool builder function that returns LLM-callable functions.
    
    This follows the subtool pattern where configuration is done at creation time,
    and the returned function has minimal parameters for LLM use.
    
    Args:
        chain_name: Name of the blockchain network (e.g., "Arbitrum", "Core")
        vault_address: Address of the vault to operate from
        private_key: Optional private key (defaults to PRIVATE_KEY env var)
        
    Returns:
        Dictionary containing the configured Aave tool function
    """
    # Get configuration at tool creation time
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
    from tools.tool_executor import ToolExecutor
    
    # Get private key
    if not private_key:
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise ValueError("PRIVATE_KEY not provided and not found in environment")
    
    # Find chain_id from chain_name
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
    
    # Create the LLM-callable function with minimal parameters
    async def aave_operation(
        token_symbol: str,
        amount: float,
        action: str = "supply"
    ) -> str:
        """
        Execute Aave lending operation (supply or withdraw).
        
        This is a simple LLM-friendly interface that accepts only essential parameters.
        All configuration (chain, vault, keys) is handled at tool creation time.
        
        Args:
            token_symbol: Symbol of the token (e.g., "USDC", "USDT")
            amount: Amount in human-readable format (e.g., 100.5)
            action: Operation to perform - "supply" or "withdraw"
            
        Returns:
            JSON string with operation result including transaction hash
        """
        try:
            # Validate action
            if action not in ["supply", "withdraw"]:
                return json.dumps({
                    "status": "error",
                    "message": f"Invalid action: {action}. Must be 'supply' or 'withdraw'"
                })
            
            # Get token configuration
            token_config = SUPPORTED_TOKENS.get(token_symbol.upper())
            if not token_config:
                return json.dumps({
                    "status": "error",
                    "message": f"Unsupported token: {token_symbol}"
                })
            
            asset_address = token_config["addresses"].get(chain_id)
            if not asset_address:
                return json.dumps({
                    "status": "error",
                    "message": f"Token {token_symbol} not available on {chain_name}"
                })
            
            # Convert amount to wei
            decimals = token_config["decimals"]
            amount_wei = int(amount * (10 ** decimals))
            
            # Create executor
            executor = ToolExecutor(rpc_url, private_key)
            
            # Execute the operation
            if action == "supply":
                tx_hash = await supply_to_aave(
                    executor=executor,
                    chain_id=chain_id,
                    vault_address=vault_address,
                    asset_address=asset_address,
                    amount=amount_wei
                )
                message = f"Successfully supplied {amount} {token_symbol} to Aave"
            else:  # withdraw
                tx_hash = await withdraw_from_aave(
                    executor=executor,
                    chain_id=chain_id,
                    vault_address=vault_address,
                    asset_address=asset_address,
                    amount=amount_wei
                )
                message = f"Successfully withdrew {amount} {token_symbol} from Aave"
            
            return json.dumps({
                "status": "success",
                "message": message,
                "data": {
                    "action": action,
                    "token": token_symbol,
                    "amount": amount,
                    "chain": chain_name,
                    "vault": vault_address,
                    "tx_hash": tx_hash
                }
            })
            
        except Exception as e:
            logger.error(f"Error in aave_operation: {e}")
            return json.dumps({
                "status": "error",
                "message": f"Failed to {action}: {str(e)}"
            })
    
    # Return the configured tool
    return {
        "tool": aave_operation,
        "metadata": {
            "name": "aave_lending",
            "description": f"Supply or withdraw tokens on Aave V3 ({chain_name})",
            "chain": chain_name,
            "vault": vault_address,
            "parameters": {
                "token_symbol": "Token to operate with (e.g., USDC, USDT)",
                "amount": "Amount in human-readable format",
                "action": "Operation type: 'supply' or 'withdraw'"
            }
        }
    }