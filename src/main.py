from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.services.assistant import run_chatbot
from eth_account.messages import encode_defunct
from web3 import Web3
from typing import Optional, List, Dict, Any
from config import logger
from services.portfolio_service import PortfolioService
from contextlib import asynccontextmanager
from src.utils.mongo_connection import mongo_connection
from src.services.portfolio_data_handler import PortfolioDataHandler
from src.archive.task_manager import TaskManager
from src.archive.strategy_registry import register_all_strategies

# Global instances
portfolio_service = None
task_manager = None
portfolio_data_handler = None

# Auth message that must match frontend DEMAI_AUTH_MESSAGE
DEMAI_AUTH_MESSAGE = """Welcome to demAI!

This signature will be used to authenticate your interactions with the demAI platform.

This signature will not trigger any blockchain transactions or grant any token approvals."""

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic here
    # Connect to MongoDB
    try:
        db = await mongo_connection.connect()
        
        global portfolio_service, task_manager, portfolio_data_handler
        
        # Initialize portfolio data handler
        portfolio_data_handler = PortfolioDataHandler(db)
        await portfolio_data_handler.create_indexes()
        app.state.portfolio_data_handler = portfolio_data_handler
        
        # Initialize portfolio service with MongoDB
        portfolio_service = PortfolioService(db, cache_ttl_seconds=3600)  # 60 minute cache
        app.state.portfolio_service = portfolio_service
        logger.info("Portfolio service initialized on startup")
        
        # Initialize task manager
        task_manager = TaskManager(db)
        app.state.task_manager = task_manager
        
        # Register all strategies
        register_all_strategies(task_manager)
        
        logger.info("Task manager initialized on startup")
        
    except Exception as e:
        logger.error(f"Failed to initialize MongoDB connection: {e}")
        raise
    
    yield
    
    # Shutdown logic here
    await mongo_connection.disconnect()

app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow any origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    wallet_address: str  # Wallet address for authentication
    vault_address: Optional[str] = None  # Vault address for portfolio context
    signature: str

class PortfolioRequest(BaseModel):
    vault_address: Optional[str] = None  # Make vault address optional
    wallet_address: str  # Wallet address for authentication
    signature: str
    refresh: Optional[bool] = False

class CreateTaskRequest(BaseModel):
    wallet_address: str
    vault_address: str
    signature: str
    strategy_id: str
    amount: str  # Amount in wei
    chain_id: int
    params: Optional[Dict[str, Any]] = None
    interval_hours: Optional[int] = None

class TaskActionRequest(BaseModel):
    wallet_address: str
    signature: str
    task_id: str

class RunTasksRequest(BaseModel):
    secret_key: str  # Simple auth for cron job

def verify_signature(message: str, signature: str, address: str) -> bool:
    try:
        w3 = Web3()
        message_hash = encode_defunct(text=message)
        recovered_address = w3.eth.account.recover_message(message_hash, signature=signature)
        return recovered_address.lower() == address.lower()
    except Exception:
        return False

@app.post("/chat/")
async def chat_endpoint(request: ChatRequest):
    # Verify the signature with the auth message from frontend
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=request.signature,
        address=request.wallet_address
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")

    # Run the chatbot with the user's message and vault address
    # The assistant.py has hardcoded window list, no need to pass from frontend
    response = await run_chatbot(
        message=request.message, 
        chat_id=request.wallet_address,  # Use wallet address for chat history consistency
        vault_address=request.vault_address
    )
    return {"response": response}

@app.post("/portfolio/")
async def portfolio_endpoint(request: PortfolioRequest):
    """Get portfolio summary for a vault address or wallet address"""
    # Verify the signature with the same auth message as chat endpoint
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=request.signature,
        address=request.wallet_address  # Use wallet address for authentication
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")
    
    try:
        # Use the global portfolio service instance
        portfolio_service = getattr(app.state, 'portfolio_service', None)
        if portfolio_service is None:
            raise HTTPException(status_code=500, detail="Portfolio service not initialized")
        
        # Ensure wallet address is properly checksummed for Web3 operations
        w3 = Web3()
        checksummed_wallet_address = w3.to_checksum_address(request.wallet_address)
        checksummed_vault_address = w3.to_checksum_address(request.vault_address) if request.vault_address else None
        
        # If refresh is requested, clear cache first
        if request.refresh:
            # Determine target address for cache clearing
            target_address = checksummed_vault_address if checksummed_vault_address else checksummed_wallet_address
            await portfolio_service.clear_portfolio_cache(target_address)
        
        # Get portfolio summary - pass both vault and wallet address (both properly checksummed)
        portfolio_data = await portfolio_service.get_portfolio_summary(
            vault_address=checksummed_vault_address,
            wallet_address=checksummed_wallet_address
        )
        
        return portfolio_data
        
    except Exception as e:
        logger.error(f"Error getting portfolio for vault {request.vault_address} / wallet {request.wallet_address}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/strategies/")
async def list_strategies():
    """List all available strategies"""
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    strategies = []
    for strategy in task_manager.strategies.values():
        strategies.append(strategy.to_dict())
    
    return {"strategies": strategies}

@app.post("/strategies/tasks/create")
async def create_strategy_task(request: CreateTaskRequest):
    """Create a new strategy task for a user"""
    # Verify signature
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=request.signature,
        address=request.wallet_address
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")
    
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    try:
        result = await task_manager.create_task(
            user_address=request.wallet_address,
            vault_address=request.vault_address,
            strategy_id=request.strategy_id,
            amount=request.amount,
            chain_id=request.chain_id,
            params=request.params,
            interval_hours=request.interval_hours
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail="Failed to create task")

@app.get("/strategies/tasks/")
async def get_user_tasks(wallet_address: str, signature: str):
    """Get all tasks for a user"""
    # Verify signature
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=signature,
        address=wallet_address
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")
    
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    tasks = await task_manager.get_user_tasks(wallet_address)
    return {"tasks": tasks}

@app.post("/strategies/tasks/pause")
async def pause_task(request: TaskActionRequest):
    """Pause a user's task"""
    # Verify signature
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=request.signature,
        address=request.wallet_address
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")
    
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    success = await task_manager.pause_task(request.task_id, request.wallet_address)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or unauthorized")
    
    return {"success": True}

@app.post("/strategies/tasks/resume")
async def resume_task(request: TaskActionRequest):
    """Resume a paused task"""
    # Verify signature
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=request.signature,
        address=request.wallet_address
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")
    
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    success = await task_manager.resume_task(request.task_id, request.wallet_address)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or unauthorized")
    
    return {"success": True}

@app.post("/strategies/tasks/delete")
async def delete_task(request: TaskActionRequest):
    """Delete a task"""
    # Verify signature
    is_valid = verify_signature(
        message=DEMAI_AUTH_MESSAGE,
        signature=request.signature,
        address=request.wallet_address
    )
    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid signature or wallet address")
    
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    success = await task_manager.delete_task(request.task_id, request.wallet_address)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or unauthorized")
    
    return {"success": True}

@app.post("/strategies/tasks/run")
async def run_due_tasks(request: RunTasksRequest):
    """Run all due tasks - called by cron job"""
    # Simple secret key auth for cron job
    import os
    expected_secret = os.getenv("CRON_SECRET_KEY", "default-secret-key")
    
    if request.secret_key != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid secret key")
    
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    try:
        results = await task_manager.run_due_tasks()
        return results
    except Exception as e:
        logger.error(f"Error running tasks: {e}")
        raise HTTPException(status_code=500, detail="Failed to run tasks")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)