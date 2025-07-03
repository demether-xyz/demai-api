"""
Uniswap Universal Router strategy implementation for executing swaps.
Ref: https://docs.uniswap.org/contracts/universal-router/technical-reference
"""
from typing import Optional, List, Dict, Any
from web3 import Web3
from eth_abi import encode
from eth_abi.packed import encode_packed
import asyncio
import logging
import json
import os
import time

logger = logging.getLogger(__name__)

# Uniswap Universal Router addresses
UNISWAP_UNIVERSAL_ROUTER_CONTRACTS = {
    42161: {  # Arbitrum
        "universal_router": "0xA51afAFe0263b40EdaEf0Df8781eA9aa03E381a3",
    },
    1116: { # Core
        # NOTE: This address is from a third-party deployment (Archer), not an official Uniswap deployment.
        "universal_router": "0x3429CF954b5A6993512e113614399b1A89269435",
    }
}

# Uniswap Universal Router commands
# See: https://docs.uniswap.org/contracts/universal-router/technical-reference
UNISWAP_COMMANDS = {
    "V3_SWAP_EXACT_IN": b'\x00',
    "V2_SWAP_EXACT_IN": b'\x08',
    "WRAP_ETH": b'\x0b',
    "UNWRAP_WETH": b'\x0c',
    "SWEEP": b'\x04',
}

def _construct_v3_path(token_in: str, token_out: str, fee: int) -> bytes:
    """Constructs the path for a V3 single-hop swap."""
    return encode_packed(
        ['address', 'uint24', 'address'],
        [Web3.to_checksum_address(token_in), fee, Web3.to_checksum_address(token_out)]
    )

def _construct_universal_router_calldata(commands: bytes, inputs: List[bytes], deadline: int) -> bytes:
    """Constructs the calldata for the Universal Router's execute function."""
    # function execute(bytes calldata commands, bytes[] calldata inputs, uint256 deadline)
    function_selector = Web3.keccak(text="execute(bytes,bytes[],uint256)")[:4]

    encoded_params = encode(
        ['bytes', 'bytes[]', 'uint256'],
        [commands, inputs, deadline]
    )
    return function_selector + encoded_params

def _construct_uniswap_approvals(params: Dict[str, Any]) -> List[tuple]:
    """Construct token approvals needed for Uniswap strategies"""
    # For V3_SWAP_EXACT_IN, we need to approve the input token to the Uniswap router
    return [(
        Web3.to_checksum_address(params["token_in"]),
        params["amount_in"]
    )]

async def execute_uniswap_swap(
    executor,  # StrategyExecutor instance
    chain_id: int,
    vault_address: str,
    token_in_address: str,
    token_out_address: str,
    amount_in: int,
    fee: int = 3000, # Default fee tier 0.3%
    amount_out_minimum: int = 0, # Allow any amount out by default for simplicity
    gas_limit: Optional[int] = None
) -> str:
    """
    Execute a swap on Uniswap V3 via the Universal Router.
    
    Args:
        executor: StrategyExecutor instance
        chain_id: The chain ID
        vault_address: Vault contract address
        token_in_address: Token address to swap from
        token_out_address: Token address to swap to
        amount_in: Amount in token's smallest unit (wei)
        fee: The fee tier of the pool
        amount_out_minimum: The minimum amount of output tokens that must be received
        gas_limit: Optional gas limit override
        
    Returns:
        Transaction hash
    """
    if chain_id not in UNISWAP_UNIVERSAL_ROUTER_CONTRACTS:
        raise ValueError(f"Uniswap Universal Router not supported on chain {chain_id}")

    router_address = UNISWAP_UNIVERSAL_ROUTER_CONTRACTS[chain_id]["universal_router"]

    # 1. Prepare commands and inputs for Universal Router
    path = _construct_v3_path(token_in_address, token_out_address, fee)
    commands = UNISWAP_COMMANDS["V3_SWAP_EXACT_IN"]
    
    # Input for V3_SWAP_EXACT_IN command: (address recipient, uint256 amountIn, uint256 amountOutMin, bytes path, bool payerIsUser)
    # payerIsUser is True because the Vault (`msg.sender` to the router) will pay for the swap.
    v3_swap_input = (
        vault_address,          # recipient
        amount_in,              # amountIn
        amount_out_minimum,     # amountOutMin
        path,                   # path
        True,                   # payerIsUser (the vault contract is the payer)
    )
    
    inputs = [
        encode(
            ['(address,uint256,uint256,bytes,bool)'],
            [v3_swap_input]
        )
    ]
    
    deadline = int(time.time()) + 600 # 10 minutes

    # 2. Construct the final calldata for the Vault's executeStrategy function.
    # This calldata is the encoded call to the Universal Router's execute function.
    router_calldata = _construct_universal_router_calldata(commands, inputs, deadline)

    # 3. Approvals for the Universal Router to spend the input token from the vault.
    approval_params = {"token_in": token_in_address, "amount_in": amount_in}
    approvals = _construct_uniswap_approvals(approval_params)

    # 4. Execute the strategy via the vault
    return await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=router_address,
        call_data=router_calldata,
        approvals=approvals,
        gas_limit=gas_limit
    )

