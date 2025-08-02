"""
Research Tool for LLM Integration

This module creates an LLM-friendly tool for conducting research using Perplexity's Sonar model.
The tool allows LLMs to perform web searches and get real-time information.
"""

import json
import logging
import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


def create_research_tool() -> Dict[str, Any]:
    """
    Create a research tool using Perplexity's Sonar model.
    
    Returns:
        Dictionary with "tool" function and "metadata"
    """
    
    async def research_tool(query: str) -> str:
        """
        Perform research on a given query using Perplexity's Sonar model.
        
        Args:
            query: The research query or question
            
        Returns:
            Research results as a string
        """
        try:
            # Get API key
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                return json.dumps({
                    "error": "OPENROUTER_API_KEY not found in environment variables"
                })
            
            # Initialize Perplexity Sonar model via OpenRouter
            llm = ChatOpenAI(
                model="perplexity/sonar",
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=0.0
            )
            
            # Create the research prompt
            messages = [HumanMessage(content=f"Research the following topic and provide detailed, up-to-date information: {query}")]
            
            # Get the response
            response = await llm.ainvoke(messages)
            
            # Return the research results
            return json.dumps({
                "query": query,
                "results": response.content,
                "model": "perplexity/sonar"
            })
            
        except Exception as e:
            logger.error(f"Research tool error: {e}")
            return json.dumps({
                "error": str(e),
                "query": query
            })
    
    return {
        "tool": research_tool,
        "metadata": {
            "name": "research",
            "description": "Perform web research and get real-time information on any topic",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The research query or question to investigate"
                    }
                },
                "required": ["query"]
            }
        }
    }