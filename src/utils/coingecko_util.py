import requests
import time
import asyncio
import aiohttp
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
import logging

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

from services.coingecko_cache_service import CoinGeckoCacheService

logger = logging.getLogger(__name__)


class CoinGeckoUtil:
    """Utility for fetching token prices from CoinGecko API with dual-layer caching"""
    
    def __init__(self, db: Optional['AsyncIOMotorDatabase'] = None):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.db = db
            
        self.cache_duration = timedelta(minutes=15)  # Legacy cache for 15 minutes
        # Initialize the new 60-minute cache service
        self.price_cache_service = CoinGeckoCacheService(db=db, cache_ttl_minutes=60)
        
    def get_token_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """
        Get current USD prices for a list of token IDs
        Uses cached prices if available and recent enough
        """
        prices = {}
        tokens_to_fetch = []
        
        # Check cache first
        if self.db is not None:
            for token_id in token_ids:
                cached_price = self._get_cached_price(token_id)
                if cached_price:
                    prices[token_id] = cached_price
                else:
                    tokens_to_fetch.append(token_id)
        else:
            tokens_to_fetch = token_ids
            
        # Fetch missing prices from API
        if tokens_to_fetch:
            fetched_prices = self._fetch_prices_from_api(tokens_to_fetch)
            prices.update(fetched_prices)
            
            # Cache the fetched prices
            if self.db is not None:
                self._cache_prices(fetched_prices)
                
        return prices
    
    async def get_token_prices_async(self, token_ids: List[str]) -> Dict[str, float]:
        """
        Async version of get_token_prices that uses the 60-minute cache service
        """
        if not token_ids:
            return {}
        
        # First, check the 60-minute cache
        cached_prices = await self.price_cache_service.get_prices(token_ids)
        
        # Determine which tokens still need to be fetched
        tokens_to_fetch = [tid for tid in token_ids if tid not in cached_prices]
        
        if tokens_to_fetch:
            logger.info(f"Fetching {len(tokens_to_fetch)} token prices from API (out of {len(token_ids)} requested)")
            
            # Fetch missing prices from API
            fetched_prices = await self._fetch_prices_from_api_async(tokens_to_fetch)
            
            # Update the 60-minute cache with fetched prices
            if fetched_prices:
                await self.price_cache_service.set_prices(fetched_prices)
            
            # Combine cached and fetched prices
            cached_prices.update(fetched_prices)
        else:
            logger.info(f"All {len(token_ids)} token prices retrieved from 60-minute cache")
        
        return cached_prices
    
    async def _get_cached_price_async(self, token_id: str) -> Optional[float]:
        """Async version of _get_cached_price"""
        try:
            if self.db is None:
                return None
            
            # Database is async Motor, use await for database operations
            cache_entry = await self.db.price_cache.find_one({"token_id": token_id})
            
            if not cache_entry:
                return None
                
            cached_time = cache_entry.get("timestamp")
            if not cached_time:
                return None
                
            # Check if cache is still valid (within 15 minutes)
            if datetime.utcnow() - cached_time < self.cache_duration:
                return cache_entry.get("price_usd")
                
        except Exception as e:
            logger.error(f"Error reading cached price for {token_id}: {e}")
            
        return None
    
    async def _cache_prices_async(self, prices: Dict[str, float]):
        """Async version of _cache_prices"""
        try:
            if self.db is None:
                return
            
            # Database is async Motor, use await for database operations
            for token_id, price in prices.items():
                await self.db.price_cache.update_one(
                    {"token_id": token_id},
                    {
                        "$set": {
                            "token_id": token_id,
                            "price_usd": price,
                            "timestamp": datetime.utcnow()
                        }
                    },
                    upsert=True
                )
            
            logger.info(f"Cached prices for {len(prices)} tokens")
        except Exception as e:
            logger.error(f"Error caching prices: {e}")
    
    async def _fetch_prices_from_api_async(self, token_ids: List[str]) -> Dict[str, float]:
        """Async version of _fetch_prices_from_api using aiohttp"""
        if not token_ids:
            return {}
            
        try:
            # CoinGecko API endpoint for simple price lookup
            ids_param = ",".join(token_ids)
            url = f"{self.base_url}/simple/price"
            params = {
                "ids": ids_param,
                "vs_currencies": "usd"
            }
            
            logger.info(f"Fetching prices for tokens: {token_ids}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            prices = {}
            for token_id in token_ids:
                if token_id in data and "usd" in data[token_id]:
                    prices[token_id] = float(data[token_id]["usd"])
                else:
                    logger.warning(f"Price not found for token: {token_id}")
                    prices[token_id] = 0.0
                    
            logger.info(f"Successfully fetched {len(prices)} token prices")
            return prices
            
        except Exception as e:
            logger.error(f"Error fetching prices from CoinGecko: {e}")
            return {token_id: 0.0 for token_id in token_ids}
    
    def _get_cached_price(self, token_id: str) -> Optional[float]:
        """Get cached price if it exists and is recent enough"""
        try:
            if self.db is None:
                return None
                
            cache_entry = self.db.price_cache.find_one({"token_id": token_id})
            if not cache_entry:
                return None
                
            cached_time = cache_entry.get("timestamp")
            if not cached_time:
                return None
                
            # Check if cache is still valid (within 15 minutes)
            if datetime.utcnow() - cached_time < self.cache_duration:
                return cache_entry.get("price_usd")
                
        except Exception as e:
            logger.error(f"Error reading cached price for {token_id}: {e}")
            
        return None
    
    def _cache_prices(self, prices: Dict[str, float]):
        """Cache prices in MongoDB"""
        try:
            if self.db is None:
                return
                
            for token_id, price in prices.items():
                self.db.price_cache.update_one(
                    {"token_id": token_id},
                    {
                        "$set": {
                            "token_id": token_id,
                            "price_usd": price,
                            "timestamp": datetime.utcnow()
                        }
                    },
                    upsert=True
                )
            logger.info(f"Cached prices for {len(prices)} tokens")
        except Exception as e:
            logger.error(f"Error caching prices: {e}")
    
    def _fetch_prices_from_api(self, token_ids: List[str]) -> Dict[str, float]:
        """Fetch prices from CoinGecko API"""
        if not token_ids:
            return {}
            
        try:
            # CoinGecko API endpoint for simple price lookup
            ids_param = ",".join(token_ids)
            url = f"{self.base_url}/simple/price"
            params = {
                "ids": ids_param,
                "vs_currencies": "usd"
            }
            
            logger.info(f"Fetching prices for tokens: {token_ids}")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            prices = {}
            
            for token_id in token_ids:
                if token_id in data and "usd" in data[token_id]:
                    prices[token_id] = float(data[token_id]["usd"])
                else:
                    logger.warning(f"Price not found for token: {token_id}")
                    prices[token_id] = 0.0
                    
            logger.info(f"Successfully fetched {len(prices)} token prices")
            return prices
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching prices: {e}")
            return {token_id: 0.0 for token_id in token_ids}
        except Exception as e:
            logger.error(f"Error fetching prices from CoinGecko: {e}")
            return {token_id: 0.0 for token_id in token_ids}
    
    async def get_cache_stats(self) -> Dict[str, any]:
        """Get cache statistics from the price cache service"""
        return await self.price_cache_service.get_cache_stats()
    
    async def clear_price_cache(self, token_id: Optional[str] = None):
        """Clear the 60-minute price cache"""
        await self.price_cache_service.clear_cache(token_id)