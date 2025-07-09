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
    ("ezenciel", "MONGO_CONNECTION", None),
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
    "SOLVBTC": {
        "symbol": "SOLVBTC",
        "name": "SolvBTC",
        "decimals": 18,
        "addresses": {
            1116: "0x5B1Fb849f1F76217246B8AAAC053b5C7b15b7dc3",  # Core
        },
        "aave_atokens": {
            1116: "0x58e95162dBc71650BCac4AeAD39fe2d758Fc967C",  # aCoreSOLVBTC
        },
        "coingeckoId": "solvbtc",
    },
    "BTCB": {
        "symbol": "BTCB",
        "name": "Bitcoin",
        "decimals": 18,
        "addresses": {
            1116: "0x7a6888c85edba8e38f6c7e0485212da602761c08",  # Core
        },
        "aave_atokens": {
            1116: "0x7a6888c85edba8e38f6c7e0485212da602761c08",  # Colend BTCB
        },
        "coingeckoId": "bitcoin",
    },
    "WBTC": {
        "symbol": "WBTC",
        "name": "Wrapped Bitcoin",
        "decimals": 18,
        "addresses": {
            1116: "0x5832f53d147b3d6Cd4578B9CBD62425C7ea9d0Bd",  # Core
        },
        "aave_atokens": {
            1116: "0x2e3ea6cf100632A4A4B34F26681A6f50347775C9",  # aCoreWBTC
        },
        "coingeckoId": "wrapped-bitcoin",
    },
    "USDC": {
        "symbol": "USDC",
        "name": "USD Coin",
        "decimals": 6,
        "addresses": {
            42161: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # Arbitrum (native USDC)
            1116: "0xa4151B2B3e269645181dCcF2D426cE75fcbDeca9",  # Core
        },
        "aave_atokens": {
            42161: "0x724dc807b04555b71ed48a6896b6F41593b8C637",  # aArbUSDC
            1116: "0x8f9d6649C4ac1d894BB8A26c3eed8f1C9C5f82Dd",  # aToken address on Core
        },
        "coingeckoId": "usd-coin",
    },
    "USDT": {
        "symbol": "USDT",
        "name": "Tether USD",
        "decimals": 6,
        "addresses": {
            42161: "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",  # Arbitrum
            1116: "0x900101d06A7426441Ae63e9AB3B9b0F63Be145F1",  # Core
        },
        "aave_atokens": {
            42161: "0x6ab707Aca953eDAeFBc4fD23bA73294241490620",  # aArbUSDT
            1116: "0x98cD652fD1f5324A1AF6D64b3F6c8DCF2d8cd0D3",  # aCoreUSDT
        },
        "coingeckoId": "tether",
    },
}

# Chain configuration
CHAIN_CONFIG = {
    42161: {
        "name": "Arbitrum",
        "rpc_url": os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
        "native_currency": {"symbol": "ETH", "name": "Ethereum", "decimals": 18, "coingeckoId": "ethereum"}
    },
    1116: {
        "name": "Core",
        "rpc_url": os.getenv("CORE_RPC_URL", "https://rpc.coredao.org"),
        "native_currency": {"symbol": "CORE", "name": "Core", "decimals": 18, "coingeckoId": "core"}
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

# VaultFactory contract addresses (same address on all chains due to CREATE2)
VAULT_FACTORY_ADDRESS = "0x5C97F0a08a1c8a3Ed6C1E1dB2f7Ce08a4BFE53C7"

# VaultFactory ABI - only the methods we need
VAULT_FACTORY_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "vaultOwner", "type": "address"}],
        "name": "predictVaultAddress",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "getUserVault",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "user", "type": "address"}],
        "name": "hasVault",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    }
]