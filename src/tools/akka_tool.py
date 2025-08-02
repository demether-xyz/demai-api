"""
Token swap tool implementation for swapping tokens via the vault

This module provides a unified interface for token swaps across different chains,
using the appropriate DEX aggregator for each chain:
- Core: Akka Finance
- Other chains: To be implemented

The module uses the Vault's executeStrategy function for all swaps.
"""
from typing import Optional, List, Dict, Any
from web3 import Web3
from eth_abi import encode
import asyncio
import logging
import json
import os
import httpx

logger = logging.getLogger(__name__)

# Default slippage tolerance for swaps (3%)
DEFAULT_SLIPPAGE = 0.03

# Use Akka swap API instead of quote-based approach
# If True: Uses /swap API (requires pre-approval from vault to router)
# If False: Uses /pks-quote API (no pre-approval needed, approvals handled internally)
USE_SWAP_API = False

# Default gas limit for swap operations
DEFAULT_SWAP_GAS_LIMIT = 1_500_000

# Default gas limit for approval operations
DEFAULT_APPROVAL_GAS_LIMIT = 200000

# Akka router contract addresses
AKKA_STRATEGY_CONTRACTS = {
    1116: {  # Core
        "router": "0x7C5Af181D9e9e91B15660830B52f7B7076Be0d64",
    }
}

# Vault ABI for approveToken function
VAULT_APPROVE_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "spender", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "approveToken",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Akka API endpoints
AKKA_API_BASE = "https://routerv2.akka.finance/v2"

# Akka router function signatures
AKKA_STRATEGY_FUNCTIONS = {
    "multiPathSwap": {
        "function_name": "multiPathSwap",
        "function_signature": "multiPathSwap(uint256,uint256,(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[],address,uint256,uint8,bytes32,bytes32)",
        "requires_approval": True
    }
}

