"""
Test the simple assistant.
"""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.services.assistant import SimpleAssistant, create_assistant


async def main():
    """Test the simple assistant."""
    # Test vault address
    vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
    
    print("Creating assistant...")
    assistant = await create_assistant(vault_address)
    
    # Test queries
    queries = [
        "What's in my portfolio?",
    ]
    
    for query in queries:
        print(f"\n👤 User: {query}")
        response = await assistant.chat(query)
        print(f"🤖 Assistant: {response}")


if __name__ == "__main__":
    asyncio.run(main())