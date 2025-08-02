import requests
import time
import asyncio
import aiohttp
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
import logging

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class CoinGeckoUtil:
    """Utility for fetching token prices from CoinGecko API with caching"""
    
    def __init__(self, db: Optional['AsyncIOMotorDatabase'] = None):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.db = db
            
        self.cache_duration = timedelta(minutes=15)  # Cache for 15 minutes
        
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
        Async version of get_token_prices that properly handles the event loop
        """
        prices = {}
        tokens_to_fetch = []
        
        # Check cache first
        if self.db is not None:
            for token_id in token_ids:
                cached_price = await self._get_cached_price_async(token_id)
                if cached_price:
                    prices[token_id] = cached_price
                else:
                    tokens_to_fetch.append(token_id)
        else:
            tokens_to_fetch = token_ids
            
        # Fetch missing prices from API
        if tokens_to_fetch:
            fetched_prices = await self._fetch_prices_from_api_async(tokens_to_fetch)
            prices.update(fetched_prices)
            
            # Cache the fetched prices
            if self.db is not None:
                await self._cache_prices_async(fetched_prices)
                
        return prices
    
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