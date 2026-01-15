"""
LLM Provider for RAG system model initialization.

This module handles initialization of language models and embeddings:
- OpenAI embeddings model initialization
- LLM client using AISuite for unified interface
- Model configuration
- MCP tool integration for autonomous tool calling
"""

import asyncio
import concurrent.futures
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import aisuite as ai  # type: ignore[import-untyped]
import nest_asyncio  # type: ignore[import-untyped]
from app.core.config import Settings
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM invocation compatible with LangChain interface."""

    content: str
    usage: dict | None = None  # Token usage statistics from the LLM


@dataclass
class ToolCallResult:
    """Result from a tool-enabled LLM invocation.

    Attributes:
        content: The final response content from the LLM
        tool_calls_made: List of tool calls executed during the invocation
        iterations: Number of tool calling iterations that occurred
    """

    content: str
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0


def convert_mcp_tools_to_openai_format(mcp_tools: list) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to OpenAI function calling format.

    Args:
        mcp_tools: List of MCP Tool objects from server.list_tools()

    Returns:
        List of tool definitions in OpenAI function calling format
    """
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                },
            }
        )
    return openai_tools


class AISuiteLLMWrapper:
    """Wrapper class to make AISuite compatible with existing RAG code.

    This wrapper provides an interface similar to LangChain's LLM classes,
    allowing the RAG system to use AISuite without major refactoring.
    """

    def __init__(
        self, client: ai.Client, model: str, max_tokens: int, temperature: float
    ):
        """Initialize the AISuite LLM wrapper.

        Args:
            client: AISuite Client instance
            model: Full model identifier with provider prefix (e.g., "openai:gpt-4o-mini")
            max_tokens: Maximum tokens for completion
            temperature: Temperature for response generation (0.0-2.0)
        """
        self.client = client
        self.model_id = model  # Use directly, expect "provider:model" format
        self.max_tokens = max_tokens
        self.temperature = temperature

        # Direct OpenAI client for tool calling
        # AISuite doesn't correctly pass tools to providers, so we use OpenAI directly
        self.openai_client = OpenAI()
        # Extract model name without provider prefix for direct OpenAI calls
        self.openai_model = model.split(":", 1)[1] if ":" in model else model

    def invoke(self, prompt: str) -> LLMResponse:
        """Invoke the LLM with a prompt string.

        Args:
            prompt: The prompt text

        Returns:
            LLMResponse object with 'content' attribute containing the response text
            and 'usage' attribute with token usage statistics

        Raises:
            RuntimeError: If LLM invocation fails
        """
        messages = [{"role": "user", "content": prompt}]

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Extract token usage if available
            usage = None
            if hasattr(response, "usage") and response.usage:
                usage = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(
                        response.usage, "completion_tokens", 0
                    ),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }

            return LLMResponse(content=response.choices[0].message.content, usage=usage)
        except Exception as e:
            error_msg = (
                f"Failed to invoke LLM (model={self.model_id}, "
                f"prompt_length={len(prompt)}): {e}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def invoke_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        max_turns: int = 3,
    ) -> ToolCallResult:
        """Invoke LLM with MCP tools available for autonomous calling.

        This method enables the LLM to autonomously decide when to call tools
        and handles the multi-turn conversation loop until the LLM provides
        a final response or max_turns is reached.

        Args:
            prompt: User prompt/question
            tools: List of tool definitions in OpenAI function calling format
            max_turns: Maximum tool call iterations (default 3)

        Returns:
            ToolCallResult with final content and tool call history
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tool_calls_made: list[dict[str, Any]] = []
        iterations = 0

        # Log tools being passed for debugging
        logger.info(f"invoke_with_tools called with {len(tools)} tools")
        for tool in tools:
            func = tool.get("function", {})
            logger.info(
                f"  Tool: {func.get('name')} - {func.get('description', '')[:50]}..."
            )

        while iterations < max_turns:
            try:
                logger.info(
                    f"Making LLM API call with tools (iteration {iterations + 1}/{max_turns})"
                )
                # Use direct OpenAI client for tool calling
                # AISuite doesn't correctly pass tools to providers (requires callables)
                response = self.openai_client.chat.completions.create(
                    model=self.openai_model,
                    messages=messages,  # type: ignore[arg-type]
                    tools=tools,  # type: ignore[arg-type]
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
            except Exception as e:
                logger.error(f"LLM call failed during tool invocation: {e}")
                return ToolCallResult(
                    content=f"Error during LLM invocation: {e}",
                    tool_calls_made=tool_calls_made,
                    iterations=iterations,
                )

            choice = response.choices[0]

            # Log tool call status at INFO level for visibility
            logger.info(
                f"LLM response - has tool_calls: {bool(choice.message.tool_calls)}"
            )
            if choice.message.tool_calls:
                logger.info(f"LLM made {len(choice.message.tool_calls)} tool call(s)")
                for tc in choice.message.tool_calls:
                    logger.info(
                        f"Tool call: {tc.function.name}({tc.function.arguments})"  # type: ignore[union-attr]
                    )
            else:
                content_preview = (
                    choice.message.content[:200] if choice.message.content else "None"
                )
                logger.info(f"LLM returned text (no tool calls): {content_preview}...")

            # Check if LLM made tool calls
            if choice.message.tool_calls:
                iterations += 1
                # Add assistant message with tool calls to conversation
                messages.append(
                    {
                        "role": "assistant",
                        "content": choice.message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,  # type: ignore[union-attr]
                                    "arguments": tc.function.arguments,  # type: ignore[union-attr]
                                },
                            }
                            for tc in choice.message.tool_calls
                        ],
                    }
                )

                for tool_call in choice.message.tool_calls:
                    # Execute tool and add result to conversation
                    tool_result = self._execute_tool_call(tool_call)
                    tool_calls_made.append(
                        {
                            "tool": tool_call.function.name,  # type: ignore[union-attr]
                            "args": tool_call.function.arguments,  # type: ignore[union-attr]
                            "result": tool_result,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )
            else:
                # No more tool calls, return final response
                return ToolCallResult(
                    content=choice.message.content or "",
                    tool_calls_made=tool_calls_made,
                    iterations=iterations,
                )

        # Max turns reached
        return ToolCallResult(
            content=choice.message.content or "Maximum tool iterations reached.",
            tool_calls_made=tool_calls_made,
            iterations=iterations,
        )

    # Class-level thread pool executor for efficient async tool execution
    _executor: concurrent.futures.ThreadPoolExecutor | None = None

    @classmethod
    def _get_executor(cls) -> concurrent.futures.ThreadPoolExecutor:
        """Get or create the shared thread pool executor.

        Returns:
            ThreadPoolExecutor instance for running async tool calls
        """
        if cls._executor is None:
            # Use a small pool since tool calls are I/O bound
            cls._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="mcp_tool_"
            )
        return cls._executor

    def _execute_tool_call(self, tool_call: Any, timeout: float = 10.0) -> str:
        """Execute a tool call via MCP server with timeout.

        Args:
            tool_call: Tool call object from LLM response
            timeout: Maximum seconds to wait for tool execution (default 10.0)

        Returns:
            String result from the tool execution
        """
        from app.services.mcp.bisq_mcp_server import get_mcp_server

        def run_async_with_timeout(coro: Any, timeout_seconds: float) -> Any:
            """Run coroutine in thread pool with proper timeout handling.

            Uses a shared thread pool executor instead of creating new threads
            for each call, and applies asyncio.wait_for for proper timeout.
            """

            def thread_target() -> Any:
                # Create a new standard asyncio event loop for this thread
                # (not uvloop, which the main thread uses)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                # Apply nest_asyncio to allow nested loops in this thread
                nest_asyncio.apply(loop)
                try:
                    # Wrap coroutine with asyncio timeout
                    async def with_timeout():
                        return await asyncio.wait_for(coro, timeout=timeout_seconds)

                    return loop.run_until_complete(with_timeout())
                finally:
                    loop.close()

            # Submit to thread pool and wait with timeout
            executor = self._get_executor()
            future = executor.submit(thread_target)
            try:
                # Add extra buffer time for thread overhead
                return future.result(timeout=timeout_seconds + 2.0)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"Tool execution timed out after {timeout_seconds} seconds"
                )

        try:
            server = get_mcp_server()
            args = json.loads(tool_call.function.arguments)

            # Run async tool with timeout using thread pool
            result = run_async_with_timeout(
                server.call_tool(tool_call.function.name, args), timeout
            )

            # Handle tuple return from call_tool: (content_list, metadata)
            content_list, _ = result
            return content_list[0].text
        except TimeoutError as e:
            logger.warning(f"Tool {tool_call.function.name} timed out: {e}")
            return "Tool execution timed out. Please try again."
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_call.function.name}: {e}")
            return f"Tool execution error: {e}"


class LLMProvider:
    """Provider for LLM and embeddings initialization in RAG system.

    This class handles:
    - OpenAI embeddings initialization
    - LLM client using AISuite for unified interface
    """

    def __init__(self, settings: Settings):
        """Initialize the LLM provider.

        Args:
            settings: Application settings with API keys and model configuration
        """
        self.settings = settings
        self.embeddings: OpenAIEmbeddings | None = None
        self.llm: AISuiteLLMWrapper | None = None

        try:
            self.ai_client = ai.Client()
            logger.info("LLM provider initialized with AISuite client")
        except Exception as e:
            error_msg = f"Failed to initialize AISuite client: {e}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def _validate_openai_api_key(self) -> None:
        """Validate that OpenAI API key is configured.

        Raises:
            ValueError: If OpenAI API key is not configured
        """
        if not self.settings.OPENAI_API_KEY:
            error_msg = (
                "OpenAI API key is required but not configured. "
                "Please set OPENAI_API_KEY in environment variables."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def initialize_embeddings(self) -> OpenAIEmbeddings:
        """Initialize the OpenAI embedding model.

        Returns:
            OpenAIEmbeddings instance configured with API key and model

        Raises:
            ValueError: If OpenAI API key is not configured
        """
        logger.info("Initializing OpenAI embeddings model...")
        self._validate_openai_api_key()

        try:
            self.embeddings = OpenAIEmbeddings(
                api_key=self.settings.OPENAI_API_KEY,  # type: ignore[arg-type]
                model=self.settings.OPENAI_EMBEDDING_MODEL,
            )
            logger.info("OpenAI embeddings model initialized")
            return self.embeddings
        except Exception as e:
            error_msg = f"Failed to initialize OpenAI embeddings: {e}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def initialize_llm(self) -> AISuiteLLMWrapper:
        """Initialize the language model using AISuite.

        Returns:
            Initialized LLM wrapper with AISuite client
        """
        logger.info("Initializing language model with AISuite...")
        self._validate_openai_api_key()

        try:
            self.llm = AISuiteLLMWrapper(
                client=self.ai_client,
                model=self.settings.OPENAI_MODEL,
                max_tokens=self.settings.MAX_TOKENS,
                temperature=self.settings.LLM_TEMPERATURE,
            )
            logger.info(f"LLM initialized with model: {self.settings.OPENAI_MODEL}")
            return self.llm
        except Exception as e:
            error_msg = f"Failed to initialize LLM wrapper: {e}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def get_embeddings(self) -> OpenAIEmbeddings | None:
        """Get the initialized embeddings model.

        Returns:
            OpenAIEmbeddings instance or None if not initialized
        """
        return self.embeddings

    def get_llm(self) -> AISuiteLLMWrapper | None:
        """Get the initialized LLM.

        Returns:
            LLM wrapper instance or None if not initialized
        """
        return self.llm
