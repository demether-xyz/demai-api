import os
import motor.motor_asyncio
from pymongo.errors import ConnectionFailure
from config import logger
from typing import Optional

class MongoConnection:
    """Singleton MongoDB connection handler using motor for async operations."""
    
    _instance: Optional['MongoConnection'] = None
    _client: Optional[motor.motor_asyncio.AsyncIOMotorClient] = None
    _db: Optional[motor.motor_asyncio.AsyncIOMotorDatabase] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def connect(self) -> motor.motor_asyncio.AsyncIOMotorDatabase:
        """Connect to MongoDB using MONGO_CONNECTION env var."""
        if self._db is not None:
            return self._db
            
        connection_string = f"{os.getenv('MONGO_CONNECTION')}/demai"
        if not connection_string:
            raise ValueError("MONGO_CONNECTION environment variable not set")
        
        try:
            # Create async motor client
            self._client = motor.motor_asyncio.AsyncIOMotorClient(
                connection_string,
                maxPoolSize=10,
                minPoolSize=1,
                maxIdleTimeMS=30000,  # 30 seconds
                serverSelectionTimeoutMS=5000  # 5 seconds
            )
            
            # Test the connection
            await self._client.admin.command('ping')
            
            # Get database name from connection string or use default
            # MongoDB connection strings typically include the database name after the last '/'
            if '/' in connection_string.split('?')[0]:
                db_name = connection_string.split('/')[-1].split('?')[0]
            else:
                db_name = "demai"  # Default database name
            
            self._db = self._client[db_name]
            logger.info(f"Successfully connected to MongoDB database: {db_name}")
            
            return self._db
            
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error connecting to MongoDB: {e}")
            raise
    
    async def disconnect(self):
        """Close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("Disconnected from MongoDB")
    
    @property
    def db(self) -> Optional[motor.motor_asyncio.AsyncIOMotorDatabase]:
        """Get the database instance."""
        return self._db
    
    @property
    def client(self) -> Optional[motor.motor_asyncio.AsyncIOMotorClient]:
        """Get the client instance."""
        return self._client

# Global instance
mongo_connection = MongoConnection()