#!/usr/bin/env python3
"""Simple test for portfolio JSON output - tests the same endpoint used by frontend"""

import asyncio
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Vault address to check
VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

async def test_portfolio_json():
    """Test portfolio JSON output for frontend endpoint (without refresh)"""
    try:
        from services.portfolio_service import PortfolioService
        from utils.mongo_connection import mongo_connection
        
        print(f"🔍 Testing portfolio JSON for vault: {VAULT_ADDRESS}")
        
        # Initialize MongoDB connection
        db = await mongo_connection.connect()
        
        # Initialize portfolio service
        portfolio_service = PortfolioService(db)
        
        # Test portfolio summary without refresh (same as FE endpoint)
        print("\n📊 Frontend JSON Output (get_portfolio_summary) - No refresh:")
        result = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS)
        
        # Pretty print the full result
        print(json.dumps(result, indent=2))
        
        # Show summary info
        print(f"\n📈 Summary:")
        print(f"  Total Value: ${result.get('total_value_usd', 0):,.2f}")
        print(f"  Total Holdings: {len(result.get('holdings', []))}")
        
        # Count holdings by chain
        holdings_by_chain = {}
        for holding in result.get('holdings', []):
            chain = holding.get('chain', 'Unknown')
            holdings_by_chain[chain] = holdings_by_chain.get(chain, 0) + 1
        
        print(f"  Holdings by chain:")
        for chain, count in holdings_by_chain.items():
            print(f"    - {chain}: {count} tokens")
        
        # Close MongoDB connection
        await mongo_connection.disconnect()
        
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(test_portfolio_json())