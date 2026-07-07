"""LLM Provider using AISuite with direct HTTP MCP support.

This module provides:
- LLM client using AISuite for unified interface
- Direct HTTP MCP tool calling (bypasses uvloop/nest_asyncio incompatibility)
- Embeddings via OpenAI provider
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aisuite as ai  # type: ignore[import-untyped]
import httpx
from app.core.config import get_settings
from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider
from app.utils.instrumentation import track_tokens_and_cost

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


def _parse_tool_content(content: str) -> str:
    """Parse tool result content, handling JSON-encoded strings.

    AISuite may return tool content as a JSON-encoded string (with quotes
    and escaped characters). This function detects and parses such strings
    to return the raw content that parsers expect.

    Args:
        content: Tool result content (may be JSON-encoded)

    Returns:
        Parsed content string
    """
    if not content:
        return content

    # Detect JSON-encoded string: starts and ends with quotes
    if content.startswith('"') and content.endswith('"'):
        try:
            parsed = json.loads(content)
            if isinstance(parsed, str):
                return parsed
        except json.JSONDecodeError:
            pass  # Not valid JSON, return as-is

    return content


# OpenAI reasoning-model families reject `max_tokens` (they require
# `max_completion_tokens`) and only support the default temperature.
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _completion_params(
    model_id: str, temperature: float, max_tokens: int
) -> dict[str, Any]:
    """Build per-model kwargs for chat.completions.create.

    AISuite passes kwargs verbatim to the provider, so reasoning-class
    OpenAI models (o1/o3/o4/gpt-5 families) need `max_completion_tokens`
    instead of `max_tokens` and must not receive a non-default temperature.

    Args:
        model_id: Model identifier, optionally with provider prefix
            (e.g. "openai:o4-mini", "xai:grok-3")
        temperature: Configured sampling temperature
        max_tokens: Configured completion token budget

    Returns:
        Keyword arguments adapted to the model family
    """
    model_name = model_id.rpartition(":")[2]
    if model_name.startswith(_REASONING_MODEL_PREFIXES):
        return {"max_completion_tokens": max_tokens}
    return {"temperature": temperature, "max_tokens": max_tokens}


def _build_messages(prompt: str, system_content: str | None) -> list[dict[str, str]]:
    """Build the chat message list, keeping guardrails at system trust level.

    Args:
        prompt: User-level content (the question)
        system_content: Optional system-level content (persona, guardrails,
            chat history, retrieved context)

    Returns:
        Chat messages for chat.completions.create
    """
    messages: list[dict[str, str]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


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


def needs_live_data(query: str) -> bool:
    """Detect if query might benefit from live Bisq 2 data.

    Args:
        query: User query text

    Returns:
        True if query likely needs live data
    """
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in LIVE_DATA_KEYWORDS)


def _needs_live_data(query: str) -> bool:
    """Backward-compatible alias for older imports."""
    return needs_live_data(query)


def _usage_to_dict(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None

    def usage_value(key: str) -> Any:
        return usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)

    def token_count(value: Any, default: int = 0) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    prompt_tokens = token_count(usage_value("prompt_tokens"))
    completion_tokens = token_count(usage_value("completion_tokens"))
    total_tokens = token_count(
        usage_value("total_tokens"),
        default=prompt_tokens + completion_tokens,
    )
    usage_dict = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
    if usage_dict["total_tokens"] <= 0:
        return None
    return usage_dict


def _track_usage(usage: dict[str, int]) -> None:
    try:
        settings = get_settings()
        track_tokens_and_cost(
            input_tokens=usage["prompt_tokens"],
            output_tokens=usage["completion_tokens"],
            input_cost_per_token=settings.OPENAI_INPUT_COST_PER_TOKEN,
            output_cost_per_token=settings.OPENAI_OUTPUT_COST_PER_TOKEN,
        )
    except Exception:
        logger.warning("Failed to track streamed LLM token usage", exc_info=True)


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

    def invoke(self, prompt: str, system_content: str | None = None) -> LLMResponse:
        """Invoke LLM without tools.

        Args:
            prompt: User-level prompt text (the question)
            system_content: Optional system-level content (persona,
                guardrails, chat history, retrieved context)

        Returns:
            LLMResponse with content and optional usage statistics

        Raises:
            RuntimeError: If LLM invocation fails
        """
        messages = _build_messages(prompt, system_content)

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                **_completion_params(self.model_id, self.temperature, self.max_tokens),
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

    def stream(
        self,
        prompt: str,
        system_content: str | None = None,
    ) -> Iterator[str]:
        """Stream LLM text chunks without tools.

        Args:
            prompt: User-level prompt text (the question)
            system_content: Optional system-level content

        Yields:
            Text deltas from the provider as they arrive.

        Raises:
            RuntimeError: If LLM streaming fails before completion
        """
        messages = _build_messages(prompt, system_content)

        try:
            stream_kwargs = {
                "model": self.model_id,
                "messages": messages,
                "stream": True,
                **_completion_params(self.model_id, self.temperature, self.max_tokens),
            }
            if self.model_id.startswith("openai:"):
                stream_kwargs["stream_options"] = {"include_usage": True}
            response_stream = self.client.chat.completions.create(**stream_kwargs)

            usage: dict[str, int] | None = None
            for chunk in response_stream:
                chunk_usage = _usage_to_dict(getattr(chunk, "usage", None))
                if chunk_usage is not None:
                    usage = chunk_usage
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None)
                if isinstance(content, str) and content:
                    yield content
            if usage is not None:
                _track_usage(usage)
        except Exception as e:
            logger.exception(f"LLM streaming failed: {e}")
            raise RuntimeError(f"Failed to stream LLM response: {e}") from e

    def invoke_with_tools(
        self,
        prompt: str,
        max_turns: int = 3,
        system_content: str | None = None,
    ) -> ToolCallResult:
        """Invoke LLM with MCP tools via AISuite automatic mode.

        AISuite handles the entire tool execution loop automatically
        when max_turns is provided with MCP configuration.

        Args:
            prompt: User prompt/question
            max_turns: Maximum tool call iterations (default 3)
            system_content: Optional system-level content (persona,
                guardrails, chat history, retrieved context)

        Returns:
            ToolCallResult with final content and tool call history
        """
        messages = _build_messages(prompt, system_content)

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
                **_completion_params(self.model_id, self.temperature, self.max_tokens),
            )

            # Extract tool calls AND their results from intermediate messages
            tool_calls_made: list[dict[str, Any]] = []
            tool_results: dict[str, str] = {}  # Map tool_call_id -> result
            iterations = 0

            if hasattr(response.choices[0], "intermediate_messages"):
                # First pass: collect all tool results
                for msg in response.choices[0].intermediate_messages:
                    # Check for tool result messages - can be dict or object
                    if isinstance(msg, dict):
                        # AISuite returns tool results as dicts
                        if msg.get("role") == "tool":
                            tool_call_id = msg.get("tool_call_id")
                            content = msg.get("content", "")
                            if tool_call_id and content:
                                # Parse JSON-encoded content if needed
                                tool_results[tool_call_id] = _parse_tool_content(
                                    content
                                )
                    else:
                        # OpenAI SDK style message objects
                        if getattr(msg, "role", None) == "tool":
                            tool_call_id = getattr(msg, "tool_call_id", None)
                            content = getattr(msg, "content", "")
                            if tool_call_id and content:
                                # Parse JSON-encoded content if needed
                                tool_results[tool_call_id] = _parse_tool_content(
                                    content
                                )

                # Second pass: collect tool calls and match with results
                for msg in response.choices[0].intermediate_messages:
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        iterations += 1
                        for tc in msg.tool_calls:
                            tool_call_id = getattr(tc, "id", None)
                            result = (
                                tool_results.get(tool_call_id, "")
                                if tool_call_id
                                else ""
                            )
                            tool_calls_made.append(
                                {
                                    "tool": tc.function.name,
                                    "args": tc.function.arguments,
                                    "result": result,
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
        self.embeddings: OpenAIEmbeddingsProvider | None = None
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

    def initialize_embeddings(self) -> OpenAIEmbeddingsProvider:
        """Initialize embeddings using the OpenAI provider.

        Returns:
            OpenAIEmbeddingsProvider instance configured from settings

        Raises:
            ValueError: If API key is not configured
        """
        logger.info("Initializing OpenAI embeddings...")
        self._validate_openai_api_key()

        self.embeddings = OpenAIEmbeddingsProvider.from_settings(self.settings)
        logger.info("OpenAI embeddings initialized")
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

    def get_embeddings(self) -> OpenAIEmbeddingsProvider | None:
        """Get the initialized embeddings model.

        Returns:
            OpenAIEmbeddingsProvider instance or None if not initialized
        """
        return self.embeddings

    def get_llm(self) -> AISuiteLLMWrapper | None:
        """Get the initialized LLM.

        Returns:
            AISuiteLLMWrapper instance or None if not initialized
        """
        return self.llm
