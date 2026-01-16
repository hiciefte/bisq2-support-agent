"""LLM Provider using AISuite with native MCP support.

This module provides:
- LLM client using AISuite for unified interface
- Native MCP support via HTTP transport
- Embeddings via LiteLLM abstraction
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aisuite as ai  # type: ignore[import-untyped]
from app.services.rag.embeddings_provider import LiteLLMEmbeddings

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM invocation."""

    content: str
    usage: dict | None = None


@dataclass
class ToolCallResult:
    """Result from tool-enabled LLM invocation."""

    content: str
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    success: bool = True  # False if tool invocation infrastructure failed


class AISuiteLLMWrapper:
    """LLM wrapper using AISuite with native MCP support via HTTP transport."""

    def __init__(
        self,
        client: ai.Client,
        model: str,
        max_tokens: int,
        temperature: float,
        mcp_url: str = "http://localhost:8000/mcp",
    ):
        """Initialize the AISuite LLM wrapper.

        Args:
            client: AISuite Client instance
            model: Full model identifier with provider prefix (e.g., "openai:gpt-4o-mini")
            max_tokens: Maximum tokens for completion
            temperature: Temperature for response generation (0.0-2.0)
            mcp_url: URL of the MCP HTTP server (default: "http://localhost:8000/mcp")
        """
        self.client = client
        self.model_id = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.mcp_url = mcp_url

        logger.info(f"AISuite LLM initialized: {model}, MCP URL: {mcp_url}")

    def invoke(self, prompt: str) -> LLMResponse:
        """Invoke LLM without tools.

        Args:
            prompt: The prompt text

        Returns:
            LLMResponse with content and optional usage statistics

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
            logger.exception(f"LLM invocation failed: {e}")
            raise RuntimeError(f"Failed to invoke LLM: {e}") from e

    def invoke_with_tools(self, prompt: str, max_turns: int = 3) -> ToolCallResult:
        """Invoke LLM with MCP tools via AISuite automatic mode.

        AISuite handles the entire tool execution loop automatically
        when max_turns is provided with MCP configuration.

        Args:
            prompt: User prompt/question
            max_turns: Maximum tool call iterations (default 3)

        Returns:
            ToolCallResult with final content and tool call history
        """
        messages = [{"role": "user", "content": prompt}]

        # MCP configuration for HTTP transport
        mcp_config = {
            "type": "mcp",
            "name": "bisq",
            "server_url": self.mcp_url,
        }

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                tools=[mcp_config],
                max_turns=max_turns,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Extract tool calls from intermediate messages if available
            tool_calls_made = []
            iterations = 0
            if hasattr(response.choices[0], "intermediate_messages"):
                for msg in response.choices[0].intermediate_messages:
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        iterations += 1
                        for tc in msg.tool_calls:
                            tool_calls_made.append(
                                {
                                    "tool": tc.function.name,
                                    "args": tc.function.arguments,
                                }
                            )

            return ToolCallResult(
                content=response.choices[0].message.content or "",
                tool_calls_made=tool_calls_made,
                iterations=iterations,
            )

        except Exception as e:
            logger.error(f"Tool invocation failed: {e}")
            return ToolCallResult(
                content=f"Error during tool invocation: {e}",
                tool_calls_made=[],
                iterations=0,
                success=False,
            )


class LLMProvider:
    """Provider for LLM and embeddings initialization in RAG system."""

    def __init__(self, settings: "Settings"):
        """Initialize the LLM provider.

        Args:
            settings: Application settings with API keys and model configuration
        """
        self.settings = settings
        self.embeddings: LiteLLMEmbeddings | None = None
        self.llm: AISuiteLLMWrapper | None = None

        try:
            self.ai_client = ai.Client()
            logger.info("LLM provider initialized with AISuite client")
        except Exception as e:
            logger.exception(f"Failed to initialize AISuite client: {e}")
            raise RuntimeError(f"AISuite initialization failed: {e}") from e

    def _validate_openai_api_key(self) -> None:
        """Validate that OpenAI API key is configured.

        Raises:
            ValueError: If OpenAI API key is not configured
        """
        if not self.settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key is required but not configured.")

    def initialize_embeddings(self) -> LiteLLMEmbeddings:
        """Initialize embeddings using LiteLLM abstraction.

        Returns:
            LiteLLMEmbeddings instance configured from settings

        Raises:
            ValueError: If API key is not configured
        """
        logger.info("Initializing embeddings via LiteLLM...")
        self._validate_openai_api_key()

        self.embeddings = LiteLLMEmbeddings.from_settings(self.settings)
        logger.info("Embeddings initialized via LiteLLM")
        return self.embeddings

    def initialize_llm(
        self, mcp_url: str = "http://localhost:8000/mcp"
    ) -> AISuiteLLMWrapper:
        """Initialize LLM with native MCP support.

        Args:
            mcp_url: URL of the MCP HTTP server

        Returns:
            AISuiteLLMWrapper configured with MCP URL
        """
        logger.info("Initializing LLM with AISuite MCP support...")
        self._validate_openai_api_key()

        self.llm = AISuiteLLMWrapper(
            client=self.ai_client,
            model=self.settings.OPENAI_MODEL,
            max_tokens=self.settings.MAX_TOKENS,
            temperature=self.settings.LLM_TEMPERATURE,
            mcp_url=mcp_url,
        )
        logger.info(f"LLM initialized: {self.settings.OPENAI_MODEL}")
        return self.llm

    def get_embeddings(self) -> LiteLLMEmbeddings | None:
        """Get the initialized embeddings model.

        Returns:
            LiteLLMEmbeddings instance or None if not initialized
        """
        return self.embeddings

    def get_llm(self) -> AISuiteLLMWrapper | None:
        """Get the initialized LLM.

        Returns:
            AISuiteLLMWrapper instance or None if not initialized
        """
        return self.llm
