#!/usr/bin/env python3
"""
Simple test script for yield optimizer on Core chain with USDT/USDC

Usage:
    python test_yield_optimizer_core.py        # Check status only
    python test_yield_optimizer_core.py run    # Execute optimization
"""

import json
import sys
import os
from dotenv import load_dotenv

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from strategies.yield_optimizer_strategy import (
    optimize_yield,
    check_yield_optimization_status
)

# Load environment variables
load_dotenv()

# Configuration
VAULT_ADDRESS = "0x89a7F138951258087dbc0ADFf8fDD6b09B3584c3"
CHAIN_NAME = "Core"
TOKENS = ["USDT", "USDC"]

def check_status():
    """Check current yield status"""
    print(f"\n🔍 Checking yield status on {CHAIN_NAME}")
    print(f"📍 Vault: {VAULT_ADDRESS}")
    print(f"💰 Tokens: {', '.join(TOKENS)}")
    print("-" * 50)
    
    result = check_yield_optimization_status(CHAIN_NAME, VAULT_ADDRESS, TOKENS)
    data = json.loads(result)
    
    if data["status"] == "success":
        positions = data["data"]["current_positions"]
        recommendation = data["data"]["recommendation"]
        
        print("\n📊 Current Positions:")
        for token, info in positions.items():
            print(f"  {token}:")
            print(f"    Balance: {info['balance']}")
            print(f"    APY: {info['yield_apy']}")
        
        print(f"\n💡 Recommendation:")
        print(f"  Current position: {recommendation['current_best']}")
        print(f"  Best yield token: {recommendation['optimal_token']}")
        print(f"  Should switch: {'✅ Yes' if recommendation['should_switch'] else '❌ No'}")
        print(f"  Yield difference: {recommendation['yield_difference']}")
        print(f"  Reason: {recommendation['reason']}")
        
        return recommendation['should_switch']
    else:
        print(f"❌ Error: {data['message']}")
        return False

def execute_optimization():
    """Execute yield optimization"""
    print(f"\n🚀 Executing yield optimization on {CHAIN_NAME}")
    print(f"📍 Vault: {VAULT_ADDRESS}")
    print("-" * 50)
    
    result = optimize_yield(CHAIN_NAME, VAULT_ADDRESS, TOKENS)
    data = json.loads(result)
    
    if data["status"] == "success":
        print(f"✅ {data['message']}")
        
        if "details" in data:
            details = data["details"]
            print("\n📋 Transaction Details:")
            
            if "action" in details and details["action"] == "No switch needed":
                print(f"  Status: {details['action']}")
                print(f"  Current token: {details.get('current_token', 'N/A')}")
                print(f"  Current yield: {details.get('current_yield', 'N/A')}")
            else:
                print(f"  From: {details.get('from_token', 'N/A')}")
                print(f"  To: {details.get('to_token', 'N/A')}")
                print(f"  Yield improvement: {details.get('yield_improvement', 'N/A')}")
                print(f"  New yield: {details.get('new_yield', 'N/A')}")
                
                if "transactions" in details:
                    print("\n📝 Transactions:")
                    for tx in details["transactions"]:
                        print(f"  - {tx}")
    else:
        print(f"❌ Error: {data['message']}")

def main():
    """Main function"""
    print("\n" + "="*60)
    print("🏆 YIELD OPTIMIZER - CORE CHAIN (USDT/USDC)")
    print("="*60)
    
    # Check if private key is set
    if not os.getenv("PRIVATE_KEY"):
        print("\n⚠️  WARNING: PRIVATE_KEY not set in environment")
        print("   You can check status but cannot execute optimization")
        print("   Set it in .env file: PRIVATE_KEY=your_key")
    
    # Always check status first
    should_switch = check_status()
    
    # Check if user wants to execute
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        if not os.getenv("PRIVATE_KEY"):
            print("\n❌ Cannot execute optimization without PRIVATE_KEY")
            return
            
        if should_switch:
            print("\n" + "="*60)
            response = input("⚠️  Do you want to execute the optimization? (yes/no): ")
            if response.lower() == "yes":
                execute_optimization()
            else:
                print("❌ Optimization cancelled")
        else:
            print("\n✅ No optimization needed - already in optimal position")
    else:
        print("\n💡 To execute optimization, run:")
        print("   python test_yield_optimizer_core.py run")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()