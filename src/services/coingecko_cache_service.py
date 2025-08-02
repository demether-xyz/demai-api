from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone
import logging
import asyncio
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class CoinGeckoCacheService:
    """
    Dedicated cache service for CoinGecko token prices with 60-minute TTL.
    This provides a separate caching layer that persists across portfolio refreshes.
    """
    
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None, cache_ttl_minutes: int = 60):
        self.db = db
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
        
        # Initialize database indexes
        if self.db:
            asyncio.create_task(self._ensure_indexes())
    
    async def _ensure_indexes(self):
        """Ensure database indexes exist for optimal performance"""
        if not self.db:
            return
            
        try:
            collection = self.db.coingecko_price_cache
            await collection.create_index("token_id", unique=True)
            await collection.create_index("timestamp")
            logger.info("CoinGecko cache indexes ensured")
        except Exception as e:
            logger.error(f"Error creating CoinGecko cache indexes: {e}")
    
    async def get_price(self, token_id: str) -> Optional[float]:
        """
        Get cached price for a single token.
        Returns None if not found or expired.
        """
        # Check memory cache first
        if token_id in self._memory_cache:
            entry = self._memory_cache[token_id]
            if self._is_cache_valid(entry['timestamp']):
                logger.debug(f"Memory cache hit for {token_id}: ${entry['price']}")
                return entry['price']
            else:
                # Remove expired entry
                async with self._cache_lock:
                    self._memory_cache.pop(token_id, None)
        
        # Check database cache
        if self.db:
            try:
                collection = self.db.coingecko_price_cache
                result = await collection.find_one({"token_id": token_id})
                
                if result and self._is_cache_valid(result['timestamp']):
                    price = result['price']
                    
                    # Update memory cache
                    async with self._cache_lock:
                        self._memory_cache[token_id] = {
                            'price': price,
                            'timestamp': result['timestamp']
                        }
                    
                    logger.debug(f"Database cache hit for {token_id}: ${price}")
                    return price
                elif result:
                    # Remove expired entry
                    await collection.delete_one({"token_id": token_id})
                    
            except Exception as e:
                logger.error(f"Error getting cached price for {token_id}: {e}")
        
        return None
    
    async def get_prices(self, token_ids: list[str]) -> Dict[str, float]:
        """
        Get cached prices for multiple tokens.
        Returns dict with token_id -> price for cached tokens only.
        """
        cached_prices = {}
        
        for token_id in token_ids:
            price = await self.get_price(token_id)
            if price is not None:
                cached_prices[token_id] = price
        
        if cached_prices:
            logger.info(f"Retrieved {len(cached_prices)}/{len(token_ids)} prices from cache")
        
        return cached_prices
    
    async def set_price(self, token_id: str, price: float):
        """Cache a single token price"""
        timestamp = datetime.now(timezone.utc)
        
        # Update memory cache
        async with self._cache_lock:
            self._memory_cache[token_id] = {
                'price': price,
                'timestamp': timestamp
            }
        
        # Update database cache
        if self.db:
            try:
                collection = self.db.coingecko_price_cache
                await collection.update_one(
                    {"token_id": token_id},
                    {
                        "$set": {
                            "token_id": token_id,
                            "price": price,
                            "timestamp": timestamp
                        }
                    },
                    upsert=True
                )
                logger.debug(f"Cached price for {token_id}: ${price}")
            except Exception as e:
                logger.error(f"Error caching price for {token_id}: {e}")
    
    async def set_prices(self, prices: Dict[str, float]):
        """Cache multiple token prices"""
        timestamp = datetime.now(timezone.utc)
        
        # Update memory cache
        async with self._cache_lock:
            for token_id, price in prices.items():
                self._memory_cache[token_id] = {
                    'price': price,
                    'timestamp': timestamp
                }
        
        # Update database cache
        if self.db:
            try:
                collection = self.db.coingecko_price_cache
                operations = []
                
                for token_id, price in prices.items():
                    operations.append({
                        "update_one": {
                            "filter": {"token_id": token_id},
                            "update": {
                                "$set": {
                                    "token_id": token_id,
                                    "price": price,
                                    "timestamp": timestamp
                                }
                            },
                            "upsert": True
                        }
                    })
                
                if operations:
                    await collection.bulk_write(operations)
                    logger.info(f"Cached {len(prices)} token prices")
                    
            except Exception as e:
                logger.error(f"Error bulk caching prices: {e}")
    
    def _is_cache_valid(self, timestamp: datetime) -> bool:
        """Check if cache entry is still valid based on TTL"""
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        age = datetime.now(timezone.utc) - timestamp
        return age < self.cache_ttl
    
    async def clear_cache(self, token_id: Optional[str] = None):
        """Clear cache for specific token or all tokens"""
        if token_id:
            # Clear specific token
            async with self._cache_lock:
                self._memory_cache.pop(token_id, None)
            
            if self.db:
                try:
                    collection = self.db.coingecko_price_cache
                    await collection.delete_one({"token_id": token_id})
                    logger.info(f"Cleared cache for token {token_id}")
                except Exception as e:
                    logger.error(f"Error clearing cache for {token_id}: {e}")
        else:
            # Clear all cache
            async with self._cache_lock:
                self._memory_cache.clear()
            
            if self.db:
                try:
                    collection = self.db.coingecko_price_cache
                    await collection.delete_many({})
                    logger.info("Cleared all CoinGecko price cache")
                except Exception as e:
                    logger.error(f"Error clearing all cache: {e}")
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        memory_size = len(self._memory_cache)
        db_size = 0
        
        if self.db:
            try:
                collection = self.db.coingecko_price_cache
                db_size = await collection.count_documents({})
            except Exception as e:
                logger.error(f"Error getting cache stats: {e}")
        
        # Count valid entries
        valid_memory = sum(
            1 for entry in self._memory_cache.values() 
            if self._is_cache_valid(entry['timestamp'])
        )
        
        return {
            "memory_cache_total": memory_size,
            "memory_cache_valid": valid_memory,
            "database_cache_total": db_size,
            "cache_ttl_minutes": self.cache_ttl.total_seconds() / 60,
            "cache_ttl_seconds": self.cache_ttl.total_seconds()
        }
    
    async def cleanup_expired(self):
        """Remove expired entries from cache"""
        # Clean memory cache
        expired_keys = []
        async with self._cache_lock:
            for token_id, entry in self._memory_cache.items():
                if not self._is_cache_valid(entry['timestamp']):
                    expired_keys.append(token_id)
            
            for key in expired_keys:
                self._memory_cache.pop(key, None)
        
        if expired_keys:
            logger.info(f"Removed {len(expired_keys)} expired entries from memory cache")
        
        # Clean database cache
        if self.db:
            try:
                collection = self.db.coingecko_price_cache
                cutoff_time = datetime.now(timezone.utc) - self.cache_ttl
                result = await collection.delete_many({
                    "timestamp": {"$lt": cutoff_time}
                })
                
                if result.deleted_count > 0:
                    logger.info(f"Removed {result.deleted_count} expired entries from database cache")
                    
            except Exception as e:
                logger.error(f"Error cleaning up expired cache entries: {e}")