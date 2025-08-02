#!/usr/bin/env python3

import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Vault address to check - modify this to test different addresses
VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

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
        
        # Get portfolio summary
        result = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS)
        
        # Close MongoDB connection
        await mongo_connection.disconnect()
        
        print(f"✅ Portfolio summary completed!")
        print(f"📊 Total value: ${result['total_value_usd']:.6f}")
        
        summary = result.get('summary', {})
        chains = result.get('chains', {})
        assets = result.get('assets', {})
        
        print(f"🏦 Chains: {len(summary.get('active_chains', []))}")
        print(f"🪙 Tokens: {summary.get('total_tokens', 0)}")
        print(f"⚡ Active assets: {len(summary.get('active_assets', []))}")
        
        if summary.get('active_assets'):
            print(f"🔗 Assets: {', '.join(summary['active_assets'])}")
        
        # Display chain information
        if chains:
            print("\n🌐 Chains:")
            for chain_name, chain_data in chains.items():
                print(f"  • {chain_name}: ${chain_data.get('total_value_usd', 0):.6f}")
                
        # Display asset information (aTokens, etc.)
        if assets:
            print("\n💎 Protocol Assets:")
            for asset_name, asset_data in assets.items():
                print(f"  • {asset_name}: ${asset_data.get('total_value_usd', 0):.6f}")
                for token_symbol, token_data in asset_data.get('tokens', {}).items():
                    print(f"    - {token_symbol}: {token_data.get('balance', 0):.6f} (${token_data.get('value_usd', 0):.6f})")
        else:
            print("📭 No protocol assets found")
            
        if 'error' in result:
            print(f"⚠️ Error: {result['error']}")
            
        return result
        
    except Exception as e:
        print(f"❌ Portfolio check error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(check_portfolio()) 