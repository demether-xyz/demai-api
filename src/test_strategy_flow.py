#!/usr/bin/env python3
"""
Test script to manually trigger and test strategy execution flow.

This script helps verify that the entire strategy execution pipeline works:
1. Create a strategy task
2. Execute the task manually 
3. Check results and cleanup

Usage:
    python test_strategy_flow.py --strategy katana_ausd_morpho_optimizer --percentage 25 --vault 0x... --user 0x...
"""
import asyncio
import sys
import os
import argparse
from datetime import datetime, timezone
from typing import Dict, Any

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from utils.mongo_connection import mongo_connection
from services.task_manager import TaskManager
from services.task_executor import TaskExecutor
from services.strategies import get_all_strategies, get_strategy, format_strategy_task
from services.strategy_execution import execute_defi_strategy
from config import logger

class StrategyFlowTester:
    """Test the complete strategy execution flow."""
    
    def __init__(self):
        self.db = None
        self.task_manager = None
        
    async def init(self):
        """Initialize database connection."""
        self.db = await mongo_connection.connect()
        self.task_manager = TaskManager(self.db)
        await self.task_manager.create_indexes()
    
    async def list_strategies(self):
        """List all available strategies."""
        print("=== Available Strategies ===")
        strategies = get_all_strategies()
        
        for strategy in strategies:
            print(f"\n📋 {strategy['name']}")
            print(f"   ID: {strategy['id']}")
            print(f"   Chain: {strategy['chain']}")
            print(f"   Tokens: {', '.join(strategy['tokens'])}")
            print(f"   Frequency: {strategy['frequency']}")
            print(f"   Description: {strategy['description']}")
            
            if 'vaults' in strategy:
                print(f"   Vaults:")
                for vault in strategy['vaults']:
                    print(f"     - {vault['name']}: {vault['address']}")
        
        return strategies
    
    async def create_test_task(self, strategy_id: str, vault_address: str, user_address: str, percentage: int = 25) -> str:
        """Create a test strategy task."""
        print(f"\n=== Creating Test Task ===")
        
        try:
            # Get strategy to determine chain
            strategy = get_strategy(strategy_id)
            chain = strategy['chain']
            
            print(f"Creating task for strategy: {strategy['name']}")
            print(f"Chain: {chain}")
            print(f"User: {user_address}")
            print(f"Vault: {vault_address}")
            print(f"Percentage: {percentage}%")
            
            task = await self.task_manager.create_task(
                user_address=user_address,
                vault_address=vault_address,
                strategy_id=strategy_id,
                percentage=percentage,
                chain=chain,
                enabled=True
            )
            
            task_id = task['_id']
            print(f"✅ Task created with ID: {task_id}")
            print(f"   Next run time: {task['next_run_time']}")
            
            return task_id
            
        except Exception as e:
            print(f"❌ Error creating task: {e}")
            raise
    
    async def execute_task_directly(self, strategy_id: str, vault_address: str, percentage: int = 25):
        """Execute strategy directly without creating a task."""
        print(f"\n=== Direct Strategy Execution ===")
        
        try:
            # Format the strategy task
            formatted_task = format_strategy_task(strategy_id, {"percentage": percentage})
            print(f"📋 Formatted Task: {formatted_task}")
            
            print(f"🚀 Executing strategy for vault {vault_address}...")
            
            # Execute the strategy directly
            result = await execute_defi_strategy(
                task=formatted_task,
                vault_address=vault_address,
                model="openai/gpt-oss-120b"
            )
            
            print(f"\n📊 Execution Result:")
            print(f"   Status: {result.get('status', 'unknown')}")
            print(f"   Task: {result.get('task', 'N/A')}")
            
            if result.get('actions_taken'):
                print(f"   Actions Taken:")
                for i, action in enumerate(result['actions_taken'], 1):
                    print(f"     {i}. {action}")
            
            if result.get('transactions'):
                print(f"   Transactions:")
                for i, tx in enumerate(result['transactions'], 1):
                    print(f"     {i}. {tx}")
            
            if result.get('memo'):
                print(f"   Memo: {result['memo']}")
            
            if result.get('error'):
                print(f"   Error: {result['error']}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error executing strategy: {e}")
            raise
    
    async def execute_task_by_id(self, task_id: str):
        """Execute a specific task by ID using TaskExecutor."""
        print(f"\n=== Executing Task by ID ===")
        print(f"Task ID: {task_id}")
        
        try:
            task_executor = TaskExecutor(self.task_manager)
            result = await task_executor.execute_task_by_id(task_id)
            
            print(f"\n📊 Task Execution Result:")
            print(f"   Status: {result.get('status', 'unknown')}")
            print(f"   User: {result.get('user_address', 'N/A')}")
            print(f"   Vault: {result.get('vault_address', 'N/A')}")
            print(f"   Strategy: {result.get('strategy_id', 'N/A')}")
            
            if result.get('memo'):
                print(f"   Memo: {result['memo']}")
            
            if result.get('execution_result'):
                exec_result = result['execution_result']
                if exec_result.get('actions_taken'):
                    print(f"   Actions:")
                    for i, action in enumerate(exec_result['actions_taken'], 1):
                        print(f"     {i}. {action}")
                
                if exec_result.get('transactions'):
                    print(f"   Transactions:")
                    for i, tx in enumerate(exec_result['transactions'], 1):
                        print(f"     {i}. {tx}")
            
            if result.get('error'):
                print(f"   Error: {result['error']}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error executing task: {e}")
            raise
    
    async def cleanup_test_tasks(self, user_address: str):
        """Clean up test tasks for a user."""
        print(f"\n=== Cleaning Up Test Tasks ===")
        
        try:
            tasks = await self.task_manager.get_user_tasks(user_address)
            
            if not tasks:
                print("No tasks found to clean up")
                return
            
            print(f"Found {len(tasks)} tasks to clean up")
            
            for task in tasks:
                task_id = task['_id']
                strategy_id = task['strategy_id']
                
                success = await self.task_manager.delete_task(task_id, user_address)
                if success:
                    print(f"✅ Deleted task {task_id} (strategy: {strategy_id})")
                else:
                    print(f"❌ Failed to delete task {task_id}")
                    
        except Exception as e:
            print(f"❌ Error cleaning up tasks: {e}")
    
    async def get_next_due_task(self):
        """Check what's the next due task."""
        print(f"\n=== Checking Next Due Task ===")
        
        task = await self.task_manager.get_next_due_task()
        
        if not task:
            print("No tasks are currently due for execution")
            return None
        
        print(f"📋 Next Due Task:")
        print(f"   Task ID: {task['_id']}")
        print(f"   User: {task['user_address']}")
        print(f"   Strategy: {task['strategy_id']}")
        print(f"   Percentage: {task['percentage']}%")
        print(f"   Next Run Time: {task['next_run_time']}")
        print(f"   Enabled: {task['enabled']}")
        
        return task


