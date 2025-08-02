from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from bson import ObjectId
import motor.motor_asyncio
from config import logger

class PortfolioDataHandler:
    """Handler for portfolio data operations in MongoDB."""
    
    def __init__(self, db: motor.motor_asyncio.AsyncIOMotorDatabase):
        """Initialize with a MongoDB database instance."""
        self.db = db
        self.portfolios = db.portfolios
        self.portfolio_history = db.portfolio_history
        self.messages = db.messages  # For chat history
        self.tasks = db.tasks  # For task management
    
    async def save_portfolio(self, wallet_address: str, vault_address: Optional[str], portfolio_data: Dict[str, Any]) -> str:
        """Save portfolio data to MongoDB."""
        try:
            document = {
                "wallet_address": wallet_address.lower(),
                "vault_address": vault_address.lower() if vault_address else None,
                "portfolio_data": portfolio_data,
                "timestamp": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
            
            # Upsert - update if exists, insert if not
            result = await self.portfolios.replace_one(
                {
                    "wallet_address": wallet_address.lower(),
                    "vault_address": vault_address.lower() if vault_address else None
                },
                document,
                upsert=True
            )
            
            if result.upserted_id:
                logger.info(f"Created new portfolio record for wallet {wallet_address}")
                return str(result.upserted_id)
            else:
                logger.info(f"Updated portfolio record for wallet {wallet_address}")
                return "updated"
                
        except Exception as e:
            logger.error(f"Error saving portfolio: {e}")
            raise
    
    async def get_portfolio(self, wallet_address: str, vault_address: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get portfolio data from MongoDB."""
        try:
            query = {
                "wallet_address": wallet_address.lower(),
                "vault_address": vault_address.lower() if vault_address else None
            }
            
            portfolio = await self.portfolios.find_one(query)
            
            if portfolio:
                # Convert ObjectId to string for JSON serialization
                portfolio["_id"] = str(portfolio["_id"])
                return portfolio
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching portfolio: {e}")
            raise
    
    async def save_portfolio_history(self, wallet_address: str, vault_address: Optional[str], portfolio_data: Dict[str, Any]) -> str:
        """Save portfolio snapshot to history collection."""
        try:
            document = {
                "wallet_address": wallet_address.lower(),
                "vault_address": vault_address.lower() if vault_address else None,
                "portfolio_data": portfolio_data,
                "timestamp": datetime.now(timezone.utc)
            }
            
            result = await self.portfolio_history.insert_one(document)
            logger.info(f"Saved portfolio history snapshot for wallet {wallet_address}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Error saving portfolio history: {e}")
            raise
    
    async def get_portfolio_history(
        self, 
        wallet_address: str, 
        vault_address: Optional[str] = None,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get portfolio history from MongoDB."""
        try:
            query = {
                "wallet_address": wallet_address.lower(),
                "vault_address": vault_address.lower() if vault_address else None
            }
            
            # Add date filters if provided
            if start_date or end_date:
                query["timestamp"] = {}
                if start_date:
                    query["timestamp"]["$gte"] = start_date
                if end_date:
                    query["timestamp"]["$lte"] = end_date
            
            cursor = self.portfolio_history.find(query).sort("timestamp", -1).limit(limit)
            
            history = []
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                history.append(doc)
            
            return history
            
        except Exception as e:
            logger.error(f"Error fetching portfolio history: {e}")
            raise
    
    async def save_chat_message(self, chat_id: str, sender: str, content: str) -> str:
        """Save a chat message."""
        try:
            document = {
                "chat_id": chat_id,
                "sender": sender,
                "content": content,
                "timestamp": datetime.now(timezone.utc)
            }
            
            result = await self.messages.insert_one(document)
            logger.info(f"Saved chat message for chat_id {chat_id}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Error saving chat message: {e}")
            raise
    
    async def get_chat_history(self, chat_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get chat history."""
        try:
            cursor = self.messages.find({"chat_id": chat_id}).sort("timestamp", 1).limit(limit)
            
            messages = []
            async for msg in cursor:
                msg["_id"] = str(msg["_id"])
                messages.append(msg)
            
            return messages
            
        except Exception as e:
            logger.error(f"Error fetching chat history: {e}")
            raise
    
    async def create_indexes(self):
        """Create necessary indexes for performance."""
        try:
            # Portfolio indexes
            await self.portfolios.create_index([("wallet_address", 1), ("vault_address", 1)], unique=True)
            await self.portfolios.create_index([("updated_at", -1)])
            
            # Portfolio history indexes
            await self.portfolio_history.create_index([("wallet_address", 1), ("vault_address", 1), ("timestamp", -1)])
            
            # Message indexes
            await self.messages.create_index([("chat_id", 1), ("timestamp", 1)])
            
            # Task indexes if needed
            await self.tasks.create_index([("user_address", 1), ("status", 1)])
            await self.tasks.create_index([("next_run", 1), ("status", 1)])
            
            logger.info("MongoDB indexes created successfully")
            
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
            raise