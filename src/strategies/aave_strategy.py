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

# ABI for reading reserve data from Aave V3 Pool
AAVE_POOL_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            {"internalType": "uint256", "name": "unbacked", "type": "uint256"},
            {"internalType": "uint256", "name": "accruedToTreasuryScaled", "type": "uint256"},
            {"internalType": "uint256", "name": "totalAToken", "type": "uint256"},
            {"internalType": "uint256", "name": "totalStableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "totalVariableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityRate", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "averageStableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityIndex", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowIndex", "type": "uint256"},
            {"internalType": "uint40", "name": "lastUpdateTimestamp", "type": "uint40"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# ABI for AaveProtocolDataProvider
AAVE_PROTOCOL_DATA_PROVIDER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "asset", "type": "address"}],
        "name": "getReserveData",
        "outputs": [
            {"internalType": "uint256", "name": "unbacked", "type": "uint256"},
            {"internalType": "uint256", "name": "accruedToTreasuryScaled", "type": "uint256"},
            {"internalType": "uint256", "name": "totalAToken", "type": "uint256"},
            {"internalType": "uint256", "name": "totalStableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "totalVariableDebt", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityRate", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "stableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "averageStableBorrowRate", "type": "uint256"},
            {"internalType": "uint256", "name": "liquidityIndex", "type": "uint256"},
            {"internalType": "uint256", "name": "variableBorrowIndex", "type": "uint256"},
            {"internalType": "uint40", "name": "lastUpdateTimestamp", "type": "uint40"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# Ray math constants - Aave uses ray (1e27) for rates
RAY = 10**27
SECONDS_PER_YEAR = 365 * 24 * 60 * 60

async def get_aave_strategy_balances(web3_instances: Dict, vault_address: str, supported_tokens: Dict) -> List[Dict[str, Any]]:
    """
    Get Aave strategy balances for all supported tokens
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        vault_address: Vault contract address to check balances for
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        List of strategy balance dictionaries
    """
    strategy_balances = []
    
    try:
        vault_address = Web3.to_checksum_address(vault_address)
        
        # Check each supported token's aToken balance
        for token_symbol, token_config in supported_tokens.items():
            for chain_id in token_config["addresses"].keys():
                if chain_id not in web3_instances:
                    logger.warning(f"Chain {chain_id} not available for Aave strategy")
                    continue
                    
                # Get aToken address from centralized config
                atoken_address = get_atoken_address(token_symbol, chain_id)
                if not atoken_address:
                    logger.warning(f"Aave aToken not configured for {token_symbol} on chain {chain_id}")
                    continue
                balance = await _get_atoken_balance_async(
                    web3_instances[chain_id], 
                    vault_address, 
                    atoken_address, 
                    token_config["decimals"]
                )
                
                # Get current yield information
                yield_info = await get_aave_current_yield(
                    web3_instances, token_symbol, chain_id, supported_tokens
                )
                
                if balance > 0:
                    balance_data = {
                        "strategy": "aave_v3",
                        "protocol": "Aave V3",
                        "token_symbol": token_symbol,
                        "token_name": token_config["name"],
                        "chain_id": chain_id,
                        "balance": balance,
                        "atoken_address": atoken_address,
                        "underlying_token": token_config["addresses"][chain_id],
                        "coingeckoId": token_config.get("coingeckoId"),
                        "strategy_type": "lending"
                    }
                    
                    # Add yield information if available
                    if "error" not in yield_info:
                        balance_data.update({
                            "current_apy": yield_info.get("supply_apy", 0),
                            "utilization_rate": yield_info.get("utilization_rate", 0),
                            "total_liquidity": yield_info.get("total_liquidity", 0),
                            "last_update_timestamp": yield_info.get("last_update_timestamp", 0)
                        })
                    
                    strategy_balances.append(balance_data)
                    logger.info(f"Found Aave balance: {balance} {token_symbol} on chain {chain_id} with APY: {yield_info.get('supply_apy', 'N/A')}%")
    
    except Exception as e:
        logger.error(f"Error getting Aave strategy balances: {e}")
    
    return strategy_balances

async def get_aave_current_yield(web3_instances: Dict, token_symbol: str, chain_id: int, supported_tokens: Dict) -> Dict[str, Any]:
    """
    Get current yield (APY) for a token on Aave V3
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        token_symbol: Token symbol (e.g., "USDC", "USDT")
        chain_id: Chain ID to check
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        Dictionary containing yield information
    """
    try:
        if chain_id not in web3_instances:
            logger.error(f"Chain {chain_id} not available for Aave yield query")
            return {"error": f"Chain {chain_id} not available"}
            
        if chain_id not in AAVE_STRATEGY_CONTRACTS:
            logger.error(f"Aave contracts not configured for chain {chain_id}")
            return {"error": f"Aave not supported on chain {chain_id}"}
            
        if token_symbol not in supported_tokens:
            logger.error(f"Token {token_symbol} not supported")
            return {"error": f"Token {token_symbol} not supported"}
            
        token_config = supported_tokens[token_symbol]
        if chain_id not in token_config["addresses"]:
            logger.error(f"Token {token_symbol} not available on chain {chain_id}")
            return {"error": f"Token {token_symbol} not available on chain {chain_id}"}
            
        token_address = token_config["addresses"][chain_id]
        w3 = web3_instances[chain_id]
        
        # Get yield data from Aave Pool contract
        yield_data = await _get_aave_reserve_data_async(w3, token_address, chain_id)
        
        if yield_data:
            # Convert ray format to APY percentage
            supply_apy = _ray_to_apy(yield_data["liquidityRate"])
            borrow_apy = _ray_to_apy(yield_data["variableBorrowRate"])
            
            return {
                "token_symbol": token_symbol,
                "chain_id": chain_id,
                "supply_apy": supply_apy,
                "borrow_apy": borrow_apy,
                "liquidity_rate_ray": yield_data["liquidityRate"],
                "variable_borrow_rate_ray": yield_data["variableBorrowRate"],
                "total_liquidity": yield_data["totalAToken"],
                "total_debt": yield_data["totalVariableDebt"],
                "utilization_rate": _calculate_utilization_rate(
                    yield_data["totalAToken"], 
                    yield_data["totalVariableDebt"]
                ),
                "last_update_timestamp": yield_data["lastUpdateTimestamp"]
            }
        else:
            return {"error": "Failed to retrieve yield data"}
            
    except Exception as e:
        logger.error(f"Error getting Aave yield for {token_symbol} on chain {chain_id}: {e}")
        return {"error": str(e)}

async def get_aave_yields_for_all_tokens(web3_instances: Dict, supported_tokens: Dict) -> List[Dict[str, Any]]:
    """
    Get current yields for all supported tokens on all chains
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        List of yield information for all tokens
    """
    yields = []
    
    for token_symbol, token_config in supported_tokens.items():
        for chain_id in token_config["addresses"].keys():
            if chain_id in AAVE_STRATEGY_CONTRACTS:
                yield_data = await get_aave_current_yield(
                    web3_instances, token_symbol, chain_id, supported_tokens
                )
                if "error" not in yield_data:
                    yields.append(yield_data)
                    
    return yields

async def _get_aave_reserve_data_async(w3: Web3, token_address: str, chain_id: int) -> Optional[Dict]:
    """
    Async wrapper for getting Aave reserve data
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        _get_aave_reserve_data, 
        w3, token_address, chain_id
    )

def _get_aave_reserve_data(w3: Web3, token_address: str, chain_id: int) -> Optional[Dict]:
    """
    Get reserve data from Aave V3 Pool contract
    
    Args:
        w3: Web3 instance
        token_address: Token contract address
        chain_id: Chain ID
        
    Returns:
        Dictionary with reserve data or None if error
    """
    try:
        # Use Pool contract directly for Core, AaveProtocolDataProvider for Arbitrum
        if chain_id == 1116:  # Core
            # Use raw call for Core since ABI decoding fails
            pool_address = AAVE_STRATEGY_CONTRACTS[chain_id]["aave_v3_supply"]
            function_selector = w3.keccak(text='getReserveData(address)')[:4]
            encoded_address = w3.to_bytes(hexstr=token_address.replace('0x', '').zfill(64))
            call_data = function_selector + encoded_address
            
            result = w3.eth.call({
                'to': pool_address,
                'data': call_data.hex()
            })
            
            # Decode raw result manually
            chunks = [result[i:i+32] for i in range(0, len(result), 32)]
            reserve_data = [int.from_bytes(chunk, 'big') for chunk in chunks]
        else:  # Arbitrum - use AaveProtocolDataProvider
            data_provider_address = AAVE_STRATEGY_CONTRACTS[chain_id]["aave_protocol_data_provider"]
            data_provider_contract = w3.eth.contract(
                address=Web3.to_checksum_address(data_provider_address),
                abi=AAVE_PROTOCOL_DATA_PROVIDER_ABI
            )
            reserve_data = data_provider_contract.functions.getReserveData(
                Web3.to_checksum_address(token_address)
            ).call()
        
        # Map the returned tuple to named fields
        if chain_id == 1116:  # Core has different structure
            # Based on UI comparison, Field 2 contains the correct supply APY
            return {
                "unbacked": 0,
                "accruedToTreasuryScaled": 0,
                "totalAToken": reserve_data[1] if len(reserve_data) > 1 else 0,
                "totalStableDebt": 0,
                "totalVariableDebt": reserve_data[4] if len(reserve_data) > 4 else 0,
                "liquidityRate": reserve_data[2] if len(reserve_data) > 2 else 0,  # Field 2 is the correct supply APY
                "variableBorrowRate": reserve_data[4] if len(reserve_data) > 4 else 0,  # Field 4 might be borrow rate
                "stableBorrowRate": 0,
                "averageStableBorrowRate": 0,
                "liquidityIndex": 0,
                "variableBorrowIndex": 0,
                "lastUpdateTimestamp": reserve_data[6] if len(reserve_data) > 6 else 0  # Field 6 is timestamp
            }
        else:  # Standard Aave V3 structure
            return {
                "unbacked": reserve_data[0],
                "accruedToTreasuryScaled": reserve_data[1],
                "totalAToken": reserve_data[2],
                "totalStableDebt": reserve_data[3],
                "totalVariableDebt": reserve_data[4],
                "liquidityRate": reserve_data[5],
                "variableBorrowRate": reserve_data[6],
                "stableBorrowRate": reserve_data[7],
                "averageStableBorrowRate": reserve_data[8],
                "liquidityIndex": reserve_data[9],
                "variableBorrowIndex": reserve_data[10],
                "lastUpdateTimestamp": reserve_data[11]
            }
        
    except Exception as e:
        logger.error(f"Error getting Aave reserve data for {token_address} on chain {chain_id}: {e}")
        return None

def _ray_to_apy(ray_rate: int) -> float:
    """
    Convert Aave ray format rate to APY percentage
    
    Args:
        ray_rate: Rate in ray format (1e27 = 100%)
        
    Returns:
        APY as percentage (e.g., 5.25 for 5.25%)
    """
    try:
        if ray_rate == 0:
            return 0.0
        
        # Use Decimal for high precision arithmetic to avoid overflow
        from decimal import Decimal, getcontext
        getcontext().prec = 50  # Set high precision
        
        # Convert ray to decimal (ray rates in Aave V3 are annual rates)
        ray_decimal = Decimal(str(ray_rate))
        ray_base = Decimal('1000000000000000000000000000')  # 1e27
        
        # Get annual rate as decimal
        annual_rate = ray_decimal / ray_base
        
        # Convert to percentage
        return float(annual_rate * 100)
        
    except (OverflowError, ValueError) as e:
        logger.error(f"Error converting ray {ray_rate} to APY: {e}")
        return 0.0

def _calculate_utilization_rate(total_liquidity: int, total_debt: int) -> float:
    """
    Calculate utilization rate as percentage
    
    Args:
        total_liquidity: Total liquidity in the pool
        total_debt: Total debt borrowed
        
    Returns:
        Utilization rate as percentage
    """
    if total_liquidity == 0:
        return 0.0
        
    return (total_debt / total_liquidity) * 100

def get_aave_yield_for_token(
    token_symbol: str,
    chain_name: str
) -> str:
    """
    Get current yield (APY) for a token on Aave V3 on a specified chain.
    This is a synchronous function for LangChain compatibility.

    Args:
        token_symbol: The symbol of the token (e.g., "USDC", "USDT").
        chain_name: The name of the blockchain network (e.g., "Arbitrum").

    Returns:
        A JSON string with yield information or error message.
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from web3 import Web3
        
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

        token_address = token_config["addresses"].get(chain_id)
        if not token_address:
            return json.dumps({"status": "error", "message": f"Token {token_symbol} not available on {chain_name}"})

        # Get RPC URL and create Web3 instance
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            return json.dumps({"status": "error", "message": f"Failed to connect to {chain_name} RPC"})

        # Get yield data synchronously
        reserve_data = _get_aave_reserve_data(w3, token_address, chain_id)
        
        if reserve_data:
            supply_apy = _ray_to_apy(reserve_data["liquidityRate"])
            borrow_apy = _ray_to_apy(reserve_data["variableBorrowRate"])
            utilization_rate = _calculate_utilization_rate(
                reserve_data["totalAToken"], 
                reserve_data["totalVariableDebt"]
            )
            
            return json.dumps({
                "status": "success",
                "data": {
                    "token_symbol": token_symbol,
                    "chain_name": chain_name,
                    "supply_apy": round(supply_apy, 4),
                    "borrow_apy": round(borrow_apy, 4),
                    "utilization_rate": round(utilization_rate, 2),
                    "total_liquidity": reserve_data["totalAToken"],
                    "total_debt": reserve_data["totalVariableDebt"]
                }
            })
        else:
            return json.dumps({"status": "error", "message": "Failed to retrieve yield data from Aave"})

    except Exception as e:
        logger.error(f"Error in get_aave_yield_for_token: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

async def _get_atoken_balance_async(w3: Web3, vault_address: str, atoken_address: str, decimals: int) -> float:
    """
    Async wrapper for getting aToken balance
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, 
        _get_atoken_balance, 
        w3, vault_address, atoken_address, decimals
    )

def _get_atoken_balance(w3: Web3, vault_address: str, atoken_address: str, decimals: int) -> float:
    """
    Get aToken balance for a vault address
    
    Args:
        w3: Web3 instance
        vault_address: Vault contract address
        atoken_address: aToken contract address
        decimals: Token decimals
        
    Returns:
        Balance as float
    """
    try:
        # ERC20 ABI for balanceOf
        erc20_abi = [
            {
                "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        # Create contract instance
        atoken_contract = w3.eth.contract(
            address=Web3.to_checksum_address(atoken_address),
            abi=erc20_abi
        )
        
        # Get balance
        balance_wei = atoken_contract.functions.balanceOf(
            Web3.to_checksum_address(vault_address)
        ).call()
        
        # Convert to human readable format
        balance = balance_wei / (10 ** decimals)
        
        logger.debug(f"aToken balance for {vault_address}: {balance}")
        return balance
        
    except Exception as e:
        logger.error(f"Error getting aToken balance from {atoken_address}: {e}")
        return 0.0

def _construct_aave_call_data(strategy_name: str, params: Dict[str, Any]) -> bytes:
    """Construct the call data for Aave strategy functions"""
    
    if strategy_name == "aave_v3_supply":
        # supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode)
        function_selector = Web3.keccak(text="supply(address,uint256,address,uint16)")[:4]
        encoded_params = encode(
            ['address', 'uint256', 'address', 'uint16'],
            [
                Web3.to_checksum_address(params["asset"]),
                params["amount"],
                Web3.to_checksum_address(params["on_behalf_of"]),
                params.get("referral_code", 0)
            ]
        )
        return function_selector + encoded_params
               
    elif strategy_name == "aave_v3_withdraw":
        # withdraw(address asset, uint256 amount, address to)
        function_selector = Web3.keccak(text="withdraw(address,uint256,address)")[:4]
        encoded_params = encode(
            ['address', 'uint256', 'address'],
            [
                Web3.to_checksum_address(params["asset"]),
                params["amount"],
                Web3.to_checksum_address(params["to"])
            ]
        )
        return function_selector + encoded_params
    
    else:
        raise ValueError(f"Unknown Aave strategy: {strategy_name}")

def _construct_aave_approvals(strategy_name: str, params: Dict[str, Any]) -> List[tuple]:
    """Construct token approvals needed for Aave strategies"""
    
    if strategy_name == "aave_v3_supply":
        # Need to approve the asset token to the Aave pool
        return [(
            Web3.to_checksum_address(params["asset"]),
            params["amount"]
        )]
        
    elif strategy_name == "aave_v3_withdraw":
        # Withdrawal typically doesn't need approvals (aTokens are burned)
        return []
        
    else:
        return []

async def supply_to_aave(
    executor,  # StrategyExecutor instance
    chain_id: int,
    vault_address: str,
    asset_address: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """
    Supply tokens to Aave V3
    
    Args:
        executor: StrategyExecutor instance
        chain_id: The chain ID
        vault_address: Vault contract address
        asset_address: Token address to supply
        amount: Amount in token's smallest unit (wei)
        gas_limit: Optional gas limit override
        
    Returns:
        Transaction hash
    """
    params = {
        "asset": asset_address,
        "amount": amount,
        "on_behalf_of": vault_address,  # Supply on behalf of the vault
        "referral_code": 0
    }
    
    # Construct Aave-specific call data and approvals
    call_data = _construct_aave_call_data("aave_v3_supply", params)
    approvals = _construct_aave_approvals("aave_v3_supply", params)
    
    if chain_id not in AAVE_STRATEGY_CONTRACTS:
        raise ValueError(f"Aave strategy not supported on chain {chain_id}")
        
    target_contract = AAVE_STRATEGY_CONTRACTS[chain_id]["aave_v3_supply"]
    
    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=target_contract,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )

async def withdraw_from_aave(
    executor,  # StrategyExecutor instance
    chain_id: int,
    vault_address: str,
    asset_address: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """
    Withdraw tokens from Aave V3
    
    Args:
        executor: StrategyExecutor instance
        chain_id: The chain ID
        vault_address: Vault contract address
        asset_address: Token address to withdraw
        amount: Amount in token's smallest unit (wei), or type(uint256).max for full withdrawal
        gas_limit: Optional gas limit override
        
    Returns:
        Transaction hash
    """
    params = {
        "asset": asset_address,
        "amount": amount,
        "to": vault_address  # Withdraw to the vault
    }
    
    # Construct Aave-specific call data and approvals
    call_data = _construct_aave_call_data("aave_v3_withdraw", params)
    approvals = _construct_aave_approvals("aave_v3_withdraw", params)
    
    if chain_id not in AAVE_STRATEGY_CONTRACTS:
        raise ValueError(f"Aave strategy not supported on chain {chain_id}")
        
    target_contract = AAVE_STRATEGY_CONTRACTS[chain_id]["aave_v3_withdraw"]
    
    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=target_contract,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )

def supply_token_to_aave(
    token_symbol: str,
    amount: float,
    chain_name: str,
    vault_address: str
) -> str:
    """
    Supplies a given token to Aave V3 on a specified chain.
    This is a synchronous function for LangChain compatibility.

    Args:
        token_symbol: The symbol of the token to supply (e.g., "USDC", "WBTC").
        amount: The amount of the token to supply (human-readable format, e.g., 100.5).
        chain_name: The name of the blockchain network (e.g., "Arbitrum").
        vault_address: The address of the vault initiating the supply.

    Returns:
        A JSON string indicating the success or failure of the operation,
        including the transaction hash if successful.
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from strategies.strategies import StrategyExecutor
        
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
        
        executor = StrategyExecutor(rpc_url, PRIVATE_KEY)

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
        logger.error(f"Error in supply_token_to_aave: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

def withdraw_token_from_aave(
    token_symbol: str,
    amount: float,
    chain_name: str,
    vault_address: str
) -> str:
    """
    Withdraws a given token from Aave V3 on a specified chain.
    This is a synchronous function for LangChain compatibility.

    Args:
        token_symbol: The symbol of the token to withdraw (e.g., "USDC", "WBTC").
        amount: The amount of the token to withdraw (human-readable format, e.g., 100.5).
        chain_name: The name of the blockchain network (e.g., "Arbitrum").
        vault_address: The address of the vault initiating the withdrawal.

    Returns:
        A JSON string indicating the success or failure of the operation,
        including the transaction hash if successful.
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from strategies.strategies import StrategyExecutor
        
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
        
        executor = StrategyExecutor(rpc_url, PRIVATE_KEY)

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