async def check_token_allowance(
    executor,  # ToolExecutor instance
    token_address: str,
    owner_address: str,
    spender_address: str
) -> int:
    """
    Check the current allowance for a token
    
    Args:
        executor: ToolExecutor instance
        token_address: Token contract address
        owner_address: Address that owns the tokens
        spender_address: Address that is allowed to spend
        
    Returns:
        Current allowance amount
    """
    try:
        # Minimal ERC20 ABI for allowance
        erc20_abi = [
            {
                "inputs": [
                    {"name": "owner", "type": "address"},
                    {"name": "spender", "type": "address"}
                ],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        token_contract = executor.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=erc20_abi
        )
        
        allowance = await token_contract.functions.allowance(
            Web3.to_checksum_address(owner_address),
            Web3.to_checksum_address(spender_address)
        ).call()
        
        return allowance
        
    except Exception as e:
        logger.error(f"Error checking allowance: {e}")
        return 0

async def approve_vault_token_for_akka(
    executor,  # ToolExecutor instance
    vault_address: str,
    token_address: str,
    amount: int,
    chain_id: int
) -> str:
    """
    Approve token from vault to Akka router
    
    Args:
        executor: ToolExecutor instance
        vault_address: Vault contract address
        token_address: Token to approve
        amount: Amount to approve in smallest unit
        chain_id: Chain ID
        
    Returns:
        Transaction hash
    """
    try:
        if chain_id not in AKKA_STRATEGY_CONTRACTS:
            raise ValueError(f"Akka not supported on chain {chain_id}")
            
        akka_router = AKKA_STRATEGY_CONTRACTS[chain_id]["router"]
        
        # Get vault contract
        vault_contract = executor.w3.eth.contract(
            address=Web3.to_checksum_address(vault_address),
            abi=VAULT_APPROVE_ABI
        )
        
        # Build transaction
        nonce = await executor.w3.eth.get_transaction_count(executor.account.address)
        gas_price = await executor.w3.eth.gas_price
        
        transaction = await vault_contract.functions.approveToken(
            Web3.to_checksum_address(token_address),
            Web3.to_checksum_address(akka_router),
            amount
        ).build_transaction({
            'from': executor.account.address,
            'nonce': nonce,
            'gas': DEFAULT_APPROVAL_GAS_LIMIT,
            'gasPrice': gas_price,
        })
        
        # Sign and send transaction
        signed_txn = executor.w3.eth.account.sign_transaction(transaction, executor.account.key)
        tx_hash = await executor.w3.eth.send_raw_transaction(signed_txn.raw_transaction)
        
        logger.info(f"Approved {amount} of token {token_address} from vault {vault_address} to Akka router {akka_router}. TX: {tx_hash.hex()}")
        return tx_hash.hex()
        
    except Exception as e:
        logger.error(f"Error approving token for Akka: {e}")
        raise

async def get_akka_quote(
    chain_id: int,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = DEFAULT_SLIPPAGE
) -> Optional[Dict[str, Any]]:
    """
    Get swap quote from Akka API
    
    Args:
        chain_id: Chain ID
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        slippage: Slippage tolerance (default 5%)
        
    Returns:
        Quote data or None if error
    """
    try:
        url = f"{AKKA_API_BASE}/{chain_id}/pks-quote"
        params = {
            "src": src_token,
            "dst": dst_token,
            "amount": str(amount)
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                quote_data = response.json()
                logger.info(f"Got Akka quote: {amount} {src_token} -> {quote_data.get('outputAmount', {}).get('value', 'N/A')} {dst_token}")
                return quote_data
            else:
                logger.error(f"Failed to get Akka quote: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Error getting Akka quote: {e}")
        return None

async def get_akka_swap_transaction(
    chain_id: int,
    src_token: str,
    dst_token: str,
    amount: int,
    from_address: str,
    slippage: float = DEFAULT_SLIPPAGE
) -> Optional[Dict[str, Any]]:
    """
    Get swap transaction from Akka API
    
    Args:
        chain_id: Chain ID
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        from_address: Address that will execute the swap
        slippage: Slippage tolerance (default 5%)
        
    Returns:
        Transaction data or None if error
    """
    try:
        url = f"{AKKA_API_BASE}/{chain_id}/swap"
        params = {
            "src": src_token,
            "dst": dst_token,
            "amount": str(amount),
            "from": from_address,
            "slippage": int(slippage * 100)  # Convert to basis points
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                swap_data = response.json()
                logger.info(f"Got Akka swap transaction for {amount} {src_token} -> {dst_token}")
                return swap_data
            else:
                logger.error(f"Failed to get Akka swap transaction: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Error getting Akka swap transaction: {e}")
        return None


async def get_akka_strategy_balances(web3_instances: Dict, vault_address: str, supported_tokens: Dict) -> List[Dict[str, Any]]:
    """
    Get Akka strategy balances (placeholder - Akka is a DEX aggregator, not a lending protocol)
    
    Args:
        web3_instances: Dictionary of Web3 instances by chain_id
        vault_address: Vault contract address
        supported_tokens: Dictionary of supported tokens from config
        
    Returns:
        Empty list as Akka doesn't hold balances
    """
    # Akka is a DEX aggregator, not a lending/yield protocol
    # It doesn't hold user funds, so there are no balances to retrieve
    return []

def _construct_akka_swap_calldata(
    quote_data: Dict[str, Any],
    receiver: str
) -> bytes:
    """
    Construct calldata for Akka multiPathSwap from quote data
    
    Args:
        quote_data: Quote data from Akka pks-quote API
        receiver: Address to receive swapped tokens (vault address)
        
    Returns:
        Encoded calldata for swap
    """
    try:
        swap_data = quote_data.get("swapData", {})
        
        # Debug logging
        logger.info(f"Quote data keys: {quote_data.keys()}")
        logger.info(f"SwapData keys: {swap_data.keys() if swap_data else 'None'}")
        
        # Extract parameters from swapData
        amount_in = int(swap_data.get("amountIn", "0"))
        amount_out_min = int(swap_data.get("amountOutMin", "0"))
        paths_data = swap_data.get("data", [])
        
        # Extract signature parameters from akkaFee
        akka_fee = swap_data.get("akkaFee", {})
        fee = int(akka_fee.get("fee", "0"))
        v = int(akka_fee.get("v", "0"))
        r = akka_fee.get("r", "0x" + "0" * 64)
        s = akka_fee.get("s", "0x" + "0" * 64)
        
        # Convert paths data to proper format
        paths = []
        for path_data in paths_data:
            if len(path_data) >= 5:
                src_amount = int(path_data[0])
                dst_min_amount = int(path_data[1])
                is_from_native = int(path_data[2])
                is_to_native = int(path_data[3])
                pools_data = path_data[4]
                
                # Convert pools
                pools = []
                for pool in pools_data:
                    if len(pool) >= 9:
                        pools.append((
                            Web3.to_checksum_address(pool[0]),  # srcToken
                            Web3.to_checksum_address(pool[1]),  # dstToken
                            Web3.to_checksum_address(pool[2]),  # pairAddr
                            int(pool[3]),  # fee
                            int(pool[4]),  # srcAmount
                            int(pool[5]),  # dstMinAmount
                            int(pool[6]),  # feeSrc
                            int(pool[7]),  # feeDst
                            int(pool[8])   # liquidityType
                        ))
                
                paths.append((
                    src_amount,
                    dst_min_amount,
                    is_from_native,
                    is_to_native,
                    pools
                ))
        
        logger.info(f"Constructed {len(paths)} paths for multiPathSwap")
        logger.info(f"AmountIn: {amount_in}, AmountOutMin: {amount_out_min}")
        
        # Encode multiPathSwap function call
        function_selector = Web3.keccak(text="multiPathSwap(uint256,uint256,(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[],address,uint256,uint8,bytes32,bytes32)")[:4]
        
        # Encode parameters
        encoded_params = encode(
            ['uint256', 'uint256', '(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[]', 'address', 'uint256', 'uint8', 'bytes32', 'bytes32'],
            [
                amount_in,  # amountIn
                amount_out_min,  # amountOutMin
                paths,  # paths
                Web3.to_checksum_address(receiver),  # to
                fee,  # fee
                v,  # v
                bytes.fromhex(r[2:]) if isinstance(r, str) and r.startswith("0x") else r,  # r
                bytes.fromhex(s[2:]) if isinstance(s, str) and s.startswith("0x") else s   # s
            ]
        )
        
        return function_selector + encoded_params
            
    except Exception as e:
        logger.error(f"Error constructing Akka swap calldata: {e}")
        raise


async def execute_akka_swap(
    executor,  # ToolExecutor instance
    chain_id: int,
    vault_address: str,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = DEFAULT_SLIPPAGE,
    gas_limit: Optional[int] = None,
    use_swap_api: bool = False
) -> str:
    """
    Execute token swap via Akka
    
    Args:
        executor: ToolExecutor instance
        chain_id: Chain ID
        vault_address: Vault contract address
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        slippage: Slippage tolerance (default 5%)
        gas_limit: Optional gas limit override
        use_swap_api: If True, use swap API (requires pre-approval)
        
    Returns:
        Transaction hash
    """
    if use_swap_api:
        # Try to use the swap API (requires vault to have approved Akka router)
        swap_tx_data = await get_akka_swap_transaction(
            chain_id, src_token, dst_token, amount, vault_address, slippage
        )
        if swap_tx_data and "tx" in swap_tx_data and "data" in swap_tx_data["tx"]:
            # Extract calldata from the transaction
            calldata_hex = swap_tx_data["tx"]["data"]
            if isinstance(calldata_hex, str) and calldata_hex.startswith("0x"):
                call_data = bytes.fromhex(calldata_hex[2:])
            else:
                raise ValueError("Invalid calldata format from Akka API")
                
            # Get the router address
            if "to" in swap_tx_data["tx"]:
                target_contract = swap_tx_data["tx"]["to"]
            else:
                if chain_id not in AKKA_STRATEGY_CONTRACTS:
                    raise ValueError(f"Akka strategy not supported on chain {chain_id}")
                target_contract = AKKA_STRATEGY_CONTRACTS[chain_id]["router"]
                
            logger.info("Using Akka swap API for transaction")
        else:
            logger.warning("Swap API failed, falling back to quote-based approach")
            use_swap_api = False
    
    if not use_swap_api:
        # Fallback to quote-based approach
        quote_data = await get_akka_quote(
            chain_id, src_token, dst_token, amount, slippage
        )
        if not quote_data:
            raise ValueError("Failed to get Akka quote")
        
        # Construct calldata from quote
        call_data = _construct_akka_swap_calldata(quote_data, vault_address)
        
        # Get the router address
        if chain_id not in AKKA_STRATEGY_CONTRACTS:
            raise ValueError(f"Akka strategy not supported on chain {chain_id}")
        target_contract = AKKA_STRATEGY_CONTRACTS[chain_id]["router"]
        
        logger.info("Using quote-based approach for transaction")
    
    # Construct approvals based on source token
    approvals = [(Web3.to_checksum_address(src_token), amount)]
    
    # Use provided gas limit or default to SWAP_GAS_LIMIT
    if gas_limit is None:
        gas_limit = DEFAULT_SWAP_GAS_LIMIT
        logger.info(f"Using default gas limit: {gas_limit}")
    
    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=target_contract,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )

async def get_akka_swap_estimate(
    chain_id: int,
    src_token: str,
    dst_token: str,
    amount: int,
    slippage: float = DEFAULT_SLIPPAGE
) -> Dict[str, Any]:
    """
    Get swap estimate from Akka without executing
    
    Args:
        chain_id: Chain ID
        src_token: Source token address
        dst_token: Destination token address
        amount: Amount to swap in smallest unit
        slippage: Slippage tolerance (default 5%)
        
    Returns:
        Dictionary with swap estimate details
    """
    quote_data = await get_akka_quote(chain_id, src_token, dst_token, amount, slippage)
    
    if not quote_data:
        return {"error": "Failed to get quote from Akka"}
    
    try:
        input_amount = quote_data["inputAmount"]
        output_amount = quote_data["outputAmount"]
        
        # Calculate price impact if available
        price_impact = None
        if "priceImpact" in quote_data:
            price_impact = float(quote_data["priceImpact"])
        
        return {
            "src_token": src_token,
            "dst_token": dst_token,
            "src_amount": input_amount["value"],
            "dst_amount": output_amount["value"],
            "dst_amount_min": int(int(output_amount["value"]) * (1 - slippage)),
            "price_impact": price_impact,
            "route": quote_data.get("route", "Unknown"),
            "gas_estimate": quote_data.get("estimatedGas", 0)
        }
        
    except Exception as e:
        logger.error(f"Error parsing Akka quote: {e}")
        return {"error": str(e)}

def swap_tokens_via_akka(
    src_token_symbol: str,
    dst_token_symbol: str,
    amount: float,
    chain_name: str,
    vault_address: str,
    slippage: float = DEFAULT_SLIPPAGE
) -> str:
    """
    Swap tokens using Akka Finance on a specified chain.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        src_token_symbol: Symbol of source token (e.g., "USDC")
        dst_token_symbol: Symbol of destination token (e.g., "USDT")
        amount: Amount to swap (human-readable format)
        chain_name: Name of the blockchain network (e.g., "Arbitrum")
        vault_address: Address of the vault initiating the swap
        slippage: Slippage tolerance (default 5%)
        
    Returns:
        JSON string indicating success or failure with transaction hash
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
        
        # Get token details
        src_token_config = SUPPORTED_TOKENS.get(src_token_symbol.upper())
        dst_token_config = SUPPORTED_TOKENS.get(dst_token_symbol.upper())
        
        if not src_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported source token: {src_token_symbol}"})
        if not dst_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported destination token: {dst_token_symbol}"})
        
        src_address = src_token_config["addresses"].get(chain_id)
        dst_address = dst_token_config["addresses"].get(chain_id)
        
        if not src_address:
            return json.dumps({"status": "error", "message": f"Source token {src_token_symbol} not available on {chain_name}"})
        if not dst_address:
            return json.dumps({"status": "error", "message": f"Destination token {dst_token_symbol} not available on {chain_name}"})
        
        # Convert amount to smallest unit
        decimals = src_token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get RPC URL and initialize executor
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        executor = ToolExecutor(rpc_url, PRIVATE_KEY)
        
        # Run the async swap function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tx_hash = loop.run_until_complete(execute_akka_swap(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                src_token=src_address,
                dst_token=dst_address,
                amount=amount_wei,
                slippage=slippage
            ))
        finally:
            loop.close()
            
        if tx_hash:
            return json.dumps({
                "status": "success",
                "message": "Swap transaction sent!",
                "tx_hash": tx_hash,
                "details": {
                    "src_token": src_token_symbol,
                    "dst_token": dst_token_symbol,
                    "amount": amount,
                    "chain": chain_name
                }
            })
        else:
            return json.dumps({"status": "error", "message": "Failed to send swap transaction"})
            
    except Exception as e:
        logger.error(f"Error in swap_tokens_via_akka: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

def get_akka_swap_quote(
    src_token_symbol: str,
    dst_token_symbol: str,
    amount: float,
    chain_name: str
) -> str:
    """
    Get a swap quote from Akka Finance without executing.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        src_token_symbol: Symbol of source token (e.g., "USDC")
        dst_token_symbol: Symbol of destination token (e.g., "USDT")
        amount: Amount to swap (human-readable format)
        chain_name: Name of the blockchain network (e.g., "Arbitrum")
        
    Returns:
        JSON string with quote details
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG
        
        # Find chain_id from chain_name
        chain_id = None
        for c_id, config in CHAIN_CONFIG.items():
            if config["name"].lower() == chain_name.lower():
                chain_id = c_id
                break
                
        if chain_id is None:
            return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})
        
        # Get token details
        src_token_config = SUPPORTED_TOKENS.get(src_token_symbol.upper())
        dst_token_config = SUPPORTED_TOKENS.get(dst_token_symbol.upper())
        
        if not src_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported source token: {src_token_symbol}"})
        if not dst_token_config:
            return json.dumps({"status": "error", "message": f"Unsupported destination token: {dst_token_symbol}"})
        
        src_address = src_token_config["addresses"].get(chain_id)
        dst_address = dst_token_config["addresses"].get(chain_id)
        
        if not src_address:
            return json.dumps({"status": "error", "message": f"Source token {src_token_symbol} not available on {chain_name}"})
        if not dst_address:
            return json.dumps({"status": "error", "message": f"Destination token {dst_token_symbol} not available on {chain_name}"})
        
        # Convert amount to smallest unit
        decimals = src_token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get quote synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            estimate = loop.run_until_complete(get_akka_swap_estimate(
                chain_id=chain_id,
                src_token=src_address,
                dst_token=dst_address,
                amount=amount_wei
            ))
        finally:
            loop.close()
            
        if "error" in estimate:
            return json.dumps({"status": "error", "message": estimate["error"]})
            
        # Convert amounts back to human-readable format
        dst_decimals = dst_token_config["decimals"]
        
        return json.dumps({
            "status": "success",
            "data": {
                "src_token": src_token_symbol,
                "dst_token": dst_token_symbol,
                "src_amount": amount,
                "dst_amount": float(estimate["dst_amount"]) / (10 ** dst_decimals),
                "dst_amount_min": float(estimate["dst_amount_min"]) / (10 ** dst_decimals),
                "price_impact": estimate.get("price_impact"),
                "route": estimate.get("route"),
                "gas_estimate": estimate.get("gas_estimate"),
                "chain": chain_name
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_akka_swap_quote: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})

def approve_vault_for_akka(
    token_symbol: str,
    amount: float,
    chain_name: str,
    vault_address: str
) -> str:
    """
    Approve tokens from vault to Akka router.
    This is a synchronous function for LangChain compatibility.
    
    Args:
        token_symbol: Symbol of token to approve (e.g., "USDC")
        amount: Amount to approve (human-readable format)
        chain_name: Name of the blockchain network (e.g., "Core")
        vault_address: Address of the vault
        
    Returns:
        JSON string indicating success or failure with transaction hash
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
        
        # Get token details
        token_config = SUPPORTED_TOKENS.get(token_symbol.upper())
        if not token_config:
            return json.dumps({"status": "error", "message": f"Unsupported token: {token_symbol}"})
        
        token_address = token_config["addresses"].get(chain_id)
        if not token_address:
            return json.dumps({"status": "error", "message": f"Token {token_symbol} not available on {chain_name}"})
        
        # Convert amount to smallest unit
        decimals = token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get RPC URL and initialize executor
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})
        
        executor = ToolExecutor(rpc_url, PRIVATE_KEY)
        
        # Run the async approve function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tx_hash = loop.run_until_complete(approve_vault_token_for_akka(
                executor=executor,
                vault_address=vault_address,
                token_address=token_address,
                amount=amount_wei,
                chain_id=chain_id
            ))
        finally:
            loop.close()
            
        if tx_hash:
            return json.dumps({
                "status": "success",
                "message": "Approval transaction sent!",
                "tx_hash": tx_hash,
                "details": {
                    "token": token_symbol,
                    "amount": amount,
                    "vault": vault_address,
                    "spender": AKKA_STRATEGY_CONTRACTS[chain_id]["router"],
                    "chain": chain_name
                }
            })
        else:
            return json.dumps({"status": "error", "message": "Failed to send approval transaction"})
            
    except Exception as e:
        logger.error(f"Error in approve_vault_for_akka: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})


# ===========================================
# LLM-Friendly Interface with Subtool Pattern
# ===========================================

def create_swap_tool(
    vault_address: str,
    private_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a swap tool builder function that returns LLM-callable functions.
    
    This tool handles token swaps across different chains using the appropriate
    DEX aggregator for each chain (e.g., Akka for Core, others for different chains).
    
    Args:
        vault_address: Address of the vault to operate from
        private_key: Optional private key (defaults to PRIVATE_KEY env var)
        
    Returns:
        Dictionary containing the configured swap tool function
    """
    # Get configuration at tool creation time
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
    from tools.tool_executor import ToolExecutor
    
    # Get private key
    if not private_key:
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise ValueError("PRIVATE_KEY not provided and not found in environment")
    
    # Create the LLM-callable function with chain as a parameter
    async def swap_operation(
        chain_name: str,
        src_token: str,
        dst_token: str,
        amount: float
    ) -> str:
        """
        Execute token swap on specified chain using the appropriate DEX aggregator.
        This function will automatically handle approvals if needed.
        
        Args:
            chain_name: Name of the blockchain network (e.g., "Core", "Arbitrum")
            src_token: Source token symbol (e.g., "USDC")
            dst_token: Destination token symbol (e.g., "USDT")
            amount: Amount to swap in human-readable format (e.g., 100.5)
            
        Returns:
            JSON string with swap result including transaction hash
        """
        try:
            # Set default slippage internally
            slippage = DEFAULT_SLIPPAGE
            
            # Find chain_id from chain_name
            chain_id = None
            for c_id, config in CHAIN_CONFIG.items():
                if config["name"].lower() == chain_name.lower():
                    chain_id = c_id
                    break
            
            if chain_id is None:
                return json.dumps({
                    "status": "error",
                    "message": f"Unknown chain name: {chain_name}"
                })
            
            # Get RPC URL
            rpc_url = RPC_ENDPOINTS.get(chain_id)
            if not rpc_url:
                return json.dumps({
                    "status": "error",
                    "message": f"RPC URL not found for chain: {chain_name}"
                })
            
            # Check which DEX aggregator to use based on chain
            if chain_id == 1116:  # Core chain uses Akka
                # Continue with Akka implementation
                pass
            else:
                # Other chains not yet supported for swaps
                return json.dumps({
                    "status": "error",
                    "message": f"Token swaps not yet supported on {chain_name}. Currently only Core chain is supported."
                })
            
            # Get source token configuration
            src_token_config = SUPPORTED_TOKENS.get(src_token.upper())
            if not src_token_config:
                return json.dumps({
                    "status": "error",
                    "message": f"Unsupported token: {src_token}"
                })
            
            src_address = src_token_config["addresses"].get(chain_id)
            if not src_address:
                return json.dumps({
                    "status": "error",
                    "message": f"Token {src_token} not available on {chain_name}"
                })
            
            # Convert amount to wei
            decimals = src_token_config["decimals"]
            amount_wei = int(amount * (10 ** decimals))
            
            # Get destination token configuration
            dst_token_config = SUPPORTED_TOKENS.get(dst_token.upper())
            if not dst_token_config:
                return json.dumps({
                    "status": "error",
                    "message": f"Unsupported destination token: {dst_token}"
                })
            
            dst_address = dst_token_config["addresses"].get(chain_id)
            if not dst_address:
                return json.dumps({
                    "status": "error",
                    "message": f"Token {dst_token} not available on {chain_name}"
                })
            
            # Create executor for swap
            executor = ToolExecutor(rpc_url, private_key)
            
            # Use the configured approach (swap API or quote-based)
            use_swap_api = USE_SWAP_API
            
            # If using swap API, we need to check/ensure approval first
            if use_swap_api and chain_id in AKKA_STRATEGY_CONTRACTS:
                akka_router = AKKA_STRATEGY_CONTRACTS[chain_id]["router"]
                
                # Check current allowance
                current_allowance = await check_token_allowance(
                    executor=executor,
                    token_address=src_address,
                    owner_address=vault_address,
                    spender_address=akka_router
                )
                
                # If allowance is insufficient, approve first
                if current_allowance < amount_wei:
                    logger.info(f"Swap API requires approval. Current allowance ({current_allowance}) < amount ({amount_wei})")
                    
                    # Approve max uint256 for convenience
                    max_uint256 = 2**256 - 1
                    approval_tx = await approve_vault_token_for_akka(
                        executor=executor,
                        vault_address=vault_address,
                        token_address=src_address,
                        amount=max_uint256,
                        chain_id=chain_id
                    )
                    
                    logger.info(f"Approval transaction sent: {approval_tx}")
                    await asyncio.sleep(5)  # Wait for confirmation
            
            # Execute the swap
            logger.info(f"Executing swap: {amount} {src_token} -> {dst_token} on chain {chain_id}")
            logger.info(f"Vault: {vault_address}, Slippage: {slippage}, Use swap API: {use_swap_api}")
            
            tx_hash = await execute_akka_swap(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                src_token=src_address,
                dst_token=dst_address,
                amount=amount_wei,
                slippage=slippage,
                use_swap_api=use_swap_api,
                gas_limit=DEFAULT_SWAP_GAS_LIMIT
            )
            
            return json.dumps({
                "status": "success",
                "message": f"Successfully swapped {amount} {src_token} to {dst_token} on {chain_name}",
                "data": {
                    "src_token": src_token,
                    "dst_token": dst_token,
                    "amount": amount,
                    "chain": chain_name,
                    "vault": vault_address,
                    "tx_hash": tx_hash
                }
            })
            
        except Exception as e:
            logger.error(f"Error in swap_operation: {e}")
            return json.dumps({
                "status": "error",
                "message": f"Failed to swap: {str(e)}"
            })
    
    # Return the configured tool
    return {
        "tool": swap_operation,
        "metadata": {
            "name": "token_swap",
            "description": "Execute token swaps across different chains using the best available DEX aggregator",
            "vault": vault_address,
            "parameters": {
                "chain_name": "Blockchain network (e.g., 'Core', 'Arbitrum')",
                "src_token": "Source token symbol (e.g., USDC, USDT)",
                "dst_token": "Destination token symbol",
                "amount": "Amount to swap in human-readable format"
            }
        }
    }

# Alias for backward compatibility
create_akka_tool = create_swap_tool