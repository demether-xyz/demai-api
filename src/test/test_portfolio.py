#!/usr/bin/env python3

import os
import asyncio
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Vault address to check - modify this to test different addresses
VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

# Test configuration
TEST_BATCH_PERFORMANCE = True  # Set to True to compare performance

async def check_portfolio():
    """Check portfolio for the specified vault address"""
    try:
        from services.portfolio_service import PortfolioService
        from utils.mongo_connection import mongo_connection
        
        print(f"🔍 Checking portfolio for vault: {VAULT_ADDRESS}")
        
        # Initialize MongoDB connection
        db = await mongo_connection.connect()
        
        # Initialize portfolio service
        portfolio_service = PortfolioService(db)
        
        # Clear any existing cache to ensure fair comparison
        await portfolio_service.clear_portfolio_cache(VAULT_ADDRESS)
        
        # First call - no cache (cold start)
        print("\n📊 First call (no cache - cold start)...")
        start_time = time.time()
        result = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS)
        first_call_time = time.time() - start_time
        print(f"⏱️  First call time: {first_call_time:.2f} seconds")
        
        # Second call - should use cache (warm start)
        print("\n📊 Second call (using cache - warm start)...")
        start_time = time.time()
        result_cached = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS)
        second_call_time = time.time() - start_time
        print(f"⏱️  Second call time: {second_call_time:.2f} seconds")
        
        # Calculate speedup
        if second_call_time > 0:
            speedup = first_call_time / second_call_time
            print(f"\n🚀 Speedup: {speedup:.1f}x faster with cache!")
            print(f"⚡ Time saved: {first_call_time - second_call_time:.2f} seconds")
        
        # Verify results are the same
        if result['total_value_usd'] == result_cached['total_value_usd']:
            print("✅ Cache validation: Results match perfectly!")
        else:
            print("⚠️  Warning: Cached results differ from original")
        
        # Third call - with refresh=True to bypass cache
        print("\n📊 Third call (with refresh=True - bypass cache)...")
        start_time = time.time()
        result_refreshed = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS, refresh=True)
        third_call_time = time.time() - start_time
        print(f"⏱️  Third call time (bypassing cache): {third_call_time:.2f} seconds")
        print(f"📊 This call fetched fresh data despite cache being available")
        
        # Show cache statistics
        cache_stats = await portfolio_service.get_cache_stats()
        print(f"\n📈 Cache Statistics:")
        print(f"  • Memory cache entries: {cache_stats['memory_cache_entries']}")
        print(f"  • Database cache entries: {cache_stats['database_cache_entries']}")
        print(f"  • Cache TTL: {cache_stats['cache_ttl_seconds']} seconds")
        
        # Close MongoDB connection
        await mongo_connection.disconnect()
        
        print(f"✅ Portfolio summary completed!")
        print(f"📊 Total value: ${result['total_value_usd']:.6f}")
        
        # Import token config to show comprehensive breakdown
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG
        
        summary = result.get('summary', {})
        chains = result.get('chains', {})
        assets = result.get('assets', {})
        holdings = result.get('holdings', [])
        
        print(f"🏦 Chains: {len(summary.get('active_chains', []))}")
        print(f"🪙 Tokens: {summary.get('total_tokens', 0)}")
        print(f"⚡ Active assets: {len(summary.get('active_assets', []))}")
        
        if summary.get('active_assets'):
            print(f"🔗 Assets: {', '.join(summary['active_assets'])}")
        
        # Create a comprehensive view of all supported tokens by chain
        print("\n🌐 Chains & All Supported Tokens:")
        
        # Build balance lookup from holdings
        balance_lookup = {}
        for holding in holdings:
            chain_id = holding.get('chain_id')
            symbol = holding.get('symbol')
            if chain_id not in balance_lookup:
                balance_lookup[chain_id] = {}
            balance_lookup[chain_id][symbol] = {
                'balance': holding.get('balance', 0),
                'value_usd': holding.get('value_usd', 0)
            }
        
        # Show all chains and their supported tokens
        for chain_id, chain_config in CHAIN_CONFIG.items():
            chain_name = chain_config['name']
            chain_total = 0
            
            # Calculate chain total
            if chain_name in chains:
                chain_total = chains[chain_name].get('total_value_usd', 0)
            
            print(f"\n  • {chain_name} (Chain {chain_id}): ${chain_total:.6f}")
            
            # Show native currency
            native_currency = chain_config.get('native_currency', {})
            if native_currency:
                native_symbol = native_currency['symbol']
                native_balance = balance_lookup.get(chain_id, {}).get(native_symbol, {})
                print(f"    💰 {native_symbol} (Native): {native_balance.get('balance', 0):.6f} (${native_balance.get('value_usd', 0):.6f})")
            
            # Show all supported ERC20 tokens for this chain
            erc20_tokens = []
            btc_tokens = []
            stable_tokens = []
            
            for token_symbol, token_config in SUPPORTED_TOKENS.items():
                if chain_id in token_config.get('addresses', {}):
                    token_balance = balance_lookup.get(chain_id, {}).get(token_symbol, {})
                    balance = token_balance.get('balance', 0)
                    value_usd = token_balance.get('value_usd', 0)
                    
                    # Categorize tokens
                    if token_symbol in ['SOLVBTC', 'BTCB', 'WBTC']:
                        btc_tokens.append(f"{token_symbol}: {balance:.6f} (${value_usd:.6f})")
                    elif token_symbol in ['USDC', 'USDT']:
                        stable_tokens.append(f"{token_symbol}: {balance:.6f} (${value_usd:.6f})")
                    else:
                        erc20_tokens.append(f"{token_symbol}: {balance:.6f} (${value_usd:.6f})")
            
            # Display categorized tokens
            if btc_tokens:
                print("    ₿ BTC Tokens:")
                for token_info in btc_tokens:
                    print(f"      - {token_info}")
            
            if stable_tokens:
                print("    💵 Stablecoins:")
                for token_info in stable_tokens:
                    print(f"      - {token_info}")
            
            if erc20_tokens:
                print("    🪙 Other Tokens:")
                for token_info in erc20_tokens:
                    print(f"      - {token_info}")
            
            # Show protocol assets for this chain
            if chain_name in chains and chains[chain_name].get('assets'):
                print("    🏛️ Protocol Assets:")
                for asset_key, asset_data in chains[chain_name]['assets'].items():
                    protocol = asset_data.get('protocol', 'Unknown')
                    asset_type = asset_data.get('asset_type', 'Unknown')
                    total_value = asset_data.get('total_value_usd', 0)
                    print(f"      • {protocol} {asset_type}: ${total_value:.6f}")
                    for token_symbol, token_data in asset_data.get('tokens', {}).items():
                        print(f"        - {token_symbol}: {token_data.get('balance', 0):.6f} (${token_data.get('value_usd', 0):.6f})")
        
        # Display overall protocol assets summary
        if assets:
            print("\n💎 Protocol Assets Summary:")
            for asset_name, asset_data in assets.items():
                print(f"  • {asset_name}: ${asset_data.get('total_value_usd', 0):.6f}")
        else:
            print("\n📭 No protocol assets found")
            
        if 'error' in result:
            print(f"⚠️ Error: {result['error']}")
            
        return result
        
    except Exception as e:
        print(f"❌ Portfolio check error: {e}")
        import traceback
        traceback.print_exc()
        return None

