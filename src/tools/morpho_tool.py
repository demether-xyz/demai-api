"""
Morpho Blue strategy implementation with contract definitions and helper functions.
- Mirrors the structure & ergonomics of your Aave V3 module.
- Focused on *lending* (supply) and *withdraw* flows via a ToolExecutor-based orchestrator.
"""

from typing import Optional, Dict, Any, List, Tuple, Union
from web3 import Web3
from eth_abi import encode
import asyncio
import logging
import json
import os
import math
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# --------------------------------------------------------
# Core addresses (Morpho singleton) by chain_id
# Keep vanity address; extend mapping as you enable chains.
# --------------------------------------------------------
MORPHO_CONTRACTS = {
    1:    {"morpho": "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"},  # Ethereum
    8453: {"morpho": "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"},  # Base
    42161:{"morpho": "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"},  # Arbitrum
    747474:{"morpho": "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"},  # Katana (placeholder vanity)
    # Add others if you run them; the address is shared across many L2s
}

SECONDS_PER_YEAR = 31_536_000
WAD = 10**18

# --------------------------------------------------------
# Minimal ABIs (only functions we call)
# --------------------------------------------------------

# IMorpho core subset
MORPHO_ABI = [
    # supply((loan,collateral,oracle,irm,lltv), assets, shares, onBehalf, data)
    {
        "name": "supply",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "marketParams", "type": "tuple",
                "components": [
                    {"name":"loanToken","type":"address"},
                    {"name":"collateralToken","type":"address"},
                    {"name":"oracle","type":"address"},
                    {"name":"irm","type":"address"},
                    {"name":"lltv","type":"uint256"},
                ]
            },
            {"name":"assets","type":"uint256"},
            {"name":"shares","type":"uint256"},
            {"name":"onBehalf","type":"address"},
            {"name":"data","type":"bytes"},
        ],
        "outputs": [
            {"name":"assetsSupplied","type":"uint256"},
            {"name":"sharesSupplied","type":"uint256"},
        ]
    },
    # withdraw((...), assets, shares, onBehalf, receiver)
    {
        "name": "withdraw",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "marketParams", "type": "tuple",
                "components": [
                    {"name":"loanToken","type":"address"},
                    {"name":"collateralToken","type":"address"},
                    {"name":"oracle","type":"address"},
                    {"name":"irm","type":"address"},
                    {"name":"lltv","type":"uint256"},
                ]
            },
            {"name":"assets","type":"uint256"},
            {"name":"shares","type":"uint256"},
            {"name":"onBehalf","type":"address"},
            {"name":"receiver","type":"address"},
        ],
        "outputs": [
            {"name":"assetsWithdrawn","type":"uint256"},
            {"name":"sharesWithdrawn","type":"uint256"},
        ]
    },
    # view: market(id) -> Market struct
    {
        "name":"market",
        "type":"function",
        "stateMutability":"view",
        "inputs":[{"name":"id","type":"bytes32"}],
        "outputs":[
            {
                "name":"m","type":"tuple",
                "components":[
                    {"name":"totalSupplyAssets","type":"uint128"},
                    {"name":"totalSupplyShares","type":"uint128"},
                    {"name":"totalBorrowAssets","type":"uint128"},
                    {"name":"totalBorrowShares","type":"uint128"},
                    {"name":"lastUpdate","type":"uint128"},
                    {"name":"fee","type":"uint128"}
                ]
            }
        ]
    },
    # view: idToMarketParams(id) -> MarketParams
    {
        "name":"idToMarketParams",
        "type":"function",
        "stateMutability":"view",
        "inputs":[{"name":"id","type":"bytes32"}],
        "outputs":[
            {
                "name":"marketParams","type":"tuple",
                "components":[
                    {"name":"loanToken","type":"address"},
                    {"name":"collateralToken","type":"address"},
                    {"name":"oracle","type":"address"},
                    {"name":"irm","type":"address"},
                    {"name":"lltv","type":"uint256"},
                ]
            }
        ]
    },
    # view: position(id, user) -> (supplyShares, borrowShares, collateral)
    {
        "name":"position",
        "type":"function",
        "stateMutability":"view",
        "inputs":[
            {"name":"id","type":"bytes32"},
            {"name":"user","type":"address"}
        ],
        "outputs":[
            {"name":"supplyShares","type":"uint256"},
            {"name":"borrowShares","type":"uint128"},
            {"name":"collateral","type":"uint128"},
        ]
    },
]

