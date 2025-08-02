from typing import Dict, List, Optional, Any, TYPE_CHECKING
from decimal import Decimal
import logging
import asyncio
import datetime
from datetime import timezone
from utils.coingecko_util import CoinGeckoUtil
from config import SUPPORTED_TOKENS, RPC_ENDPOINTS, NATIVE_CURRENCIES, ERC20_ABI, CHAIN_CONFIG, VAULT_FACTORY_ADDRESS, VAULT_FACTORY_ABI, VAULT_ABI
from services.asset_config import ASSET_BALANCE_CHECKERS

if TYPE_CHECKING:
    from web3 import Web3
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class PortfolioService:
    """Service for fetching portfolio balances and calculating total value"""
    
    def __init__(self, db: Optional["AsyncIOMotorDatabase"] = None, cache_ttl_seconds: int = 300):
        # Now only accepts database directly
        self.db = db
        self.cache_ttl = datetime.timedelta(seconds=cache_ttl_seconds)
        self.coingecko = CoinGeckoUtil(self.db)
        self.web3_instances = {}
        self.Web3 = None
        
        # In-memory cache for portfolio data
        self._memory_cache = {}
        
        self._import_web3()
        self._initialize_web3_connections()
    
    def _import_web3(self):
        """Safely import web3 library"""
        try:
            from web3 import Web3
            self.Web3 = Web3
        except ImportError:
            logger.error("web3 package not available")
            self.Web3 = None
    
    def _initialize_web3_connections(self):
        """Initialize Web3 connections for all supported chains"""
        if not self.Web3:
            logger.error("Web3 not available - cannot initialize connections")
            return
        
        # Initialize connections asynchronously to avoid blocking startup
        import threading
        
        def init_connections():
            for chain_id, rpc_url in RPC_ENDPOINTS.items():
                try:
                    w3 = self.Web3(self.Web3.HTTPProvider(rpc_url))
                    # Quick connection test with timeout
                    try:
                        w3.eth.get_block_number()  # Fast test
                        self.web3_instances[chain_id] = w3
                        logger.info(f"Connected to chain {chain_id}")
                    except Exception as e:
                        logger.warning(f"Failed to connect to chain {chain_id}: {e}")
                except Exception as e:
                    logger.error(f"Error creating Web3 instance for chain {chain_id}: {e}")
        
        # Run connection initialization in background thread
        thread = threading.Thread(target=init_connections, daemon=True)
        thread.start()
        logger.info("Web3 connections initializing in background...")
    
    async def ensure_web3_connections(self):
        """Ensure Web3 connections are ready, with retry logic"""
        max_retries = 3  # Reduced retries since we'll proceed with available chains
        retry_delay = 0.5  # Shorter delay
        
        for attempt in range(max_retries):
            if len(self.web3_instances) > 0:
                connected_chains = set(self.web3_instances.keys())
                logger.info(f"Web3 connections ready: {sorted(connected_chains)}")
                return True
            
            logger.info(f"Waiting for Web3 connections... (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(retry_delay)
        
        # Log final connection status
        if self.web3_instances:
            connected_chains = set(self.web3_instances.keys())
            expected_chains = set(RPC_ENDPOINTS.keys())
            missing_chains = expected_chains - connected_chains
            
            logger.info(f"Proceeding with available connections: {sorted(connected_chains)}")
            if missing_chains:
                logger.warning(f"Missing connections (will retry later): {sorted(missing_chains)}")
        else:
            logger.error("No Web3 connections available")
        
        return len(self.web3_instances) > 0
    
    async def warm_cache_for_vault(self, vault_address: str):
        """Warm the cache for a specific vault address"""
        try:
            logger.info(f"Warming cache for vault {vault_address}")
            await self.get_portfolio_summary(vault_address=vault_address)
            logger.info(f"Cache warmed for vault {vault_address}")
        except Exception as e:
            logger.error(f"Error warming cache for vault {vault_address}: {e}")
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        memory_cache_size = len(self._memory_cache)
        
        db_cache_size = 0
        if self.db is not None:
            try:
                cache_collection = self.db.portfolio_cache
                db_cache_size = await cache_collection.count_documents({})
            except Exception as e:
                logger.error(f"Error getting database cache size: {e}")
        
        return {
            "memory_cache_entries": memory_cache_size,
            "database_cache_entries": db_cache_size,
            "cache_ttl_seconds": self.cache_ttl.total_seconds(),
            "web3_connections": len(self.web3_instances),
            "available_chains": list(self.web3_instances.keys())
        }
    
    async def clear_portfolio_cache(self, vault_address: Optional[str] = None):
        """Clear all caches (memory and DB) for a specific vault or all vaults."""
        # Clear memory cache
        if vault_address:
            if vault_address in self._memory_cache:
                del self._memory_cache[vault_address]
                logger.info(f"Cleared memory cache for vault {vault_address}")
        else:
            self._memory_cache.clear()
            logger.info("Cleared all memory cache")

        # Clear database cache
        if self.db is not None:
            cache_collection = self.db.portfolio_cache
            try:
                if vault_address:
                    await cache_collection.delete_one({"vault_address": vault_address})
                    logger.info(f"Cleared database cache for vault {vault_address}")
                else:
                    await cache_collection.delete_many({})
                    logger.info("Cleared all database cache")
            except Exception as e:
                logger.error(f"Error clearing database cache: {e}")
    
    def clear_memory_cache(self, vault_address: Optional[str] = None):
        """Clear memory cache for a specific vault or all vaults"""
        if vault_address:
            if vault_address in self._memory_cache:
                del self._memory_cache[vault_address]
                logger.info(f"Cleared memory cache for vault {vault_address}")
        else:
            self._memory_cache.clear()
            logger.info("Cleared all memory cache")
    
    async def _ensure_database_indexes(self):
        """Ensure database indexes exist for optimal performance"""
        if self.db is None:
            return
        
        try:
            # Index for wallet-vault mapping
            wallet_vault_collection = self.db.wallet_vault_mapping
            await wallet_vault_collection.create_index("wallet_address", unique=True)
            
            # Index for portfolio cache
            cache_collection = self.db.portfolio_cache
            await cache_collection.create_index("vault_address", unique=True)
            await cache_collection.create_index("timestamp")  # For TTL cleanup
            
            logger.info("Database indexes ensured for portfolio service")
        except Exception as e:
            logger.error(f"Error creating database indexes: {e}")

    async def _get_vault_from_database(self, wallet_address: str) -> Optional[str]:
        """Get vault address from database cache"""
        if self.db is None:
            return None
            
        try:
            # Ensure indexes exist (idempotent operation)
            await self._ensure_database_indexes()
            
            wallet_vault_collection = self.db.wallet_vault_mapping
            result = await wallet_vault_collection.find_one({"wallet_address": wallet_address})
            
            if result and "vault_address" in result:
                logger.info(f"Found cached vault address for wallet {wallet_address}: {result['vault_address']}")
                return result["vault_address"]
                
        except Exception as e:
            logger.error(f"Error querying database for wallet {wallet_address}: {e}")
            
        return None
    
    async def _save_vault_to_database(self, wallet_address: str, vault_address: str):
        """Save wallet-vault mapping to database"""
        if self.db is None:
            return
            
        try:
            wallet_vault_collection = self.db.wallet_vault_mapping
            await wallet_vault_collection.update_one(
                {"wallet_address": wallet_address},
                {
                    "$set": {
                        "wallet_address": wallet_address,
                        "vault_address": vault_address,
                        "timestamp": datetime.datetime.now(timezone.utc)
                    }
                },
                upsert=True
            )
            logger.info(f"Saved vault mapping: {wallet_address} -> {vault_address}")
            
        except Exception as e:
            logger.error(f"Error saving vault mapping to database: {e}")
    
    async def _get_vault_from_chain(self, wallet_address: str) -> Optional[str]:
        """Get vault address from VaultFactory contract on Arbitrum (works for all chains due to CREATE2)"""
        if not self.Web3:
            logger.error("Web3 not available for on-chain vault lookup")
            return None
            
        try:
            # Use Arbitrum as the reference chain (42161) since all factories have same address
            arbitrum_chain_id = 42161
            w3 = self.web3_instances.get(arbitrum_chain_id)
            
            if not w3:
                logger.error(f"Web3 instance not available for chain {arbitrum_chain_id}")
                return None
            
            # Create VaultFactory contract instance
            factory_contract = w3.eth.contract(
                address=self.Web3.to_checksum_address(VAULT_FACTORY_ADDRESS),
                abi=VAULT_FACTORY_ABI
            )
            
            # Check if user has a vault
            wallet_checksum = self.Web3.to_checksum_address(wallet_address)
            has_vault = factory_contract.functions.hasVault(wallet_checksum).call()
            
            if has_vault:
                # Get the actual vault address
                vault_address = factory_contract.functions.getUserVault(wallet_checksum).call()
                logger.info(f"Found vault on-chain for wallet {wallet_address}: {vault_address}")
                return vault_address
            else:
                # Predict what the vault address would be if deployed
                predicted_vault = factory_contract.functions.predictVaultAddress(wallet_checksum).call()
                logger.info(f"No vault deployed for wallet {wallet_address}, predicted address: {predicted_vault}")
                return predicted_vault
                
        except Exception as e:
            logger.error(f"Error getting vault from chain for wallet {wallet_address}: {e}")
            return None
    
    async def _resolve_vault_address(self, wallet_address: str) -> Optional[str]:
        """
        Resolve vault address for a wallet address using:
        1. Database cache lookup
        2. On-chain VaultFactory contract call
        3. Save result to database for future use
        """
        if not wallet_address:
            logger.error("No wallet address provided for vault resolution")
            return None
            
        try:
            logger.info(f"Starting vault resolution for wallet: {wallet_address}")
            
            # Normalize wallet address - handle different cases
            if not self.Web3:
                logger.error("Web3 not available for address normalization")
                return None
                
            # Check if address is valid format
            if not wallet_address.startswith('0x') or len(wallet_address) != 42:
                logger.error(f"Invalid wallet address format: {wallet_address} (length: {len(wallet_address)})")
                return None
                
            wallet_address = self.Web3.to_checksum_address(wallet_address)
            logger.info(f"Normalized wallet address: {wallet_address}")
            
            # Step 1: Check database cache
            logger.info("Step 1: Checking database cache...")
            cached_vault = await self._get_vault_from_database(wallet_address)
            if cached_vault:
                logger.info(f"Found cached vault address: {cached_vault}")
                return cached_vault
            
            # Step 2: Query on-chain
            logger.info("Step 2: Querying on-chain...")
            vault_address = await self._get_vault_from_chain(wallet_address)
            if vault_address:
                logger.info(f"Resolved vault address from chain: {vault_address}")
                # Step 3: Save to database for future use
                await self._save_vault_to_database(wallet_address, vault_address)
                return vault_address
                
            logger.warning(f"Could not resolve vault address for wallet {wallet_address}")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving vault address for wallet {wallet_address}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    async def get_portfolio_summary(self, vault_address: Optional[str] = None, wallet_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Get complete portfolio summary for a vault address or wallet address including balances and USD values
        Uses optimized batch balance queries - one call per chain
        """
        if not self.Web3:
            return {
                "total_value_usd": 0.0,
                "chains": {},
                "strategies": {},
                "summary": {"error": "Web3 not available"},
            }

        # Ensure Web3 connections are ready
        connections_ready = await self.ensure_web3_connections()
        if not connections_ready:
            return {
                "total_value_usd": 0.0,
                "chains": {},
                "strategies": {},
                "summary": {"error": "Web3 connections not ready"},
            }

        target_address = None
        if vault_address:
            target_address = self.Web3.to_checksum_address(vault_address)
        elif wallet_address:
            resolved_vault = await self._resolve_vault_address(wallet_address)
            if resolved_vault:
                target_address = self.Web3.to_checksum_address(resolved_vault)

        if not target_address:
            return {
                "total_value_usd": 0.0,
                "chains": {},
                "strategies": {},
                "summary": {"error": "Could not determine vault address"},
            }
            
        cached_data = await self._get_from_cache(target_address)
        if cached_data:
            logger.info(f"Returning cached portfolio for {target_address}")
            return cached_data

        try:
            # Use optimized batch balance query - one call per chain
            logger.info(f"Using optimized batch balance queries for {target_address}")
            all_balances_task = self._get_all_token_balances(target_address)
            asset_balances_task = self._get_all_asset_balances(target_address)
            
            all_balances, all_asset_balances = await asyncio.gather(
                all_balances_task,
                asset_balances_task
            )
            
            # Use all balances (includes both native and token balances)
            all_holdings = all_balances
            
            all_holdings = [h for h in all_holdings if h.get("balance") and h["balance"] > 0]
            
            asset_holdings = [h for h in all_asset_balances if h.get("balance") and h["balance"] > 0]

            coingecko_ids = list(set(
                [h["coingeckoId"] for h in all_holdings if "coingeckoId" in h] +
                [h["coingeckoId"] for h in asset_holdings if "coingeckoId" in h]
            ))
            
            token_prices = await self._get_token_prices_async(coingecko_ids)

            total_value_usd = 0
            for holding in all_holdings:
                price = token_prices.get(holding.get("coingeckoId"))
                if price:
                    holding["price_usd"] = price
                    holding["value_usd"] = holding["balance"] * price
                    total_value_usd += holding["value_usd"]
            
            for holding in asset_holdings:
                price = token_prices.get(holding.get("coingeckoId"))
                if price:
                    holding["price_usd"] = price
                    holding["value_usd"] = holding["balance"] * price
                    total_value_usd += holding["value_usd"]
            
            formatted_portfolio = self._format_portfolio_output(
                target_address, 
                all_holdings, 
                asset_holdings,
                total_value_usd, 
                wallet_address
            )
            
            await self._put_in_cache(target_address, formatted_portfolio)
            
            return formatted_portfolio

        except Exception as e:
            logger.error(f"Error getting portfolio summary for address {target_address}: {e}")
            return {
                "total_value_usd": 0.0,
                "chains": {},
                "strategies": {},
                "summary": {"error": str(e)},
            }

    async def _get_from_cache(self, vault_address: str) -> Optional[Dict[str, Any]]:
        """Check memory cache first, then database cache for fresh data."""
        # Step 1: Check memory cache
        if vault_address in self._memory_cache:
            cached_entry = self._memory_cache[vault_address]
            is_stale = datetime.datetime.now(timezone.utc) - cached_entry['timestamp'] > self.cache_ttl
            if not is_stale:
                logger.info(f"Returning in-memory cached portfolio for address {vault_address}")
                return cached_entry['data']
            else:
                # Remove stale memory cache
                del self._memory_cache[vault_address]
                logger.info(f"Removed stale memory cache for address {vault_address}")
        
        # Step 2: Check database cache
        if self.db is not None:
            try:
                cache_collection = self.db.portfolio_cache
                result = await cache_collection.find_one({"vault_address": vault_address})
                
                if result and "data" in result and "timestamp" in result:
                    cached_timestamp = result["timestamp"]
                    is_db_stale = datetime.datetime.now(timezone.utc) - cached_timestamp > self.cache_ttl
                    
                    if not is_db_stale:
                        logger.info(f"Returning database cached portfolio for address {vault_address}")
                        # Also put back in memory cache for faster future access
                        portfolio_data = result["data"]
                        self._memory_cache[vault_address] = {
                            'data': portfolio_data,
                            'timestamp': cached_timestamp
                        }
                        return portfolio_data
                    else:
                        # Remove stale database cache
                        await cache_collection.delete_one({"vault_address": vault_address})
                        logger.info(f"Removed stale database cache for address {vault_address}")
                        
            except Exception as e:
                logger.error(f"Error checking database cache for {vault_address}: {e}")
        
        return None

    async def _put_in_cache(self, vault_address: str, portfolio_data: Dict[str, Any]):
        """Put data into both memory and database cache."""
        timestamp = datetime.datetime.now(timezone.utc)
        
        # Put in memory cache
        self._memory_cache[vault_address] = {
            'data': portfolio_data,
            'timestamp': timestamp
        }
        logger.info(f"Cached portfolio in memory for address {vault_address}")
        
        # Put in database cache
        if self.db is not None:
            try:
                cache_collection = self.db.portfolio_cache
                await cache_collection.update_one(
                    {"vault_address": vault_address},
                    {
                        "$set": {
                            "vault_address": vault_address,
                            "data": portfolio_data,
                            "timestamp": timestamp
                        }
                    },
                    upsert=True
                )
                logger.info(f"Cached portfolio in database for address {vault_address}")
            except Exception as e:
                logger.error(f"Error caching portfolio in database for {vault_address}: {e}")
        
    def _format_portfolio_output(
        self, 
        vault_address: str, 
        token_holdings: List[Dict], 
        asset_holdings: List[Dict],
        total_value_usd: float, 
        wallet_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Format the portfolio data into the structure expected by the frontend."""
        chains_data = {}
        
        for holding in token_holdings:
            chain_id = holding["chain_id"]
            if chain_id not in chains_data:
                chains_data[chain_id] = {
                    "chain_name": CHAIN_CONFIG.get(chain_id, {}).get("name", f"Chain {chain_id}"),
                    "total_value_usd": 0,
                    "tokens": {},
                    "assets": {}
                }
            
            chain = chains_data[chain_id]
            chain["total_value_usd"] += holding.get("value_usd", 0)
            
            symbol = holding["symbol"]
            chain["tokens"][symbol] = {
                "balance": holding["balance"],
                "value_usd": holding.get("value_usd", 0)
            }

        assets_data = {}
        for holding in asset_holdings:
            chain_id = holding["chain_id"]
            if chain_id not in chains_data:
                 chains_data[chain_id] = {
                    "chain_name": CHAIN_CONFIG.get(chain_id, {}).get("name", f"Chain {chain_id}"),
                    "total_value_usd": 0,
                    "tokens": {},
                    "assets": {}
                }
            
            chain = chains_data[chain_id]
            chain["total_value_usd"] += holding.get("value_usd", 0)
            
            asset_key = f'{holding["protocol"]}_{holding["strategy"]}'
            if asset_key not in assets_data:
                assets_data[asset_key] = {
                    "protocol": holding["protocol"],
                    "asset_type": holding["strategy"],
                    "total_value_usd": 0,
                    "tokens": {}
                }
            
            asset = assets_data[asset_key]
            asset["total_value_usd"] += holding.get("value_usd", 0)
            
            symbol = holding["token_symbol"]
            asset["tokens"][symbol] = {
                "balance": holding["balance"],
                "value_usd": holding.get("value_usd", 0)
            }

            if asset_key not in chain["assets"]:
                chain["assets"][asset_key] = {
                    "protocol": holding["protocol"],
                    "asset_type": holding["strategy"],
                    "total_value_usd": 0,
                    "tokens": {}
                }
            
            chain_asset = chain["assets"][asset_key]
            chain_asset["total_value_usd"] += holding.get("value_usd", 0)
            chain_asset["tokens"][symbol] = {
                 "balance": holding["balance"],
                "value_usd": holding.get("value_usd", 0)
            }

        summary = {
            "total_tokens": len(token_holdings),
            "active_assets": list(assets_data.keys()),
            "active_chains": list(chains_data.keys())
        }

        return {
            "vault_address": vault_address,
            "wallet_address": wallet_address,
            "total_value_usd": total_value_usd,
            "chains": {v["chain_name"]: v for _, v in chains_data.items()},
            "assets": assets_data,
            "summary": summary,
            "holdings": token_holdings + asset_holdings  # Add holdings for detailed balance lookup
        }

    async def _get_token_prices_async(self, coingecko_ids: List[str]) -> Dict[str, float]:
        """Async wrapper for getting token prices with proper event loop handling"""
        if not coingecko_ids:
            logger.info("No CoinGecko IDs provided, returning empty prices")
            return {}
            
        # Use the async version that properly handles the event loop and database
        return await self.coingecko.get_token_prices_async(coingecko_ids)
    
    
    async def _get_all_token_balances(self, vault_address: str) -> List[Dict[str, Any]]:
        """Get balances for all tokens using batch balance function per chain - one call per chain"""
        all_balances = []
        
        # Group tokens by chain - only process chains that are currently connected
        tokens_by_chain = {}
        skipped_chains = set()
        
        for token_symbol, token_config in SUPPORTED_TOKENS.items():
            for chain_id, token_address in token_config["addresses"].items():
                if chain_id not in self.web3_instances:
                    # Track skipped chains but don't log warnings yet (connections might still be initializing)
                    if chain_id in RPC_ENDPOINTS:
                        skipped_chains.add(chain_id)
                    continue
                    
                if chain_id not in tokens_by_chain:
                    tokens_by_chain[chain_id] = []
                
                tokens_by_chain[chain_id].append({
                    "address": token_address,
                    "config": token_config,
                    "symbol": token_symbol
                })
        
        # Log skipped chains only once (not per token)
        if skipped_chains:
            skipped_names = [CHAIN_CONFIG.get(cid, {}).get("name", f"Chain {cid}") for cid in sorted(skipped_chains)]
            logger.info(f"Skipping chains not yet connected: {', '.join(skipped_names)} - will process with available chains")
        
        # Ensure all configured chains are included, even if they have no ERC20 tokens
        for chain_id in self.web3_instances:
            if chain_id not in tokens_by_chain:
                tokens_by_chain[chain_id] = []
        
        # Add native tokens (address 0x0) to each chain
        for chain_id in tokens_by_chain:
            if chain_id in NATIVE_CURRENCIES:
                tokens_by_chain[chain_id].append({
                    "address": "0x0000000000000000000000000000000000000000",
                    "config": NATIVE_CURRENCIES[chain_id],
                    "symbol": NATIVE_CURRENCIES[chain_id]["symbol"],
                    "is_native": True
                })
        
        # Execute batch balance queries for each chain
        tasks = []
        for chain_id, token_list in tokens_by_chain.items():
            task = self._get_batch_balances_for_chain(vault_address, chain_id, token_list)
            tasks.append((task, chain_id, token_list))
        
        # Log summary of what we're querying
        total_tokens = sum(len(token_list) for _, _, token_list in tasks)
        logger.info(f"Executing batch balance queries for {len(tasks)} chains with {total_tokens} total tokens")
        for _, chain_id, token_list in tasks:
            chain_name = CHAIN_CONFIG.get(chain_id, {}).get("name", f"Chain {chain_id}")
            token_symbols = [t["symbol"] for t in token_list]
            logger.debug(f"{chain_name} ({chain_id}): {len(token_list)} tokens - {', '.join(token_symbols)}")
        
        # Execute all batch queries concurrently
        results = await asyncio.gather(*[task for task, _, _ in tasks], return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            _, chain_id, token_list = tasks[i]
            
            if isinstance(result, Exception):
                logger.error(f"Error getting batch balances for chain {chain_id}: {result}")
                # Fall back to individual queries for this chain
                fallback_balances = await self._get_balances_fallback(vault_address, chain_id, token_list)
                all_balances.extend(fallback_balances)
                continue
            
            # Process successful batch result
            balances = result
            if balances and len(balances) == len(token_list):
                for j, balance_wei in enumerate(balances):
                    token_info = token_list[j]
                    
                    # Convert balance to human readable format
                    decimals = token_info["config"].get("decimals", 18)
                    balance = float(balance_wei) / (10 ** decimals)
                    
                    balance_entry = {
                        "symbol": token_info["symbol"],
                        "name": token_info["config"]["name"],
                        "chain_id": chain_id,
                        "balance": balance,
                        "coingeckoId": token_info["config"].get("coingeckoId")
                    }
                    
                    if token_info.get("is_native"):
                        balance_entry["is_native"] = True
                    
                    all_balances.append(balance_entry)
                    logger.debug(f"{token_info['symbol']} on chain {chain_id}: {balance}")
            else:
                logger.error(f"Batch balance result mismatch for chain {chain_id}")
                # Fall back to individual queries
                fallback_balances = await self._get_balances_fallback(vault_address, chain_id, token_list)
                all_balances.extend(fallback_balances)
        
        # Try to reconnect to missing chains and process them if successful
        if skipped_chains:
            retry_balances = await self._retry_missing_chains(vault_address, skipped_chains)
            all_balances.extend(retry_balances)
        
        logger.info(f"Retrieved balances for {len(all_balances)} tokens using batch queries")
        return all_balances
    
    async def _retry_missing_chains(self, vault_address: str, skipped_chains: set) -> List[Dict[str, Any]]:
        """Try to reconnect to missing chains and process tokens if connections become available"""
        retry_balances = []
        
        # Give a brief moment for any ongoing connections to complete
        await asyncio.sleep(0.1)
        
        # Check which chains are now available
        newly_available = []
        for chain_id in skipped_chains:
            if chain_id in self.web3_instances:
                newly_available.append(chain_id)
        
        if newly_available:
            # Process tokens for newly available chains
            for chain_id in newly_available:
                chain_name = CHAIN_CONFIG.get(chain_id, {}).get("name", f"Chain {chain_id}")
                logger.info(f"Chain {chain_name} now available - processing tokens")
                
                # Get tokens for this chain
                chain_tokens = []
                for token_symbol, token_config in SUPPORTED_TOKENS.items():
                    if chain_id in token_config["addresses"]:
                        chain_tokens.append({
                            "address": token_config["addresses"][chain_id],
                            "config": token_config,
                            "symbol": token_symbol
                        })
                
                # Add native token
                if chain_id in NATIVE_CURRENCIES:
                    chain_tokens.append({
                        "address": "0x0000000000000000000000000000000000000000",
                        "config": NATIVE_CURRENCIES[chain_id],
                        "symbol": NATIVE_CURRENCIES[chain_id]["symbol"],
                        "is_native": True
                    })
                
                if chain_tokens:
                    # Process this chain's tokens
                    try:
                        result = await self._get_batch_balances_for_chain(vault_address, chain_id, chain_tokens)
                        if result and len(result) == len(chain_tokens):
                            for j, balance_wei in enumerate(result):
                                token_info = chain_tokens[j]
                                decimals = token_info["config"].get("decimals", 18)
                                balance = float(balance_wei) / (10 ** decimals)
                                
                                balance_entry = {
                                    "symbol": token_info["symbol"],
                                    "name": token_info["config"]["name"],
                                    "chain_id": chain_id,
                                    "balance": balance,
                                    "coingeckoId": token_info["config"].get("coingeckoId")
                                }
                                
                                if token_info.get("is_native"):
                                    balance_entry["is_native"] = True
                                
                                retry_balances.append(balance_entry)
                    except Exception as e:
                        logger.warning(f"Failed to process newly available chain {chain_name}: {e}")
        
        return retry_balances
    
    async def _get_batch_balances_for_chain(self, vault_address: str, chain_id: int, token_list: List[Dict]) -> Optional[List[int]]:
        """Get batch balances for a specific chain using Vault contract"""
        loop = asyncio.get_event_loop()
        
        def get_balances():
            try:
                w3 = self.web3_instances.get(chain_id)
                if not w3 or not self.Web3:
                    return None
                
                # Create Vault contract instance
                vault_contract = w3.eth.contract(
                    address=self.Web3.to_checksum_address(vault_address),
                    abi=VAULT_ABI
                )
                
                # Prepare token addresses array
                token_addresses = [self.Web3.to_checksum_address(token["address"]) for token in token_list]
                
                # Call getMultipleTokenBalances
                balances = vault_contract.functions.getMultipleTokenBalances(token_addresses).call()
                
                return balances
                
            except Exception as e:
                logger.error(f"Error getting batch balances for chain {chain_id}: {e}")
                raise e
        
        return await loop.run_in_executor(None, get_balances)
    
    async def _get_balances_fallback(self, vault_address: str, chain_id: int, token_list: List[Dict]) -> List[Dict[str, Any]]:
        """Fallback to individual balance queries when batch query fails"""
        balances = []
        w3 = self.web3_instances.get(chain_id)
        if not w3 or not self.Web3:
            return balances
        
        for token_info in token_list:
            try:
                balance = None
                if token_info.get("is_native"):
                    # Get native balance directly
                    balance_wei = w3.eth.get_balance(vault_address)
                    balance = float(balance_wei) / (10 ** 18)
                else:
                    # Get ERC20 balance directly
                    contract = w3.eth.contract(
                        address=self.Web3.to_checksum_address(token_info["address"]),
                        abi=ERC20_ABI
                    )
                    balance_wei = contract.functions.balanceOf(vault_address).call()
                    decimals = token_info["config"]["decimals"]
                    balance = float(balance_wei) / (10 ** decimals)
                
                if balance is not None:
                    balance_entry = {
                        "symbol": token_info["symbol"],
                        "name": token_info["config"]["name"],
                        "chain_id": chain_id,
                        "balance": balance,
                        "coingeckoId": token_info["config"].get("coingeckoId")
                    }
                    
                    if token_info.get("is_native"):
                        balance_entry["is_native"] = True
                    
                    balances.append(balance_entry)
                    
            except Exception as e:
                logger.error(f"Error in fallback balance query for {token_info['symbol']} on chain {chain_id}: {e}")
        
        return balances
    
    async def _get_all_asset_balances(self, vault_address: str) -> List[Dict[str, Any]]:
        """Get balances for all protocol assets (like aTokens) concurrently"""
        tasks = []
        
        # Create tasks for each asset balance checker
        for asset_type, balance_checker in ASSET_BALANCE_CHECKERS.items():
            if balance_checker is None:
                logger.warning(f"Asset type {asset_type} has no balance checker configured, skipping")
                continue
                
            try:
                task = balance_checker(self.web3_instances, vault_address, SUPPORTED_TOKENS)
                tasks.append(task) # Directly append the coroutine
            except Exception as e:
                logger.error(f"Error creating task for {asset_type} asset: {e}")
                continue
        
        logger.info(f"Checking asset balances for {len(tasks)} asset types")
        
        # Execute all asset balance checks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_asset_balances = []
        for i, result in enumerate(results):
            asset_type = list(ASSET_BALANCE_CHECKERS.keys())[i]
            if isinstance(result, Exception):
                logger.error(f"Error getting {asset_type} asset balances: {result}")
                continue
                
            # Result should be a list of asset balance dictionaries
            if isinstance(result, list):
                all_asset_balances.extend(result)
                logger.info(f"Found {len(result)} asset balances from {asset_type}")
        
        logger.info(f"Retrieved total of {len(all_asset_balances)} asset balances")
        return all_asset_balances
    

    async def get_portfolio_for_llm(self, vault_address: Optional[str] = None, wallet_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Get portfolio data organized for LLM consumption - structured by chains, strategies, tokens, amounts
        """
        portfolio_summary = await self.get_portfolio_summary(vault_address=vault_address, wallet_address=wallet_address)
        
        if portfolio_summary.get('error'):
            return {"error": portfolio_summary['error']}
        
        # Use actual chain configuration from config.py
        chain_names = {
            chain_id: config["name"] 
            for chain_id, config in CHAIN_CONFIG.items()
        }
        
        # Organize data by chains and strategies
        result = {
            "total_value_usd": portfolio_summary.get('total_value_usd', 0),
            "chains": {},
            "strategies": {},
            "summary": {
                "active_chains": [],
                "active_strategies": [],
                "total_tokens": 0
            }
        }
        
        holdings = portfolio_summary.get('holdings', [])
        
        # Process each holding
        for holding in holdings:
            chain_id = holding.get('chain_id')
            chain_name = chain_names.get(chain_id, f'Chain {chain_id}')
            symbol = holding.get('symbol', 'Unknown')
            balance = holding.get('balance', 0)
            value_usd = holding.get('value_usd', 0)
            holding_type = holding.get('type', 'token')
            
            # Initialize chain if not exists
            if chain_name not in result["chains"]:
                result["chains"][chain_name] = {
                    "chain_id": chain_id,
                    "total_value_usd": 0,
                    "tokens": {},
                    "assets": {}
                }
            
            # Add to chain total
            result["chains"][chain_name]["total_value_usd"] += value_usd
            
            if holding_type == "token":
                # Regular token holding
                result["chains"][chain_name]["tokens"][symbol] = {
                    "balance": balance,
                    "value_usd": value_usd
                }
            elif holding_type == "strategy":
                # Strategy holding
                strategy = holding.get('strategy', 'Unknown')
                protocol = holding.get('protocol', 'Unknown')
                strategy_key = f"{protocol}_{strategy}"
                
                # Initialize strategy globally if not exists
                if strategy_key not in result["strategies"]:
                    result["strategies"][strategy_key] = {
                        "protocol": protocol,
                        "strategy": strategy,
                        "total_value_usd": 0,
                        "positions": {}
                    }
                
                # Add to global strategy
                position_key = f"{chain_name}_{symbol}"
                result["strategies"][strategy_key]["positions"][position_key] = {
                    "chain": chain_name,
                    "token": symbol,
                    "balance": balance,
                    "value_usd": value_usd
                }
                result["strategies"][strategy_key]["total_value_usd"] += value_usd
                
                # Add to chain's strategy section
                if strategy_key not in result["chains"][chain_name]["strategies"]:
                    result["chains"][chain_name]["strategies"][strategy_key] = {
                        "protocol": protocol,
                        "strategy": strategy,
                        "tokens": {}
                    }
                
                result["chains"][chain_name]["strategies"][strategy_key]["tokens"][symbol] = {
                    "balance": balance,
                    "value_usd": value_usd
                }
        
        # Build summary
        result["summary"]["active_chains"] = list(result["chains"].keys())
        result["summary"]["active_strategies"] = [
            f"{data['protocol']} {data['strategy']}" 
            for data in result["strategies"].values()
        ]
        result["summary"]["total_tokens"] = sum(
            len(chain_data["tokens"]) 
            for chain_data in result["chains"].values()
        )
        
        return result