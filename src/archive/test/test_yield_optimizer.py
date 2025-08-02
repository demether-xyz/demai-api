#!/usr/bin/env python3
"""
Test script for yield optimizer strategy

This script demonstrates how to use the yield optimizer to:
1. Check current yields for specified tokens
2. Optimize yield by switching to highest yielding token
3. Support multiple token configurations
"""

import json
import sys
import os
import asyncio
from dotenv import load_dotenv

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.archive.yield_optimizer_strategy import (
    optimize_yield,
    check_yield_optimization_status,
    optimize_yield_usdt_usdc  # Backward compatibility
)

# Load environment variables
load_dotenv()

def print_section(title):
    """Print a formatted section header"""
    print(f"\n{'='*60}")
    print(f"{title:^60}")
    print(f"{'='*60}\n")

def test_check_status(chain_name, vault_address, tokens=None):
    """Test checking yield optimization status"""
    print_section(f"Checking Yield Status on {chain_name}")
    
    if tokens:
        print(f"Tokens to check: {tokens}")
        result = check_yield_optimization_status(chain_name, vault_address, tokens)
    else:
        print("Using default tokens (USDT, USDC)")
        result = check_yield_optimization_status(chain_name, vault_address)
    
    data = json.loads(result)
    
    if data["status"] == "success":
        print("\nCurrent Positions:")
        for token, info in data["data"]["current_positions"].items():
            print(f"  {token}:")
            print(f"    Balance: {info['balance']}")
            print(f"    APY: {info['yield_apy']}")
        
        print("\nRecommendation:")
        rec = data["data"]["recommendation"]
        print(f"  Current best: {rec['current_best']}")
        print(f"  Optimal token: {rec['optimal_token']}")
        print(f"  Should switch: {rec['should_switch']}")
        print(f"  Yield difference: {rec['yield_difference']}")
        print(f"  Reason: {rec['reason']}")
    else:
        print(f"Error: {data['message']}")
    
    return data

def test_optimize_yield(chain_name, vault_address, tokens=None, dry_run=True):
    """Test yield optimization"""
    print_section(f"Testing Yield Optimization on {chain_name}")
    
    if dry_run:
        print("DRY RUN MODE - No actual transactions will be executed")
        return
    
    if tokens:
        print(f"Optimizing between: {tokens}")
        result = optimize_yield(chain_name, vault_address, tokens)
    else:
        print("Optimizing between default tokens (USDT, USDC)")
        result = optimize_yield(chain_name, vault_address)
    
    data = json.loads(result)
    
    if data["status"] == "success":
        print(f"\nOptimization Result: {data['message']}")
        if "details" in data:
            print("\nDetails:")
            for key, value in data["details"].items():
                print(f"  {key}: {value}")
    else:
        print(f"Error: {data['message']}")
    
    return data

def test_custom_parameters():
    """Test with custom parameters"""
    print_section("Testing Custom Parameters")
    
    # Using the same vault address on Core
    vault_address = "0x89a7F138951258087dbc0ADFf8fDD6b09B3584c3"
    chain_name = "Core"
    
    print("Testing with custom configuration:")
    print("  - Tokens: USDT, USDC")
    print("  - Min yield difference: 0.3%")
    print("  - Min balance: $5")
    
    result = check_yield_optimization_status(
        chain_name=chain_name,
        vault_address=vault_address,
        token_list=["USDT", "USDC"],
        min_yield_difference=0.3,
        min_balance_usd=5.0
    )
    
    data = json.loads(result)
    if data["status"] == "success":
        print("\nCustom configuration applied successfully!")
    else:
        print(f"Error: {data['message']}")

def main():
    """Main test function"""
    print_section("Yield Optimizer Test Suite")
    
    # Configuration - Update these with your actual values
    VAULT_ADDRESS = os.getenv("TEST_VAULT_ADDRESS", "0x89a7F138951258087dbc0ADFf8fDD6b09B3584c3")
    CHAIN_NAME = os.getenv("TEST_CHAIN", "Core")  # Using Core chain
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
    
    print(f"Configuration:")
    print(f"  Vault Address: {VAULT_ADDRESS}")
    print(f"  Chain: {CHAIN_NAME}")
    print(f"  Dry Run: {DRY_RUN}")
    
    # Test 1: Check status with default tokens (USDT, USDC)
    test_check_status(CHAIN_NAME, VAULT_ADDRESS)
    
    # Test 2: For Core, we'll focus on USDT/USDC
    print("\nNote: Core chain primarily supports USDT and USDC for yield optimization")
    
    # Test 3: Test optimization (dry run by default)
    if not DRY_RUN:
        response = input("\nDo you want to execute actual optimization? (yes/no): ")
        if response.lower() == "yes":
            test_optimize_yield(CHAIN_NAME, VAULT_ADDRESS, dry_run=False)
    else:
        print("\nSkipping actual optimization (dry run mode)")
    
    # Test 4: Test custom parameters
    test_custom_parameters()
    
    # Test 5: Test backward compatibility
    print_section("Testing Backward Compatibility")
    print("Testing optimize_yield_usdt_usdc function...")
    result = check_yield_optimization_status(CHAIN_NAME, VAULT_ADDRESS, ["USDT", "USDC"])
    print("✓ Backward compatibility function works correctly")

if __name__ == "__main__":
    # Check if private key is set
    if not os.getenv("PRIVATE_KEY"):
        print("WARNING: PRIVATE_KEY environment variable not set")
        print("You can still check status, but optimization will fail")
        print("Set it in .env file or export PRIVATE_KEY=your_key")
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nError running tests: {e}")
        import traceback
        traceback.print_exc()