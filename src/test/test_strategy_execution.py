"""
Test the strategy execution service.
"""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.services.strategy_execution import execute_defi_strategy


async def main():
    """Test the strategy execution service."""
    # Test vault address (same as simple assistant test)
    vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
    
    # Single test task
    task = "Move 50% of USDC to the best yield opportunity"
    
    print("Executing strategy...")
    print(f"Task: {task}")
    
    # Execute the strategy
    result = await execute_defi_strategy(
        task=task,
        vault_address=vault_address,
        model="google/gemini-2.5-flash"
    )
    
    # Print results
    print(f"\n📊 Execution Result:")
    print(f"Status: {result.get('status')}")
    
    if result.get('actions_taken'):
        print(f"\n🔧 Actions Taken:")
        for action in result.get('actions_taken', []):
            print(f"  - {action}")
    
    if result.get('transactions'):
        print(f"\n💰 Transactions:")
        for tx in result.get('transactions', []):
            print(f"  - {tx}")
    
    if result.get('result'):
        print(f"\n✅ Result: {result.get('result')}")
    
    if result.get('error'):
        print(f"\n❌ Error: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())