"""
Generic LangChain Agent Interface for Tool Calling

This module provides a generic LangChain-based agent implementation that handles
tool calling with any MCP or LangChain tools, supporting multiple sequential tool calls.
"""

from typing import Any, Dict, List, Optional, Union

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from config import logger


class LangChainToolsAgent:
    """
    A generic LangChain-based agent that handles tool operations using MCP or LangChain tools.

    This agent supports:
    - Multiple sequential tool calls
    - Structured output formatting
    - Error handling and retries
    - Verbose logging for debugging
    - Any type of tools (not just HubSpot)
    """

    def __init__(
        self,
        tools: List[StructuredTool],
        model_id: str = "google/gemini-2.0-flash-thinking-exp",
        temperature: float = 0.0,
        max_iterations: int = 15,
        verbose: bool = False,
    ):
        """
        Initialize the LangChain agent with tools.

        Args:
            tools: List of StructuredTool objects from MCP or LangChain
            model_id: The model identifier (uses OpenRouter by default)
            temperature: Model temperature for responses
            max_iterations: Maximum number of agent iterations
            verbose: Enable verbose logging
        """
        self.tools = tools
        self.model_id = model_id
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.verbose = verbose

        # Initialize the LLM using OpenRouter
        self.llm = self._initialize_llm()

        # Create the agent
        self.agent = self._create_agent()

    def _initialize_llm(self):
        """
        Initialize the LLM using OpenRouter (following ai_router.py pattern).

        Returns:
            Configured LLM instance
        """
        # Use the same pattern as ai_router.py for OpenRouter
        import os

        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")

        # Handle model ID for OpenRouter (following ai_router.py logic)
        effective_model = self.model_id

        # Check if it's already an OpenRouter model (has provider prefix)
        openrouter_prefixes = ["deepseek/", "meta-llama/", "mistralai/", "google/", "anthropic/", "x-ai/"]
        if not any(self.model_id.startswith(prefix) for prefix in openrouter_prefixes):
            # For non-OpenRouter prefixed models, check if it's a known provider
            if self.model_id.startswith("gpt-") or self.model_id.startswith("o1-") or self.model_id.startswith("o3-"):
                effective_model = f"openai/{self.model_id}"
            elif self.model_id.startswith("claude-"):
                effective_model = f"anthropic/{self.model_id}"
            elif self.model_id.startswith("grok-"):
                effective_model = "x-ai/grok-beta"

        llm_kwargs = {
            "model": effective_model,
            "api_key": api_key,
            "base_url": "https://openrouter.ai/api/v1",
            "temperature": self.temperature,
            "max_tokens": 4096,
        }

        # Disable parallel tool calls for Gemini models to avoid function response mismatch
        if "gemini" in effective_model.lower():
            llm_kwargs["parallel_tool_calls"] = False

        return ChatOpenAI(**llm_kwargs)

    def _create_agent(self) -> AgentExecutor:
        """
        Create a LangChain agent with tool calling capabilities.

        Returns:
            AgentExecutor configured with tools
        """
        # Create a prompt template that includes tool descriptions
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "{system_message}"),
                MessagesPlaceholder(variable_name="chat_history", optional=True),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

        # Create the tool calling agent
        agent = create_tool_calling_agent(llm=self.llm, tools=self.tools, prompt=prompt)

        # Create the agent executor
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=self.verbose,
            max_iterations=self.max_iterations,
            return_intermediate_steps=True,
            handle_parsing_errors=True,
            max_execution_time=None,  # Disable timeout for complex operations
        )

        return agent_executor

    async def execute(
        self, user_instructions: str, system_message: str, chat_history: Optional[List[Union[HumanMessage, AIMessage]]] = None
    ) -> Dict[str, Any]:
        """
        Execute the agent with given instructions and system context.

        Args:
            user_instructions: The user's request/instructions
            system_message: System context including metadata and formatting requirements
            chat_history: Optional chat history for context

        Returns:
            Dictionary containing:
            - final_output: The final response from the agent
            - intermediate_steps: List of tool calls and results
            - total_steps: Number of tool calls made
            - error: Any error that occurred
        """
        try:
            # Prepare the input
            inputs = {
                "input": user_instructions,
                "system_message": system_message,
            }

            if chat_history:
                inputs["chat_history"] = chat_history

            # Execute the agent with retry logic for Gemini function response errors
            max_retries = 2
            retry_count = 0

            while retry_count <= max_retries:
                try:
                    result = await self.agent.ainvoke(inputs, config=RunnableConfig(callbacks=[] if not self.verbose else None))
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e)
                    # Check for Gemini-specific function response error
                    if "function response parts is equal to the number of function call parts" in error_str and retry_count < max_retries:
                        logger.warning(f"Gemini function response mismatch error, retrying ({retry_count + 1}/{max_retries})")
                        retry_count += 1
                        # Add a small delay before retry
                        import asyncio

                        await asyncio.sleep(1)
                        continue
                    else:
                        # Re-raise for other errors or if max retries exceeded
                        raise

            # Extract intermediate steps for logging
            intermediate_steps = result.get("intermediate_steps", [])

            # Count tool calls
            total_steps = len(intermediate_steps)

            # Log tool usage if verbose
            if self.verbose:
                for i, (action, observation) in enumerate(intermediate_steps):
                    logger.info(f"Step {i+1}: Tool '{action.tool}' called with input: {action.tool_input}")

            return {
                "final_output": result.get("output", ""),
                "intermediate_steps": intermediate_steps,
                "total_steps": total_steps,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Agent execution failed: {str(e)}")
            return {
                "final_output": "",
                "intermediate_steps": [],
                "total_steps": 0,
                "error": str(e),
            }


async def create_tools_agent(
    tools: List[StructuredTool], model_id: str = "google/gemini-2.0-flash-thinking-exp", verbose: bool = False
) -> LangChainToolsAgent:
    """
    Factory function to create a configured tools agent.

    Args:
        tools: List of StructuredTool objects from MCP or LangChain
        model_id: The model identifier (uses OpenRouter by default)
        verbose: Enable verbose logging

    Returns:
        Configured LangChainToolsAgent instance
    """
    agent = LangChainToolsAgent(tools=tools, model_id=model_id, verbose=verbose)

    return agent

def create_langchain_tool(func: callable, name: Optional[str] = None, description: Optional[str] = None, args_schema: Optional[Any] = None):
    """Helper function to create a LangChain tool from a regular Python function.

    Automatically detects if the function is sync or async and creates the appropriate tool.

    Args:
        func: The Python function to convert to a LangChain tool
        name: Optional name for the tool (defaults to function name)
        description: Optional description for the tool (defaults to function docstring)
        args_schema: Optional Pydantic model for input validation

    Returns:
        A LangChain StructuredTool
    """
    try:
        import inspect

        from langchain_core.tools import StructuredTool

        # Use provided name or function name
        tool_name = name or func.__name__

        # Use provided description or function docstring
        tool_description = description or (func.__doc__ or f"Tool for {tool_name}")

        # Check if function is async
        if inspect.iscoroutinefunction(func):
            # Create async tool
            return StructuredTool.from_function(
                func=None,  # No sync function
                coroutine=func,  # Async function
                name=tool_name, 
                description=tool_description,
                args_schema=args_schema
            )
        else:
            # Create sync tool
            return StructuredTool.from_function(
                func=func,  # Sync function
                coroutine=None,  # No async function
                name=tool_name, 
                description=tool_description,
                args_schema=args_schema
            )

    except ImportError:
        raise ImportError("LangChain is required for create_langchain_tool function")