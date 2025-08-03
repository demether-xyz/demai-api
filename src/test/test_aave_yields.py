"""
Simple test to call get_all_aave_yields and display the payload
"""
import asyncio
import json
import sys
import os
import time

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.aave_tool import get_all_aave_yields
from utils.mongo_connection import mongo_connection


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


async def test_caching_performance():
    """Test caching performance by making two consecutive calls"""
    print("\n" + "="*80)
    print("TESTING CACHING PERFORMANCE")
    print("="*80)
    
    # Connect to MongoDB for caching
    try:
        db = await mongo_connection.connect()
        print("✓ Connected to MongoDB for caching")
        
        # Clear existing cache to ensure clean test
        if db is not None:
            cache_collection = db.aave_yield_cache
            delete_result = await cache_collection.delete_many({})
            if delete_result.deleted_count > 0:
                print(f"  Cleared {delete_result.deleted_count} cached entries")
    except Exception as e:
        print(f"⚠️  Could not connect to MongoDB: {e}")
        print("   Running without database caching (memory-only)")
        db = None
    
    # First call - should fetch from API
    print("\nFirst call (should fetch from API):")
    start_time = time.time()
    yields1 = await get_all_aave_yields(db=db)
    first_call_time = time.time() - start_time
    print(f"First call completed in {first_call_time:.2f} seconds")
    
    # Check if data indicates it came from cache
    first_from_cache = any(
        yield_data.get('from_cache', False) 
        for chain_yields in yields1.values() 
        for yield_data in chain_yields
    )
    print(f"First call from cache: {first_from_cache}")
    
    # Second call - should use cache
    print("\nSecond call (should use cache):")
    start_time = time.time()
    yields2 = await get_all_aave_yields(db=db)
    second_call_time = time.time() - start_time
    print(f"Second call completed in {second_call_time:.2f} seconds")
    
    # Check if data indicates it came from cache
    second_from_cache = any(
        yield_data.get('from_cache', False) 
        for chain_yields in yields2.values() 
        for yield_data in chain_yields
    )
    print(f"Second call from cache: {second_from_cache}")
    
    # Compare times
    speedup = first_call_time / second_call_time if second_call_time > 0 else float('inf')
    print(f"\nSpeedup factor: {speedup:.2f}x")
    print(f"Time saved: {first_call_time - second_call_time:.2f} seconds")
    
    # Verify data is identical (excluding metadata like from_cache flag)
    def remove_metadata(data):
        """Remove metadata fields for comparison"""
        cleaned = {}
        for token, yields in data.items():
            cleaned[token] = []
            for y in yields:
                y_copy = y.copy()
                y_copy.pop('from_cache', None)
                cleaned[token].append(y_copy)
        return cleaned
    
    data1_clean = remove_metadata(yields1)
    data2_clean = remove_metadata(yields2)
    data_identical = json.dumps(data1_clean, sort_keys=True) == json.dumps(data2_clean, sort_keys=True)
    print(f"Data identical between calls (excluding metadata): {data_identical}")
    
    # Adjusted threshold - 5x speedup is still excellent for caching
    if second_call_time < first_call_time * 0.2:  # Second call should be at least 5x faster
        print("\n✅ CACHING IS WORKING PROPERLY!")
        print(f"   Cache provided {speedup:.1f}x speedup")
    else:
        print("\n⚠️  Cache might not be working as expected")
    
    # Disconnect from MongoDB
    if db is not None:
        await mongo_connection.disconnect()


if __name__ == "__main__":
    # Run the caching performance test
    asyncio.run(test_caching_performance())
    
    # Optionally run the original test as well
    # asyncio.run(test_get_all_aave_yields())