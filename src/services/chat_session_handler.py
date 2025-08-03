"""
MongoDB handler for chat sessions with message history and memory management.
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
import motor.motor_asyncio
from config import logger

# Configuration constants
SESSION_TTL_HOURS = 24  # Sessions expire after 24 hours of inactivity
HISTORY_LIMIT = 100  # Maximum messages to retrieve


class ChatSessionHandler:
    """Handler for chat session data operations in MongoDB."""
    
    def __init__(self, db: motor.motor_asyncio.AsyncIOMotorDatabase):
        """Initialize with a MongoDB database instance."""
        self.db = db
        self.sessions = db.chat_sessions
        
    async def get_or_create_session(
        self,
        agent_id: str,
        user_id: str,
        agent_name: str = "assistant",
        account_id: Optional[str] = None,
        maintain_global_history: bool = True
    ) -> Dict[str, Any]:
        """Get existing session or create new one."""
        try:
            # Create session ID based on global history setting
            if maintain_global_history:
                session_id = f"global_{user_id}"
            else:
                session_id = f"{agent_id}_{user_id}"
            
            # Try to get existing session
            session = await self.sessions.find_one({"session_id": session_id})
            
            if session:
                # Update last accessed time
                await self.sessions.update_one(
                    {"_id": session["_id"]},
                    {
                        "$set": {
                            "last_accessed": datetime.now(timezone.utc),
                            "agent_name": agent_name  # Update agent name in case it changed
                        }
                    }
                )
                
                # Convert ObjectId to string for JSON serialization
                session["_id"] = str(session["_id"])
                logger.info(f"Retrieved existing session: {session_id}")
                return session
            else:
                # Create new session
                new_session = {
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "agent_name": agent_name,
                    "account_id": account_id,
                    "messages": [],
                    "memory_data": {},
                    "created_at": datetime.now(timezone.utc),
                    "last_accessed": datetime.now(timezone.utc),
                    "maintain_global_history": maintain_global_history
                }
                
                result = await self.sessions.insert_one(new_session)
                new_session["_id"] = str(result.inserted_id)
                logger.info(f"Created new session: {session_id}")
                return new_session
                
        except Exception as e:
            logger.error(f"Error getting/creating session: {e}")
            raise
    
    async def add_messages(
        self,
        agent_id: str,
        user_id: str,
        account_id: Optional[str],
        maintain_global_history: bool,
        messages: List[Dict[str, str]]
    ) -> None:
        """Add messages to session history."""
        try:
            # Determine session ID
            if maintain_global_history:
                session_id = f"global_{user_id}"
            else:
                session_id = f"{agent_id}_{user_id}"
            
            # Prepare message documents with timestamps
            message_docs = []
            for msg in messages:
                message_docs.append({
                    "role": msg["role"],
                    "content": msg["content"],
                    "timestamp": datetime.now(timezone.utc),
                    "agent_id": agent_id
                })
            
            # Update session with new messages
            await self.sessions.update_one(
                {"session_id": session_id},
                {
                    "$push": {
                        "messages": {
                            "$each": message_docs,
                            "$slice": -HISTORY_LIMIT  # Keep only last N messages
                        }
                    },
                    "$set": {
                        "last_accessed": datetime.now(timezone.utc)
                    }
                }
            )
            
            logger.info(f"Added {len(messages)} messages to session {session_id}")
            
        except Exception as e:
            logger.error(f"Error adding messages to session: {e}")
            raise
    
    async def update_memory_data(
        self,
        agent_id: str,
        user_id: str,
        memory_updates: Dict[str, Any],
        account_id: Optional[str] = None,
        maintain_global_history: bool = True
    ) -> None:
        """Update session memory data."""
        try:
            # Determine session ID
            if maintain_global_history:
                session_id = f"global_{user_id}"
            else:
                session_id = f"{agent_id}_{user_id}"
            
            # Build update operations for each memory field
            update_ops = {}
            for key, value in memory_updates.items():
                update_ops[f"memory_data.{key}"] = value
            
            # Add last accessed timestamp
            update_ops["last_accessed"] = datetime.now(timezone.utc)
            
            # Update session
            await self.sessions.update_one(
                {"session_id": session_id},
                {"$set": update_ops}
            )
            
            logger.info(f"Updated memory data for session {session_id}: {list(memory_updates.keys())}")
            
        except Exception as e:
            logger.error(f"Error updating memory data: {e}")
            raise
    
    async def get_recent_messages(
        self,
        agent_id: str,
        user_id: str,
        limit: int = 20,
        maintain_global_history: bool = True
    ) -> List[Dict[str, Any]]:
        """Get recent messages from session."""
        try:
            # Determine session ID
            if maintain_global_history:
                session_id = f"global_{user_id}"
            else:
                session_id = f"{agent_id}_{user_id}"
            
            session = await self.sessions.find_one({"session_id": session_id})
            
            if session and "messages" in session:
                # Return last N messages
                messages = session["messages"]
                return messages[-limit:] if len(messages) > limit else messages
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting recent messages: {e}")
            raise
    
    async def clear_session(
        self,
        agent_id: str,
        user_id: str,
        maintain_global_history: bool = True
    ) -> bool:
        """Clear a session's messages and memory."""
        try:
            # Determine session ID
            if maintain_global_history:
                session_id = f"global_{user_id}"
            else:
                session_id = f"{agent_id}_{user_id}"
            
            result = await self.sessions.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "messages": [],
                        "memory_data": {},
                        "last_accessed": datetime.now(timezone.utc)
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Cleared session: {session_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error clearing session: {e}")
            raise
    
    async def cleanup_expired_sessions(self, ttl_hours: int = SESSION_TTL_HOURS) -> int:
        """Remove sessions that haven't been accessed recently."""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
            
            result = await self.sessions.delete_many({
                "last_accessed": {"$lt": cutoff_time}
            })
            
            if result.deleted_count > 0:
                logger.info(f"Cleaned up {result.deleted_count} expired sessions")
            
            return result.deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired sessions: {e}")
            raise
    
    async def create_indexes(self):
        """Create necessary indexes for performance."""
        try:
            # First, clean up any documents with null session_id
            cleanup_result = await self.sessions.delete_many({"session_id": None})
            if cleanup_result.deleted_count > 0:
                logger.info(f"Cleaned up {cleanup_result.deleted_count} documents with null session_id")
            
            # Session lookup index with sparse option to ignore null values
            await self.sessions.create_index(
                "session_id", 
                unique=True,
                sparse=True  # Ignore documents without session_id
            )
            
            # TTL index for automatic expiration
            await self.sessions.create_index(
                "last_accessed",
                expireAfterSeconds=SESSION_TTL_HOURS * 3600
            )
            
            # User lookup index
            await self.sessions.create_index("user_id")
            
            logger.info("Chat session indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error creating session indexes: {e}")
            # If it's a duplicate key error on an existing index, try to drop and recreate
            if "E11000" in str(e) or "IndexOptionsConflict" in str(e):
                logger.info("Attempting to drop and recreate indexes...")
                try:
                    await self.sessions.drop_index("session_id_1")
                    await self.sessions.create_index(
                        "session_id",
                        unique=True,
                        sparse=True
                    )
                    logger.info("Successfully recreated session_id index")
                except Exception as drop_error:
                    logger.error(f"Error dropping/recreating index: {drop_error}")
                    # Don't raise, continue with other operations
            else:
                raise