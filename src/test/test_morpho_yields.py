"""
Test script for Morpho yield fetching functionality.
"""
import asyncio
import os
import logging
from typing import Dict, Any

# Set environment variable to load keychain secrets before importing config
os.environ["LOAD_KEYCHAIN_SECRETS"] = "1"

from utils.morpho_yields_utils import get_simplified_morpho_yields, get_best_morpho_yield_for_token
from tools.morpho_tool import get_all_morpho_yields

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def test_morpho_yields_fetching():
    """Test fetching Morpho yields through the utils function."""
    logging.info("🧪 Testing Morpho yield fetching...")
    
    try:
        # Test simplified yields
        logging.info("📊 Fetching simplified Morpho yields...")
        simplified_yields = await get_simplified_morpho_yields()
        
        if simplified_yields:
            logging.info(f"✅ Found {len(simplified_yields)} Morpho yield opportunities:")
            for yield_data in simplified_yields:
                logging.info(f"  - {yield_data['token']} on {yield_data['chain']}: "
                           f"{yield_data['supply_apy']}% APY via {yield_data['protocol']}")
        else:
            logging.warning("⚠️  No Morpho yields found (expected if Katana RPC is unavailable)")
        
        # Test best yield for AUSD
        logging.info("\n🏆 Finding best AUSD yield on Morpho...")
        best_ausd_yield = await get_best_morpho_yield_for_token("AUSD")
        
        if "error" not in best_ausd_yield:
            logging.info(f"✅ Best AUSD yield: {best_ausd_yield['best_apy']}% APY "
                        f"on {best_ausd_yield['protocol']} ({best_ausd_yield['chain']})")
        else:
            logging.warning(f"⚠️  Error finding best AUSD yield: {best_ausd_yield['error']}")
        
        return simplified_yields
        
    except Exception as e:
        logging.error(f"❌ Error testing Morpho yields: {e}")
        return []


async def test_direct_morpho_yields():
    """Test direct Morpho yield fetching function."""
    logging.info("\n🔬 Testing direct Morpho yield fetching...")
    
    try:
        # Test with specific known vaults
        known_vaults = {
            747474: [  # Katana
                "0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD",  # Steakhouse Prime
                "0x9540441C503D763094921dbE4f13268E6d1d3B56",  # Gauntlet
            ]
        }
        
        yields_by_token = await get_all_morpho_yields(
            known_markets_and_vaults=known_vaults
        )
        
        if yields_by_token:
            logging.info(f"✅ Direct fetch found yields for {len(yields_by_token)} tokens:")
            for token, yield_list in yields_by_token.items():
                logging.info(f"  {token}:")
                for yield_data in yield_list:
                    vault_addr = yield_data.get('vault_address', 'N/A')
                    supply_apy = yield_data.get('supply_apy', 0)
                    logging.info(f"    - Vault {vault_addr[:10]}... : {supply_apy}% APY")
        else:
            logging.warning("⚠️  No yields found via direct fetch")
        
        return yields_by_token
        
    except Exception as e:
        logging.error(f"❌ Error in direct Morpho yield test: {e}")
        return {}


async def main():
    """Main test function."""
    logging.info("🚀 Starting Morpho yield fetching tests...\n")
    
    # Load keychain secrets if enabled
    if os.getenv("LOAD_KEYCHAIN_SECRETS") == "1":
        try:
            from config import load_keychain_secrets
            load_keychain_secrets()
            logging.info("✅ Loaded keychain secrets")
        except Exception as e:
            logging.warning(f"⚠️  Could not load keychain secrets: {e}")
    
    # Run tests
    simplified_yields = await test_morpho_yields_fetching()
    direct_yields = await test_direct_morpho_yields()
    
    # Summary
    logging.info(f"\n📋 Test Summary:")
    logging.info(f"   Simplified yields found: {len(simplified_yields)}")
    logging.info(f"   Direct yields tokens: {len(direct_yields)}")
    
    if simplified_yields or direct_yields:
        logging.info("✅ Morpho yield fetching is working!")
        logging.info("💡 The assistant can now compare Aave and Morpho yields to recommend the best options")
    else:
        logging.info("⚠️  No yields found - this is expected if Katana RPC is unavailable or vaults are empty")
    
    logging.info("\n🎯 Next steps:")
    logging.info("   1. The assistant will now include Morpho yields in context")
    logging.info("   2. Users can ask for 'best AUSD yield' and get both Aave and Morpho options")
    logging.info("   3. The assistant will automatically choose the highest yield protocol")


if __name__ == "__main__":
    asyncio.run(main())