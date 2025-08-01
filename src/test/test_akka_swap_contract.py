"""
Test file for AkkaSwapExecutor contract using PKS quote data.
"""
import asyncio
import logging
import httpx
import os
from web3 import Web3
from eth_abi import encode
from config import CHAIN_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s | %(message)s')

# --- Configuration ---
CHAIN_ID = 1116  # Core Testnet
USDC_ADDRESS = "0xa4151B2B3e269645181dCcF2D426cE75fcbDeca9"
USDT_ADDRESS = "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1"
SWAP_AMOUNT_USDC = 0.01  # 0.01 USDC

# AkkaSwapExecutor contract ABI (subset needed for testing)
AKKA_SWAP_EXECUTOR_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "bytes", "name": "swapData", "type": "bytes"},
                    {"internalType": "uint256", "name": "value", "type": "uint256"}
                ],
                "internalType": "struct AkkaSwapExecutor.SwapParams",
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "executeSwap",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"}
        ],
        "name": "checkAllowance",
        "outputs": [
            {"internalType": "bool", "name": "sufficient", "type": "bool"},
            {"internalType": "uint256", "name": "currentAllowance", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "user", "type": "address"}
        ],
        "name": "getUserBalance",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getAkkaRouter",
        "outputs": [
            {"internalType": "address", "name": "", "type": "address"}
        ],
        "stateMutability": "pure",
        "type": "function"
    }
]

# ERC20 ABI (minimal)
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]

async def get_pks_quote(src, dst, amount):
    """Get PKS quote from AKKA"""
    pks_quote_url = f"https://routerv2.akka.finance/v2/{CHAIN_ID}/pks-quote"
    params = {
        "src": src,
        "dst": dst,
        "amount": str(amount),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(pks_quote_url, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"PKS Quote failed: {response.status_code} - {response.text}")
                return None
    except Exception as e:
        logging.error(f"Error getting PKS quote: {e}")
        return None

def parse_swap_data(quote_data):
    """Parse PKS quote data into format needed for contract"""
    try:
        swap_data = quote_data['swapData']
        input_amount = quote_data['inputAmount']
        output_amount = quote_data['outputAmount']
        
        # Extract the raw transaction data from swapData
        raw_data = swap_data.get('data', [])
        bridge_data = swap_data.get('bridge', [])
        dst_data = swap_data.get('dstData', [])
        
        # For now, we'll use the encoded data as bytes
        # In a real implementation, you'd need to properly encode this based on AKKA's expected format
        encoded_data = encode(['bytes'], [bytes(str(raw_data), 'utf-8')])
        
        return {
            'tokenIn': input_amount['currency']['address'],
            'tokenOut': output_amount['currency']['address'],
            'amountIn': int(input_amount['value']),
            'amountOutMin': int(output_amount['value']) * 95 // 100,  # 5% slippage
            'swapData': encoded_data,
            'value': int(swap_data.get('value', 0))
        }
    except Exception as e:
        logging.error(f"Error parsing swap data: {e}")
        return None

async def test_akka_swap_contract():
    """Test the AkkaSwapExecutor contract"""
    
    # You'll need to deploy the contract first and put the address here
    AKKA_SWAP_EXECUTOR_ADDRESS = "0x..." # Replace with deployed contract address
    
    if AKKA_SWAP_EXECUTOR_ADDRESS == "0x...":
        logging.error("❌ Please deploy the AkkaSwapExecutor contract and update the address!")
        return
    
    # Setup Web3
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable not set.")
    
    rpc_url = CHAIN_CONFIG[CHAIN_ID].get("rpc_url")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    
    logging.info(f"--- Testing AkkaSwapExecutor Contract ---")
    logging.info(f"Account: {account.address}")
    logging.info(f"Contract: {AKKA_SWAP_EXECUTOR_ADDRESS}")
    
    # Setup contracts
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
    akka_executor = w3.eth.contract(address=AKKA_SWAP_EXECUTOR_ADDRESS, abi=AKKA_SWAP_EXECUTOR_ABI)
    
    amount_in_wei = int(SWAP_AMOUNT_USDC * (10**6))
    
    # Step 1: Get PKS quote
    logging.info("Getting PKS quote...")
    quote_data = await get_pks_quote(USDC_ADDRESS, USDT_ADDRESS, amount_in_wei)
    
    if not quote_data:
        logging.error("❌ Failed to get PKS quote")
        return
    
    logging.info(f"✅ Got PKS quote: {quote_data['inputAmount']['value']} USDC -> {quote_data['outputAmount']['value']} USDT")
    
    # Step 2: Parse swap data
    swap_params = parse_swap_data(quote_data)
    if not swap_params:
        logging.error("❌ Failed to parse swap data")
        return
    
    logging.info(f"Parsed swap params: {swap_params}")
    
    # Step 3: Check current allowance
    current_allowance = usdc_contract.functions.allowance(account.address, AKKA_SWAP_EXECUTOR_ADDRESS).call()
    logging.info(f"Current allowance: {current_allowance}")
    
    # Step 4: Approve if needed
    if current_allowance < amount_in_wei:
        logging.info("Approving USDC for contract...")
        approve_tx = usdc_contract.functions.approve(
            AKKA_SWAP_EXECUTOR_ADDRESS, 
            amount_in_wei * 2  # Approve extra for future swaps
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gasPrice': w3.eth.gas_price,
        })
        
        signed_tx = w3.eth.account.sign_transaction(approve_tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logging.info(f"Approval tx: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        logging.info(f"✅ Approval confirmed in block: {receipt.blockNumber}")
    
    # Step 5: Execute swap through contract
    logging.info("Executing swap through AkkaSwapExecutor...")
    
    try:
        # Estimate gas first
        gas_estimate = akka_executor.functions.executeSwap(swap_params).estimate_gas({
            'from': account.address,
            'value': swap_params['value']
        })
        
        logging.info(f"Gas estimate: {gas_estimate}")
        
        # Build transaction
        swap_tx = akka_executor.functions.executeSwap(swap_params).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gasPrice': w3.eth.gas_price,
            'gas': gas_estimate + 50000,  # Add buffer
            'value': swap_params['value']
        })
        
        signed_swap_tx = w3.eth.account.sign_transaction(swap_tx, private_key)
        swap_tx_hash = w3.eth.send_raw_transaction(signed_swap_tx.raw_transaction)
        
        logging.info(f"Swap tx: {swap_tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(swap_tx_hash)
        
        if receipt.status == 1:
            logging.info(f"✅ Swap successful in block: {receipt.blockNumber}")
            logging.info(f"Gas used: {receipt.gasUsed}")
        else:
            logging.error(f"❌ Swap failed")
            
    except Exception as e:
        logging.error(f"❌ Swap execution failed: {e}")

async def main():
    await test_akka_swap_contract()

if __name__ == "__main__":
    asyncio.run(main()) 