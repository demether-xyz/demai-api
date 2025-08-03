"""
Test executing a specific task by ID.
"""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.services.task_manager import TaskManager
from src.services.task_executor import TaskExecutor
from src.utils.mongo_connection import mongo_connection


async def main():
    """Test executing a specific task."""
    # TODO: Replace with your actual task ID
    TASK_ID = "688f0a2fe9fd614af2ed5565"  # e.g., "6745abc123def456789"
    
    print(f"🚀 Testing task execution for ID: {TASK_ID}")
    
    try:
        # Connect to MongoDB
        db = await mongo_connection.connect()
        
        # Initialize task manager and executor
        task_manager = TaskManager(db)
        task_executor = TaskExecutor(task_manager)
        
        # Execute the task
        print(f"\n📋 Executing task {TASK_ID}...")
        result = await task_executor.execute_task_by_id(TASK_ID)
        
        # Print results
        print(f"\n📊 Execution Result:")
        print(f"Status: {result.get('status')}")
        
        if result.get('memo'):
            print(f"\n📱 SMS Memo: {result.get('memo')}")
        
        if result.get('execution_result'):
            exec_result = result['execution_result']
            
            if exec_result.get('actions_taken'):
                print(f"\n🔧 Actions Taken:")
                for action in exec_result.get('actions_taken', []):
                    print(f"  - {action}")
            
            if exec_result.get('transactions'):
                print(f"\n💰 Transactions:")
                for tx in exec_result.get('transactions', []):
                    print(f"  - {tx}")
            
            if exec_result.get('result'):
                print(f"\n✅ Result: {exec_result.get('result')}")
        
        if result.get('error'):
            print(f"\n❌ Error: {result.get('error')}")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Disconnect from MongoDB
        await mongo_connection.disconnect()


if __name__ == "__main__":
    asyncio.run(main())