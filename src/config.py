import sys
import logging
import os
from dotenv import load_dotenv

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(name)-10s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)

# Create logger instance
logger = logging.getLogger()

load_dotenv()

# Keychain secrets configuration
# Format: (service_name, account_name, env_var_name)
# If env_var_name is None, account_name will be used
KEYCHAIN_SECRETS = [
    ("global", "OPENROUTER_API_KEY", None),
    ("demether", "PRIVATE_KEY", None),
]


def load_keychain_secrets():
    """Load secrets from keychain if enabled"""
    if os.getenv("LOAD_KEYCHAIN_SECRETS", "0") == "1":
        try:
            from keychain import load_secrets
            if load_secrets(KEYCHAIN_SECRETS):
                logger.info("Successfully loaded secrets from keychain")
            else:
                logger.warning("Failed to load some secrets from keychain")
        except Exception as e:
            logger.error(f"Error loading secrets from keychain: {e}")

# Load secrets before environment variables
load_keychain_secrets()

# Token configuration matching frontend tokens.ts
SUPPORTED_TOKENS = {
    "WBTC": {
        "symbol": "WBTC",
        "name": "Wrapped Bitcoin",
        "decimals": 8,
        "addresses": {
            42161: "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",  # Arbitrum
        },
        "coingeckoId": "wrapped-bitcoin",
    },
    "USDC": {
        "symbol": "USDC",
        "name": "USD Coin",
        "decimals": 6,
        "addresses": {
            42161: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # Arbitrum (native USDC)
        },
        "coingeckoId": "usd-coin",
    },
}

# Chain configuration
CHAIN_CONFIG = {
    42161: {
        "name": "Arbitrum",
        "rpc_url": os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
        "native_currency": {"symbol": "ETH", "name": "Ethereum", "decimals": 18, "coingeckoId": "ethereum"}
    }
}

# RPC endpoints configuration (derived from CHAIN_CONFIG)
RPC_ENDPOINTS = {
    chain_id: config["rpc_url"] 
    for chain_id, config in CHAIN_CONFIG.items()
}

# Native currencies for each chain (derived from CHAIN_CONFIG)
NATIVE_CURRENCIES = {
    chain_id: config["native_currency"] 
    for chain_id, config in CHAIN_CONFIG.items()
}

# ERC20 ABI for balance calls
ERC20_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]