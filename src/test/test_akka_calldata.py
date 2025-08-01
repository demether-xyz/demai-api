"""
Test file to verify Akka calldata construction.

This script tests the calldata construction for Akka's multiPathSwap function
using sample quote data.
"""
import json
import logging
from web3 import Web3
from strategies.akka_strategy import _construct_akka_swap_calldata

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Sample quote data from the API
SAMPLE_QUOTE_DATA = {
    "inputAmount": {
        "currency": {
            "address": "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1",
            "symbol": "USDT",
            "decimals": 6
        },
        "value": "100000"
    },
    "outputAmount": {
        "currency": {
            "address": "0x9410e8052Bc661041e5cB27fDf7d9e9e842af2aa",
            "symbol": "SolvBTC.CORE",
            "decimals": 18
        },
        "value": "914772538386"
    },
    "swapData": {
        "akkaFee": {
            "r": "0xc45b16e46c6f7533bfbd93190afd5c430bb902f4ba83fa7df0934cc383b61efe",
            "s": "0x2861a554f93a7009aac897c49327aa76bca4e20766877165a19ae416269c8225",
            "v": "28",
            "fee": "14"
        },
        "data": [
            [
                "90000",
                "818565713284",
                "0",
                "0",
                [
                    [
                        "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1",
                        "0x7A6888c85eDBA8E38F6C7E0485212da602761C08",
                        "0xC88a3B8F439BAd6Db4E30C4cc16f4216aDE7aE52",
                        "9970",
                        "90000",
                        "788935082671",
                        "10000",
                        "10000",
                        "0"
                    ]
                ]
            ],
            [
                "10000",
                "91632962409",
                "0",
                "0",
                [
                    [
                        "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1",
                        "0x40375C92d9FAf44d2f9db9Bd9ba41a3317a2404f",
                        "0xb5aC6a7f20e9ECF8CFEDF614741F78395c3F029d",
                        "9975",
                        "10000",
                        "21426007491296744",
                        "10000",
                        "10000",
                        "0"
                    ]
                ]
            ]
        ],
        "amountIn": "100000",
        "amountOutMin": "910198675694",
        "value": 0
    }
}


def test_calldata_construction():
    """Test the construction of Akka multiPathSwap calldata."""
    
    logging.info("--- Testing Akka Calldata Construction ---")
    
    # Test vault address
    vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
    
    try:
        # Construct calldata
        calldata = _construct_akka_swap_calldata(SAMPLE_QUOTE_DATA, vault_address)
        
        # Convert to hex string for display
        calldata_hex = "0x" + calldata.hex()
        
        logging.info(f"Successfully constructed calldata:")
        logging.info(f"Length: {len(calldata)} bytes")
        logging.info(f"First 10 bytes (function selector + start of params): {calldata_hex[:20]}")
        
        # Verify function selector
        expected_selector = Web3.keccak(text="multiPathSwap(uint256,uint256,(uint256,uint256,uint256,uint256,(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256)[])[],address,uint256,uint8,bytes32,bytes32)")[:4]
        actual_selector = calldata[:4]
        
        if actual_selector == expected_selector:
            logging.info("✅ Function selector matches expected multiPathSwap signature")
        else:
            logging.error(f"❌ Function selector mismatch!")
            logging.error(f"Expected: 0x{expected_selector.hex()}")
            logging.error(f"Actual: 0x{actual_selector.hex()}")
        
        # Display parsed parameters from the quote
        swap_data = SAMPLE_QUOTE_DATA["swapData"]
        akka_fee = swap_data["akkaFee"]
        
        logging.info("\nParsed parameters:")
        logging.info(f"  Amount In: {swap_data['amountIn']}")
        logging.info(f"  Amount Out Min: {swap_data['amountOutMin']}")
        logging.info(f"  Paths: {len(swap_data['data'])} paths")
        logging.info(f"  Receiver: {vault_address}")
        logging.info(f"  Fee: {akka_fee['fee']}")
        logging.info(f"  Signature v: {akka_fee['v']}")
        logging.info(f"  Signature r: {akka_fee['r'][:10]}...")
        logging.info(f"  Signature s: {akka_fee['s'][:10]}...")
        
        # Test with minimal quote data
        minimal_quote = {
            "swapData": {
                "amountIn": "1000000",
                "amountOutMin": "900000",
                "data": [],
                "akkaFee": {
                    "fee": "0",
                    "v": "0",
                    "r": "0x0000000000000000000000000000000000000000000000000000000000000000",
                    "s": "0x0000000000000000000000000000000000000000000000000000000000000000"
                }
            }
        }
        
        logging.info("\n--- Testing with minimal quote data ---")
        minimal_calldata = _construct_akka_swap_calldata(minimal_quote, vault_address)
        logging.info(f"✅ Successfully constructed calldata for minimal quote")
        logging.info(f"Length: {len(minimal_calldata)} bytes")
        
    except Exception as e:
        logging.error(f"❌ Failed to construct calldata: {e}", exc_info=True)
    
    logging.info("\n--- Calldata Construction Test Finished ---")


if __name__ == "__main__":
    test_calldata_construction()