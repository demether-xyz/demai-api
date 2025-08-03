#!/usr/bin/env python3
"""
Test script to demonstrate capturing intermediate steps from the assistant
"""
import asyncio
import json
from src.services.assistant import run_chatbot

async def test_intermediate_steps():
    """Test the assistant with intermediate steps capture"""
    
    # Configuration
    vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
    chat_id = "test_user_123"
    
    # Test message that will trigger multiple tool calls
    message = "deposit 10% of any stablecoin into the highest yield on Core chain"
    
    print("Testing assistant with intermediate steps capture...")
    print(f"Message: {message}")
    print("-" * 80)
    
    # Call the assistant with return_intermediate_steps=True
    result = await run_chatbot(
        message=message,
        chat_id=chat_id,
        vault_address=vault_address,
        return_intermediate_steps=True
    )
    
    # Display the results
    if isinstance(result, dict):
        print(f"\nFinal Response:\n{result['response']}")
        print(f"\nTotal Steps: {result['total_steps']}")
        print("\nIntermediate Steps:")
        print("-" * 80)
        
        for step in result['intermediate_steps']:
            if step['type'] == 'tool_invocation':
                print(f"\nStep {step['step']}: {step['message']}")
            elif step['type'] == 'tool_response':
                print(f"Response: {json.dumps(step['output'], indent=2)[:500]}...")  # Truncate long responses
        
    else:
        print(f"Response: {result}")

if __name__ == "__main__":
    asyncio.run(test_intermediate_steps())