# IIrm subset (AdaptiveCurveIRM, etc.)
IRM_ABI = [
    # borrowRateView(MarketParams, Market) -> uint256 (per-second WAD)
    {
        "name":"borrowRateView",
        "type":"function",
        "stateMutability":"view",
        "inputs":[
            {
                "name":"marketParams","type":"tuple",
                "components":[
                    {"name":"loanToken","type":"address"},
                    {"name":"collateralToken","type":"address"},
                    {"name":"oracle","type":"address"},
                    {"name":"irm","type":"address"},
                    {"name":"lltv","type":"uint256"},
                ]
            },
            {
                "name":"market","type":"tuple",
                "components":[
                    {"name":"totalSupplyAssets","type":"uint128"},
                    {"name":"totalSupplyShares","type":"uint128"},
                    {"name":"totalBorrowAssets","type":"uint128"},
                    {"name":"totalBorrowShares","type":"uint128"},
                    {"name":"lastUpdate","type":"uint128"},
                    {"name":"fee","type":"uint128"}
                ]
            }
        ],
        "outputs":[{"name":"","type":"uint256"}]
    }
]

# Minimal ERC20 for decimals + approve
ERC20_ABI = [
    {"name":"decimals","type":"function","inputs":[],"outputs":[{"name":"","type":"uint8"}],"stateMutability":"view"},
    {"name":"approve","type":"function","inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable"},
]

