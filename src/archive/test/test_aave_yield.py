"""
Test script for reading Aave V3 yield rates
"""
import asyncio
import logging
from web3 import Web3
from tools.aave_tool import (
    get_aave_current_yield,
    get_aave_yields_for_all_tokens,
    get_aave_yield_for_token,
    _ray_to_apy
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CHAIN_ID = 42161  # Arbitrum
TEST_TOKEN_SYMBOL = "USDC"
TEST_RPC_URL = "https://arb1.arbitrum.io/rpc"

# Mock supported tokens for testing
SUPPORTED_TOKENS = {
    "USDC": {
        "name": "USD Coin",
        "symbol": "USDC",
        "decimals": 6,
        "addresses": {
            42161: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC on Arbitrum
        },
        "coingeckoId": "usd-coin"
    },
    "USDT": {
        "name": "Tether USD",
        "symbol": "USDT", 
        "decimals": 6,
        "addresses": {
            42161: "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",  # USDT on Arbitrum
        },
        "coingeckoId": "tether"
    }
}

async def test_single_token_yield():
    """Test getting yield for a single token"""
    logger.info("=== Testing Single Token Yield ===")
    
    # Create Web3 instance
    w3 = Web3(Web3.HTTPProvider(TEST_RPC_URL))
    if not w3.is_connected():
        logger.error("Failed to connect to RPC")
        return
    
    web3_instances = {TEST_CHAIN_ID: w3}
    
    # Get yield for USDC
    yield_data = await get_aave_current_yield(
        web3_instances, 
        TEST_TOKEN_SYMBOL, 
        TEST_CHAIN_ID, 
        SUPPORTED_TOKENS
    )
    
    if "error" in yield_data:
        logger.error(f"Error getting yield: {yield_data['error']}")
    else:
        logger.info(f"USDC Yield Data:")
        logger.info(f"  Supply APY: {yield_data['supply_apy']:.4f}%")
        logger.info(f"  Borrow APY: {yield_data['borrow_apy']:.4f}%")
        logger.info(f"  Utilization Rate: {yield_data['utilization_rate']:.2f}%")
        logger.info(f"  Total Liquidity: {yield_data['total_liquidity']:,}")
        logger.info(f"  Total Debt: {yield_data['total_debt']:,}")

async def test_all_tokens_yield():
    """Test getting yields for all supported tokens"""
    logger.info("\n=== Testing All Tokens Yield ===")
    
    # Create Web3 instance
    w3 = Web3(Web3.HTTPProvider(TEST_RPC_URL))
    if not w3.is_connected():
        logger.error("Failed to connect to RPC")
        return
    
    web3_instances = {TEST_CHAIN_ID: w3}
    
    # Get yields for all tokens
    all_yields = await get_aave_yields_for_all_tokens(web3_instances, SUPPORTED_TOKENS)
    
    logger.info(f"Found yields for {len(all_yields)} tokens:")
    for yield_data in all_yields:
        logger.info(f"  {yield_data['token_symbol']}: {yield_data['supply_apy']:.4f}% APY")

def test_sync_yield_function():
    """Test the synchronous yield function for LangChain compatibility"""
    logger.info("\n=== Testing Synchronous Yield Function ===")
    
    result = get_aave_yield_for_token("USDC", "Arbitrum")
    logger.info(f"Sync function result: {result}")

def test_ray_conversion():
    """Test ray to APY conversion"""
    logger.info("\n=== Testing Ray Conversion ===")
    
    # Example ray values (these are typical Aave rates in ray format)
    test_rays = [
        0,  # 0%
        1000000000000000000000000000,  # ~0% (1e27 = 100% per second, very small rate)
        1000000001547125957863212448,  # ~5% APY
        1000000002440418608258400030,  # ~8% APY
    ]
    
    for ray_rate in test_rays:
        apy = _ray_to_apy(ray_rate)
        logger.info(f"Ray rate {ray_rate} = {apy:.6f}% APY")

async def main():
    """Run all tests"""
    logger.info("Starting Aave Yield Tests")
    
    # Test ray conversion first (no network required)
    test_ray_conversion()
    
    # Test network-dependent functions
    try:
        await test_single_token_yield()
        await test_all_tokens_yield()
        test_sync_yield_function()
    except Exception as e:
        logger.error(f"Network test failed: {e}")
        logger.info("This is expected if you don't have network access or the RPC is down")
    
    logger.info("Aave Yield Tests Complete")

if __name__ == "__main__":
    asyncio.run(main()) 