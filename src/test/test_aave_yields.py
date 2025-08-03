"""
Simple test to call get_all_aave_yields and display the payload
"""
import asyncio
import json
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.aave_tool import get_all_aave_yields


async def test_get_all_aave_yields():
    """Test fetching all Aave yields and display the results"""
    print("Fetching Aave yields for all supported tokens across chains...")
    print("-" * 60)
    
    try:
        # Fetch yields (will use cache if available within 3 hours)
        yields = await get_all_aave_yields()
        
        # Display results in a nice format
        if yields:
            print(f"\nFound yields for {len(yields)} tokens:")
            print("-" * 60)
            
            for token_symbol, chain_yields in yields.items():
                print(f"\n{token_symbol}:")
                for yield_data in chain_yields:
                    chain_id = yield_data.get('chain_id')
                    chain_name = "Arbitrum" if chain_id == 42161 else "Core" if chain_id == 1116 else f"Chain {chain_id}"
                    
                    print(f"  {chain_name} (Chain ID: {chain_id}):")
                    print(f"    Supply APY: {yield_data.get('supply_apy', 0):.2f}%")
                    print(f"    Borrow APY: {yield_data.get('borrow_apy', 0):.2f}%")
                    print(f"    Utilization: {yield_data.get('utilization_rate', 0):.2f}%")
                    print(f"    From Cache: {yield_data.get('from_cache', False)}")
                    if yield_data.get('atoken_address'):
                        print(f"    aToken: {yield_data.get('atoken_address')}")
        else:
            print("No yields found!")
        
        # Also display as JSON for easy viewing
        print("\n" + "="*60)
        print("Full JSON Response:")
        print("="*60)
        print(json.dumps(yields, indent=2, default=str))
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_get_all_aave_yields())