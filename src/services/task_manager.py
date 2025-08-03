"""
Task manager for handling user strategy subscriptions.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
import logging
from .strategies import get_strategy, get_all_strategies, format_strategy_task

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages user strategy subscriptions and tasks."""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        """Initialize task manager with database connection.
        
        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.tasks_collection = db.strategy_tasks
        
    def calculate_next_run_time(self, frequency: str, last_executed: Optional[datetime] = None) -> datetime:
        """Calculate the next run time based on frequency.
        
        Args:
            frequency: Task frequency ('daily', 'hourly', etc.)
            last_executed: Last execution time (use current time if None)
            
        Returns:
            Next scheduled run time
        """
        base_time = last_executed or datetime.now(timezone.utc)
        
        frequency_map = {
            "daily": timedelta(days=1),
            "hourly": timedelta(hours=1),
            "weekly": timedelta(weeks=1),
            "monthly": timedelta(days=30),  # Approximate
        }
        
        delta = frequency_map.get(frequency.lower(), timedelta(days=1))
        return base_time + delta
        
    async def create_indexes(self):
        """Create necessary database indexes."""
        await self.tasks_collection.create_index("user_address")
        await self.tasks_collection.create_index([("user_address", 1), ("strategy_id", 1)])
        await self.tasks_collection.create_index("status")
        await self.tasks_collection.create_index("next_run_time")
        
    async def create_task(
        self,
        user_address: str,
        vault_address: str,
        strategy_id: str,
        percentage: int,
        chain: str,
        enabled: bool = True
    ) -> Dict[str, Any]:
        """Create a new strategy task for a user.
        
        Args:
            user_address: User's wallet address
            vault_address: User's vault address
            strategy_id: Strategy ID from strategies.py
            percentage: Percentage of funds to allocate (1-100)
            chain: Chain name (must match strategy chain)
            enabled: Whether the strategy is enabled
            
        Returns:
            Created task document
            
        Raises:
            ValueError: If validation fails
        """
        # Validate strategy exists
        try:
            strategy = get_strategy(strategy_id)
        except ValueError as e:
            raise ValueError(f"Invalid strategy: {str(e)}")
            
        # Validate chain matches
        if strategy["chain"].lower() != chain.lower():
            raise ValueError(f"Strategy '{strategy_id}' is for {strategy['chain']} chain, not {chain}")
            
        # Validate percentage
        if not 1 <= percentage <= 100:
            raise ValueError("Percentage must be between 1 and 100")
            
        # Check if user already has this strategy
        existing = await self.tasks_collection.find_one({
            "user_address": user_address.lower(),
            "strategy_id": strategy_id
        })
        
        if existing:
            raise ValueError(f"User already has strategy '{strategy_id}' active")
            
        # Check total percentage for this chain doesn't exceed 100
        chain_tasks = await self.tasks_collection.find({
            "user_address": user_address.lower(),
            "chain": chain.lower()
        }).to_list(None)
        
        total_percentage = sum(task.get("percentage", 0) for task in chain_tasks)
        if total_percentage + percentage > 100:
            raise ValueError(f"Total percentage for {chain} chain would exceed 100% (current: {total_percentage}%, adding: {percentage}%)")
            
        # Create task document
        current_time = datetime.now(timezone.utc)
        task = {
            "user_address": user_address.lower(),
            "vault_address": vault_address.lower(),
            "strategy_id": strategy_id,
            "chain": chain.lower(),
            "percentage": percentage,
            "enabled": enabled,
            "created_at": current_time,
            "updated_at": current_time,
            "last_executed": None,
            "next_run_time": self.calculate_next_run_time(strategy["frequency"]),
            "execution_count": 0,
            "last_execution_memo": None,
            "last_execution_status": None
        }
        
        # Insert into database
        result = await self.tasks_collection.insert_one(task)
        task["_id"] = str(result.inserted_id)
        
        logger.info(f"Created task {task['_id']} for user {user_address} with strategy {strategy_id}")
        
        return task
        
    async def get_user_tasks(self, user_address: str) -> List[Dict[str, Any]]:
        """Get all tasks for a user.
        
        Args:
            user_address: User's wallet address
            
        Returns:
            List of user's tasks
        """
        tasks = await self.tasks_collection.find({
            "user_address": user_address.lower()
        }).to_list(None)
        
        # Convert ObjectId to string and add strategy details
        for task in tasks:
            task["_id"] = str(task["_id"])
            try:
                strategy = get_strategy(task["strategy_id"])
                task["strategy"] = strategy
            except ValueError:
                task["strategy"] = None
                
        return tasks
        
    async def update_task(
        self,
        task_id: str,
        user_address: str,
        percentage: Optional[int] = None,
        enabled: Optional[bool] = None
    ) -> bool:
        """Update a task's settings.
        
        Args:
            task_id: Task ID
            user_address: User's wallet address (for authorization)
            percentage: New percentage allocation
            enabled: New enabled status
            
        Returns:
            True if updated successfully
        """
        # Find the task
        task = await self.tasks_collection.find_one({
            "_id": ObjectId(task_id),
            "user_address": user_address.lower()
        })
        
        if not task:
            return False
            
        # Build update document
        update_doc = {"updated_at": datetime.now(timezone.utc)}
        
        if percentage is not None:
            # Validate percentage
            if not 1 <= percentage <= 100:
                raise ValueError("Percentage must be between 1 and 100")
                
            # Check total percentage for chain
            chain_tasks = await self.tasks_collection.find({
                "user_address": user_address.lower(),
                "chain": task["chain"],
                "_id": {"$ne": ObjectId(task_id)}
            }).to_list(None)
            
            total_percentage = sum(t.get("percentage", 0) for t in chain_tasks)
            if total_percentage + percentage > 100:
                raise ValueError(f"Total percentage for {task['chain']} chain would exceed 100%")
                
            update_doc["percentage"] = percentage
            
        if enabled is not None:
            update_doc["enabled"] = enabled
            
        # Update task
        result = await self.tasks_collection.update_one(
            {"_id": ObjectId(task_id), "user_address": user_address.lower()},
            {"$set": update_doc}
        )
        
        return result.modified_count > 0
        
    async def delete_task(self, task_id: str, user_address: str) -> bool:
        """Delete a task.
        
        Args:
            task_id: Task ID
            user_address: User's wallet address (for authorization)
            
        Returns:
            True if deleted successfully
        """
        result = await self.tasks_collection.delete_one({
            "_id": ObjectId(task_id),
            "user_address": user_address.lower()
        })
        
        return result.deleted_count > 0
        
    async def get_enabled_tasks(self) -> List[Dict[str, Any]]:
        """Get all enabled tasks for execution.
        
        Returns:
            List of enabled tasks
        """
        tasks = await self.tasks_collection.find({
            "enabled": True
        }).to_list(None)
        
        # Convert ObjectId to string and add strategy details
        for task in tasks:
            task["_id"] = str(task["_id"])
            try:
                strategy = get_strategy(task["strategy_id"])
                task["strategy"] = strategy
            except ValueError:
                task["strategy"] = None
                
        return tasks
        
    async def get_next_due_task(self) -> Optional[Dict[str, Any]]:
        """Get the next task that is due for execution.
        
        Returns:
            The next due task, or None if no tasks are due
        """
        current_time = datetime.now(timezone.utc)
        
        # Find enabled tasks that are due (next_run_time <= current_time)
        task = await self.tasks_collection.find_one(
            {
                "enabled": True,
                "next_run_time": {"$lte": current_time}
            },
            sort=[("next_run_time", 1)]  # Get the oldest due task
        )
        
        if task:
            task["_id"] = str(task["_id"])
            try:
                strategy = get_strategy(task["strategy_id"])
                task["strategy"] = strategy
            except ValueError:
                task["strategy"] = None
                
        return task
    
    async def mark_task_executed(self, task_id: str, execution_memo: Optional[str] = None, execution_status: str = "success") -> bool:
        """Mark a task as executed and update next run time.
        
        Args:
            task_id: Task ID
            execution_memo: Brief summary of execution results (for SMS notifications)
            execution_status: Status of execution ("success" or "failed")
            
        Returns:
            True if updated successfully
        """
        # Get the task to retrieve strategy frequency
        task = await self.tasks_collection.find_one({"_id": ObjectId(task_id)})
        if not task:
            return False
            
        strategy = get_strategy(task["strategy_id"])
        current_time = datetime.now(timezone.utc)
        next_run_time = self.calculate_next_run_time(strategy["frequency"], current_time)
        
        # Build update document
        update_doc = {
            "$set": {
                "last_executed": current_time,
                "next_run_time": next_run_time,
                "last_execution_status": execution_status
            },
            "$inc": {"execution_count": 1}
        }
        
        # Add memo if provided
        if execution_memo:
            update_doc["$set"]["last_execution_memo"] = execution_memo[:160]  # Ensure SMS-friendly length
        
        result = await self.tasks_collection.update_one(
            {"_id": ObjectId(task_id)},
            update_doc
        )
        
        return result.modified_count > 0