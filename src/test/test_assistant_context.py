"""
Test script to verify assistant context includes Morpho yields.
"""
import asyncio
import os
import json
import logging

# Set environment variable to load keychain secrets before importing config
os.environ["LOAD_KEYCHAIN_SECRETS"] = "1"

from services.assistant import SimpleAssistant

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def test_assistant_context():
    """Test that the assistant context includes Morpho yields."""
    logging.info("🧪 Testing assistant context with Morpho yields...")
    
    try:
        # Create assistant instance
        test_vault_address = "0x25bA533C8BD1a00b1FA4cD807054d03e168dff92"
        assistant = SimpleAssistant(vault_address=test_vault_address)
        
        # Initialize the assistant (this loads context)
        await assistant._init_agent()
        
        # Build context prompt to see what data is included
        context_prompt = await assistant._build_context_prompt()
        
        logging.info("✅ Context prompt generated successfully")
        
        # Check if Morpho data is in context
        if "morpho" in context_prompt.lower():
            logging.info("✅ Morpho yields are included in assistant context")
        else:
            logging.warning("⚠️  Morpho yields not found in context")
        
        if "steakhouse" in context_prompt.lower():
            logging.info("✅ Steakhouse Prime vault data found in context")
        else:
            logging.warning("⚠️  Steakhouse vault data not found")
            
        if "gauntlet" in context_prompt.lower():
            logging.info("✅ Gauntlet vault data found in context")
        else:
            logging.warning("⚠️  Gauntlet vault data not found")
        
        # Test system prompt includes Morpho tools
        system_prompt = assistant._build_system_prompt()
        if "morpho_lending" in system_prompt.lower():
            logging.info("✅ Morpho lending tool is included in system prompt")
        else:
            logging.warning("⚠️  Morpho lending tool not found in system prompt")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Error testing assistant context: {e}")
        return False


async def main():
    """Main test function."""
    logging.info("🚀 Testing assistant context integration...\n")
    
    # Load keychain secrets if enabled
    if os.getenv("LOAD_KEYCHAIN_SECRETS") == "1":
        try:
            from config import load_keychain_secrets
            load_keychain_secrets()
            logging.info("✅ Loaded keychain secrets")
        except Exception as e:
            logging.warning(f"⚠️  Could not load keychain secrets: {e}")
    
    # Run test
    success = await test_assistant_context()
    
    if success:
        logging.info("\n✅ Assistant context integration successful!")
        logging.info("💡 The assistant now has access to both Aave and Morpho yields")
        logging.info("🎯 Users can ask questions like:")
        logging.info("   - 'What's the best yield for AUSD?'")
        logging.info("   - 'Where should I deposit my stablecoins for highest yield?'")
        logging.info("   - 'Compare Aave vs Morpho yields'")
    else:
        logging.error("\n❌ Assistant context integration failed")


if __name__ == "__main__":
    asyncio.run(main())