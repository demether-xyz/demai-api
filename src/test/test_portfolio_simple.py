#!/usr/bin/env python3
"""Simple test for portfolio JSON output - uses cache for fast testing"""

import asyncio
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Vault address to check
VAULT_ADDRESS = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"

async def test_portfolio_json():
    """Test portfolio JSON output for frontend endpoint"""
    try:
        from services.portfolio_service import PortfolioService
        from utils.mongo_connection import mongo_connection
        
        print(f"🔍 Testing portfolio JSON for vault: {VAULT_ADDRESS}")
        
        # Initialize MongoDB connection
        db = await mongo_connection.connect()
        
        # Initialize portfolio service
        portfolio_service = PortfolioService(db)
        
        # Test 1: Regular portfolio summary (used by FE endpoint)
        print("\n📊 Frontend JSON Output (get_portfolio_summary):")
        result = await portfolio_service.get_portfolio_summary(VAULT_ADDRESS)
        
        # Show just the structure without holdings array
        display_result = {k: v for k, v in result.items() if k != 'holdings'}
        print(json.dumps(display_result, indent=2))
        
        # Test 2: LLM-formatted output (with refresh=False to use cache)
        print("\n🤖 LLM JSON Output (get_portfolio_for_llm) - Using cache:")
        llm_result = await portfolio_service.get_portfolio_for_llm(vault_address=VAULT_ADDRESS, refresh=False)
        print(json.dumps(llm_result, indent=2))
        
        # Verify no "Unknown" tokens in the output
        def check_for_unknown(data, path=""):
            issues = []
            if isinstance(data, dict):
                for key, value in data.items():
                    if key == "Unknown" or value == "Unknown":
                        issues.append(f"{path}.{key} = {value}")
                    else:
                        issues.extend(check_for_unknown(value, f"{path}.{key}"))
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    issues.extend(check_for_unknown(item, f"{path}[{i}]"))
            return issues
        
        issues = check_for_unknown(llm_result)
        if issues:
            print("\n⚠️  Found 'Unknown' values in:")
            for issue in issues:
                print(f"  - {issue}")
        else:
            print("\n✅ No 'Unknown' tokens found in output!")
        
        # Show summary
        print(f"\n📈 Summary:")
        print(f"  Total Value: ${llm_result.get('total_value_usd', 0):.2f}")
        print(f"  Active Chains: {', '.join(llm_result.get('summary', {}).get('active_chains', []))}")
        print(f"  Active Strategies: {', '.join(llm_result.get('summary', {}).get('active_strategies', []))}")
        print(f"  Total Tokens: {llm_result.get('summary', {}).get('total_tokens', 0)}")
        
        # Close MongoDB connection
        await mongo_connection.disconnect()
        
        return llm_result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(test_portfolio_json())