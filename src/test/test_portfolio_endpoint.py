#!/usr/bin/env python3
"""
Test script to verify the portfolio endpoint can detect AUSD in the vault.
"""
import asyncio
import json
import os
import sys
import logging
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_portfolio_endpoint():
    """Test the portfolio endpoint to see if it detects AUSD in vaults."""
    # Load secrets
    os.environ["LOAD_KEYCHAIN_SECRETS"] = "1"
    
    try:
        from config import load_keychain_secrets
        load_keychain_secrets()
    except Exception as e:
        logger.warning(f"Could not load keychain secrets: {e}")
    
    from services.portfolio_service import PortfolioService
    from motor.motor_asyncio import AsyncIOMotorClient
    
    # Test addresses
    test_addresses = {
        "user_account": "0x55b3d73e525227A7F0b25e28e17c1E94006A25dd",  # User from test
        "strategy_vault": "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92",  # Strategy vault
        "another_test_account": "0x3f17f1962B36e491b30A40b2405849e597Ba5FB5",  # From earlier test
    }
    
    # Initialize portfolio service
    try:
        # Try to connect to MongoDB if available
        mongo_connection = os.getenv("MONGO_CONNECTION")
        if mongo_connection:
            client = AsyncIOMotorClient(mongo_connection)
            db = client.demai
        else:
            logger.info("No MongoDB connection - running without database")
            db = None
            
        portfolio_service = PortfolioService(db, cache_ttl_seconds=0)  # No cache for testing
        
        logger.info("=== Testing Portfolio Endpoint ===")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")
        
        for name, address in test_addresses.items():
            logger.info(f"\n--- Testing {name}: {address} ---")
            
            try:
                # Get portfolio data
                portfolio = await portfolio_service.get_portfolio_summary(wallet_address=address, refresh=True)
                
                logger.info(f"Portfolio result for {name}:")
                logger.info(f"  Total Value USD: ${portfolio.get('total_value_usd', 0):,.4f}")
                logger.info(f"  Total Tokens: {portfolio.get('summary', {}).get('total_tokens', 0)}")
                logger.info(f"  Active Chains: {portfolio.get('summary', {}).get('active_chains', [])}")
                
                # Check chains
                chains = portfolio.get('chains', {})
                if chains:
                    logger.info(f"  Found data on {len(chains)} chains:")
                    for chain_name, chain_data in chains.items():
                        logger.info(f"    {chain_name}:")
                        logger.info(f"      Value: ${chain_data.get('total_value_usd', 0):,.4f}")
                        
                        # Check tokens
                        tokens = chain_data.get('tokens', {})
                        if tokens:
                            for token_symbol, token_data in tokens.items():
                                balance = token_data.get('balance', 0)
                                value = token_data.get('value_usd', 0)
                                if balance > 0:
                                    logger.info(f"        {token_symbol}: {balance:,.6f} (${value:,.2f})")
                        else:
                            logger.info(f"        No tokens found")
                else:
                    logger.info(f"  No chain data found")
                
                # Check for assets (yield-bearing tokens like Morpho)
                assets = portfolio.get('assets', {})
                if assets:
                    logger.info(f"  Found {len(assets)} asset types:")
                    for asset_key, asset_data in assets.items():
                        protocol = asset_data.get('protocol', 'Unknown')
                        asset_type = asset_data.get('asset_type', 'Unknown')
                        value = asset_data.get('total_value_usd', 0)
                        logger.info(f"    {asset_key} ({protocol}/{asset_type}): ${value:,.4f}")
                        
                        # Show tokens in this asset
                        asset_tokens = asset_data.get('tokens', {})
                        for token_symbol, token_data in asset_tokens.items():
                            balance = token_data.get('balance', 0)
                            token_value = token_data.get('value_usd', 0)
                            if balance > 0:
                                logger.info(f"      {token_symbol}: {balance:,.6f} (${token_value:,.4f})")
                
                # Look specifically for AUSD and Morpho assets
                ausd_found = False
                morpho_found = False
                
                if chains:
                    for chain_name, chain_data in chains.items():
                        # Check regular AUSD tokens
                        tokens = chain_data.get('tokens', {})
                        if 'AUSD' in tokens:
                            ausd_data = tokens['AUSD']
                            logger.info(f"  ✅ AUSD found on {chain_name}:")
                            logger.info(f"    Balance: {ausd_data.get('balance', 0):,.6f}")
                            logger.info(f"    Value: ${ausd_data.get('value_usd', 0):,.4f}")
                            ausd_found = True
                        
                        # Check for Morpho assets in chain
                        chain_assets = chain_data.get('assets', {})
                        for asset_key, asset_data in chain_assets.items():
                            if asset_data.get('protocol') == 'Morpho':
                                morpho_found = True
                                logger.info(f"  ✅ Morpho asset found on {chain_name}: {asset_key}")
                                asset_tokens = asset_data.get('tokens', {})
                                for token_symbol, token_data in asset_tokens.items():
                                    balance = token_data.get('balance', 0)
                                    token_value = token_data.get('value_usd', 0)
                                    logger.info(f"    {token_symbol}: {balance:,.6f} (${token_value:,.4f})")
                
                if not ausd_found:
                    logger.info(f"  ❌ No regular AUSD found for {name}")
                
                if not morpho_found:
                    logger.info(f"  ❌ No Morpho assets found for {name}")
                    
            except Exception as e:
                logger.error(f"Error testing {name}: {e}")
                import traceback
                traceback.print_exc()
        
        logger.info("\n=== Testing Complete ===")
        
    except Exception as e:
        logger.error(f"Error initializing portfolio service: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_portfolio_endpoint())