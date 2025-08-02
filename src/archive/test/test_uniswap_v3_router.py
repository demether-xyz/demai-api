"""
Test file for Uniswap V3 SwapRouter02 - simpler approach to test basic swap functionality
"""
import asyncio
import os
import time
import logging
from web3 import Web3
from eth_abi import encode
from eth_abi.packed import encode_packed

from config import SUPPORTED_TOKENS

# --- Test Configuration ---
CHAIN_ID = 42161  # Arbitrum
TOKEN_IN_SYMBOL = "USDC"
TOKEN_OUT_SYMBOL = "WBTC"
SWAP_AMOUNT_HUMAN = 0.01  # 0.01 USDC - need more for WBTC swap
# --- End Configuration ---

# SwapRouter (v3) address on Arbitrum (from Uniswap docs)
SWAP_ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_web3_instance(chain_id: int):
    """Initializes a Web3 instance based on the chain ID."""
    rpc_url = ""
    if chain_id == 42161:
        rpc_url = os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc")
    elif chain_id == 1116:
        rpc_url = os.getenv("CORE_RPC_URL", "https://rpc.coredao.org")
    else:
        raise ValueError(f"Unsupported chain ID for direct test: {chain_id}")
    
    if not rpc_url:
        raise ValueError(f"RPC_URL not set for chain {chain_id}")
        
    return Web3(Web3.HTTPProvider(rpc_url))

async def main():
    """Main function to execute the V3 SwapRouter02 test."""
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        logging.error("PRIVATE_KEY environment variable not set.")
        return

    w3 = get_web3_instance(CHAIN_ID)
    account = w3.eth.account.from_key(private_key)
    eoa_address = account.address
    
    token_in_config = SUPPORTED_TOKENS[TOKEN_IN_SYMBOL]
    token_in_address = token_in_config["addresses"][CHAIN_ID]
    token_in_decimals = token_in_config["decimals"]
    token_out_address = SUPPORTED_TOKENS[TOKEN_OUT_SYMBOL]["addresses"][CHAIN_ID]

    amount_in_wei = int(SWAP_AMOUNT_HUMAN * (10**token_in_decimals))

    erc20_abi = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"}, {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"}]'
    token_in_contract = w3.eth.contract(address=Web3.to_checksum_address(token_in_address), abi=erc20_abi)

    # 1. Approve the SwapRouter to spend tokens
    logging.info(f"Checking allowance for {TOKEN_IN_SYMBOL} for SwapRouter {SWAP_ROUTER_ADDRESS}...")
    allowance = token_in_contract.functions.allowance(eoa_address, SWAP_ROUTER_ADDRESS).call()

    if allowance < amount_in_wei:
        logging.info("Allowance is insufficient, sending approve transaction...")
        approve_txn = token_in_contract.functions.approve(SWAP_ROUTER_ADDRESS, amount_in_wei).build_transaction({
            'from': eoa_address,
            'nonce': w3.eth.get_transaction_count(eoa_address),
            'gasPrice': w3.eth.gas_price,
        })
        signed_approve_txn = w3.eth.account.sign_transaction(approve_txn, private_key)
        approve_tx_hash = w3.eth.send_raw_transaction(signed_approve_txn.raw_transaction)
        logging.info(f"Approve transaction sent, waiting for receipt... Hash: {approve_tx_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(approve_tx_hash)
        logging.info("Approval confirmed.")
    else:
        logging.info("Sufficient allowance already set.")

    # 2. Prepare the swap using SwapRouter exactInputSingle
    logging.info("Constructing SwapRouter exactInputSingle call...")
    
    # exactInputSingle function signature and parameters
    # function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
    # struct ExactInputSingleParams {
    #     address tokenIn;
    #     address tokenOut;
    #     uint24 fee;
    #     address recipient;
    #     uint256 deadline;
    #     uint256 amountIn;
    #     uint256 amountOutMinimum;
    #     uint160 sqrtPriceLimitX96;
    # }
    
    deadline = int(time.time()) + 600
    
    # Build exactInputSingle calldata
    function_selector = Web3.keccak(text="exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))")[:4]
    params_encoded = encode(
        ['(address,address,uint24,address,uint256,uint256,uint256,uint160)'],
        [(
            Web3.to_checksum_address(token_in_address),  # tokenIn
            Web3.to_checksum_address(token_out_address), # tokenOut
            500,  # fee (0.05%) - USDC/WBTC typically uses 0.05% fee tier
            eoa_address,  # recipient
            deadline,  # deadline
            amount_in_wei,  # amountIn
            0,  # amountOutMinimum
            0   # sqrtPriceLimitX96 (0 = no limit)
        )]
    )
    
    swap_calldata = function_selector + params_encoded
    
    swap_txn = {
        'from': eoa_address,
        'to': Web3.to_checksum_address(SWAP_ROUTER_ADDRESS),
        'value': 0,
        'nonce': w3.eth.get_transaction_count(eoa_address),
        'gasPrice': w3.eth.gas_price,
        'data': swap_calldata,
    }
    
    # Estimate gas
    try:
        gas_estimate = w3.eth.estimate_gas(swap_txn)
        swap_txn['gas'] = int(gas_estimate * 1.1) # Add 10% buffer instead of 20%
        logging.info(f"Gas estimate: {gas_estimate}")
    except Exception as e:
        logging.error(f"Gas estimation failed: {e}. The transaction will likely fail.")
        # Use a reasonable gas limit that fits our budget
        swap_txn['gas'] = 200_000

    # 3. Sign and send the swap transaction
    logging.info(f"Sending swap transaction to SwapRouter {SWAP_ROUTER_ADDRESS}...")
    signed_swap_txn = w3.eth.account.sign_transaction(swap_txn, private_key)
    swap_tx_hash = w3.eth.send_raw_transaction(signed_swap_txn.raw_transaction)
    logging.info(f"Swap transaction sent, waiting for receipt... Hash: {swap_tx_hash.hex()}")

    try:
        receipt = w3.eth.wait_for_transaction_receipt(swap_tx_hash, timeout=120)
        if receipt['status'] == 1:
            logging.info(f"SwapRouter transaction successful! Receipt: {receipt}")
        else:
            logging.error(f"SwapRouter transaction failed! Receipt: {receipt}")
    except Exception as e:
        logging.error(f"An error occurred while waiting for the swap transaction receipt: {e}")


if __name__ == "__main__":
    asyncio.run(main()) 