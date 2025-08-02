#!/usr/bin/env python3

import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Vault address to check - modify this to test different addresses
VAULT_ADDRESS = "0xdBFCBEDe24F05a7d4EaeD44C115F0Fa7803F5e49"

async def check_portfolio():
    """Check portfolio for the specified vault address"""
    try:
        from backend.services.portfolio_service import PortfolioService
        from utils.mongo_util import MongoUtil
        
        print(f"🔍 Checking portfolio for vault: {VAULT_ADDRESS}")
        
        # Initialize MongoDB connection
        mongo_util = MongoUtil()
        mongo_util.connect()
        
        # Initialize portfolio service
        portfolio_service = PortfolioService(mongo_util)
        
        # Get portfolio summary
        result = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS)
        
        # Close MongoDB connection
        mongo_util.close()
        
        print(f"✅ Portfolio summary completed!")
        print(f"📊 Total value: ${result['total_value_usd']:.6f}")
        print(f"🏦 Chains: {result['chains_count']}")
        print(f"🪙 Tokens: {result['tokens_count']}")
        print(f"⚡ Active strategies: {result['strategy_count']}")
        
        if result['active_strategies']:
            print(f"🔗 Strategies: {', '.join(result['active_strategies'])}")
        
        if result['holdings']:
            print("\n💰 Holdings:")
            for holding in result['holdings']:
                if holding.get('type') == 'strategy':
                    print(f"  • {holding['symbol']}: {holding['balance']:.6f} (${holding['value_usd']:.6f}) - {holding['protocol']} {holding['strategy_type']}")
                else:
                    print(f"  • {holding['symbol']}: {holding['balance']:.6f} (${holding['value_usd']:.6f})")
        else:
            print("📭 No holdings found")
            
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