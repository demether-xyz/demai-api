"""
Shared utilities for fetching and formatting AAVE yields data.
"""
from typing import List, Dict, Any
from tools.aave_tool import get_all_aave_yields
from utils.mongo_connection import mongo_connection
from config import logger, CHAIN_CONFIG


async def get_simplified_aave_yields() -> List[Dict[str, Any]]:
    """Get simplified AAVE yields data for context.
    
    Returns:
        List of dicts with token, chain, and borrow_apy
    """
    try:
        # Connect to database
        db = await mongo_connection.connect()
        
        # Fetch all yields with database for caching
        yields = await get_all_aave_yields(db=db)
        
        # Simplify the data
        simplified_yields = []
        for token_symbol, chain_yields in yields.items():
            for yield_data in chain_yields:
                chain_id = yield_data.get('chain_id')
                chain_name = CHAIN_CONFIG.get(chain_id, {}).get('name', f'Chain {chain_id}')
                
                simplified_yields.append({
                    'token': token_symbol,
                    'chain': chain_name,
                    'borrow_apy': round(yield_data.get('borrow_apy', 0), 2)
                })
        
        return simplified_yields
    except Exception as e:
        logger.warning(f"Failed to fetch AAVE yields: {e}")
        return []


def get_available_tokens_and_chains() -> Dict[str, Any]:
    """Get available tokens and chains from config.
    
    Returns:
        Dict with available_tokens and available_chains
    """
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG
    
    # Extract available tokens and their chains
    available_tokens = {}
    for token_symbol, token_info in SUPPORTED_TOKENS.items():
        chains = []
        for chain_id in token_info.get("addresses", {}):
            if chain_id in CHAIN_CONFIG:
                chains.append(CHAIN_CONFIG[chain_id]["name"])
        if chains:
            available_tokens[token_symbol] = chains
    
    # Extract available chains
    available_chains = [config["name"] for config in CHAIN_CONFIG.values()]
    
    return {
        "available_tokens": available_tokens,
        "available_chains": available_chains
    }


def get_available_tokens_and_yield_assets() -> Dict[str, Any]:
    """Get available tokens, yield-bearing assets, and chains from config.
    
    Returns:
        Dict with available_tokens, yield_bearing_assets, and available_chains
    """
    from config import SUPPORTED_TOKENS, CHAIN_CONFIG
    
    # Extract available tokens and their chains
    available_tokens = {}
    yield_bearing_assets = {}
    
    for token_symbol, token_info in SUPPORTED_TOKENS.items():
        # Get regular token chains
        chains = []
        for chain_id in token_info.get("addresses", {}):
            if chain_id in CHAIN_CONFIG:
                chains.append(CHAIN_CONFIG[chain_id]["name"])
        if chains:
            available_tokens[token_symbol] = chains
        
        # Get yield-bearing assets (aTokens/vault tokens)
        if "aave_atokens" in token_info:
            for chain_id, atoken_config in token_info["aave_atokens"].items():
                if chain_id not in CHAIN_CONFIG:
                    continue
                    
                chain_name = CHAIN_CONFIG[chain_id]["name"]
                
                # Handle both single aToken and multiple aTokens (array format)
                if isinstance(atoken_config, list):
                    # Multiple yield assets (new array format like Katana vaults)
                    for atoken_data in atoken_config:
                        asset_name = atoken_data.get("name")
                        if asset_name:
                            if asset_name not in yield_bearing_assets:
                                yield_bearing_assets[asset_name] = []
                            if chain_name not in yield_bearing_assets[asset_name]:
                                yield_bearing_assets[asset_name].append(chain_name)
                elif isinstance(atoken_config, str):
                    # Legacy single aToken (string address)
                    # Determine protocol based on chain
                    if chain_id == 747474:  # Katana
                        asset_name = f"Steakhouse High Yield {token_symbol}"
                    else:
                        asset_name = f"a{token_symbol}"
                    
                    if asset_name not in yield_bearing_assets:
                        yield_bearing_assets[asset_name] = []
                    if chain_name not in yield_bearing_assets[asset_name]:
                        yield_bearing_assets[asset_name].append(chain_name)
                else:
                    # Single aToken (dict format)
                    asset_name = atoken_config.get("name")
                    if not asset_name:
                        # Fallback naming based on chain
                        if chain_id == 747474:  # Katana
                            asset_name = f"Steakhouse High Yield {token_symbol}"
                        else:
                            asset_name = f"a{token_symbol}"
                    
                    if asset_name not in yield_bearing_assets:
                        yield_bearing_assets[asset_name] = []
                    if chain_name not in yield_bearing_assets[asset_name]:
                        yield_bearing_assets[asset_name].append(chain_name)
    
    # Extract available chains
    available_chains = [config["name"] for config in CHAIN_CONFIG.values()]
    
    return {
        "available_tokens": available_tokens,
        "yield_bearing_assets": yield_bearing_assets,
        "available_chains": available_chains
    }