async def check_portfolio_by_wallet():
    """Check portfolio by wallet address (tests vault resolution)"""
    try:
        from services.portfolio_service import PortfolioService
        from utils.mongo_connection import mongo_connection
        
        # Example wallet address - modify as needed
        WALLET_ADDRESS = "0x1234567890123456789012345678901234567890"
        
        print(f"🔍 Checking portfolio for wallet: {WALLET_ADDRESS}")
        
        # Initialize MongoDB connection
        db = await mongo_connection.connect()
        
        # Initialize portfolio service
        portfolio_service = PortfolioService(db)
        
        # Get portfolio summary by wallet address
        result = await portfolio_service.get_portfolio_summary(wallet_address=WALLET_ADDRESS)
        
        # Close MongoDB connection
        await mongo_connection.disconnect()
        
        if result.get('vault_address'):
            print(f"🏦 Resolved vault address: {result['vault_address']}")
            print(f"📊 Total value: ${result['total_value_usd']:.6f}")
        else:
            print("❌ Could not resolve vault address")
            
        return result
        
    except Exception as e:
        print(f"❌ Portfolio check error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    # Run the main portfolio check
    asyncio.run(check_portfolio())
    
    # Uncomment to test wallet address resolution
    # asyncio.run(check_portfolio_by_wallet()) 