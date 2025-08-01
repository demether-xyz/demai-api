#!/usr/bin/env python3
"""Test specific token balance"""

import asyncio
import sys
from pathlib import Path
from web3 import Web3

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import RPC_ENDPOINTS, ERC20_ABI

async def check_token_on_chains():
    vault_address = "0x70ed9BD034D9F797DFF34e12354330f329344BBA"
    token_address = "0x9410e8052bc661041e5cb27fdf7d9e9e842af2aa"
    
    print(f"Checking token {token_address} balance for vault {vault_address}")
    print(f"Available chains: {list(RPC_ENDPOINTS.keys())}")
    
    # Check common chains that might have this token
    common_chains = {
        1: "Ethereum",
        10: "Optimism", 
        8453: "Base",
        42161: "Arbitrum",
        137: "Polygon",
        1116: "Core",
        56: "BSC",
        43114: "Avalanche",
        250: "Fantom",
        1337: "Dev/Local",
        31337: "Hardhat",
        11155111: "Sepolia",
        84532: "Base Sepolia"
    }
    
    for chain_id, chain_name in common_chains.items():
        if chain_id in RPC_ENDPOINTS:
            rpc_url = RPC_ENDPOINTS[chain_id]
        else:
            # Try common RPC endpoints
            if chain_id == 8453:  # Base
                rpc_url = "https://mainnet.base.org"
            elif chain_id == 10:  # Optimism
                rpc_url = "https://mainnet.optimism.io"
            elif chain_id == 1:  # Ethereum
                rpc_url = "https://eth.llamarpc.com"
            else:
                continue
                
        print(f"\nChecking {chain_name} (Chain ID: {chain_id})...")
        
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            
            # Check if connected
            if not w3.is_connected():
                print(f"  Failed to connect to {chain_name}")
                continue
                
            # Create token contract
            token_contract = w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            
            # Try to get token info
            try:
                # First check if it's a contract
                code = w3.eth.get_code(Web3.to_checksum_address(token_address))
                if code == b'':
                    print(f"  No contract at this address on {chain_name}")
                    continue
                    
                symbol = token_contract.functions.symbol().call()
                decimals = token_contract.functions.decimals().call()
                balance_raw = token_contract.functions.balanceOf(vault_address).call()
                balance = balance_raw / (10 ** decimals)
                
                print(f"  Token found: {symbol}")
                print(f"  Decimals: {decimals}")
                print(f"  Balance: {balance} {symbol}")
                
                if balance > 0:
                    print(f"  ✅ NON-ZERO BALANCE FOUND on {chain_name}!")
                    
                # Also check native balance
                native_balance = w3.eth.get_balance(vault_address)
                if native_balance > 0:
                    eth_balance = native_balance / (10 ** 18)
                    print(f"  Native balance: {eth_balance} ETH")
                    
            except Exception as e:
                # Token might not exist on this chain
                print(f"  Error reading token on {chain_name}: {str(e)}")
                
        except Exception as e:
            print(f"  Error checking {chain_name}: {e}")

if __name__ == "__main__":
    asyncio.run(check_token_on_chains())