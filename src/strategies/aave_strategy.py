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
    "aave_v3_supply": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",  # Aave V3 Pool on Arbitrum
    "aave_v3_withdraw": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",  # Same contract, different function
}

# Aave V3 aToken addresses for supported tokens
AAVE_ATOKENS = {
    42161: {  # Arbitrum
        "USDC": "0x724dc807b04555b71ed48a6896b6F41593b8C637",  # aArbUSDC
    }
}

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
                    
                if chain_id not in AAVE_ATOKENS:
                    logger.warning(f"Aave aTokens not configured for chain {chain_id}")
                    continue
                    
                if token_symbol not in AAVE_ATOKENS[chain_id]:
                    logger.warning(f"Aave aToken not configured for {token_symbol} on chain {chain_id}")
                    continue
                
                # Get aToken balance
                atoken_address = AAVE_ATOKENS[chain_id][token_symbol]
                balance = await _get_atoken_balance_async(
                    web3_instances[chain_id], 
                    vault_address, 
                    atoken_address, 
                    token_config["decimals"]
                )
                
                if balance > 0:
                    strategy_balances.append({
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
                    })
                    logger.info(f"Found Aave balance: {balance} {token_symbol} on chain {chain_id}")
    
    except Exception as e:
        logger.error(f"Error getting Aave strategy balances: {e}")
    
    return strategy_balances

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
    vault_address: str,
    asset_address: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """
    Supply tokens to Aave V3
    
    Args:
        executor: StrategyExecutor instance
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
    target_contract = AAVE_STRATEGY_CONTRACTS["aave_v3_supply"]
    
    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=target_contract,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )

async def withdraw_from_aave(
    executor,  # StrategyExecutor instance
    vault_address: str,
    asset_address: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """
    Withdraw tokens from Aave V3
    
    Args:
        executor: StrategyExecutor instance
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
    target_contract = AAVE_STRATEGY_CONTRACTS["aave_v3_withdraw"]
    
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