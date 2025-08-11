# DemAI API

AI-powered DeFi assistant API for portfolio management and DeFi protocol interactions.

## What it is

DemAI API is a FastAPI-based service that provides an AI assistant capable of:
- Managing cryptocurrency portfolios
- Interacting with DeFi protocols (Aave, Akka)
- Executing automated trading strategies
- Providing real-time portfolio analytics
- Telegram bot integration for user interactions

## Prerequisites

- Python 3.11-3.13
- Poetry for dependency management
- MongoDB for data storage
- API keys (OpenAI/Google AI, Telegram bot token)

## Installation

1. Install dependencies:
```bash
poetry install
```

2. Set up environment variables in `.env`:
```bash
DEMAI_AUTH_MESSAGE="Your auth message"
TELEGRAM_BOT_TOKEN="Your telegram bot token"
MONGO_URI="mongodb://localhost:27017"
# Add other required API keys
```

## How to run

1. Activate the Poetry environment:
```bash
poetry shell
```

2. Start the FastAPI server:
```bash
poetry run uvicorn src.main:app --reload
```

The API will be available at `http://localhost:8000`

## Testing

Run tests with:
```bash
poetry run python src/test/test_simple_assistant.py
```