async def main():
    """Main test function."""
    parser = argparse.ArgumentParser(description='Test Strategy Execution Flow')
    parser.add_argument('--strategy', default='katana_ausd_morpho_optimizer', help='Strategy ID to test')
    parser.add_argument('--vault', help='Vault address')
    parser.add_argument('--user', help='User wallet address') 
    parser.add_argument('--percentage', type=int, default=25, help='Percentage to allocate (1-100)')
    parser.add_argument('--direct-only', action='store_true', help='Only test direct execution, skip task creation')
    parser.add_argument('--cleanup', action='store_true', help='Clean up test tasks and exit')
    parser.add_argument('--list-strategies', action='store_true', help='List available strategies and exit')
    parser.add_argument('--check-due', action='store_true', help='Check next due task and exit')
    
    args = parser.parse_args()
    
    # Initialize tester
    tester = StrategyFlowTester()
    await tester.init()
    
    try:
        # Handle specific actions
        if args.list_strategies:
            await tester.list_strategies()
            return
        
        if args.cleanup:
            await tester.cleanup_test_tasks(args.user)
            return
        
        if args.check_due:
            await tester.get_next_due_task()
            return
        
        # Check required arguments for execution tests
        if not args.vault or not args.user:
            print("❌ --vault and --user are required for execution tests")
            print("Use --list-strategies to see available strategies")
            return
        
        # Validate strategy exists
        try:
            strategy = get_strategy(args.strategy)
            print(f"✅ Testing strategy: {strategy['name']}")
        except ValueError as e:
            print(f"❌ Invalid strategy: {e}")
            print("\nAvailable strategies:")
            await tester.list_strategies()
            return
        
        # Test direct execution
        print(f"\n🔥 TESTING: Direct Strategy Execution")
        direct_result = await tester.execute_task_directly(
            strategy_id=args.strategy,
            vault_address=args.vault,
            percentage=args.percentage
        )
        
        if args.direct_only:
            print("\n✅ Direct execution test completed")
            return
        
        # Test full task workflow
        print(f"\n🔥 TESTING: Full Task Workflow")
        
        # Clean up any existing tasks first
        await tester.cleanup_test_tasks(args.user)
        
        # Create task
        task_id = await tester.create_test_task(
            strategy_id=args.strategy,
            vault_address=args.vault,
            user_address=args.user,
            percentage=args.percentage
        )
        
        # Execute task
        task_result = await tester.execute_task_by_id(task_id)
        
        # Clean up
        await tester.cleanup_test_tasks(args.user)
        
        print(f"\n✅ Full workflow test completed!")
        print(f"   Direct execution: {'✅ Success' if direct_result.get('status') == 'success' else '❌ Failed'}")
        print(f"   Task execution: {'✅ Success' if task_result.get('status') == 'success' else '❌ Failed'}")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await mongo_connection.disconnect()


if __name__ == "__main__":
    asyncio.run(main())