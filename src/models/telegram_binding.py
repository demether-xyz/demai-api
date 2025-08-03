"""
Telegram binding model for storing chat ID to wallet/vault mappings.
"""
from datetime import datetime
from typing import Optional
from pymongo import IndexModel, ASCENDING
from pymongo.database import Database


class TelegramBinding:
    """Model for telegram chat ID to wallet/vault bindings."""
    
    def __init__(self, db: Database):
        self.collection = db.telegram_bindings
    
    async def create_indexes(self):
        """Create database indexes for performance."""
        indexes = [
            IndexModel([("chat_id", ASCENDING)], unique=True),
            IndexModel([("wallet_address", ASCENDING)]),
            IndexModel([("verified_at", ASCENDING)])
        ]
        await self.collection.create_indexes(indexes)
    
    async def create_or_update_binding(
        self,
        chat_id: str,
        wallet_address: str,
        vault_address: str,
        verification_signature: str
    ) -> dict:
        """Create or update a telegram binding."""
        binding = {
            "chat_id": chat_id,
            "wallet_address": wallet_address.lower(),
            "vault_address": vault_address.lower(),
            "verification_signature": verification_signature,
            "verified_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await self.collection.replace_one(
            {"chat_id": chat_id},
            binding,
            upsert=True
        )
        
        return binding
    
    async def get_binding(self, chat_id: str) -> Optional[dict]:
        """Get binding for a chat ID."""
        return await self.collection.find_one({"chat_id": chat_id})
    
    async def remove_binding(self, chat_id: str) -> bool:
        """Remove a binding."""
        result = await self.collection.delete_one({"chat_id": chat_id})
        return result.deleted_count > 0
    
    async def get_bindings_by_wallet(self, wallet_address: str) -> list:
        """Get all bindings for a wallet address."""
        cursor = self.collection.find({"wallet_address": wallet_address.lower()})
        return await cursor.to_list(length=None)