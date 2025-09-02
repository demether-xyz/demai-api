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
            
        base_connection = os.getenv('MONGO_CONNECTION')
        # Remove existing database name and trailing slash if present
        if '/' in base_connection and not base_connection.endswith('//'):
            # Split by '?' first to handle query parameters
            parts = base_connection.split('?')
            base_url = parts[0].rstrip('/')
            # Remove database name (everything after the last '/')
            if base_url.count('/') > 2:  # mongodb://host:port has 2 slashes, anything more is database
                base_url = '/'.join(base_url.split('/')[:-1])
            # Reconstruct with query params if they existed
            base_connection = base_url + ('?' + parts[1] if len(parts) > 1 else '')
        
        connection_string = f"{base_connection}/demai"
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