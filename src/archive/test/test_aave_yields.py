#!/usr/bin/env python3
"""
Standalone test script for Aave V3 yield reading functionality
Run this script to test the Aave yield functions

Usage:
    cd demai-api
    python test_aave_yields.py
"""

import sys
import os
import asyncio
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from web3 import Web3
    from tools.aave_tool import (
        get_aave_current_yield,
        get_aave_yields_for_all_tokens,
        _ray_to_apy,
        AAVE_STRATEGY_CONTRACTS
    )
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_aave_yields():
    """Test Aave yields for all configured tokens on all configured chains"""
    
    print("🧪 Testing Aave Yields for All Configured Tokens & Chains")
    print("=" * 60)
    
    # Create web3 instances for all chains
    web3_instances = {}
    for chain_id, config in CHAIN_CONFIG.items():
        try:
            w3 = Web3(Web3.HTTPProvider(config["rpc_url"]))
            if w3.is_connected():
                web3_instances[chain_id] = w3
                print(f"✅ Connected to {config['name']} (Chain {chain_id})")
            else:
                print(f"❌ Failed to connect to {config['name']} (Chain {chain_id})")
        except Exception as e:
            print(f"❌ Error connecting to {config['name']}: {e}")
    
    if not web3_instances:
        print("❌ No blockchain connections available")
        return
    
    print(f"\n📊 Testing yields for {len(SUPPORTED_TOKENS)} tokens across {len(web3_instances)} chains")
    print("-" * 60)
    
    # Test grouped by chain
    for chain_id, config in CHAIN_CONFIG.items():
        if chain_id not in web3_instances:
            continue
            
        print(f"\n🌐 {config['name']} (Chain {chain_id})")
        
        if chain_id not in AAVE_STRATEGY_CONTRACTS:
            print(f"  ⏭️  Aave not configured on this chain")
            continue
        
        # Test each token on this chain
        chain_has_tokens = False
        for token_symbol, token_config in SUPPORTED_TOKENS.items():
            if chain_id not in token_config["addresses"]:
                continue
                
            chain_has_tokens = True
            try:
                # Get yield data
                yield_data = await get_aave_current_yield(
                    web3_instances, token_symbol, chain_id, SUPPORTED_TOKENS
                )
                
                if "error" in yield_data:
                    print(f"  ❌ {token_symbol}: {yield_data['error']}")
                else:
                    supply_apy = yield_data.get('supply_apy', 0)
                    borrow_apy = yield_data.get('borrow_apy', 0)
                    utilization = yield_data.get('utilization_rate', 0)
                    
                    print(f"  ✅ {token_symbol}: Supply APY: {supply_apy:.4f}%, Borrow APY: {borrow_apy:.4f}%, Utilization: {utilization:.2f}%")
                    
            except Exception as e:
                print(f"  ❌ {token_symbol}: Error - {e}")
        
        if not chain_has_tokens:
            print(f"  ⏭️  No supported tokens configured on this chain")
    
    print(f"\n🎯 Testing batch yield function...")
    try:
        all_yields = await get_aave_yields_for_all_tokens(web3_instances, SUPPORTED_TOKENS)
        print(f"✅ Retrieved {len(all_yields)} yield records")
        
        for yield_data in all_yields:
            token = yield_data.get('token_symbol', 'Unknown')
            chain_name = CHAIN_CONFIG.get(yield_data.get('chain_id', 0), {}).get('name', 'Unknown')
            apy = yield_data.get('supply_apy', 0)
            print(f"  📈 {token} on {chain_name}: {apy:.4f}% APY")
            
    except Exception as e:
        print(f"❌ Batch yield test failed: {e}")
    
    print(f"\n🎉 Test completed!")

if __name__ == "__main__":
    asyncio.run(test_aave_yields()) 