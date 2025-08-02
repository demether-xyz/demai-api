"""
Test file for executing a direct swap with Akka from an EOA.
"""
import asyncio
import logging
import httpx
import time
import os
from web3 import Web3
from eth_abi import encode
from config import CHAIN_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s | %(message)s')

# --- Configuration ---
CHAIN_ID = 1116  # Core Testnet
USDC_ADDRESS = "0xa4151B2B3e269645181dCcF2D426cE75fcbDeca9"
USDT_ADDRESS = "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1" # USDT on Core
SOLVBTC_ADDRESS = "0x9410e8052Bc661041e5cB27fDf7d9e9e842af2aa"
SWAP_AMOUNT_USDC = 0.01  # 0.01 USDC

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

async def main():
    # --- Setup Web3 ---
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        raise ValueError("PRIVATE_KEY environment variable not set.")
    
    rpc_url = CHAIN_CONFIG[CHAIN_ID].get("rpc_url")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    
    logging.info("✅ Successfully loaded secrets from environment variables")
    logging.info(f"--- Starting Direct Akka Swap Test on Chain ID: {CHAIN_ID} ---")
    logging.info(f"Using account: {account.address}")
    
    # --- Setup Contracts ---
    usdc_contract = w3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
    solvbtc_contract = w3.eth.contract(address=SOLVBTC_ADDRESS, abi=ERC20_ABI)
    
    amount_in_wei = int(SWAP_AMOUNT_USDC * (10**6)) # USDC has 6 decimals

    # --- Step 1: Get Akka Router Address ---
    logging.info("Getting Akka router address...")
    async with httpx.AsyncClient() as client:
        spender_response = await client.get(f"https://routerv2.akka.finance/v2/{CHAIN_ID}/approve/spender")
        spender_response.raise_for_status()
        spender_data = spender_response.json()
        akka_router_address = Web3.to_checksum_address(spender_data['address'])
        logging.info(f"Akka router address: {akka_router_address}")

    # --- Step 2: Check Current Allowance ---
    logging.info("Checking current allowance...")
    async with httpx.AsyncClient() as client:
        allowance_response = await client.get(f"https://routerv2.akka.finance/v2/{CHAIN_ID}/approve/allowance", params={
            "tokenAddress": USDC_ADDRESS,
            "walletAddress": account.address
        })
        allowance_response.raise_for_status()
        allowance_data = allowance_response.json()
        current_allowance = int(allowance_data['allowance'])
        logging.info(f"Current allowance: {current_allowance}")

    # --- Step 3: Approve if Needed ---
    if current_allowance < amount_in_wei:
        logging.info("Insufficient allowance, requesting approval transaction...")
        async with httpx.AsyncClient() as client:
            approve_response = await client.get(f"https://routerv2.akka.finance/v2/{CHAIN_ID}/approve/transaction", params={
                "tokenAddress": USDC_ADDRESS,
                "amount": str(amount_in_wei * 100)  # Approve more for future transactions
            })
            approve_response.raise_for_status()
            approve_data = approve_response.json()
            
            # Execute approval transaction
            approve_tx = approve_data['tx']
            approve_tx['from'] = account.address
            approve_tx['nonce'] = w3.eth.get_transaction_count(account.address)
            approve_tx['gasPrice'] = w3.eth.gas_price
            
            signed_approve_tx = w3.eth.account.sign_transaction(approve_tx, private_key)
            approve_tx_hash = w3.eth.send_raw_transaction(signed_approve_tx.raw_transaction)
            
            logging.info(f"Approval transaction sent: {approve_tx_hash.hex()}")
            
            # Wait for confirmation
            receipt = w3.eth.wait_for_transaction_receipt(approve_tx_hash)
            logging.info(f"✅ Approval confirmed in block: {receipt.blockNumber}")
    else:
        logging.info("✅ Sufficient allowance already exists")

    # --- Step 4: Get Swap Transaction from Akka API ---
    logging.info("Fetching swap transaction from Akka /swap endpoint...")
    swap_url = f"https://routerv2.akka.finance/v2/{CHAIN_ID}/swap"
    swap_params = {
        "src": USDC_ADDRESS,
        "dst": USDT_ADDRESS,
        "amount": str(amount_in_wei),
        "from": account.address,
        "slippage": 50, # 0.5%, sent as a number
    }

    calldata = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(swap_url, params=swap_params)

            if response.status_code != 200:
                logging.error(f"❌ Akka /swap API returned status {response.status_code}")
                logging.error(f"Response: {response.text}")
                logging.error("Unable to fetch swap transaction. The issue is likely with the Akka API.")
                return

            swap_response = response.json()
            logging.info(f"Received swap response: {swap_response}")

            if 'tx' not in swap_response:
                logging.error(f"❌ No 'tx' object in Akka response: {swap_response}")
                return

            # Extract the calldata from the response
            calldata = swap_response['tx']['data']
            akka_router_address = Web3.to_checksum_address(swap_response['tx']['to'])

            logging.info(f"✅ Successfully received transaction data from Akka API!")
            logging.info(f"Router: {akka_router_address}")
            logging.info(f"Calldata: {calldata}")

    except httpx.RequestError as e:
        logging.error(f"❌ HTTP request to Akka API failed: {e}")
        return
        
    # --- Test Gas Estimation ---
    if not calldata:
        logging.error("❌ No calldata received from Akka API, cannot proceed.")
        return

    try:
        # Create transaction dict for gas estimation
        transaction = {
            'from': account.address,
            'to': akka_router_address,
            'data': calldata,
            'value': 0
        }
        
        logging.info(f"Testing gas estimation with router: {akka_router_address}")
        
        # Estimate gas
        gas_estimate = w3.eth.estimate_gas(transaction)
        logging.info(f"✅ Gas estimation successful: {gas_estimate}")
        
    except Exception as e:
        logging.error(f"❌ Gas estimation failed even with data from /swap endpoint: {e}")
        logging.info("This indicates a potential issue with the Core testnet or the Akka router contract.")
        return

    logging.info("✅ Akka swap test completed successfully!")
    logging.info(f"Final calldata: {calldata}")
    
    # --- Save calldata to file for use with Solidity script ---
    try:
        calldata_file = "akka_swap_calldata.txt"
        with open(calldata_file, 'w') as f:
            f.write(calldata)
        logging.info(f"✅ Calldata saved to {calldata_file}")
    except Exception as e:
        logging.error(f"Error saving calldata: {e}")

if __name__ == "__main__":
    asyncio.run(main())
