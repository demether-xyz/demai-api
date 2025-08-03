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
from src.services.task_manager import TaskManager
from src.services.strategies import get_all_strategies
from src.utils.aave_yields_utils import get_simplified_aave_yields

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
        
        global portfolio_service, portfolio_data_handler, task_manager
        
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
        await task_manager.create_indexes()
        app.state.task_manager = task_manager
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
    return_intermediate_steps: Optional[bool] = False  # Return intermediate tool calls

class PortfolioRequest(BaseModel):
    vault_address: Optional[str] = None  # Make vault address optional
    wallet_address: str  # Wallet address for authentication
    signature: str
    refresh: Optional[bool] = False

class CreateStrategyRequest(BaseModel):
    wallet_address: str
    vault_address: str
    signature: str
    strategy_id: str
    percentage: int  # Percentage of funds to allocate (1-100)
    chain: str  # Chain name
    enabled: Optional[bool] = True

class UpdateStrategyRequest(BaseModel):
    wallet_address: str
    signature: str
    task_id: str
    percentage: Optional[int] = None
    enabled: Optional[bool] = None

class DeleteStrategyRequest(BaseModel):
    wallet_address: str
    signature: str
    task_id: str


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
        vault_address=request.vault_address,
        return_intermediate_steps=request.return_intermediate_steps
    )
    
    # If intermediate steps were requested, response will be a dict
    if request.return_intermediate_steps and isinstance(response, dict):
        # Format the response with messages array
        messages = []
        
        # Add intermediate messages
        for step in response.get("intermediate_steps", []):
            messages.append({
                "type": step["type"],
                "content": step["message"],
                "tool": step.get("tool"),
                "step": step.get("step")
            })
        
        # Add final response
        messages.append({
            "type": "final",
            "content": response["response"]
        })
        
        return {"response": {"messages": messages, "text": response["response"]}}
    else:
        # Standard response format for backward compatibility
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
    """List all available strategies with current yield information"""
    strategies = get_all_strategies()
    
    # Get current yields
    try:
        yields = await get_simplified_aave_yields()
        
        # Create a lookup map for yields by token and chain
        yield_map = {}
        for yield_data in yields:
            key = f"{yield_data['token']}_{yield_data['chain']}"
            yield_map[key] = yield_data['borrow_apy']
        
        # Enhance strategies with yield information
        for strategy in strategies:
            strategy['current_yields'] = {}
            for token in strategy.get('tokens', []):
                key = f"{token}_{strategy['chain']}"
                if key in yield_map:
                    strategy['current_yields'][token] = yield_map[key]
                else:
                    strategy['current_yields'][token] = 0.0
                    
    except Exception as e:
        logger.warning(f"Failed to fetch yields for strategies: {e}")
        # Add empty yields if fetch fails
        for strategy in strategies:
            strategy['current_yields'] = {token: 0.0 for token in strategy.get('tokens', [])}
    
    return {"strategies": strategies}

@app.post("/strategies/subscribe")
async def subscribe_to_strategy(request: CreateStrategyRequest):
    """Subscribe to a strategy"""
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
            percentage=request.percentage,
            chain=request.chain,
            enabled=request.enabled
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating strategy subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to subscribe to strategy")

@app.get("/strategies/subscriptions")
async def get_user_strategies(wallet_address: str, signature: str):
    """Get all strategy subscriptions for a user"""
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
    return {"subscriptions": tasks}

@app.put("/strategies/subscriptions/update")
async def update_strategy_subscription(request: UpdateStrategyRequest):
    """Update a strategy subscription"""
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
        success = await task_manager.update_task(
            task_id=request.task_id,
            user_address=request.wallet_address,
            percentage=request.percentage,
            enabled=request.enabled
        )
        if not success:
            raise HTTPException(status_code=404, detail="Strategy subscription not found or unauthorized")
        
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/strategies/subscriptions/delete")
async def delete_strategy_subscription(request: DeleteStrategyRequest):
    """Delete a strategy subscription"""
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
        raise HTTPException(status_code=404, detail="Strategy subscription not found or unauthorized")
    
    return {"success": True}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)