# EIP-4626 Vault ABI for MetaMorpho vaults
VAULT_4626_ABI = [
    {"name":"asset","type":"function","inputs":[],"outputs":[{"name":"","type":"address"}],"stateMutability":"view"},
    {"name":"totalAssets","type":"function","inputs":[],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
    {"name":"deposit","type":"function","inputs":[{"name":"assets","type":"uint256"},{"name":"receiver","type":"address"}],"outputs":[{"name":"shares","type":"uint256"}],"stateMutability":"nonpayable"},
    {"name":"withdraw","type":"function","inputs":[{"name":"assets","type":"uint256"},{"name":"receiver","type":"address"},{"name":"owner","type":"address"}],"outputs":[{"name":"shares","type":"uint256"}],"stateMutability":"nonpayable"},
    {"name":"redeem","type":"function","inputs":[{"name":"shares","type":"uint256"},{"name":"receiver","type":"address"},{"name":"owner","type":"address"}],"outputs":[{"name":"assets","type":"uint256"}],"stateMutability":"nonpayable"},
    {"name":"balanceOf","type":"function","inputs":[{"name":"account","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"},
]

# --------------------------------------------------------
# Cache service (parallel to your Aave cache)
# --------------------------------------------------------

class MorphoYieldCacheService:
    """
    Cache service for Morpho market yields (per market_id per chain) with TTL.
    """
    def __init__(self, db: Optional[AsyncIOMotorDatabase] = None, cache_ttl_hours: int = 3):
        self.db = db
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = asyncio.Lock()
        if self.db is not None:
            asyncio.create_task(self._ensure_indexes())

    async def _ensure_indexes(self):
        try:
            col = self.db.morpho_yield_cache
            await col.create_index([("market_id", 1), ("chain_id", 1)], unique=True)
            await col.create_index("timestamp")
        except Exception as e:
            logger.error(f"Error creating Morpho cache indexes: {e}")

    @staticmethod
    def _key(market_id: str, chain_id: int) -> str:
        return f"{market_id}:{chain_id}"

    def _valid(self, ts: datetime) -> bool:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts) < self.cache_ttl

    async def get(self, market_id: str, chain_id: int) -> Optional[Dict[str, Any]]:
        key = self._key(market_id, chain_id)
        if key in self._memory_cache and self._valid(self._memory_cache[key]["timestamp"]):
            return self._memory_cache[key]["data"]
        if self.db:
            col = self.db.morpho_yield_cache
            doc = await col.find_one({"market_id": market_id, "chain_id": chain_id})
            if doc and self._valid(doc["timestamp"]):
                async with self._cache_lock:
                    self._memory_cache[key] = {"data": doc["data"], "timestamp": doc["timestamp"]}
                return doc["data"]
            elif doc:
                await col.delete_one({"market_id": market_id, "chain_id": chain_id})
        return None

    async def set(self, market_id: str, chain_id: int, data: Dict[str, Any]):
        ts = datetime.now(timezone.utc)
        key = self._key(market_id, chain_id)
        async with self._cache_lock:
            self._memory_cache[key] = {"data": data, "timestamp": ts}
        if self.db:
            col = self.db.morpho_yield_cache
            await col.update_one(
                {"market_id": market_id, "chain_id": chain_id},
                {"$set": {"market_id": market_id, "chain_id": chain_id, "data": data, "timestamp": ts}},
                upsert=True
            )

    async def clear(self, market_id: Optional[str] = None, chain_id: Optional[int] = None):
        if market_id and chain_id:
            key = self._key(market_id, chain_id)
            async with self._cache_lock:
                self._memory_cache.pop(key, None)
            if self.db:
                await self.db.morpho_yield_cache.delete_one({"market_id": market_id, "chain_id": chain_id})
        else:
            async with self._cache_lock:
                self._memory_cache.clear()
            if self.db:
                try:
                    await self.db.morpho_yield_cache.delete_many({})
                    logger.info("Cleared all Morpho yield cache")
                except Exception as e:
                    logger.error(f"Error clearing all Morpho cache: {e}")

# --------------------------------------------------------
# Minimal supply/withdraw helpers and tool wrapper
# --------------------------------------------------------

def _encode_morpho_supply(market_params: tuple, assets: int, on_behalf: str) -> bytes:
    """Encode Morpho Blue supply((...),assets,shares,onBehalf,data) call.
    shares=0, data=b''
    """
    selector = Web3.keccak(text="supply((address,address,address,address,uint256),uint256,uint256,address,bytes)")[:4]
    encoded = encode(
        [
            '(address,address,address,address,uint256)',
            'uint256',
            'uint256',
            'address',
            'bytes'
        ],
        [
            market_params,
            assets,
            0,
            Web3.to_checksum_address(on_behalf),
            b''
        ]
    )
    return selector + encoded


def _encode_morpho_withdraw(market_params: tuple, assets: int, on_behalf: str, receiver: str) -> bytes:
    """Encode Morpho Blue withdraw((...),assets,shares,onBehalf,receiver) call.
    shares=0
    """
    selector = Web3.keccak(text="withdraw((address,address,address,address,uint256),uint256,uint256,address,address)")[:4]
    encoded = encode(
        [
            '(address,address,address,address,uint256)',
            'uint256',
            'uint256',
            'address',
            'address'
        ],
        [
            market_params,
            assets,
            0,
            Web3.to_checksum_address(on_behalf),
            Web3.to_checksum_address(receiver)
        ]
    )
    return selector + encoded


def _get_morpho_contract_address(chain_id: int) -> Optional[str]:
    contracts = MORPHO_CONTRACTS.get(chain_id)
    return contracts.get("morpho") if contracts else None


def _encode_vault_deposit(assets: int, receiver: str) -> bytes:
    """Encode EIP-4626 vault deposit(assets, receiver) call."""
    selector = Web3.keccak(text="deposit(uint256,address)")[:4]
    encoded = encode(
        ['uint256', 'address'],
        [assets, Web3.to_checksum_address(receiver)]
    )
    return selector + encoded


def _encode_vault_withdraw(assets: int, receiver: str, owner: str) -> bytes:
    """Encode EIP-4626 vault withdraw(assets, receiver, owner) call."""
    selector = Web3.keccak(text="withdraw(uint256,address,address)")[:4]
    encoded = encode(
        ['uint256', 'address', 'address'],
        [assets, Web3.to_checksum_address(receiver), Web3.to_checksum_address(owner)]
    )
    return selector + encoded


async def _is_metamorpho_vault(executor, vault_address: str) -> bool:
    """Check if address is a MetaMorpho vault by trying to call asset()."""
    try:
        vault_contract = executor.w3.eth.contract(
            address=Web3.to_checksum_address(vault_address),
            abi=VAULT_4626_ABI
        )
        await vault_contract.functions.asset().call()
        return True
    except:
        return False


async def _get_market_params_from_id(executor, morpho_address: str, market_id_hex: str) -> Optional[tuple]:
    """Fetch MarketParams tuple from Morpho by market id (bytes32 hex)."""
    try:
        contract = executor.w3.eth.contract(address=Web3.to_checksum_address(morpho_address), abi=MORPHO_ABI)
        market_id_bytes = bytes.fromhex(market_id_hex[2:]) if market_id_hex.startswith("0x") else bytes.fromhex(market_id_hex)
        mp = await contract.functions.idToMarketParams(market_id_bytes).call()
        # tuple order must match ABI: (loanToken, collateralToken, oracle, irm, lltv)
        return (
            Web3.to_checksum_address(mp[0]),
            Web3.to_checksum_address(mp[1]),
            Web3.to_checksum_address(mp[2]),
            Web3.to_checksum_address(mp[3]),
            int(mp[4])
        )
    except Exception as e:
        logger.error(f"Error fetching market params for id {market_id_hex}: {e}")
        return None


async def supply_to_morpho(
    executor,
    chain_id: int,
    vault_address: str,
    market_id: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """Supply assets to Morpho Blue through the vault."""
    morpho_address = _get_morpho_contract_address(chain_id)
    if not morpho_address:
        raise ValueError(f"Morpho not supported on chain {chain_id}")

    market_params = await _get_market_params_from_id(executor, morpho_address, market_id)
    if not market_params:
        raise ValueError("Unable to fetch market params for given market_id")

    loan_token = market_params[0]
    call_data = _encode_morpho_supply(market_params, amount, vault_address)
    approvals = [(loan_token, amount)]

    tx_hash = await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=morpho_address,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )
    return tx_hash


async def withdraw_from_morpho(
    executor,
    chain_id: int,
    vault_address: str,
    market_id: str,
    amount: int,
    gas_limit: Optional[int] = None
) -> str:
    """Withdraw assets from Morpho Blue through the vault."""
    morpho_address = _get_morpho_contract_address(chain_id)
    if not morpho_address:
        raise ValueError(f"Morpho not supported on chain {chain_id}")

    market_params = await _get_market_params_from_id(executor, morpho_address, market_id)
    if not market_params:
        raise ValueError("Unable to fetch market params for given market_id")

    call_data = _encode_morpho_withdraw(market_params, amount, vault_address, vault_address)
    approvals: List[tuple] = []

    tx_hash = await executor.execute_strategy(
        vault_address=vault_address,
        target_contract=morpho_address,
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )
    return tx_hash


async def deposit_to_metamorpho_vault(
    executor,
    vault_address: str,
    asset_token: str,
    amount: int,
    target_vault: str,
    gas_limit: Optional[int] = None
) -> str:
    """Deposit assets to MetaMorpho vault through the strategy vault."""
    # Encode call to deposit(amount, receiver) on the MetaMorpho vault
    call_data = _encode_vault_deposit(amount, vault_address)
    
    # Approve the MetaMorpho vault to spend our AUSD tokens
    approvals = [(asset_token, amount)]
    
    # Add debug logging
    logger.info(f"Depositing {amount} wei of {asset_token} to vault {target_vault}")
    logger.info(f"Using strategy vault: {vault_address}")
    logger.info(f"Call data: {call_data.hex()}")
    
    tx_hash = await executor.execute_strategy(
        vault_address=vault_address,  # Strategy vault that executes
        target_contract=target_vault,  # MetaMorpho vault we're calling
        call_data=call_data,
        approvals=approvals,  # Approve MetaMorpho vault to spend AUSD
        gas_limit=gas_limit
    )
    return tx_hash


async def withdraw_from_metamorpho_vault(
    executor,
    vault_address: str,
    amount: int,
    target_vault: str,
    gas_limit: Optional[int] = None
) -> str:
    """Withdraw assets from MetaMorpho vault."""
    call_data = _encode_vault_withdraw(amount, vault_address, vault_address)
    approvals: List[tuple] = []  # No approvals needed for withdraw
    
    tx_hash = await executor.execute_strategy(
        vault_address=vault_address,  # Strategy vault
        target_contract=target_vault,  # MetaMorpho vault we're withdrawing from
        call_data=call_data,
        approvals=approvals,
        gas_limit=gas_limit
    )
    return tx_hash


def create_morpho_tool(
    vault_address: str,
    private_key: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Morpho tool following the Aave tool pattern.

    The returned async function expects: chain_name, token_symbol, amount, action, market_id (hex bytes32).
    For Morpho, a market_id is required to locate the correct market.
    """
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
    from tools.tool_executor import ToolExecutor

    if not private_key:
        # Try environment first
        private_key = os.getenv("PRIVATE_KEY")
        
        # If not found, try to load from keychain
        if not private_key and os.getenv("LOAD_KEYCHAIN_SECRETS") == "1":
            try:
                from config import load_keychain_secrets
                load_keychain_secrets()
                private_key = os.getenv("PRIVATE_KEY")
            except Exception as e:
                logger.warning(f"Could not load keychain secrets: {e}")
        
        if not private_key:
            raise ValueError("PRIVATE_KEY not provided and not found in environment or keychain")

    async def morpho_operation(
        chain_name: str,
        token_symbol: str,
        amount: float,
        action: str = "supply",
        market_id: Optional[str] = None
    ) -> str:
        try:
            # Resolve chain_id
            chain_id = None
            for c_id, config in CHAIN_CONFIG.items():
                if config["name"].lower() == chain_name.lower():
                    chain_id = c_id
                    break
            if chain_id is None:
                return json.dumps({"status": "error", "message": f"Unknown chain name: {chain_name}"})

            # Validate token
            token_conf = SUPPORTED_TOKENS.get(token_symbol.upper())
            if not token_conf:
                return json.dumps({"status": "error", "message": f"Unsupported token: {token_symbol}"})
            token_address = token_conf["addresses"].get(chain_id)
            if not token_address:
                return json.dumps({"status": "error", "message": f"Token {token_symbol} not available on {chain_name}"})

            # Amount to wei
            decimals = token_conf["decimals"]
            amount_wei = int(amount * (10 ** decimals))

            # Setup executor
            rpc_url = RPC_ENDPOINTS.get(chain_id)
            if not rpc_url:
                return json.dumps({"status": "error", "message": f"RPC URL not found for chain {chain_name}"})
            
            executor = ToolExecutor(rpc_url, private_key)

            # Check if market_id is a MetaMorpho vault or direct Morpho market
            if market_id and len(market_id) == 42 and market_id.startswith("0x"):
                # Looks like an address - check if it's a MetaMorpho vault
                is_vault = await _is_metamorpho_vault(executor, market_id)
                
                if is_vault:
                    logging.info(f"Detected MetaMorpho vault: {market_id}")
                    # Use vault functions
                    if action == "supply":
                        tx_hash = await deposit_to_metamorpho_vault(
                            executor=executor,
                            vault_address=vault_address,  # Strategy vault that executes the deposit
                            asset_token=token_address,
                            amount=amount_wei,
                            target_vault=market_id  # MetaMorpho vault we're depositing to
                        )
                        message = f"Successfully deposited {amount} {token_symbol} to MetaMorpho vault on {chain_name}"
                    elif action == "withdraw":
                        tx_hash = await withdraw_from_metamorpho_vault(
                            executor=executor,
                            vault_address=vault_address,  # Strategy vault
                            amount=amount_wei,
                            target_vault=market_id  # MetaMorpho vault
                        )
                        message = f"Successfully withdrew {amount} {token_symbol} from MetaMorpho vault on {chain_name}"
                    else:
                        return json.dumps({"status": "error", "message": f"Invalid action: {action}"})
                else:
                    return json.dumps({
                        "status": "error", 
                        "message": f"Address {market_id} is not a valid MetaMorpho vault or market"
                    })
            else:
                # Traditional 32-byte market ID - use direct Morpho functions
                if not market_id:
                    return json.dumps({
                        "status": "error",
                        "message": "Missing required parameter 'market_id' for Morpho market."
                    })

                if action == "supply":
                    tx_hash = await supply_to_morpho(
                        executor=executor,
                        chain_id=chain_id,
                        vault_address=vault_address,
                        market_id=market_id,
                        amount=amount_wei
                    )
                    message = f"Successfully supplied {amount} {token_symbol} to Morpho on {chain_name}"
                elif action == "withdraw":
                    tx_hash = await withdraw_from_morpho(
                        executor=executor,
                        chain_id=chain_id,
                        vault_address=vault_address,
                        market_id=market_id,
                        amount=amount_wei
                    )
                    message = f"Successfully withdrew {amount} {token_symbol} from Morpho on {chain_name}"
                else:
                    return json.dumps({"status": "error", "message": f"Invalid action: {action}"})

            return json.dumps({
                "status": "success",
                "message": message,
                "data": {
                    "action": action,
                    "token": token_symbol,
                    "amount": amount,
                    "chain": chain_name,
                    "vault": vault_address,
                    "tx_hash": tx_hash
                }
            })

        except Exception as e:
            logger.error(f"Error in morpho_operation: {e}")
            return json.dumps({"status": "error", "message": f"Failed to {action}: {str(e)}"})

    return {
        "tool": morpho_operation,
        "metadata": {
            "name": "morpho_lending",
            "description": "Supply or withdraw tokens on Morpho Blue markets or MetaMorpho vaults. Supports both direct markets and managed vaults.",
            "vault": vault_address,
            "parameters": {
                "chain_name": "Blockchain network (e.g., 'Katana')",
                "token_symbol": "Token symbol (e.g., AUSD)",
                "amount": "Amount in human-readable format",
                "action": "'supply' or 'withdraw'",
                "market_id": "Morpho market id (bytes32 hex) or MetaMorpho vault address (e.g., 0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD)"
            }
        }
    }
