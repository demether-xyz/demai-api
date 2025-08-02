import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.coingecko_cache_service import CoinGeckoCacheService
from utils.coingecko_util import CoinGeckoUtil
from utils.mongo_connection import mongo_connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_coingecko_cache():
    """Test the CoinGecko caching system"""
    
    # Connect to MongoDB
    db = await mongo_connection.connect()
    
    # Initialize services
    cache_service = CoinGeckoCacheService(db=db, cache_ttl_minutes=60)
    coingecko_util = CoinGeckoUtil(db=db)
    
    # Test token IDs
    test_tokens = ["ethereum", "bitcoin", "chainlink"]
    
    print("\n=== Testing CoinGecko Cache Service ===\n")
    
    # 1. Clear cache to start fresh
    print("1. Clearing existing cache...")
    await cache_service.clear_cache()
    
    # 2. Get initial cache stats
    stats = await cache_service.get_cache_stats()
    print(f"Initial cache stats: {stats}")
    
    # 3. First fetch - should hit API
    print(f"\n2. First fetch for tokens: {test_tokens}")
    prices1 = await coingecko_util.get_token_prices_async(test_tokens)
    print(f"Prices fetched: {prices1}")
    
    # 4. Check cache stats after fetch
    stats = await cache_service.get_cache_stats()
    print(f"\nCache stats after first fetch: {stats}")
    
    # 5. Second fetch - should hit cache
    print(f"\n3. Second fetch (should use cache)...")
    prices2 = await coingecko_util.get_token_prices_async(test_tokens)
    print(f"Prices from cache: {prices2}")
    
    # Verify prices match
    assert prices1 == prices2, "Prices should match between API and cache"
    print("✓ Cache returned same prices")
    
    # 6. Test single token cache
    print(f"\n4. Testing single token cache retrieval...")
    eth_price = await cache_service.get_price("ethereum")
    print(f"Ethereum price from cache: ${eth_price}")
    assert eth_price == prices1.get("ethereum"), "Single token price should match"
    
    # 7. Test partial cache hit
    print(f"\n5. Testing partial cache hit...")
    mixed_tokens = ["ethereum", "polkadot"]  # ethereum cached, polkadot not
    mixed_prices = await coingecko_util.get_token_prices_async(mixed_tokens)
    print(f"Mixed fetch results: {mixed_prices}")
    
    # 8. Final cache stats
    stats = await cache_service.get_cache_stats()
    print(f"\nFinal cache stats: {stats}")
    
    # 9. Test cache cleanup
    print(f"\n6. Testing expired entry cleanup...")
    await cache_service.cleanup_expired()
    stats_after_cleanup = await cache_service.get_cache_stats()
    print(f"Stats after cleanup: {stats_after_cleanup}")
    
    print("\n✅ All tests passed!")
    
    # Disconnect
    await mongo_connection.disconnect()


if __name__ == "__main__":
    asyncio.run(test_coingecko_cache())