def swap_tokens_on_uniswap(
    token_in_symbol: str,
    token_out_symbol: str,
    amount: float,
    chain_id: int,
    vault_address: str
) -> str:
    """
    Swaps a given token for another on Uniswap V3 via the Universal Router.
    This is a synchronous function for LangChain compatibility.

    Args:
        token_in_symbol: The symbol of the token to swap from (e.g., "USDC").
        token_out_symbol: The symbol of the token to swap to (e.g., "WBTC").
        amount: The amount of the input token to swap (human-readable format).
        chain_id: The ID of the blockchain network (e.g., 42161 for Arbitrum).
        vault_address: The address of the vault initiating the swap.

    Returns:
        A JSON string indicating the success or failure of the operation,
        including the transaction hash if successful.
    """
    try:
        # Import here to avoid circular imports
        from config import SUPPORTED_TOKENS, RPC_ENDPOINTS
        from strategies.strategies import StrategyExecutor

        # Get private key from environment variable
        PRIVATE_KEY = os.getenv("PRIVATE_KEY")
        if not PRIVATE_KEY:
            return json.dumps({"status": "error", "message": "PRIVATE_KEY environment variable not set"})

        if chain_id not in UNISWAP_UNIVERSAL_ROUTER_CONTRACTS:
            return json.dumps({"status": "error", "message": f"Chain ID {chain_id} not supported for Uniswap swaps"})

        # Get token details for token_in
        token_in_config = SUPPORTED_TOKENS.get(token_in_symbol.upper())
        if not token_in_config:
            return json.dumps({"status": "error", "message": f"Unsupported input token symbol: {token_in_symbol}"})

        token_in_address = token_in_config["addresses"].get(chain_id)
        if not token_in_address:
            return json.dumps({"status": "error", "message": f"Token {token_in_symbol} not available on chain {chain_id}"})

        token_in_decimals = token_in_config["decimals"]
        amount_in_wei = int(amount * (10 ** token_in_decimals))

        # Get token details for token_out
        token_out_config = SUPPORTED_TOKENS.get(token_out_symbol.upper())
        if not token_out_config:
            return json.dumps({"status": "error", "message": f"Unsupported output token symbol: {token_out_symbol}"})

        token_out_address = token_out_config["addresses"].get(chain_id)
        if not token_out_address:
            return json.dumps({"status": "error", "message": f"Token {token_out_symbol} not available on chain {chain_id}"})

        # Get RPC URL and initialize executor
        rpc_url = RPC_ENDPOINTS.get(chain_id)
        if not rpc_url:
            return json.dumps({"status": "error", "message": f"RPC URL not found for chain ID: {chain_id}"})

        executor = StrategyExecutor(rpc_url, PRIVATE_KEY)

        # Run the async execute_uniswap_swap function synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tx_hash = loop.run_until_complete(execute_uniswap_swap(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                token_in_address=token_in_address,
                token_out_address=token_out_address,
                amount_in=amount_in_wei
            ))
        finally:
            loop.close()

        if tx_hash:
            return json.dumps({"status": "success", "message": "Swap transaction sent!", "tx_hash": tx_hash})
        else:
            return json.dumps({"status": "error", "message": "Failed to send swap transaction."})

    except Exception as e:
        logger.error(f"Error in swap_tokens_on_uniswap: {e}")
        return json.dumps({"status": "error", "message": f"An unexpected error occurred: {str(e)}"})
