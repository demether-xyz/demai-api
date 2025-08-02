"""
Test file for AKKA PKS quote endpoint on Core Testnet.
"""
import asyncio
import logging
import httpx
from config import CHAIN_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s | %(message)s')

# --- Configuration ---
CHAIN_ID = 1116  # Core Testnet
USDC_ADDRESS = "0xa4151B2B3e269645181dCcF2D426cE75fcbDeca9"
USDT_ADDRESS = "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1" # USDT on Core
SOLVBTC_ADDRESS = "0x9410e8052Bc661041e5cB27fDf7d9e9e842af2aa"
SWAP_AMOUNT_USDC = 0.01  # 0.01 USDC

async def test_pks_quote():
    logging.info(f"--- Testing AKKA PKS Quote Endpoint on Chain ID: {CHAIN_ID} ---")
    
    amount_in_wei = int(SWAP_AMOUNT_USDC * (10**6)) # USDC has 6 decimals
    
    # Test PKS Quote endpoint
    logging.info("Testing AKKA PKS quote endpoint...")
    pks_quote_url = f"https://routerv2.akka.finance/v2/{CHAIN_ID}/pks-quote"
    pks_params = {
        "src": USDC_ADDRESS,
        "dst": USDT_ADDRESS,
        "amount": str(amount_in_wei),
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(pks_quote_url, params=pks_params)

            logging.info(f"PKS Quote Response Status: {response.status_code}")
            logging.info(f"PKS Quote Response Headers: {response.headers}")
            
            if response.status_code == 200:
                quote_data = response.json()
                logging.info(f"✅ PKS Quote successful!")
                logging.info(f"Quote data: {quote_data}")
                return quote_data
            else:
                logging.error(f"❌ PKS Quote failed with status {response.status_code}")
                logging.error(f"Response: {response.text}")
                return None

    except httpx.RequestError as e:
        logging.error(f"❌ HTTP request to AKKA PKS Quote API failed: {e}")
        return None
    except Exception as e:
        logging.error(f"❌ Unexpected error: {e}")
        return None

async def test_different_pairs():
    """Test different token pairs to see which ones work"""
    logging.info("--- Testing different token pairs ---")
    
    amount_in_wei = int(SWAP_AMOUNT_USDC * (10**6))
    
    test_pairs = [
        ("USDC -> USDT", USDC_ADDRESS, USDT_ADDRESS),
        ("USDC -> SOLVBTC", USDC_ADDRESS, SOLVBTC_ADDRESS),
        ("USDT -> USDC", USDT_ADDRESS, USDC_ADDRESS),
    ]
    
    for pair_name, src, dst in test_pairs:
        logging.info(f"\nTesting {pair_name}:")
        pks_quote_url = f"https://routerv2.akka.finance/v2/{CHAIN_ID}/pks-quote"
        pks_params = {
            "src": src,
            "dst": dst,
            "amount": str(amount_in_wei),
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(pks_quote_url, params=pks_params)
                
                if response.status_code == 200:
                    quote_data = response.json()
                    logging.info(f"✅ {pair_name} - Success: {quote_data}")
                else:
                    logging.error(f"❌ {pair_name} - Failed: Status {response.status_code}")
                    logging.error(f"Response: {response.text}")

        except Exception as e:
            logging.error(f"❌ {pair_name} - Error: {e}")

async def main():
    logging.info("=== AKKA PKS Quote Test ===")
    
    # Test main PKS quote
    quote_result = await test_pks_quote()
    
    # Test different pairs
    await test_different_pairs()
    
    if quote_result:
        logging.info("✅ PKS Quote test completed successfully!")
    else:
        logging.info("❌ PKS Quote test failed")

if __name__ == "__main__":
    asyncio.run(main()) 