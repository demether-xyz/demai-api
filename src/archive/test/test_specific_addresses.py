#!/usr/bin/env python3
"""Test script to debug portfolio retrieval for specific addresses"""

import asyncio
import sys
from pathlib import Path
from web3 import Web3

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from services.portfolio_service import PortfolioService
from config import logger
import logging

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG)

async def test_addresses():
    # Initialize portfolio service without database (we'll test the core functionality)
    portfolio_service = PortfolioService(db_or_mongo_util=None, cache_ttl_seconds=300)
    
    # Wait for Web3 connections to be ready
    await portfolio_service.ensure_web3_connections()
    
    # Test addresses
    wallet_address = "0xE1CB8c621D554AEEDB0342361d0636064300024B"
    vault_address = "0x70ed9BD034D9F797DFF34e12354330f329344BBA"
    
    print(f"\n=== Testing Portfolio Retrieval ===")
    print(f"Wallet Address: {wallet_address}")
    print(f"Vault Address: {vault_address}")
    print(f"Connected chains: {list(portfolio_service.web3_instances.keys())}")
    
    # Test 1: Resolve vault address from wallet
    print(f"\n--- Test 1: Resolving vault address from wallet ---")
    resolved_vault = await portfolio_service._resolve_vault_address(wallet_address)
    print(f"Resolved vault address: {resolved_vault}")
    
    # Test 2: Get portfolio directly with vault address
    print(f"\n--- Test 2: Get portfolio with vault address ---")
    try:
        portfolio_vault = await portfolio_service.get_portfolio_summary(vault_address=vault_address)
        print(f"Portfolio total value: ${portfolio_vault.get('total_value_usd', 0):.2f}")
        print(f"Chains: {portfolio_vault.get('summary', {}).get('active_chains', [])}")
        print(f"Strategies: {portfolio_vault.get('summary', {}).get('active_strategies', [])}")
        print(f"Total tokens: {portfolio_vault.get('summary', {}).get('total_tokens', 0)}")
        
        # Print detailed token balances
        chains_data = portfolio_vault.get('chains', {})
        for chain_name, chain_data in chains_data.items():
            print(f"\n{chain_name}:")
            tokens = chain_data.get('tokens', {})
            for token_symbol, token_data in tokens.items():
                balance = token_data.get('balance', 0)
                value_usd = token_data.get('value_usd', 0)
                if balance > 0:
                    print(f"  {token_symbol}: {balance:.6f} (${value_usd:.2f})")
            
            strategies = chain_data.get('strategies', {})
            for strategy_name, strategy_data in strategies.items():
                print(f"  Strategy {strategy_name}:")
                strategy_tokens = strategy_data.get('tokens', {})
                for token_symbol, token_data in strategy_tokens.items():
                    balance = token_data.get('balance', 0)
                    value_usd = token_data.get('value_usd', 0)
                    if balance > 0:
                        print(f"    {token_symbol}: {balance:.6f} (${value_usd:.2f})")
    except Exception as e:
        print(f"Error getting portfolio for vault: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Get portfolio with wallet address (should resolve vault)
    print(f"\n--- Test 3: Get portfolio with wallet address ---")
    try:
        portfolio_wallet = await portfolio_service.get_portfolio_summary(wallet_address=wallet_address)
        print(f"Portfolio total value: ${portfolio_wallet.get('total_value_usd', 0):.2f}")
        print(f"Resolved vault: {portfolio_wallet.get('vault_address', 'Not found')}")
    except Exception as e:
        print(f"Error getting portfolio for wallet: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 4: Check specific chains for the vault
    print(f"\n--- Test 4: Checking balances on each chain ---")
    for chain_id, w3 in portfolio_service.web3_instances.items():
        try:
            # Check native balance
            native_balance = w3.eth.get_balance(vault_address)
            eth_balance = float(native_balance) / (10 ** 18)
            print(f"Chain {chain_id}: {eth_balance:.6f} ETH")
        except Exception as e:
            print(f"Error checking chain {chain_id}: {e}")
    
    # Test 5: Check if Base chain is configured
    print(f"\n--- Test 5: Checking supported chains ---")
    from config import RPC_ENDPOINTS, CHAIN_CONFIG
    print(f"Configured chains: {list(RPC_ENDPOINTS.keys())}")
    print(f"Chain names: {[(k, v.get('name')) for k, v in CHAIN_CONFIG.items()]}")
    
    # Test 6: Direct token balance check on Base if available
    print(f"\n--- Test 6: Manual balance check on chains ---")
    # Check if we need to add Base chain support
    base_chain_id = 8453
    if base_chain_id not in portfolio_service.web3_instances:
        print(f"Base chain ({base_chain_id}) not configured in the system")

if __name__ == "__main__":
    asyncio.run(test_addresses())