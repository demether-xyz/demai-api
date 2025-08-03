#!/usr/bin/env python3
"""
Script to set up Telegram webhook
"""

import sys
import os
import asyncio
from telegram import Bot

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import TELEGRAM_BOT_TOKEN

async def setup_webhook():
    # Get bot token from config
    bot_token = TELEGRAM_BOT_TOKEN
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not found in environment variables")
        sys.exit(1)
    
    # Hardcode your webhook URL here
    # Replace with your actual domain/ngrok URL
    WEBHOOK_URL = "https://c2a7185d9ad8.ngrok-free.app/telegram"  # TODO: Replace with your actual URL
    
    try:
        # Initialize bot
        bot = Bot(token=bot_token)
        
        # Get current webhook info
        webhook_info = await bot.get_webhook_info()
        print(f"Current webhook URL: {webhook_info.url}")
        
        # Set new webhook
        success = await bot.set_webhook(url=WEBHOOK_URL)
        
        if success:
            print(f"✅ Webhook successfully set to: {WEBHOOK_URL}")
            
            # Verify the webhook was set
            webhook_info = await bot.get_webhook_info()
            print(f"Verified webhook URL: {webhook_info.url}")
            print(f"Pending update count: {webhook_info.pending_update_count}")
        else:
            print("❌ Failed to set webhook")
            
    except Exception as e:
        print(f"Error setting up webhook: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("Setting up Telegram webhook...")
    asyncio.run(setup_webhook())