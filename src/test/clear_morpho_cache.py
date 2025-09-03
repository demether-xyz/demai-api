"""
Script to clear Morpho yield cache.
"""
import asyncio
import os
import logging

# Set environment variable to load keychain secrets before importing config
os.environ["LOAD_KEYCHAIN_SECRETS"] = "1"

from tools.morpho_tool import MorphoYieldCacheService
from utils.mongo_connection import mongo_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def clear_morpho_cache():
    """Clear Morpho yield cache."""
    try:
        logging.info("🧹 Clearing Morpho yield cache...")
        
        # Connect to database
        db = await mongo_connection.connect()
        
        # Create cache service and clear all data
        cache_service = MorphoYieldCacheService(db=db)
        await cache_service.clear()  # Clear all cache entries
        
        logging.info("✅ Morpho yield cache cleared successfully")
        
    except Exception as e:
        logging.error(f"❌ Error clearing cache: {e}")


if __name__ == "__main__":
    # Load keychain secrets if enabled
    if os.getenv("LOAD_KEYCHAIN_SECRETS") == "1":
        try:
            from config import load_keychain_secrets
            load_keychain_secrets()
            logging.info("✅ Loaded keychain secrets")
        except Exception as e:
            logging.warning(f"⚠️  Could not load keychain secrets: {e}")
    
    asyncio.run(clear_morpho_cache())