"""
Task executor service for running scheduled strategy tasks.
"""
from typing import Dict, Any, Optional
from src.services.task_manager import TaskManager
from src.services.strategies import format_strategy_task
from src.services.strategy_execution import execute_defi_strategy
from src.config import logger
from src.utils.telegram_helper import TelegramHelper
from src.models.telegram_binding import TelegramBinding


class TaskExecutor:
    """Executes scheduled strategy tasks."""
    
    def __init__(self, task_manager: TaskManager, telegram_helper: Optional[TelegramHelper] = None, telegram_binding: Optional[TelegramBinding] = None):
        """Initialize with task manager instance."""
        self.task_manager = task_manager
        self.telegram_helper = telegram_helper
        self.telegram_binding = telegram_binding
    
    async def _send_telegram_notification(self, user_address: str, strategy_id: str, status: str, memo: str):
        """Send Telegram notification if user has a binding."""
        if not self.telegram_helper or not self.telegram_binding:
            return
        
        try:
            # Get all telegram bindings for this wallet
            bindings = await self.telegram_binding.get_bindings_by_wallet(user_address)
            
            if not bindings:
                logger.info(f"No Telegram binding found for {user_address}")
                return
            
            # Prepare the notification message
            status_emoji = "✅" if status == "success" else "❌"
            message = f"{status_emoji} **Strategy Execution {status.capitalize()}**\n\n"
            message += f"**Strategy:** {strategy_id}\n"
            message += f"**Status:** {status}\n"
            message += f"**Details:** {memo}\n"
            
            # Send notification to all bound chat IDs
            for binding in bindings:
                try:
                    await self.telegram_helper.send_message(
                        chat_id=int(binding["chat_id"]),
                        text=message
                    )
                    logger.info(f"Telegram notification sent to chat_id {binding['chat_id']} for {user_address}")
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification to {binding['chat_id']}: {e}")
                    
        except Exception as e:
            logger.error(f"Error sending Telegram notifications for {user_address}: {e}")
    
    async def execute_next_task(self) -> Dict[str, Any]:
        """Execute the next due task.
        
        Returns:
            Execution result with status, memo, and details
        """
        # Get the next due task
        task = await self.task_manager.get_next_due_task()
        
        if not task:
            return {"message": "No tasks due for execution"}
        
        if not task.get("strategy"):
            return {"error": f"Strategy not found for task {task['_id']}"}
        
        # Format the strategy task with user parameters
        formatted_task = format_strategy_task(
            task["strategy_id"],
            {"percentage": task["percentage"]}
        )
        
        # Execute the task using the strategy executor
        try:
            # Use strategy execution service for structured response
            result = await execute_defi_strategy(
                task=formatted_task,
                vault_address=task["vault_address"],
                model="google/gemini-2.5-pro"  # Fast model for scheduled tasks
            )
            
            # Extract memo and status from result
            execution_memo = result.get("memo", "Task completed")
            execution_status = "success" if result.get("status") == "success" else "failed"
            
            # Mark task as executed with memo
            await self.task_manager.mark_task_executed(
                task_id=task["_id"],
                execution_memo=execution_memo,
                execution_status=execution_status
            )
            
            # Send Telegram notification
            await self._send_telegram_notification(
                user_address=task["user_address"],
                strategy_id=task["strategy_id"],
                status=execution_status,
                memo=execution_memo
            )
            
            return {
                "task_id": task["_id"],
                "user_address": task["user_address"],
                "vault_address": task["vault_address"],
                "strategy_id": task["strategy_id"],
                "execution_result": result,
                "memo": execution_memo,
                "status": execution_status
            }
            
        except Exception as e:
            logger.error(f"Error executing task {task['_id']}: {e}")
            
            # Mark as failed
            await self.task_manager.mark_task_executed(
                task_id=task["_id"],
                execution_memo=f"Failed: {str(e)[:100]}",
                execution_status="failed"
            )
            
            # Send Telegram notification for failure
            await self._send_telegram_notification(
                user_address=task["user_address"],
                strategy_id=task["strategy_id"],
                status="failed",
                memo=f"Failed: {str(e)[:100]}"
            )
            
            return {
                "task_id": task["_id"],
                "error": str(e),
                "status": "failed"
            }
    
    async def execute_task_by_id(self, task_id: str) -> Dict[str, Any]:
        """Execute a specific task by ID.
        
        Args:
            task_id: The task ID to execute
            
        Returns:
            Execution result with status, memo, and details
        """
        # Get the task directly
        from bson import ObjectId
        task = await self.task_manager.tasks_collection.find_one({"_id": ObjectId(task_id)})
        
        if not task:
            return {"error": f"Task {task_id} not found"}
        
        # Convert ObjectId to string
        task["_id"] = str(task["_id"])
        
        # Get strategy details
        from src.services.strategies import get_strategy
        try:
            strategy = get_strategy(task["strategy_id"])
            task["strategy"] = strategy
        except ValueError:
            return {"error": f"Strategy {task['strategy_id']} not found for task {task_id}"}
        
        # Format the strategy task with user parameters
        formatted_task = format_strategy_task(
            task["strategy_id"],
            {"percentage": task["percentage"]}
        )
        
        # Execute the task using the strategy executor
        try:
            # Use strategy execution service for structured response
            result = await execute_defi_strategy(
                task=formatted_task,
                vault_address=task["vault_address"],
                model="google/gemini-2.5-pro"  # Fast model for scheduled tasks
            )
            
            # Extract memo and status from result
            execution_memo = result.get("memo", "Task completed")
            execution_status = "success" if result.get("status") == "success" else "failed"
            
            # Mark task as executed with memo
            await self.task_manager.mark_task_executed(
                task_id=task["_id"],
                execution_memo=execution_memo,
                execution_status=execution_status
            )
            
            # Send Telegram notification
            await self._send_telegram_notification(
                user_address=task["user_address"],
                strategy_id=task["strategy_id"],
                status=execution_status,
                memo=execution_memo
            )
            
            return {
                "task_id": task["_id"],
                "user_address": task["user_address"],
                "vault_address": task["vault_address"],
                "strategy_id": task["strategy_id"],
                "execution_result": result,
                "memo": execution_memo,
                "status": execution_status
            }
            
        except Exception as e:
            logger.error(f"Error executing task {task['_id']}: {e}")
            
            # Mark as failed
            await self.task_manager.mark_task_executed(
                task_id=task["_id"],
                execution_memo=f"Failed: {str(e)[:100]}",
                execution_status="failed"
            )
            
            # Send Telegram notification for failure
            await self._send_telegram_notification(
                user_address=task["user_address"],
                strategy_id=task["strategy_id"],
                status="failed",
                memo=f"Failed: {str(e)[:100]}"
            )
            
            return {
                "task_id": task["_id"],
                "error": str(e),
                "status": "failed"
            }