import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

from .base_strategy import BaseStrategy, TaskStatus, StrategyResult

logger = logging.getLogger(__name__)


class StrategyTask:
    """Represents a scheduled strategy task for a user"""
    def __init__(self, task_data: Dict[str, Any]):
        self._id = task_data.get("_id")
        self.user_address = task_data["user_address"].lower()
        self.vault_address = task_data["vault_address"].lower()
        self.strategy_id = task_data["strategy_id"]
        self.amount = task_data["amount"]
        self.params = task_data.get("params", {})
        self.chain_id = task_data["chain_id"]
        self.interval_hours = task_data.get("interval_hours", 24)
        self.status = TaskStatus(task_data.get("status", TaskStatus.ACTIVE.value))
        self.next_run = task_data.get("next_run", datetime.utcnow())
        self.last_run = task_data.get("last_run")
        self.last_result = task_data.get("last_result")
        self.created_at = task_data.get("created_at", datetime.utcnow())
        self.updated_at = task_data.get("updated_at", datetime.utcnow())
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            "user_address": self.user_address,
            "vault_address": self.vault_address,
            "strategy_id": self.strategy_id,
            "amount": self.amount,
            "params": self.params,
            "chain_id": self.chain_id,
            "interval_hours": self.interval_hours,
            "status": self.status.value,
            "next_run": self.next_run,
            "last_run": self.last_run,
            "last_result": self.last_result,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        if self._id:
            data["_id"] = self._id
        return data


class TaskManager:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db.strategy_tasks
        self.strategies: Dict[str, BaseStrategy] = {}
    
    def register_strategy(self, strategy: BaseStrategy):
        """Register a strategy that can be executed"""
        self.strategies[strategy.strategy_id] = strategy
        logger.info(f"Registered strategy: {strategy.strategy_id}")
    
    async def create_task(self, user_address: str, vault_address: str, 
                         strategy_id: str, amount: str, chain_id: int,
                         params: Dict[str, Any] = None, 
                         interval_hours: int = None) -> Dict[str, Any]:
        """Create a new strategy task for a user"""
        
        if strategy_id not in self.strategies:
            raise ValueError(f"Unknown strategy: {strategy_id}")
        
        strategy = self.strategies[strategy_id]
        
        # Validate parameters
        is_valid, error = strategy.validate_params(params or {})
        if not is_valid:
            raise ValueError(f"Invalid parameters: {error}")
        
        # Use strategy default interval if not specified
        if interval_hours is None:
            interval_hours = strategy.get_default_interval_hours()
        
        task = StrategyTask({
            "user_address": user_address.lower(),
            "vault_address": vault_address.lower(),
            "strategy_id": strategy_id,
            "amount": amount,
            "params": params or {},
            "chain_id": chain_id,
            "interval_hours": interval_hours,
            "status": TaskStatus.ACTIVE.value,
            "next_run": datetime.utcnow(),  # Run immediately on creation
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        
        result = await self.collection.insert_one(task.to_dict())
        task._id = result.inserted_id
        
        logger.info(f"Created task {task._id} for user {user_address} with strategy {strategy_id}")
        return {"task_id": str(task._id), "next_run": task.next_run.isoformat()}
    
    async def get_due_tasks(self, limit: int = 10) -> List[StrategyTask]:
        """Get tasks that are due to run"""
        now = datetime.utcnow()
        
        cursor = self.collection.find({
            "status": TaskStatus.ACTIVE.value,
            "next_run": {"$lte": now}
        }).sort("next_run", 1).limit(limit)
        
        tasks = []
        async for doc in cursor:
            tasks.append(StrategyTask(doc))
        
        return tasks
    
    async def execute_task(self, task: StrategyTask) -> StrategyResult:
        """Execute a single task"""
        if task.strategy_id not in self.strategies:
            logger.error(f"Strategy {task.strategy_id} not found")
            return StrategyResult(False, error="Strategy not found")
        
        strategy = self.strategies[task.strategy_id]
        
        try:
            # Prepare execution context
            task_data = {
                "user_address": task.user_address,
                "vault_address": task.vault_address,
                "amount": task.amount,
                "params": task.params,
                "chain_id": task.chain_id
            }
            
            # Execute strategy
            result = await strategy.execute(task_data)
            
            # Update task with result
            await self._update_task_after_execution(task, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing task {task._id}: {str(e)}")
            error_result = StrategyResult(False, error=str(e))
            await self._update_task_after_execution(task, error_result)
            return error_result
    
    async def _update_task_after_execution(self, task: StrategyTask, result: StrategyResult):
        """Update task after execution"""
        task.last_run = datetime.utcnow()
        task.last_result = result.to_dict()
        
        if result.success:
            # Schedule next run
            task.next_run = datetime.utcnow() + timedelta(hours=task.interval_hours)
        else:
            # On failure, retry in 1 hour
            task.next_run = datetime.utcnow() + timedelta(hours=1)
        
        task.updated_at = datetime.utcnow()
        
        await self.collection.update_one(
            {"_id": task._id},
            {"$set": {
                "last_run": task.last_run,
                "last_result": task.last_result,
                "next_run": task.next_run,
                "updated_at": task.updated_at
            }}
        )
    
    async def pause_task(self, task_id: str, user_address: str) -> bool:
        """Pause a task (only owner can pause)"""
        try:
            obj_id = ObjectId(task_id)
        except:
            return False
            
        result = await self.collection.update_one(
            {"_id": obj_id, "user_address": user_address.lower()},
            {"$set": {"status": TaskStatus.PAUSED.value, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def resume_task(self, task_id: str, user_address: str) -> bool:
        """Resume a paused task"""
        try:
            obj_id = ObjectId(task_id)
        except:
            return False
            
        result = await self.collection.update_one(
            {"_id": obj_id, "user_address": user_address.lower()},
            {"$set": {
                "status": TaskStatus.ACTIVE.value,
                "next_run": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }}
        )
        return result.modified_count > 0
    
    async def delete_task(self, task_id: str, user_address: str) -> bool:
        """Delete a task (only owner can delete)"""
        try:
            obj_id = ObjectId(task_id)
        except:
            return False
            
        result = await self.collection.delete_one(
            {"_id": obj_id, "user_address": user_address.lower()}
        )
        return result.deleted_count > 0
    
    async def get_user_tasks(self, user_address: str) -> List[Dict[str, Any]]:
        """Get all tasks for a user"""
        cursor = self.collection.find({"user_address": user_address.lower()})
        tasks = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            tasks.append(doc)
        return tasks
    
    async def run_due_tasks(self) -> Dict[str, Any]:
        """Run all due tasks (called by cron endpoint)"""
        due_tasks = await self.get_due_tasks()
        
        results = {
            "total_tasks": len(due_tasks),
            "successful": 0,
            "failed": 0,
            "results": []
        }
        
        for task in due_tasks:
            logger.info(f"Executing task {task._id} for user {task.user_address}")
            result = await self.execute_task(task)
            
            if result.success:
                results["successful"] += 1
            else:
                results["failed"] += 1
            
            results["results"].append({
                "task_id": str(task._id),
                "user": task.user_address,
                "strategy": task.strategy_id,
                "success": result.success,
                "error": result.error,
                "tx_hash": result.tx_hash
            })
        
        return results