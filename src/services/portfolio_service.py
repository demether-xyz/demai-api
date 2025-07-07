from typing import Dict, List, Optional, Any, TYPE_CHECKING, Union
from decimal import Decimal
import logging
import asyncio
import datetime
from utils.coingecko_util import CoinGeckoUtil
from utils.mongo_util import MongoUtil
from config import SUPPORTED_TOKENS, RPC_ENDPOINTS, NATIVE_CURRENCIES, ERC20_ABI, CHAIN_CONFIG, VAULT_FACTORY_ADDRESS, VAULT_FACTORY_ABI
from strategies.strategy_config import STRATEGY_BALANCE_CHECKERS

if TYPE_CHECKING:
    from web3 import Web3
    from pymongo.database import Database

logger = logging.getLogger(__name__)


class PortfolioService:
    """Service for fetching portfolio balances and calculating total value"""
    
    def __init__(self, db_or_mongo_util: Optional[Union["Database", MongoUtil]] = None, cache_ttl_seconds: int = 60):
        # Handle both database and MongoUtil for backward compatibility
        if db_or_mongo_util is not None and hasattr(db_or_mongo_util, 'db'):  # It's a MongoUtil
            self.mongo_util = db_or_mongo_util
            self.db = db_or_mongo_util.db
        else:  # It's a database directly or None
            self.mongo_util = None
            self.db = db_or_mongo_util
            
        self.cache_ttl = datetime.timedelta(seconds=cache_ttl_seconds)
        self.coingecko = CoinGeckoUtil(self.mongo_util if self.mongo_util is not None else self.db)
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
            
        for chain_id, rpc_url in RPC_ENDPOINTS.items():
            try:
                w3 = self.Web3(self.Web3.HTTPProvider(rpc_url))
                if w3.is_connected():
                    self.web3_instances[chain_id] = w3
                    logger.info(f"Connected to chain {chain_id}")
                else:
                    logger.warning(f"Failed to connect to chain {chain_id}")
            except Exception as e:
                logger.error(f"Error connecting to chain {chain_id}: {e}")
    
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
    
    async def _get_vault_from_database(self, wallet_address: str) -> Optional[str]:
        """Get vault address from database cache"""
        if not self.db:
            return None
            
        try:
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
        if not self.db:
            return
            
        try:
            wallet_vault_collection = self.db.wallet_vault_mapping
            await wallet_vault_collection.update_one(
                {"wallet_address": wallet_address},
                {
                    "$set": {
                        "wallet_address": wallet_address,
                        "vault_address": vault_address,
                        "timestamp": datetime.datetime.utcnow()
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
            return None
            
        try:
            # Normalize wallet address
            wallet_address = self.Web3.to_checksum_address(wallet_address) if self.Web3 else wallet_address
            
            # Step 1: Check database cache
            cached_vault = await self._get_vault_from_database(wallet_address)
            if cached_vault:
                return cached_vault
            
            # Step 2: Query on-chain
            vault_address = await self._get_vault_from_chain(wallet_address)
            if vault_address:
                # Step 3: Save to database for future use
                await self._save_vault_to_database(wallet_address, vault_address)
                return vault_address
                
            logger.warning(f"Could not resolve vault address for wallet {wallet_address}")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving vault address for wallet {wallet_address}: {e}")
            return None
    
    async def get_portfolio_summary(self, vault_address: Optional[str] = None, wallet_address: Optional[str] = None) -> Dict[str, Any]:
        """
        Get complete portfolio summary for a vault address or wallet address including balances and USD values
        """
        if not self.Web3:
            return {
                "vault_address": vault_address,
                "wallet_address": wallet_address,
                "total_value_usd": 0.0,
                "holdings": [],
                "chains_count": 0,
                "tokens_count": 0,
                "strategy_count": 0,
                "active_strategies": [],
                "error": "Web3 not available"
            }
        
        # Determine which address to use for portfolio lookup
        if vault_address:
            # Use vault address directly if provided
            target_address = vault_address
        elif wallet_address:
            # Resolve vault address from wallet address
            target_address = await self._resolve_vault_address(wallet_address)
            if not target_address:
                return {
                    "vault_address": vault_address,
                    "wallet_address": wallet_address,
                    "total_value_usd": 0.0,
                    "holdings": [],
                    "chains_count": 0,
                    "tokens_count": 0,
                    "strategy_count": 0,
                    "active_strategies": [],
                    "error": f"Could not resolve vault address for wallet {wallet_address}"
                }
            # Update vault_address for response consistency
            vault_address = target_address
        else:
            return {
                "vault_address": vault_address,
                "wallet_address": wallet_address,
                "total_value_usd": 0.0,
                "holdings": [],
                "chains_count": 0,
                "tokens_count": 0,
                "strategy_count": 0,
                "active_strategies": [],
                "error": "Either vault_address or wallet_address must be provided"
            }
            
        try:
            # Normalize target address
            target_address = self.Web3.to_checksum_address(target_address)
            
            # Check in-memory cache first
            if target_address in self._memory_cache:
                cached_entry = self._memory_cache[target_address]
                is_stale = datetime.datetime.utcnow() - cached_entry['timestamp'] > self.cache_ttl
                if not is_stale:
                    logger.info(f"Returning in-memory cached portfolio for address {target_address}")
                    return cached_entry['data']
                else:
                    # Remove stale cache entry
                    del self._memory_cache[target_address]
            
            # Check database cache if no fresh in-memory cache
            if self.db is not None:
                cache_collection = self.db.portfolio_cache
                cached_data = await cache_collection.find_one({"vault_address": target_address})

                if cached_data and 'timestamp' in cached_data:
                    is_stale = datetime.datetime.utcnow() - cached_data['timestamp'] > self.cache_ttl
                    if not is_stale:
                        logger.info(f"Returning database cached portfolio for address {target_address}")
                        cached_data.pop('_id', None)
                        cached_data.pop('timestamp', None)
                        
                        # Store in memory cache for next time
                        self._memory_cache[target_address] = {
                            'data': cached_data,
                            'timestamp': datetime.datetime.utcnow()
                        }
                        
                        return cached_data
            
            # Get balances for all tokens across all chains concurrently
            token_balances_task = self._get_all_token_balances(target_address)
            eth_balances_task = self._get_native_balances(target_address)
            strategy_balances_task = self._get_all_strategy_balances(target_address)
            
            # Wait for all tasks to complete
            all_balances, eth_balances, strategy_balances = await asyncio.gather(
                token_balances_task,
                eth_balances_task,
                strategy_balances_task
            )
            
            # Combine all balances
            all_balances.extend(eth_balances)
            
            # Filter to only tokens with positive balances and valid coingecko IDs
            tokens_with_balances = [
                balance for balance in all_balances 
                if balance["coingeckoId"] and balance["balance"] > 0
            ]
            
            logger.info(f"Found {len(tokens_with_balances)} tokens with positive balances for address {target_address}")
            
            # Only get prices if we have tokens with balances
            prices = {}
            if tokens_with_balances:
                unique_coingecko_ids = list(set(
                    balance["coingeckoId"] for balance in tokens_with_balances
                ))
                logger.info(f"Getting prices for {len(unique_coingecko_ids)} unique tokens: {unique_coingecko_ids}")
                prices = await self._get_token_prices_async(unique_coingecko_ids)
            else:
                logger.info("No tokens with positive balances found, skipping price lookup")
            
            # Calculate USD values for regular holdings
            total_value = 0.0
            holdings = []
            
            for balance in tokens_with_balances:
                token_price = prices.get(balance["coingeckoId"], 0.0)
                usd_value = balance["balance"] * token_price
                total_value += usd_value
                
                holdings.append({
                    "symbol": balance["symbol"],
                    "name": balance["name"],
                    "chain_id": balance["chain_id"],
                    "balance": balance["balance"],
                    "price_usd": token_price,
                    "value_usd": usd_value,
                    "type": "token"
                })
            
            # Calculate USD values for strategy balances
            strategy_holdings = []
            strategy_tokens_with_prices = [
                balance for balance in strategy_balances 
                if balance["coingeckoId"] and balance["balance"] > 0
            ]
            
            for balance in strategy_tokens_with_prices:
                token_price = prices.get(balance["coingeckoId"], 0.0)
                usd_value = balance["balance"] * token_price
                total_value += usd_value
                
                strategy_holdings.append({
                    "symbol": balance["token_symbol"],
                    "name": balance["token_name"],
                    "chain_id": balance["chain_id"],
                    "balance": balance["balance"],
                    "price_usd": token_price,
                    "value_usd": usd_value,
                    "type": "strategy",
                    "strategy": balance["strategy"],
                    "protocol": balance["protocol"],
                    "strategy_type": balance["strategy_type"]
                })
            
            # Combine all holdings
            all_holdings = holdings + strategy_holdings
            
            # Sort holdings by USD value (highest first)
            all_holdings.sort(key=lambda x: x["value_usd"], reverse=True)
            
            # Count active strategies
            active_strategies = list(set(
                h["strategy"] for h in strategy_holdings
            ))
            
            portfolio_summary = {
                "vault_address": vault_address,
                "wallet_address": wallet_address,
                "target_address": target_address,
                "total_value_usd": total_value,
                "holdings": all_holdings,
                "chains_count": len(set(h["chain_id"] for h in all_holdings)),
                "tokens_count": len(holdings),
                "strategy_count": len(strategy_holdings),
                "active_strategies": active_strategies
            }

            # Store in memory cache first
            self._memory_cache[target_address] = {
                'data': portfolio_summary.copy(),
                'timestamp': datetime.datetime.utcnow()
            }
            logger.info(f"Cached portfolio in memory for address {target_address}")

            # Also store in database cache if available
            if self.db is not None:
                try:
                    cache_collection = self.db.portfolio_cache
                    data_to_cache = portfolio_summary.copy()
                    data_to_cache['timestamp'] = datetime.datetime.utcnow()
                    
                    await cache_collection.update_one(
                        {"vault_address": target_address},
                        {"$set": data_to_cache},
                        upsert=True
                    )
                    logger.info(f"Cached portfolio in database for address {target_address}")
                except Exception as e:
                    logger.error(f"Error caching portfolio data in database for address {target_address}: {e}")
            
            return portfolio_summary
            
        except Exception as e:
            logger.error(f"Error getting portfolio summary for address {target_address}: {e}")
            return {
                "vault_address": vault_address,
                "wallet_address": wallet_address,
                "target_address": target_address,
                "total_value_usd": 0.0,
                "holdings": [],
                "chains_count": 0,
                "tokens_count": 0,
                "strategy_count": 0,
                "active_strategies": [],
                "error": str(e)
            }
    
    async def _get_token_prices_async(self, coingecko_ids: List[str]) -> Dict[str, float]:
        """Async wrapper for getting token prices with proper event loop handling"""
        if not coingecko_ids:
            logger.info("No CoinGecko IDs provided, returning empty prices")
            return {}
            
        # Use the async version that properly handles the event loop and database
        return await self.coingecko.get_token_prices_async(coingecko_ids)
    
    async def _get_all_token_balances(self, vault_address: str) -> List[Dict[str, Any]]:
        """Get balances for all ERC20 tokens across all chains concurrently"""
        tasks = []
        
        for token_symbol, token_config in SUPPORTED_TOKENS.items():
            for chain_id, token_address in token_config["addresses"].items():
                if chain_id not in self.web3_instances:
                    logger.warning(f"Chain {chain_id} not available for token {token_symbol}")
                    continue
                    
                task = self._get_token_balance_async(
                    vault_address, token_address, chain_id, token_config
                )
                tasks.append((task, token_config, chain_id))
        
        logger.info(f"Checking balances for {len(tasks)} token/chain combinations")
        
        # Execute all balance checks concurrently
        results = await asyncio.gather(*[task for task, _, _ in tasks], return_exceptions=True)
        
        balances = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error getting balance: {result}")
                continue
                
            _, token_config, chain_id = tasks[i]
            balance = result
            
            # Always include balances (even zero) for proper tracking
            if balance is not None:
                balances.append({
                    "symbol": token_config["symbol"],
                    "name": token_config["name"],
                    "chain_id": chain_id,
                    "balance": balance,
                    "coingeckoId": token_config.get("coingeckoId")
                })
                logger.debug(f"{token_config['symbol']} on chain {chain_id}: {balance}")
        
        logger.info(f"Retrieved balances for {len(balances)} tokens")
        return balances
    
    async def _get_native_balances(self, vault_address: str) -> List[Dict[str, Any]]:
        """Get native currency (ETH) balances for all chains concurrently"""
        tasks = []
        
        for chain_id in self.web3_instances:
            if chain_id in NATIVE_CURRENCIES:
                native_config = NATIVE_CURRENCIES[chain_id]
                task = self._get_native_balance_async(vault_address, chain_id)
                tasks.append((task, native_config, chain_id))
        
        logger.info(f"Checking native balances for {len(tasks)} chains")
        
        # Execute all balance checks concurrently
        results = await asyncio.gather(*[task for task, _, _ in tasks], return_exceptions=True)
        
        balances = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error getting native balance: {result}")
                continue
                
            _, native_config, chain_id = tasks[i]
            balance = result
            
            # Always include balances (even zero) for proper tracking
            if balance is not None:
                balances.append({
                    "symbol": native_config["symbol"],
                    "name": native_config["name"],
                    "chain_id": chain_id,
                    "balance": balance,
                    "coingeckoId": native_config.get("coingeckoId")
                })
                logger.debug(f"{native_config['symbol']} on chain {chain_id}: {balance}")
        
        logger.info(f"Retrieved native balances for {len(balances)} chains")
        return balances
    
    async def _get_all_strategy_balances(self, vault_address: str) -> List[Dict[str, Any]]:
        """Get balances for all strategies concurrently"""
        tasks = []
        
        # Create tasks for each strategy balance checker
        for strategy_name, balance_checker in STRATEGY_BALANCE_CHECKERS.items():
            task = balance_checker(self.web3_instances, vault_address, SUPPORTED_TOKENS)
            tasks.append(task) # Directly append the coroutine
        
        logger.info(f"Checking strategy balances for {len(tasks)} strategies")
        
        # Execute all strategy balance checks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_strategy_balances = []
        for i, result in enumerate(results):
            strategy_name = list(STRATEGY_BALANCE_CHECKERS.keys())[i]
            if isinstance(result, Exception):
                logger.error(f"Error getting {strategy_name} strategy balances: {result}")
                continue
                
            # Result should be a list of strategy balance dictionaries
            if isinstance(result, list):
                all_strategy_balances.extend(result)
                logger.info(f"Found {len(result)} strategy balances from {strategy_name}")
        
        logger.info(f"Retrieved total of {len(all_strategy_balances)} strategy balances")
        return all_strategy_balances
    
    async def _get_token_balance_async(self, vault_address: str, token_address: str, chain_id: int, token_config: Dict) -> Optional[float]:
        """Get balance for a specific ERC20 token asynchronously"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._get_token_balance,
            vault_address,
            token_address,
            chain_id,
            token_config
        )
    
    async def _get_native_balance_async(self, vault_address: str, chain_id: int) -> Optional[float]:
        """Get native currency balance (ETH) asynchronously"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._get_native_balance,
            vault_address,
            chain_id
        )
    
    def _get_token_balance(self, vault_address: str, token_address: str, chain_id: int, token_config: Dict) -> Optional[float]:
        """Get balance for a specific ERC20 token"""
        try:
            w3 = self.web3_instances.get(chain_id)
            if not w3 or not self.Web3:
                return None
            
            # Create contract instance
            contract = w3.eth.contract(
                address=self.Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )
            
            # Get balance
            balance_wei = contract.functions.balanceOf(vault_address).call()
            
            # Convert to human readable format
            decimals = token_config["decimals"]
            balance = float(balance_wei) / (10 ** decimals)
            
            return balance
            
        except Exception as e:
            logger.error(f"Error getting token balance for {token_config['symbol']} on chain {chain_id}: {e}")
            return None
    
    def _get_native_balance(self, vault_address: str, chain_id: int) -> Optional[float]:
        """Get native currency balance (ETH)"""
        try:
            w3 = self.web3_instances.get(chain_id)
            if not w3:
                return None
            
            balance_wei = w3.eth.get_balance(vault_address)
            balance_eth = float(balance_wei) / (10 ** 18)  # ETH has 18 decimals
            
            return balance_eth
            
        except Exception as e:
            logger.error(f"Error getting native balance on chain {chain_id}: {e}")
            return None

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
                    "strategies": {}
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