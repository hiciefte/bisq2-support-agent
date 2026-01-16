"""LLM Provider using AISuite with direct HTTP MCP support.

This module provides:
- LLM client using AISuite for unified interface
- Direct HTTP MCP tool calling (bypasses uvloop/nest_asyncio incompatibility)
- Embeddings via LiteLLM abstraction
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aisuite as ai  # type: ignore[import-untyped]
import httpx
from app.services.rag.embeddings_provider import LiteLLMEmbeddings

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

# Keywords that indicate live data might be helpful
LIVE_DATA_KEYWORDS = [
    # Offerbook related
    "offer",
    "offers",
    "offerbook",
    "buy",
    "sell",
    "buying",
    "selling",
    "trade",
    "trading",
    # Currency mentions
    "usd",
    "eur",
    "gbp",
    "chf",
    "cad",
    "aud",
    "dollar",
    "euro",
    "pound",
    "franc",
    # Price related
    "price",
    "prices",
    "btc price",
    "bitcoin price",
    "market",
    # Reputation related
    "reputation",
    "score",
    "rating",
    "trust",
]


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


class MCPHttpClient:
    """Direct HTTP client for MCP server (bypasses uvloop/nest_asyncio incompatibility).

    AISuite's native MCP support uses nest_asyncio which is incompatible with uvloop
    (used by FastAPI). This client makes direct HTTP calls to the MCP server.
    """

    def __init__(self, base_url: str = "http://localhost:8000/mcp"):
        """Initialize the MCP HTTP client.

        Args:
            base_url: URL of the MCP HTTP server
        """
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=30.0)

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call an MCP tool directly via HTTP.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            String result from the tool
        """
        try:
            response = await self._client.post(
                self.base_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                    "id": 1,
                },
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data and data["error"]:
                return f"Error: {data['error'].get('message', 'Unknown error')}"

            if "result" in data and "content" in data["result"]:
                content = data["result"]["content"]
                if content and isinstance(content, list) and len(content) > 0:
                    return content[0].get("text", "")
            return ""
        except httpx.HTTPError as e:
            logger.error(f"MCP HTTP call failed: {e}")
            return f"Error calling MCP tool: {e}"
        except Exception as e:
            logger.error(f"MCP tool call failed: {e}")
            return f"Error: {e}"

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


def _detect_currency(query: str) -> str | None:
    """Detect currency code from query text.

    Args:
        query: User query text

    Returns:
        Currency code (e.g., 'USD', 'EUR') or None if not detected
    """
    query_lower = query.lower()

    # Direct currency code mentions
    currency_codes = {
        "usd": "USD",
        "eur": "EUR",
        "gbp": "GBP",
        "chf": "CHF",
        "cad": "CAD",
        "aud": "AUD",
        "brl": "BRL",
        "jpy": "JPY",
    }

    # Currency name to code mapping
    currency_names = {
        "dollar": "USD",
        "dollars": "USD",
        "euro": "EUR",
        "euros": "EUR",
        "pound": "GBP",
        "pounds": "GBP",
        "franc": "CHF",
        "francs": "CHF",
    }

    # Check for explicit codes
    for code, result in currency_codes.items():
        if code in query_lower:
            return result

    # Check for currency names
    for name, result in currency_names.items():
        if name in query_lower:
            return result

    return None


def _needs_live_data(query: str) -> bool:
    """Detect if query might benefit from live Bisq 2 data.

    Args:
        query: User query text

    Returns:
        True if query likely needs live data
    """
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in LIVE_DATA_KEYWORDS)


class AISuiteLLMWrapper:
    """LLM wrapper using AISuite with direct HTTP MCP support.

    Uses direct HTTP calls to MCP server (bypasses uvloop/nest_asyncio incompatibility).
    """

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
        self.mcp_client = MCPHttpClient(mcp_url)

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
