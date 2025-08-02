"""
Direct EOA test for Akka swaps - bypassing vault to isolate issues.

This test executes swaps directly from an EOA wallet to verify the Akka integration
works correctly before testing through the vault.
"""
import asyncio
import os
import logging
import json
from web3 import Web3
from eth_abi import decode
import httpx
from config import CHAIN_CONFIG, SUPPORTED_TOKENS

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Test Configuration ---
TEST_CHAIN_ID = 1116  # Core
TEST_SRC_TOKEN = "USDC"
TEST_DST_TOKEN = "USDT"
TEST_SWAP_AMOUNT = 0.001  # 0.001 USDC
TEST_SLIPPAGE = 1  # 1% slippage (as integer for API)

# Akka configuration
AKKA_API_BASE = "https://routerv2.akka.finance/v2"
AKKA_ROUTER = "0x7C5Af181D9e9e91B15660830B52f7B7076Be0d64"

# Operations to perform
CHECK_BALANCES = True
GET_QUOTE = True
CHECK_ALLOWANCE = True
APPROVE_IF_NEEDED = True
GET_SWAP_TX = True
EXECUTE_SWAP = True  # Set to True to execute actual swap

# --- End Test Configuration ---

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
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]


async def test_direct_akka_swap():
    """Test Akka swap directly from EOA wallet"""
    
    logging.info("=== Direct Akka Swap Test ===")
    
    # Setup
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable not set")
    
    rpc_url = CHAIN_CONFIG[TEST_CHAIN_ID].get("rpc_url")
    if not rpc_url:
        raise ValueError(f"RPC URL not configured for chain ID: {TEST_CHAIN_ID}")
    
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    
    logging.info(f"Using account: {account.address}")
    logging.info(f"Chain ID: {TEST_CHAIN_ID}")
    logging.info(f"RPC URL: {rpc_url}")
    
    # Get token addresses
    src_token_info = SUPPORTED_TOKENS.get(TEST_SRC_TOKEN)
    dst_token_info = SUPPORTED_TOKENS.get(TEST_DST_TOKEN)
    
    if not src_token_info or not dst_token_info:
        raise ValueError("Token not found in config")
    
    src_address = src_token_info["addresses"].get(TEST_CHAIN_ID)
    dst_address = dst_token_info["addresses"].get(TEST_CHAIN_ID)
    
    if not src_address or not dst_address:
        raise ValueError("Token not available on this chain")
    
    logging.info(f"Source token ({TEST_SRC_TOKEN}): {src_address}")
    logging.info(f"Destination token ({TEST_DST_TOKEN}): {dst_address}")
    
    # Create contract instances
    src_contract = w3.eth.contract(address=src_address, abi=ERC20_ABI)
    dst_contract = w3.eth.contract(address=dst_address, abi=ERC20_ABI)
    
    # Convert amount to wei
    src_decimals = src_token_info["decimals"]
    amount_wei = int(TEST_SWAP_AMOUNT * (10 ** src_decimals))
    
    logging.info(f"\nSwap amount: {TEST_SWAP_AMOUNT} {TEST_SRC_TOKEN} ({amount_wei} wei)")
    
    # 1. Check balances
    if CHECK_BALANCES:
        logging.info("\n--- Checking Balances ---")
        src_balance = src_contract.functions.balanceOf(account.address).call()
        dst_balance = dst_contract.functions.balanceOf(account.address).call()
        
        logging.info(f"{TEST_SRC_TOKEN} balance: {src_balance / (10**src_decimals):.6f}")
        logging.info(f"{TEST_DST_TOKEN} balance: {dst_balance / (10**dst_token_info['decimals']):.6f}")
        
        if src_balance < amount_wei:
            logging.error(f"Insufficient {TEST_SRC_TOKEN} balance!")
            return
    
    # 2. Get quote
    if GET_QUOTE:
        logging.info("\n--- Getting Quote ---")
        url = f"{AKKA_API_BASE}/{TEST_CHAIN_ID}/pks-quote"
        params = {
            "src": src_address,
            "dst": dst_address,
            "amount": str(amount_wei)
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                quote_data = response.json()
                output_amount = quote_data["outputAmount"]["value"]
                price_impact = quote_data.get("priceImpact", "N/A")
                
                logging.info(f"✅ Quote received:")
                logging.info(f"  Output: {int(output_amount) / (10**dst_token_info['decimals']):.6f} {TEST_DST_TOKEN}")
                logging.info(f"  Price impact: {price_impact}%")
                logging.info(f"  Routes: {len(quote_data.get('routes', []))}")
            else:
                logging.error(f"Failed to get quote: {response.status_code} - {response.text}")
                return
    
    # 3. Check allowance
    current_allowance = 0
    if CHECK_ALLOWANCE:
        logging.info("\n--- Checking Allowance ---")
        current_allowance = src_contract.functions.allowance(account.address, AKKA_ROUTER).call()
        logging.info(f"Current allowance to Akka router: {current_allowance / (10**src_decimals):.6f} {TEST_SRC_TOKEN}")
        
        if current_allowance < amount_wei:
            logging.warning("Insufficient allowance!")
    
    # 4. Approve if needed
    if APPROVE_IF_NEEDED and current_allowance < amount_wei:
        logging.info("\n--- Approving Token ---")
        approve_amount = amount_wei * 100  # Approve extra for future swaps
        
        approve_tx = src_contract.functions.approve(
            AKKA_ROUTER,
            approve_amount
        ).build_transaction({
            'from': account.address,
            'nonce': w3.eth.get_transaction_count(account.address),
            'gasPrice': w3.eth.gas_price,
        })
        
        # Sign and send
        signed_tx = w3.eth.account.sign_transaction(approve_tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logging.info(f"Approval tx sent: {tx_hash.hex()}")
        
        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            logging.info("✅ Approval successful!")
        else:
            logging.error("❌ Approval failed!")
            return
    
    # 5. Get swap transaction
    swap_tx_data = None
    if GET_SWAP_TX:
        logging.info("\n--- Getting Swap Transaction ---")
        url = f"{AKKA_API_BASE}/{TEST_CHAIN_ID}/swap"
        params = {
            "src": src_address,
            "dst": dst_address,
            "amount": str(amount_wei),
            "from": account.address,
            "slippage": TEST_SLIPPAGE
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                swap_data = response.json()
                swap_tx_data = swap_data.get("tx")
                
                if swap_tx_data:
                    logging.info("✅ Swap transaction data received:")
                    logging.info(f"  To: {swap_tx_data.get('to')}")
                    logging.info(f"  Value: {swap_tx_data.get('value', 0)}")
                    logging.info(f"  Data length: {len(swap_tx_data.get('data', ''))}")
                    
                    # Try to estimate gas
                    try:
                        gas_estimate = w3.eth.estimate_gas({
                            'from': account.address,
                            'to': swap_tx_data['to'],
                            'data': swap_tx_data['data'],
                            'value': int(swap_tx_data.get('value', 0))
                        })
                        logging.info(f"  Gas estimate: {gas_estimate}")
                    except Exception as e:
                        logging.error(f"  Gas estimation failed: {e}")
                else:
                    logging.error("No transaction data in response")
                    logging.error(f"Response: {json.dumps(swap_data, indent=2)}")
            else:
                logging.error(f"Failed to get swap tx: {response.status_code} - {response.text}")
                return
    
    # 6. Execute swap
    if EXECUTE_SWAP and swap_tx_data:
        logging.info("\n--- Executing Swap ---")
        
        # Build transaction
        swap_tx = {
            'from': account.address,
            'to': swap_tx_data['to'],
            'data': swap_tx_data['data'],
            'value': int(swap_tx_data.get('value', 0)),
            'nonce': w3.eth.get_transaction_count(account.address),
            'gasPrice': w3.eth.gas_price,
        }
        
        # Add gas with buffer
        try:
            gas_estimate = w3.eth.estimate_gas(swap_tx)
            swap_tx['gas'] = int(gas_estimate * 1.2)  # 20% buffer
        except Exception as e:
            logging.error(f"Gas estimation failed: {e}")
            swap_tx['gas'] = 500000  # Fallback
        
        # Sign and send
        signed_tx = w3.eth.account.sign_transaction(swap_tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        
        logging.info(f"Swap tx sent: {tx_hash.hex()}")
        
        # Wait for receipt
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            logging.info("✅ Swap successful!")
            
            # Check final balances
            new_src_balance = src_contract.functions.balanceOf(account.address).call()
            new_dst_balance = dst_contract.functions.balanceOf(account.address).call()
            
            logging.info(f"\nFinal balances:")
            logging.info(f"{TEST_SRC_TOKEN}: {new_src_balance / (10**src_decimals):.6f}")
            logging.info(f"{TEST_DST_TOKEN}: {new_dst_balance / (10**dst_token_info['decimals']):.6f}")
        else:
            logging.error("❌ Swap failed!")
            logging.error(f"Receipt: {receipt}")
    
    logging.info("\n=== Test Complete ===")


async def main():
    try:
        await test_direct_akka_swap()
    except Exception as e:
        logging.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())