#!/usr/bin/env python3
"""Test ERC20 token on Core chain"""

import sys
from pathlib import Path
from web3 import Web3

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import RPC_ENDPOINTS

# Full ERC20 ABI
ERC20_ABI = [
    {
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "transferFrom",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

def test_erc20_token():
    vault_address = "0x70ed9BD034D9F797DFF34e12354330f329344BBA"
    token_address = "0x9410e8052bc661041e5cb27fdf7d9e9e842af2aa"
    
    print(f"Testing ERC20 token on Core Chain")
    print(f"Vault: {vault_address}")
    print(f"Token: {token_address}")
    
    # Get Core RPC
    core_rpc = RPC_ENDPOINTS.get(1116)
    w3 = Web3(Web3.HTTPProvider(core_rpc))
    
    if not w3.is_connected():
        print("Failed to connect to Core")
        return
        
    print("Connected to Core chain")
    
    # Make sure addresses are checksummed
    vault_address = Web3.to_checksum_address(vault_address)
    token_address = Web3.to_checksum_address(token_address)
    
    # Check if contract exists
    code = w3.eth.get_code(token_address)
    print(f"\nContract exists: {len(code) > 0} (code length: {len(code)} bytes)")
    
    if len(code) == 0:
        print("No contract at this address!")
        return
        
    # Create token contract with full ABI
    token_contract = w3.eth.contract(
        address=token_address,
        abi=ERC20_ABI
    )
    
    print("\nTrying to read ERC20 functions:")
    
    # Try each function separately to see which ones work
    try:
        name = token_contract.functions.name().call()
        print(f"  name(): {name}")
    except Exception as e:
        print(f"  name() failed: {e}")
        
    try:
        symbol = token_contract.functions.symbol().call()
        print(f"  symbol(): {symbol}")
    except Exception as e:
        print(f"  symbol() failed: {e}")
        
    try:
        decimals = token_contract.functions.decimals().call()
        print(f"  decimals(): {decimals}")
    except Exception as e:
        print(f"  decimals() failed: {e}")
        
    try:
        total_supply = token_contract.functions.totalSupply().call()
        print(f"  totalSupply(): {total_supply}")
    except Exception as e:
        print(f"  totalSupply() failed: {e}")
        
    try:
        balance = token_contract.functions.balanceOf(vault_address).call()
        print(f"  balanceOf(vault): {balance}")
        
        if balance > 0:
            print(f"\n✅ VAULT HAS NON-ZERO BALANCE: {balance}")
            # Try to convert to human readable if we got decimals
            try:
                decimals = token_contract.functions.decimals().call()
                human_balance = balance / (10 ** decimals)
                print(f"  Human readable: {human_balance}")
            except:
                pass
                
    except Exception as e:
        print(f"  balanceOf() failed: {e}")

if __name__ == "__main__":
    test_erc20_token()