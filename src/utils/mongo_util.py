from bson import ObjectId
from pancaik.core.config import get_config
from pancaik.core.connections import \
    ConnectionHandler as PancaikConnectionHandler
from datetime import datetime

from config import logger


class MongoUtil:
    """Handler for MongoDB operations using Pancaik setup."""

    def __init__(self):
        """Initialize the MongoDB handler."""
        self.db = get_config("db")
        assert self.db is not None, "Database must be initialized"
        self.messages_collection = self.db.messages
        self._pancaik_handler = PancaikConnectionHandler()

    def fetch_chat_history(self, chat_id: str):
        """Fetch chat history for a given chat_id."""
        if self.db is None:
            logger.error("Database connection not established.")
            return []
        
        logger.info(f"Fetching history for chat_id: {chat_id}")
        try:
            history = list(self.messages_collection.find({"chat_id": chat_id}).sort("timestamp").limit(10))
            return history
        except Exception as e:
            logger.error(f"Error fetching chat history: {e}")
            return []

    def save_message(self, chat_id: str, sender: str, content: str):
        """Save a message to the chat history."""
        if self.db is None:
            logger.error("Database connection not established.")
            return False
        
        try:
            message_doc = {
                "chat_id": chat_id,
                "sender": sender,
                "content": content,
                "timestamp": datetime.utcnow()
            }
            result = self.messages_collection.insert_one(message_doc)
            logger.info(f"Message saved with ID: {result.inserted_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False