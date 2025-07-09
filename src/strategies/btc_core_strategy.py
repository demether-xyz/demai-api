"""
BTC Core Strategy implementation for optimizing BTC yields on Core chain via Colend (Aave V3)
This strategy monitors yields for SOLVBTC, BTCB, and WBTC and allocates to the best yielding option
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from web3 import Web3

from .base_strategy import BaseStrategy, StrategyResult, RiskLevel
from .aave_strategy import (
    get_aave_current_yield, 
    supply_to_aave,
    get_aave_strategy_balances,
    _get_aave_reserve_data,
    _ray_to_apy
)

logger = logging.getLogger(__name__)


class BTCCoreStrategy(BaseStrategy):
    """
    BTC yield optimization strategy on Core chain using Colend (Aave V3)
    
    This strategy:
    1. Monitors yields for SOLVBTC, BTCB, and WBTC on Colend daily
    2. Reports current yields to the frontend  
    3. For execution, currently deposits into SOLVBTC (can be extended for optimization)
    4. Maintains yield data cache for performance
    """
    
    # Supported BTC tokens on Core
    BTC_TOKENS = ["SOLVBTC", "BTCB", "WBTC"]
    
    def __init__(self):
        # Cache for yield data
        self._yield_cache = {}
        self._cache_timestamp = None
        self._cache_ttl = timedelta(hours=1)  # Cache yields for 1 hour
        
        super().__init__(
            strategy_id="btc_core_yield",
            name="BTC Yield Optimizer",
            description="Optimizes BTC yields on Core chain via Colend lending",
            detailed_description="Monitors and optimizes yields for Bitcoin-based assets (SOLVBTC, BTCB, WBTC) on Core blockchain using Colend protocol. The strategy tracks yield rates daily and allocates funds to maximize returns while maintaining low risk exposure.",
            chain_id=1116,  # Core
            chain_name="Core",
            chain_icon="⚡",
            primary_token="SOLVBTC",
            secondary_tokens=["BTCB", "WBTC"],
            apy=0.0,  # Will be updated with live data when fetched
            risk_level=RiskLevel.LOW,
            update_frequency="Daily",
            protocol="Colend (Aave V3)",
            threshold_info="Minimum 0.0001 BTC equivalent required"
        )
    
    async def execute(self, task_data: Dict[str, Any]) -> StrategyResult:
        """
        Execute the BTC yield optimization strategy
        
        Currently: Simple implementation that deposits into SOLVBTC
        Future: Will analyze yields and choose optimal allocation
        """
        try:
            user_address = task_data["user_address"]
            vault_address = task_data["vault_address"]
            amount = task_data["amount"]
            params = task_data.get("params", {})
            chain_id = task_data["chain_id"]
            
            # Validate we're on Core chain
            if chain_id != 1116:
                return StrategyResult(
                    success=False,
                    error=f"BTC Core Strategy only supports Core chain (1116), got {chain_id}"
                )
            
            # Get target token from params or default to SOLVBTC
            target_token = params.get("target_token", "SOLVBTC")
            if target_token not in self.BTC_TOKENS:
                return StrategyResult(
                    success=False,
                    error=f"Unsupported BTC token: {target_token}. Supported: {self.BTC_TOKENS}"
                )
            
            logger.info(f"Executing BTC Core strategy for user {user_address}")
            logger.info(f"Vault: {vault_address}, Amount: {amount}, Target: {target_token}")
            
            # Get current yield information for all BTC tokens
            yield_data = await self._get_btc_yields()
            
            # Import the strategy executor and supported tokens
            from config import SUPPORTED_TOKENS, RPC_ENDPOINTS
            from strategies.strategies import StrategyExecutor
            import os
            
            # Get private key for execution
            private_key = os.getenv("PRIVATE_KEY")
            if not private_key:
                return StrategyResult(
                    success=False,
                    error="PRIVATE_KEY environment variable not set"
                )
            
            # Create executor
            rpc_url = RPC_ENDPOINTS.get(chain_id)
            if not rpc_url:
                return StrategyResult(
                    success=False,
                    error=f"RPC URL not found for chain {chain_id}"
                )
            
            executor = StrategyExecutor(rpc_url, private_key)
            
            # Get token configuration
            token_config = SUPPORTED_TOKENS.get(target_token)
            if not token_config:
                return StrategyResult(
                    success=False,
                    error=f"Token {target_token} not found in supported tokens"
                )
            
            asset_address = token_config["addresses"].get(chain_id)
            if not asset_address:
                return StrategyResult(
                    success=False,
                    error=f"Token {target_token} not available on Core chain"
                )
            
            # Convert amount from string to int (wei)
            decimals = token_config["decimals"]
            try:
                amount_float = float(amount)
                amount_wei = int(amount_float * (10 ** decimals))
            except (ValueError, TypeError):
                return StrategyResult(
                    success=False,
                    error=f"Invalid amount format: {amount}"
                )
            
            # Execute supply to Aave (Colend)
            tx_hash = await supply_to_aave(
                executor=executor,
                chain_id=chain_id,
                vault_address=vault_address,
                asset_address=asset_address,
                amount=amount_wei
            )
            
            # Prepare result data
            result_data = {
                "strategy": "btc_core_yield",
                "action": "supply",
                "target_token": target_token,
                "amount": amount,
                "amount_wei": amount_wei,
                "vault_address": vault_address,
                "asset_address": asset_address,
                "chain_id": chain_id,
                "tx_hash": tx_hash,
                "executed_at": datetime.utcnow().isoformat(),
                "yield_data": yield_data,
                "strategy_info": {
                    "name": self.name,
                    "protocol": self.protocol,
                    "primary_token": self.primary_token,
                    "current_yields": {
                        token: data.get("supply_apy", 0) 
                        for token, data in yield_data.items() 
                        if "error" not in data
                    }
                }
            }
            
            return StrategyResult(
                success=True,
                data=result_data,
                tx_hash=tx_hash
            )
            
        except Exception as e:
            logger.error(f"Error in BTC Core strategy execution: {str(e)}")
            return StrategyResult(
                success=False,
                error=str(e)
            )
    
    async def _get_btc_yields(self) -> Dict[str, Dict[str, Any]]:
        """
        Get current yields for all BTC tokens, with caching
        
        Returns:
            Dictionary mapping token symbols to their yield data
        """
        # Check cache first
        if (self._cache_timestamp and 
            datetime.utcnow() - self._cache_timestamp < self._cache_ttl and
            self._yield_cache):
            logger.info("Returning cached BTC yield data")
            return self._yield_cache
        
        logger.info("Fetching fresh BTC yield data from Colend")
        
        from config import SUPPORTED_TOKENS, CHAIN_CONFIG, RPC_ENDPOINTS
        from web3 import Web3
        
        # Create Web3 instance for Core
        rpc_url = RPC_ENDPOINTS.get(1116)
        if not rpc_url:
            logger.error("No RPC URL configured for Core chain")
            return {}
        
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            logger.error("Failed to connect to Core RPC")
            return {}
        
        web3_instances = {1116: w3}
        yield_data = {}
        
        # Get yields for all BTC tokens
        for token_symbol in self.BTC_TOKENS:
            try:
                token_yield = await get_aave_current_yield(
                    web3_instances, token_symbol, 1116, SUPPORTED_TOKENS
                )
                yield_data[token_symbol] = token_yield
                
                if "error" not in token_yield:
                    logger.info(f"{token_symbol} yield: {token_yield.get('supply_apy', 0):.4f}%")
                else:
                    logger.warning(f"Error getting yield for {token_symbol}: {token_yield['error']}")
                    
            except Exception as e:
                logger.error(f"Exception getting yield for {token_symbol}: {e}")
                yield_data[token_symbol] = {"error": str(e)}
        
        # Update cache
        self._yield_cache = yield_data
        self._cache_timestamp = datetime.utcnow()
        
        # Update strategy APY with the best available yield
        self._update_strategy_apy(yield_data)
        
        return yield_data
    
    def _update_strategy_apy(self, yield_data: Dict[str, Dict[str, Any]]):
        """Update the strategy's reported APY with the best available yield"""
        best_apy = 0.0
        
        for token_symbol, data in yield_data.items():
            if "error" not in data:
                supply_apy = data.get("supply_apy", 0)
                if supply_apy > best_apy:
                    best_apy = supply_apy
        
        self.apy = best_apy
        logger.info(f"Updated strategy APY to {best_apy:.4f}%")
    
    async def get_current_yields(self) -> Dict[str, Any]:
        """
        Public method to get current yields for frontend integration
        
        Returns:
            Dictionary with yield information for all BTC tokens
        """
        yield_data = await self._get_btc_yields()
        
        formatted_yields = {
            "strategy_id": self.strategy_id,
            "strategy_name": self.name,
            "protocol": self.protocol,
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "last_updated": datetime.utcnow().isoformat(),
            "tokens": {}
        }
        
        for token_symbol in self.BTC_TOKENS:
            token_data = yield_data.get(token_symbol, {})
            
            if "error" not in token_data:
                formatted_yields["tokens"][token_symbol] = {
                    "symbol": token_symbol,
                    "supply_apy": token_data.get("supply_apy", 0),
                    "borrow_apy": token_data.get("borrow_apy", 0),
                    "utilization_rate": token_data.get("utilization_rate", 0),
                    "total_liquidity": token_data.get("total_liquidity", 0),
                    "last_update_timestamp": token_data.get("last_update_timestamp", 0)
                }
            else:
                formatted_yields["tokens"][token_symbol] = {
                    "symbol": token_symbol,
                    "error": token_data.get("error", "Unknown error")
                }
        
        return formatted_yields
    
    async def get_strategy_balances(self, web3_instances: Dict, vault_address: str, supported_tokens: Dict) -> List[Dict[str, Any]]:
        """
        Get strategy balances for all BTC tokens managed by this strategy
        
        This integrates with the existing Aave balance checker but filters for BTC tokens only
        """
        try:
            # Get all Aave balances first
            all_balances = await get_aave_strategy_balances(web3_instances, vault_address, supported_tokens)
            
            # Filter for BTC tokens on Core chain and mark with our strategy
            btc_balances = []
            for balance in all_balances:
                if (balance.get("token_symbol") in self.BTC_TOKENS and 
                    balance.get("chain_id") == 1116):
                    
                    # Update strategy identifier
                    balance["strategy"] = self.strategy_id
                    balance["strategy_name"] = self.name
                    balance["strategy_type"] = "btc_yield_optimization"
                    
                    btc_balances.append(balance)
            
            return btc_balances
            
        except Exception as e:
            logger.error(f"Error getting BTC strategy balances: {e}")
            return []
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate parameters for the BTC Core strategy
        """
        # Check target_token if provided
        if "target_token" in params:
            target_token = params["target_token"]
            if not isinstance(target_token, str):
                return False, "target_token must be a string"
            
            if target_token not in self.BTC_TOKENS:
                return False, f"target_token must be one of: {self.BTC_TOKENS}"
        
        # Check minimum_yield if provided
        if "minimum_yield" in params:
            min_yield = params["minimum_yield"]
            if not isinstance(min_yield, (int, float)) or min_yield < 0:
                return False, "minimum_yield must be a non-negative number"
        
        return True, None
    
    def get_default_interval_hours(self) -> int:
        """Run daily to monitor yields"""
        return 24
    
    def get_required_params(self) -> list[str]:
        """No required params - uses defaults"""
        return []
    
    def to_dict(self) -> Dict[str, Any]:
        """Return strategy information with current yield data for frontend"""
        # Fetch live yield data when strategy info is requested
        self._update_live_yields()
        
        base_dict = super().to_dict()
        
        # Add BTC-specific information
        base_dict.update({
            "supported_tokens": self.BTC_TOKENS,
            "yield_cache_ttl_hours": self._cache_ttl.total_seconds() / 3600,
            "last_yield_update": self._cache_timestamp.isoformat() if self._cache_timestamp else None,
            "current_best_apy": self.apy
        })
        
        return base_dict
    
    def _update_live_yields(self):
        """Synchronously update yields and description when strategy info is requested"""
        import asyncio
        import concurrent.futures
        import json
        
        try:
            # Check if cache is still fresh (within 1 hour)
            if (self._cache_timestamp and 
                datetime.utcnow() - self._cache_timestamp < self._cache_ttl and
                self._yield_cache):
                logger.info("Using cached yield data for strategy info")
                return
            
            # Fetch fresh yields synchronously
            logger.info("Fetching fresh yields for strategy info")
            
            # Check if we're already in an event loop
            try:
                asyncio.get_running_loop()
                # Run in a thread to avoid loop conflict
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(_run_async_yields, self)
                    yields = future.result(timeout=15)  # 15 second timeout for API response
            except RuntimeError:
                # No running loop, safe to create new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    yields = loop.run_until_complete(self.get_current_yields())
                finally:
                    loop.close()
            
            # Update description with current best yield information
            if yields and "tokens" in yields:
                best_yield = 0.0
                best_token = None
                
                for token_symbol, token_data in yields["tokens"].items():
                    if "error" not in token_data:
                        supply_apy = token_data.get("supply_apy", 0)
                        if supply_apy > best_yield:
                            best_yield = supply_apy
                            best_token = token_symbol
                
                if best_token and best_yield > 0:
                    # Update description with live data
                    self.description = f"BTC yield optimization on Core chain via Colend. Currently earning {best_yield:.2f}% APY with {best_token}. Monitors SOLVBTC, BTCB, and WBTC yields daily."
                    self.detailed_description = f"Advanced BTC yield strategy that monitors lending yields for SOLVBTC, BTCB, and WBTC on Core chain's Colend (Aave V3) protocol. Currently targeting {best_token} at {best_yield:.2f}% APY. The strategy automatically updates yield data daily and can be configured to optimize allocations based on yield differentials. Executes deposits via smart contract integration for maximum capital efficiency."
                    logger.info(f"Updated strategy description with live yield: {best_yield:.2f}% APY on {best_token}")
                else:
                    logger.warning("No valid yield data found to update description")
            
        except Exception as e:
            logger.error(f"Error updating live yields for strategy info: {e}")
            # Continue with cached/default values if live update fails


# Synchronous helper functions for LangChain compatibility

def get_btc_yields_on_core() -> str:
    """
    Get current BTC yields on Core chain (Colend)
    Synchronous function for LangChain compatibility
    
    Returns:
        JSON string with yield information for all BTC tokens
    """
    import json
    import asyncio
    
    try:
        # Create strategy instance
        strategy = BTCCoreStrategy()
        
        # Check if we're already in an event loop
        try:
            # If this succeeds, we're in an event loop
            asyncio.get_running_loop()
            # Run in a thread to avoid loop conflict
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_run_async_yields, strategy)
                yields = future.result(timeout=30)  # 30 second timeout
        except RuntimeError:
            # No running loop, safe to create new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                yields = loop.run_until_complete(strategy.get_current_yields())
            finally:
                loop.close()
        
        return json.dumps({
            "status": "success",
            "data": yields
        })
        
    except Exception as e:
        logger.error(f"Error in get_btc_yields_on_core: {e}")
        return json.dumps({
            "status": "error", 
            "message": f"Failed to retrieve BTC yields: {str(e)}"
        })

def _run_async_yields(strategy):
    """Helper function to run async yields in a new event loop"""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(strategy.get_current_yields())
    finally:
        loop.close()

def _run_async_supply(executor, vault_address, asset_address, amount_wei):
    """Helper function to run async supply in a new event loop"""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(supply_to_aave(
            executor=executor,
            chain_id=1116,
            vault_address=vault_address,
            asset_address=asset_address,
            amount=amount_wei
        ))
    finally:
        loop.close()

def supply_btc_to_colend(
    token_symbol: str,
    amount: float,
    vault_address: str
) -> str:
    """
    Supply BTC token to Colend on Core chain
    Synchronous function for LangChain compatibility
    
    Args:
        token_symbol: BTC token symbol ("SOLVBTC", "BTCB", "WBTC")
        amount: Amount to supply (human-readable format)
        vault_address: Vault address to supply from
        
    Returns:
        JSON string with transaction result
    """
    import json
    import asyncio
    import os
    
    try:
        # Validate token
        if token_symbol not in BTCCoreStrategy.BTC_TOKENS:
            return json.dumps({
                "status": "error",
                "message": f"Unsupported BTC token: {token_symbol}. Supported: {BTCCoreStrategy.BTC_TOKENS}"
            })
        
        from config import SUPPORTED_TOKENS, RPC_ENDPOINTS
        from strategies.strategies import StrategyExecutor
        
        # Get private key
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            return json.dumps({
                "status": "error",
                "message": "PRIVATE_KEY environment variable not set"
            })
        
        # Get token configuration
        token_config = SUPPORTED_TOKENS.get(token_symbol)
        if not token_config:
            return json.dumps({
                "status": "error",
                "message": f"Token {token_symbol} not found in configuration"
            })
        
        asset_address = token_config["addresses"].get(1116)  # Core chain
        if not asset_address:
            return json.dumps({
                "status": "error",
                "message": f"Token {token_symbol} not available on Core chain"
            })
        
        # Convert amount to wei
        decimals = token_config["decimals"]
        amount_wei = int(amount * (10 ** decimals))
        
        # Get RPC URL and create executor
        rpc_url = RPC_ENDPOINTS.get(1116)
        if not rpc_url:
            return json.dumps({
                "status": "error",
                "message": "RPC URL not configured for Core chain"
            })
        
        executor = StrategyExecutor(rpc_url, private_key)
        
        # Execute supply
        try:
            # Check if we're already in an event loop
            asyncio.get_running_loop()
            # Run in a thread to avoid loop conflict
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor_thread:
                future = executor_thread.submit(_run_async_supply, executor, vault_address, asset_address, amount_wei)
                tx_hash = future.result(timeout=60)  # 60 second timeout for transaction
        except RuntimeError:
            # No running loop, safe to create new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                tx_hash = loop.run_until_complete(supply_to_aave(
                    executor=executor,
                    chain_id=1116,
                    vault_address=vault_address,
                    asset_address=asset_address,
                    amount=amount_wei
                ))
            finally:
                loop.close()
        
        return json.dumps({
            "status": "success",
            "message": f"Successfully supplied {amount} {token_symbol} to Colend",
            "tx_hash": tx_hash,
            "amount": amount,
            "token": token_symbol,
            "vault": vault_address
        })
        
    except Exception as e:
        logger.error(f"Error in supply_btc_to_colend: {e}")
        return json.dumps({
            "status": "error",
            "message": f"Failed to supply BTC to Colend: {str(e)}"
        }) 