"""
Shared utilities for fetching and formatting Morpho yields data.
"""
from typing import List, Dict, Any
from tools.morpho_tool import get_all_morpho_yields
from utils.mongo_connection import mongo_connection
from config import logger, CHAIN_CONFIG


async def get_simplified_morpho_yields() -> List[Dict[str, Any]]:
    """Get simplified Morpho yields data for context.
    
    Returns:
        List of dicts with token, chain, and supply_apy
    """
    try:
        # Connect to database
        db = await mongo_connection.connect()
        
        # Fetch all yields with database for caching
        yields = await get_all_morpho_yields(db=db)
        
        # Simplify the data
        simplified_yields = []
        for token_symbol, chain_yields in yields.items():
            for yield_data in chain_yields:
                chain_id = yield_data.get('chain_id')
                chain_name = CHAIN_CONFIG.get(chain_id, {}).get('name', f'Chain {chain_id}')
                
                # Determine the display name based on vault type
                vault_type = yield_data.get('vault_type', 'Direct Market')
                if vault_type == 'MetaMorpho':
                    vault_address = yield_data.get('vault_address', '')
                    # Map known vault addresses to friendly names
                    if vault_address == "0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD":
                        protocol_name = "Steakhouse Prime AUSD Vault"
                    elif vault_address == "0x9540441C503D763094921dbE4f13268E6d1d3B56":
                        protocol_name = "Gauntlet AUSD Vault"
                    else:
                        protocol_name = f"MetaMorpho Vault ({vault_address[:8]}...)"
                else:
                    market_id = yield_data.get('market_id', '')
                    protocol_name = f"Morpho Market ({market_id[:8]}...)"
                
                simplified_yields.append({
                    'token': token_symbol,
                    'chain': chain_name,
                    'supply_apy': round(yield_data.get('supply_apy', 0), 2),
                    'protocol': protocol_name,
                    'vault_type': vault_type,
                    'market_or_vault_id': yield_data.get('vault_address') or yield_data.get('market_id')
                })
        
        return simplified_yields
    except Exception as e:
        logger.warning(f"Failed to fetch Morpho yields: {e}")
        return []


def get_available_morpho_assets() -> Dict[str, Any]:
    """Get available Morpho markets and vaults information.
    
    Returns:
        Dict with available morpho assets information
    """
    # Known Morpho deployments and vaults
    morpho_assets = {
        "Katana": {
            "chain_id": 747474,
            "vaults": [
                {
                    "name": "Steakhouse Prime AUSD Vault",
                    "address": "0x82c4C641CCc38719ae1f0FBd16A64808d838fDfD",
                    "asset": "AUSD",
                    "type": "MetaMorpho"
                },
                {
                    "name": "Gauntlet AUSD Vault", 
                    "address": "0x9540441C503D763094921dbE4f13268E6d1d3B56",
                    "asset": "AUSD",
                    "type": "MetaMorpho"
                }
            ]
        }
    }
    
    return {
        "morpho_assets": morpho_assets,
        "supported_tokens": ["AUSD"],  # Currently only AUSD vaults on Katana
        "supported_chains": ["Katana"]
    }


async def get_best_morpho_yield_for_token(token_symbol: str) -> Dict[str, Any]:
    """Get the best Morpho yield opportunity for a specific token.
    
    Args:
        token_symbol: Token to find best yield for
        
    Returns:
        Dict with best yield information
    """
    try:
        yields = await get_simplified_morpho_yields()
        
        # Filter for the requested token
        token_yields = [y for y in yields if y['token'].upper() == token_symbol.upper()]
        
        if not token_yields:
            return {"error": f"No Morpho yields found for {token_symbol}"}
        
        # Find the highest supply APY
        best_yield = max(token_yields, key=lambda x: x['supply_apy'])
        
        return {
            "token": token_symbol,
            "best_apy": best_yield['supply_apy'],
            "protocol": best_yield['protocol'],
            "chain": best_yield['chain'],
            "market_or_vault_id": best_yield['market_or_vault_id'],
            "vault_type": best_yield['vault_type']
        }
    except Exception as e:
        logger.error(f"Error finding best Morpho yield for {token_symbol}: {e}")
        return {"error": f"Failed to find best yield: {str(e)}"}


async def compare_morpho_vs_aave_yields(token_symbol: str) -> Dict[str, Any]:
    """Compare Morpho vs Aave yields for a token.
    
    Args:
        token_symbol: Token to compare yields for
        
    Returns:
        Dict with comparison data
    """
    try:
        from utils.aave_yields_utils import get_simplified_aave_yields
        
        # Get yields from both protocols
        morpho_yields = await get_simplified_morpho_yields()
        aave_yields = await get_simplified_aave_yields()
        
        # Filter for requested token
        morpho_token_yields = [y for y in morpho_yields if y['token'].upper() == token_symbol.upper()]
        aave_token_yields = [y for y in aave_yields if y['token'].upper() == token_symbol.upper()]
        
        comparison = {
            "token": token_symbol,
            "morpho_options": len(morpho_token_yields),
            "aave_options": len(aave_token_yields),
            "best_morpho": None,
            "best_aave": None,
            "recommendation": None
        }
        
        # Find best from each protocol
        if morpho_token_yields:
            best_morpho = max(morpho_token_yields, key=lambda x: x['supply_apy'])
            comparison["best_morpho"] = {
                "apy": best_morpho['supply_apy'],
                "protocol": best_morpho['protocol'],
                "chain": best_morpho['chain']
            }
        
        if aave_token_yields:
            best_aave = max(aave_token_yields, key=lambda x: x['borrow_apy'])
            comparison["best_aave"] = {
                "apy": best_aave['borrow_apy'],
                "protocol": f"Aave on {best_aave['chain']}",
                "chain": best_aave['chain']
            }
        
        # Make recommendation
        if comparison["best_morpho"] and comparison["best_aave"]:
            if comparison["best_morpho"]["apy"] > comparison["best_aave"]["apy"]:
                comparison["recommendation"] = "morpho"
            else:
                comparison["recommendation"] = "aave"
        elif comparison["best_morpho"]:
            comparison["recommendation"] = "morpho"
        elif comparison["best_aave"]:
            comparison["recommendation"] = "aave"
        
        return comparison
        
    except Exception as e:
        logger.error(f"Error comparing yields for {token_symbol}: {e}")
        return {"error": f"Failed to compare yields: {str(e)}"}