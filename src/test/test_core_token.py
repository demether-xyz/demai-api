#!/usr/bin/env python3
"""Test specific token on Core chain"""

import sys
from pathlib import Path
from web3 import Web3

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config import RPC_ENDPOINTS, ERC20_ABI

def test_core_token():
    vault_address = "0x70ed9BD034D9F797DFF34e12354330f329344BBA"
    token_address = "0x9410e8052bc661041e5cb27fdf7d9e9e842af2aa"
    
    print(f"Testing on Core Chain (1116)")
    print(f"Vault: {vault_address}")
    print(f"Token: {token_address}")
    
    # Get Core RPC
    core_rpc = RPC_ENDPOINTS.get(1116)
    print(f"Core RPC: {core_rpc}")
    
    w3 = Web3(Web3.HTTPProvider(core_rpc))
    
    if not w3.is_connected():
        print("Failed to connect to Core")
        return
        
    print("Connected to Core chain")
    
    # Check if token exists
    code = w3.eth.get_code(Web3.to_checksum_address(token_address))
    print(f"Contract code length: {len(code)} bytes")
    
    if code == b'':
        print("No contract at this address!")
        return
        
    # Create token contract
    token_contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI
    )
    
    # This might not be an ERC20 token, let's check what it is
    print("\nChecking contract type...")
    
    # Try minimal proxy pattern check
    if len(code) < 500:
        print("Small contract - might be a proxy")
        
    # Let's check if this is the vault itself
    if token_address.lower() == vault_address.lower():
        print("This address IS the vault address!")
        
    # Check transaction count to see activity
    tx_count = w3.eth.get_transaction_count(Web3.to_checksum_address(token_address))
    print(f"Transaction count from this address: {tx_count}")
    
    # Let's also check if this might be a wrapped/deposited token balance
    # by looking at popular tokens on Core
    print("\nChecking standard Core tokens in the vault...")
    
    from config import SUPPORTED_TOKENS
    
    for token_name, token_config in SUPPORTED_TOKENS.items():
        if 1116 in token_config["addresses"]:
            token_addr = token_config["addresses"][1116]
            try:
                token_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_addr),
                    abi=ERC20_ABI
                )
                balance_raw = token_contract.functions.balanceOf(vault_address).call()
                if balance_raw > 0:
                    decimals = token_config["decimals"]
                    balance = balance_raw / (10 ** decimals)
                    print(f"  {token_name}: {balance} (non-zero!)")
            except Exception as e:
                print(f"  Error checking {token_name}: {e}")
        
    # Check native Core balance too
    native_balance = w3.eth.get_balance(vault_address)
    print(f"\nNative CORE balance: {native_balance / (10**18)} CORE")

if __name__ == "__main__":
    test_core_token()