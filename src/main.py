from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from src.services.assistant import run_chatbot
from eth_account.messages import encode_defunct
from web3 import Web3
from typing import Optional, List, Dict, Any, Union
from config import logger, TELEGRAM_BOT_TOKEN
from services.portfolio_service import PortfolioService
from contextlib import asynccontextmanager
from src.utils.mongo_connection import mongo_connection
from src.services.portfolio_data_handler import PortfolioDataHandler
from src.services.task_manager import TaskManager
from src.services.strategies import get_all_strategies
from src.utils.aave_yields_utils import get_simplified_aave_yields
from src.services.task_executor import TaskExecutor
from src.utils.telegram_helper import TelegramHelper
from src.models.telegram_binding import TelegramBinding

# Global instances
portfolio_service = None
task_manager = None
portfolio_data_handler = None
telegram_helper = None
telegram_binding = None

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
        
        # Initialize Telegram helper if token is available
        global telegram_helper, telegram_binding
        if TELEGRAM_BOT_TOKEN:
            telegram_helper = TelegramHelper(TELEGRAM_BOT_TOKEN)
            app.state.telegram_helper = telegram_helper
            logger.info("Telegram helper initialized on startup")
            
            # Initialize Telegram binding model
            telegram_binding = TelegramBinding(db)
            await telegram_binding.create_indexes()
            app.state.telegram_binding = telegram_binding
            logger.info("Telegram binding model initialized on startup")
        else:
            logger.warning("TELEGRAM_BOT_TOKEN not found in environment variables")
        
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

async def _process_chat_message(
    message: str,
    chat_id: str,
    vault_address: str = None,
    return_intermediate_steps: bool = False
) -> Union[str, Dict[str, Any]]:
    """
    Internal function to process chat messages.
    Shared between /chat endpoint and telegram webhook.
    
    Args:
        message: User's message
        chat_id: Chat/user identifier
        vault_address: Vault address for portfolio context
        return_intermediate_steps: If True, returns dict with response and intermediate steps
    
    Returns:
        Either response string or dict with response and intermediate steps
    """
    # Run the chatbot with the user's message and vault address
    response = await run_chatbot(
        message=message, 
        chat_id=chat_id,
        vault_address=vault_address,
        return_intermediate_steps=return_intermediate_steps
    )
    
    # If intermediate steps were requested, response will be a dict
    if return_intermediate_steps and isinstance(response, dict):
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
        
        return {"messages": messages, "text": response["response"]}
    else:
        # Standard response format
        return response

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

    response = await _process_chat_message(
        message=request.message,
        chat_id=request.wallet_address,  # Use wallet address for chat history consistency
        vault_address=request.vault_address,
        return_intermediate_steps=request.return_intermediate_steps
    )
    
    # Wrap response for API compatibility
    if request.return_intermediate_steps and isinstance(response, dict):
        return {"response": response}
    else:
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

@app.get("/tasks")
async def execute_next_task():
    """Get and execute the next due task.
    
    This endpoint can be called by anyone (e.g., a cron job) to execute due tasks.
    It picks the oldest task that is due and runs it.
    """
    task_manager = getattr(app.state, 'task_manager', None)
    if task_manager is None:
        raise HTTPException(status_code=500, detail="Task manager not initialized")
    
    # Get telegram helper and binding if available
    telegram_helper = getattr(app.state, 'telegram_helper', None)
    telegram_binding = getattr(app.state, 'telegram_binding', None)
    
    # Use task executor with telegram support
    task_executor = TaskExecutor(task_manager, telegram_helper, telegram_binding)
    return await task_executor.execute_next_task()

@app.post("/telegram")
async def telegram_webhook(request: Dict[str, Any]):
    """Handle incoming Telegram webhook updates"""
    telegram_helper = getattr(app.state, 'telegram_helper', None)
    telegram_binding_model = getattr(app.state, 'telegram_binding', None)
    
    if telegram_helper is None:
        raise HTTPException(status_code=500, detail="Telegram bot not initialized")
    
    try:
        # Process the update
        processed_data = await telegram_helper.process_update(request)
        
        if processed_data and processed_data.get("content"):
            chat_id = processed_data["chat_id"]
            user_message = processed_data["content"]
            
            # Check if this is a raw signature (starts with 0x and is ~132 characters)
            if user_message.startswith("0x") and len(user_message) >= 130 and len(user_message) <= 140:
                # This looks like a signature, prompt user to use the verify command
                await telegram_helper.send_message(
                    chat_id,
                    "It looks like you're trying to verify your wallet. Please use the following format:\n\n"
                    "/verify <wallet_address> <vault_address> <signature>\n\n"
                    "Example:\n/verify 0x1234... 0x5678... " + user_message[:20] + "..."
                )
                return {"ok": True}
            
            # Check if this is a verification command
            if user_message.startswith("/verify "):
                # Parse verification command: /verify <wallet_address> <vault_address> <signature>
                parts = user_message.split()
                if len(parts) != 4:
                    await telegram_helper.send_message(
                        chat_id, 
                        "Please use format: /verify <wallet_address> <vault_address> <signature>"
                    )
                    return {"ok": True}
                
                _, wallet_address, vault_address, signature = parts
                
                # Construct the expected message that includes vault address
                expected_message = f"Bind wallet {wallet_address} with vault {vault_address} to Telegram"
                
                # Verify the signature
                is_valid = verify_signature(
                    message=expected_message,
                    signature=signature,
                    address=wallet_address
                )
                
                if is_valid:
                    # Store the binding
                    await telegram_binding_model.create_or_update_binding(
                        chat_id=str(chat_id),
                        wallet_address=wallet_address,
                        vault_address=vault_address,
                        verification_signature=signature
                    )
                    
                    await telegram_helper.send_message(
                        chat_id,
                        f"✅ Successfully verified!\n\n"
                        f"Wallet: {wallet_address[:6]}...{wallet_address[-4:]}\n"
                        f"Vault: {vault_address[:6]}...{vault_address[-4:]}\n\n"
                        f"You can now use the DemAI assistant directly in Telegram!"
                    )
                else:
                    await telegram_helper.send_message(
                        chat_id,
                        "❌ Invalid signature. Please make sure you're signing with the correct wallet."
                    )
                
                return {"ok": True}
            
            # Check if user has existing binding
            binding = await telegram_binding_model.get_binding(str(chat_id))
            
            if not binding:
                # No binding found, prompt user to verify
                await telegram_helper.send_message(
                    chat_id,
                    "To start your verification process, please visit https://demether.ai/"
                )
                return {"ok": True}
            
            # Use the bound wallet and vault addresses
            try:
                # Use the shared chat processing logic
                response = await _process_chat_message(
                    message=user_message,
                    chat_id=binding["wallet_address"],  # Use wallet address as chat ID for consistency
                    vault_address=binding["vault_address"],
                    return_intermediate_steps=False  # Simple response for telegram
                )
                
                # Send the response back to the user using telegram chat_id
                await telegram_helper.send_message(chat_id, response)
                
            except Exception as chat_error:
                logger.error(f"Error processing chat message: {chat_error}")
                error_message = "Sorry, I encountered an error processing your message. Please try again."
                await telegram_helper.send_message(chat_id, error_message)
            
            return {"ok": True}
        
        return {"ok": True, "message": "No message to process"}
        
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {e}")
        return {"ok": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)