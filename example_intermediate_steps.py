#!/usr/bin/env python3
"""
Example of how the intermediate steps feature works
"""
import asyncio
import json
from src.services.assistant import SimpleAssistant

async def example_usage():
    """Example showing how intermediate steps are captured and returned"""
    
    # Configuration
    vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
    user_id = "test_user"
    
    # Create assistant instance
    assistant = SimpleAssistant(vault_address=vault_address)
    
    # Example message that will trigger multiple tool calls
    message = "deposit 10% of any stablecoin into the highest yield on Core chain"
    
    print("=" * 80)
    print("EXAMPLE: Assistant with Intermediate Steps")
    print("=" * 80)
    print(f"User: {message}")
    print("-" * 80)
    
    # Call with intermediate steps enabled
    result = await assistant.chat(
        message=message,
        user_id=user_id,
        return_intermediate_steps=True
    )
    
    if isinstance(result, dict):
        print("\nINTERMEDIATE STEPS:")
        print("-" * 80)
        
        for step in result['intermediate_steps']:
            if step['type'] == 'tool_invocation':
                print(f"\n🔧 Step {step['step']}: {step['message']}")
            elif step['type'] == 'tool_response':
                # Show a summary of the response
                output_str = json.dumps(step['output'], indent=2)
                if len(output_str) > 200:
                    output_str = output_str[:200] + "..."
                print(f"   Response: {output_str}")
        
        print(f"\n\nFINAL RESPONSE:")
        print("-" * 80)
        print(result['response'])
        print("\n" + "=" * 80)
        print(f"Total steps: {result['total_steps']}")
    else:
        print(f"Response: {result}")

    # Show how the API response would look
    print("\n\nAPI RESPONSE FORMAT:")
    print("-" * 80)
    api_response = {
        "response": {
            "messages": [
                {
                    "type": "tool_invocation",
                    "content": "Invoking: `view_portfolio` with `{}`",
                    "tool": "view_portfolio",
                    "step": 1
                },
                {
                    "type": "tool_invocation", 
                    "content": "Invoking: `akka_swap` with `{'dst_token': 'USDT', 'amount': 0.0097774, 'chain_name': 'Core', 'src_token': 'USDC'}`",
                    "tool": "akka_swap",
                    "step": 2
                },
                {
                    "type": "tool_invocation",
                    "content": "Invoking: `aave_lending` with `{'token_symbol': 'USDT', 'amount': 0.0097774, 'chain_name': 'Core', 'action': 'supply'}`",
                    "tool": "aave_lending",
                    "step": 3
                },
                {
                    "type": "final",
                    "content": "All done! Your USDT has been deposited into Colend on Core..."
                }
            ],
            "text": "All done! Your USDT has been deposited into Colend on Core..."
        }
    }
    print(json.dumps(api_response, indent=2))

if __name__ == "__main__":
    asyncio.run(example_usage())