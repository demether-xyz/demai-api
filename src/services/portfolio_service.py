from typing import Dict, List, Optional, Any, TYPE_CHECKING
from decimal import Decimal
import logging
import asyncio
import datetime
from datetime import timezone
from utils.coingecko_util import CoinGeckoUtil
from config import SUPPORTED_TOKENS, RPC_ENDPOINTS, NATIVE_CURRENCIES, ERC20_ABI, CHAIN_CONFIG, VAULT_FACTORY_ADDRESS, VAULT_FACTORY_ABI, VAULT_ABI

if TYPE_CHECKING:
    from web3 import Web3
    from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class PortfolioService:
    """Service for fetching portfolio balances and calculating total value"""
    
    def __init__(self, db: Optional["AsyncIOMotorDatabase"] = None, cache_ttl_seconds: int = 5):
        # Now only accepts database directly
        self.db = db
        self.cache_ttl = datetime.timedelta(seconds=cache_ttl_seconds)
        self.coingecko = CoinGeckoUtil(self.db)
        self.web3_instances = {}
        self.Web3 = None
        
        # Removed in-memory cache - using only database cache
        
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
        db_cache_size = 0
        if self.db is not None:
            try:
                cache_collection = self.db.portfolio_cache
                db_cache_size = await cache_collection.count_documents({})
            except Exception as e:
                logger.error(f"Error getting database cache size: {e}")
        
        return {
            "memory_cache_entries": 0,  # Memory cache disabled
            "database_cache_entries": db_cache_size,
            "cache_ttl_seconds": self.cache_ttl.total_seconds(),
            "web3_connections": len(self.web3_instances),
            "available_chains": list(self.web3_instances.keys())
        }
    
    async def clear_portfolio_cache(self, vault_address: Optional[str] = None):
        """Clear database cache - memory cache disabled."""

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
        """Memory cache disabled - only database cache used"""
        logger.info("Memory cache disabled - using only database cache")
    
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
    
    async def get_portfolio_summary(self, vault_address: Optional[str] = None, wallet_address: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
        """
        Get complete portfolio summary for a vault address or wallet address including balances and USD values
        Uses optimized batch balance queries - one call per chain
        
        Args:
            vault_address: Vault address to query
            wallet_address: Wallet address to resolve to vault
            refresh: If True, bypass cache and fetch fresh data
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
            
        # Check cache only if refresh is not requested
        logger.info(f"Cache check: refresh={refresh} for {target_address}")
        if not refresh:
            logger.info(f"Checking cache for {target_address}")
            cached_data = await self._get_from_cache(target_address)
            if cached_data:
                logger.info(f"Returning cached portfolio for {target_address}")
                return cached_data
            else:
                logger.info(f"No cached data found for {target_address}")
        else:
            logger.info(f"Refresh requested, bypassing cache for {target_address}")
            # Clear any existing cache when refresh is requested
            await self.clear_portfolio_cache(target_address)

        try:
            # Use optimized batch balance query - one call per chain
            logger.info(f"Using optimized batch balance queries for {target_address}")
            all_balances = await self._get_all_token_balances(target_address)
            
            # Separate regular tokens from strategy tokens (aTokens)
            regular_holdings = []
            strategy_holdings = []
            
            for holding in all_balances:
                if holding.get("balance", 0) > 0:
                    if holding.get("type") == "strategy":
                        strategy_holdings.append(holding)
                    else:
                        regular_holdings.append(holding)
            
            # Combine all holdings
            all_holdings = regular_holdings
            asset_holdings = strategy_holdings

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
        """Check database cache for fresh data - memory cache disabled."""
        # Check database cache only
        if self.db is not None:
            try:
                cache_collection = self.db.portfolio_cache
                result = await cache_collection.find_one({"vault_address": vault_address})
                
                if result and "data" in result and "timestamp" in result:
                    cached_timestamp = result["timestamp"]
                    # Ensure timestamp is timezone-aware
                    if cached_timestamp.tzinfo is None:
                        cached_timestamp = cached_timestamp.replace(tzinfo=timezone.utc)
                    is_db_stale = datetime.datetime.now(timezone.utc) - cached_timestamp > self.cache_ttl
                    
                    if not is_db_stale:
                        logger.info(f"Returning database cached portfolio for address {vault_address}")
                        # Return data directly - no memory cache
                        portfolio_data = result["data"]
                        return portfolio_data
                    else:
                        # Remove stale database cache
                        await cache_collection.delete_one({"vault_address": vault_address})
                        logger.info(f"Removed stale database cache for address {vault_address}")
                        
            except Exception as e:
                logger.error(f"Error checking database cache for {vault_address}: {e}")
        
        return None

    async def _put_in_cache(self, vault_address: str, portfolio_data: Dict[str, Any]):
        """Put data into database cache only - memory cache disabled."""
        timestamp = datetime.datetime.now(timezone.utc)
        
        # Put in database cache only
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
            # Skip tokens with zero or missing USD value
            if holding.get("value_usd", 0) == 0:
                continue
                
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

        # Count only tokens with non-zero value
        valued_tokens = [h for h in token_holdings if h.get("value_usd", 0) > 0]
        
        summary = {
            "total_tokens": len(valued_tokens),
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
            "holdings": valued_tokens + asset_holdings  # Add holdings for detailed balance lookup
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
        
        logger.info(f"Processing {len(SUPPORTED_TOKENS)} supported tokens...")
        for token_symbol, token_config in SUPPORTED_TOKENS.items():
            logger.info(f"Processing token {token_symbol}: {token_config}")
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
                
                # Also add aTokens if they exist for this token/chain combination
                if "aave_atokens" in token_config and chain_id in token_config["aave_atokens"]:
                    atoken_config = token_config["aave_atokens"][chain_id]
                    
                    # Handle both single aToken (string/dict) and multiple aTokens (list)
                    if isinstance(atoken_config, list):
                        # Multiple aTokens (new array format)
                        atoken_list = atoken_config
                    elif isinstance(atoken_config, str):
                        # Legacy single aToken (string address)
                        atoken_list = [{"address": atoken_config, "name": None, "decimals": None}]
                    else:
                        # Single aToken (dict format)
                        atoken_list = [atoken_config]
                    
                    for atoken_data in atoken_list:
                        atoken_address = atoken_data.get("address") or atoken_data
                        logger.info(f"Found aToken for {token_symbol} on chain {chain_id}: {atoken_address}")
                        logger.info(f"aToken data: {atoken_data}")
                        
                        # Determine protocol based on chain - Katana uses Morpho, others use Aave
                        if chain_id == 747474:  # Katana
                            protocol_name = "Morpho"
                            strategy_name = "morpho_v1"
                            # Use proper aToken name from config or fallback
                            if isinstance(atoken_data, dict) and atoken_data.get("name"):
                                atoken_symbol = atoken_data["name"]
                            else:
                                atoken_symbol = f"Steakhouse High Yield {token_symbol}"
                            # Get decimals from config or fallback to 18
                            atoken_decimals = atoken_data.get("decimals", 18) if isinstance(atoken_data, dict) else 18
                        else:
                            protocol_name = "Aave V3"
                            strategy_name = "aave_v3"
                            atoken_symbol = f"a{token_symbol}"
                            atoken_decimals = atoken_data.get("decimals", token_config.get("decimals", 18)) if isinstance(atoken_data, dict) else token_config.get("decimals", 18)
                        
                        atoken_info = {
                            "address": atoken_address,
                            "config": token_config,
                            "symbol": atoken_symbol,
                            "is_atoken": True,
                            "underlying_symbol": token_symbol,
                            "protocol": protocol_name,
                            "strategy": strategy_name,
                            "atoken_decimals": atoken_decimals
                        }
                        logger.info(f"Adding aToken to processing queue: {atoken_info}")
                        tokens_by_chain[chain_id].append(atoken_info)
        
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
                    # Use aToken-specific decimals if available, otherwise use underlying token decimals
                    if token_info.get("is_atoken"):
                        if "atoken_decimals" in token_info:
                            # Use decimals from atoken_info (new format)
                            decimals = token_info["atoken_decimals"]
                        elif "atoken_decimals" in token_info["config"]:
                            # Legacy format: decimals in config
                            decimals = token_info["config"]["atoken_decimals"].get(chain_id, 18)
                        else:
                            decimals = 18  # Default for aTokens
                        logger.info(f"Using aToken decimals {decimals} for {token_info['symbol']} on chain {chain_id}")
                    else:
                        decimals = token_info["config"].get("decimals", 18)
                    
                    # Ensure decimals is not None
                    if decimals is None:
                        logger.warning(f"Decimals is None for {token_info['symbol']}, defaulting to 18")
                        decimals = 18
                    
                    balance = float(balance_wei) / (10 ** decimals)
                    
                    # Log balance for aTokens
                    if token_info.get("is_atoken"):
                        logger.info(f"aToken balance check: {token_info['symbol']} = {balance} (address: {token_info['address']})")
                    
                    # Skip zero balances for aTokens to reduce clutter
                    if token_info.get("is_atoken") and balance == 0:
                        logger.info(f"Skipping zero balance aToken: {token_info['symbol']}")
                        continue
                    
                    if token_info.get("is_atoken"):
                        # Handle aToken/yield token balance entry (Aave, Morpho, etc.)
                        balance_entry = {
                            "token_symbol": token_info["symbol"],  # Use full aToken name (e.g., "Steakhouse High Yield AUSD")
                            "underlying_symbol": token_info["underlying_symbol"],  # Keep underlying for reference
                            "chain_id": chain_id,
                            "protocol": token_info.get("protocol", "Aave V3"),
                            "strategy": token_info.get("strategy", "aave_v3"),
                            "balance": balance,
                            "decimals": decimals,
                            "atoken_address": token_info["address"],
                            "coingeckoId": token_info["config"].get("coingeckoId"),  # Use underlying token's coingecko ID
                            "type": "strategy"  # Mark as strategy holding
                        }
                        logger.info(f"Processing aToken balance: {balance_entry}")
                    else:
                        # Regular token balance entry
                        balance_entry = {
                            "symbol": token_info["symbol"],
                            "name": token_info["config"]["name"],
                            "chain_id": chain_id,
                            "balance": balance,
                            "coingeckoId": token_info["config"].get("coingeckoId")
                        }
                        logger.info(f"Processing regular token balance: {balance_entry}")
                        
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
                        
                        # Also add aTokens if they exist
                        if "aave_atokens" in token_config and chain_id in token_config["aave_atokens"]:
                            atoken_config = token_config["aave_atokens"][chain_id]
                            
                            # Handle both single aToken (string/dict) and multiple aTokens (list)
                            if isinstance(atoken_config, list):
                                # Multiple aTokens (new array format)
                                atoken_list = atoken_config
                            elif isinstance(atoken_config, str):
                                # Legacy single aToken (string address)
                                atoken_list = [{"address": atoken_config, "name": None, "decimals": None}]
                            else:
                                # Single aToken (dict format)
                                atoken_list = [atoken_config]
                            
                            # Process each aToken
                            for atoken_data in atoken_list:
                                atoken_address = atoken_data.get("address") if isinstance(atoken_data, dict) else atoken_data
                                
                                # Determine protocol based on chain
                                if chain_id == 747474:  # Katana
                                    protocol_name = "Morpho"
                                    strategy_name = "morpho_v1"
                                    if isinstance(atoken_data, dict) and atoken_data.get("name"):
                                        atoken_symbol = atoken_data["name"]
                                    else:
                                        atoken_symbol = f"Steakhouse High Yield {token_symbol}"
                                else:
                                    protocol_name = "Aave V3"
                                    strategy_name = "aave_v3"
                                    atoken_symbol = f"a{token_symbol}"
                                
                                chain_tokens.append({
                                    "address": atoken_address,
                                    "config": token_config,
                                    "symbol": atoken_symbol,
                                    "is_atoken": True,
                                    "underlying_symbol": token_symbol,
                                    "protocol": protocol_name,
                                    "strategy": strategy_name
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
                                # Use aToken-specific decimals if available
                                if token_info.get("is_atoken"):
                                    if "atoken_decimals" in token_info:
                                        decimals = token_info["atoken_decimals"]
                                    elif "atoken_decimals" in token_info["config"]:
                                        decimals = token_info["config"]["atoken_decimals"].get(chain_id, 18)
                                    else:
                                        decimals = 18
                                else:
                                    decimals = token_info["config"].get("decimals", 18)
                                
                                # Ensure decimals is not None
                                if decimals is None:
                                    logger.warning(f"Decimals is None for {token_info['symbol']}, defaulting to 18")
                                    decimals = 18
                                    
                                balance = float(balance_wei) / (10 ** decimals)
                                
                                # Skip zero balances for aTokens
                                if token_info.get("is_atoken") and balance == 0:
                                    continue
                                    
                                if token_info.get("is_atoken"):
                                    balance_entry = {
                                        "token_symbol": token_info["underlying_symbol"],
                                        "chain_id": chain_id,
                                        "protocol": token_info.get("protocol", "Aave V3"),
                                        "strategy": token_info.get("strategy", "aave_v3"),
                                        "balance": balance,
                                        "decimals": decimals,
                                        "atoken_address": token_info["address"],
                                        "coingeckoId": token_info["config"].get("coingeckoId"),
                                        "type": "strategy"
                                    }
                                else:
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
                    # Use aToken-specific decimals if available
                    if token_info.get("is_atoken"):
                        if "atoken_decimals" in token_info:
                            decimals = token_info["atoken_decimals"]
                        elif "atoken_decimals" in token_info["config"]:
                            decimals = token_info["config"]["atoken_decimals"].get(chain_id, 18)
                        else:
                            decimals = 18
                    else:
                        decimals = token_info["config"].get("decimals", 18)
                    
                    # Ensure decimals is not None
                    if decimals is None:
                        logger.warning(f"Decimals is None for {token_info['symbol']}, defaulting to 18")
                        decimals = 18
                        
                    balance = float(balance_wei) / (10 ** decimals)
                
                if balance is not None:
                    # Skip zero balances for aTokens
                    if token_info.get("is_atoken") and balance == 0:
                        continue
                        
                    if token_info.get("is_atoken"):
                        # Handle aToken/yield token balance entry (Aave, Morpho, etc.)
                        balance_entry = {
                            "token_symbol": token_info["underlying_symbol"],
                            "chain_id": chain_id,
                            "protocol": token_info.get("protocol", "Aave V3"),
                            "strategy": token_info.get("strategy", "aave_v3"),
                            "balance": balance,
                            "decimals": token_info["config"]["decimals"],
                            "atoken_address": token_info["address"],
                            "coingeckoId": token_info["config"].get("coingeckoId"),
                            "type": "strategy"
                        }
                    else:
                        # Regular token balance entry
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
    

    async def get_portfolio_for_llm(self, vault_address: Optional[str] = None, wallet_address: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
        """
        Get portfolio data organized for LLM consumption - structured by chains, strategies, tokens, amounts
        
        Args:
            vault_address: Vault address to query
            wallet_address: Wallet address to resolve to vault
            refresh: If True, bypass cache and fetch fresh data (default: False to use cache)
        """
        portfolio_summary = await self.get_portfolio_summary(vault_address=vault_address, wallet_address=wallet_address, refresh=refresh)
        
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
            # Handle both 'symbol' (for regular tokens) and 'token_symbol' (for strategy tokens like aTokens)
            symbol = holding.get('symbol') or holding.get('token_symbol', 'Unknown')
            balance = holding.get('balance', 0)
            value_usd = holding.get('value_usd', 0)
            holding_type = holding.get('type', 'token')
            
            # Initialize chain if not exists
            if chain_name not in result["chains"]:
                result["chains"][chain_name] = {
                    "chain_id": chain_id,
                    "total_value_usd": 0,
                    "tokens": {},
                    "assets": {},
                    "strategies": {}  # Add strategies key
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