"""Tests for AISuite MCP tool integration.

These tests follow TDD - they are written BEFORE the implementation
to define expected behavior for LLM tool calling with MCP.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestAISuiteMCPIntegration:
    """Tests for AISuite MCP tool integration."""

    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    def test_llm_wrapper_has_invoke_with_tools_method(
        self, mock_ai_client, mock_openai, mock_settings
    ):
        """LLM wrapper should have invoke_with_tools method for tool calling."""
        from app.services.rag.llm_provider import LLMProvider

        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Should have method for tool-enabled invocation
        assert hasattr(provider.llm, "invoke_with_tools")

    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    def test_invoke_with_tools_returns_tool_call_result(
        self, mock_ai_client, mock_openai, mock_settings
    ):
        """invoke_with_tools should return ToolCallResult dataclass."""
        from app.services.rag.llm_provider import LLMProvider, ToolCallResult

        # Setup mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response"
        mock_response.choices[0].message.tool_calls = None
        mock_openai.return_value.chat.completions.create.return_value = mock_response

        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_market_prices",
                    "description": "Get BTC prices",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        result = provider.llm.invoke_with_tools("What is the BTC price?", tools)

        assert isinstance(result, ToolCallResult)
        assert hasattr(result, "content")
        assert hasattr(result, "tool_calls_made")
        assert hasattr(result, "iterations")

    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    def test_tool_call_triggers_mcp_execution(
        self, mock_ai_client, mock_openai, mock_settings, mock_bisq_service
    ):
        """When LLM calls a tool, MCP server should execute it."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        # Create MCP server first (sets up global instance)
        create_mcp_server(mock_bisq_service)

        # Create mock tool call response
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "get_market_prices"
        mock_tool_call.function.arguments = '{"currency": "EUR"}'

        # First response: LLM wants to call a tool
        mock_response_with_tool = MagicMock()
        mock_response_with_tool.choices = [MagicMock()]
        mock_response_with_tool.choices[0].message.content = None
        mock_response_with_tool.choices[0].message.tool_calls = [mock_tool_call]

        # Second response: LLM provides final answer
        mock_final_response = MagicMock()
        mock_final_response.choices = [MagicMock()]
        mock_final_response.choices[0].message.content = "BTC/EUR is 95,000.00"
        mock_final_response.choices[0].message.tool_calls = None

        mock_openai.return_value.chat.completions.create.side_effect = [
            mock_response_with_tool,
            mock_final_response,
        ]

        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_market_prices",
                    "description": "Get BTC prices",
                    "parameters": {
                        "type": "object",
                        "properties": {"currency": {"type": "string"}},
                    },
                },
            }
        ]

        result = provider.llm.invoke_with_tools("What is BTC price in EUR?", tools)

        # Verify tool was called
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["tool"] == "get_market_prices"
        mock_bisq_service.get_market_prices_formatted.assert_called_once_with("EUR")

    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    def test_max_turns_limits_tool_iterations(
        self, mock_ai_client, mock_openai, mock_settings, mock_bisq_service
    ):
        """Should respect max_turns parameter for tool call loops."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        # Create MCP server for tool execution
        create_mcp_server(mock_bisq_service)

        # Create mock that always wants to call tools (infinite loop scenario)
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "get_market_prices"
        mock_tool_call.function.arguments = "{}"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Still need more data"
        mock_response.choices[0].message.tool_calls = [mock_tool_call]

        mock_openai.return_value.chat.completions.create.return_value = mock_response

        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_market_prices",
                    "description": "Get BTC prices",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        result = provider.llm.invoke_with_tools(
            "What is BTC price?", tools, max_turns=2
        )

        # Should stop after max_turns iterations
        assert result.iterations <= 2
        # Should have made at most max_turns tool calls
        assert len(result.tool_calls_made) <= 2

    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    def test_no_tool_calls_returns_direct_response(
        self, mock_ai_client, mock_openai, mock_settings
    ):
        """When LLM doesn't call tools, should return direct response."""
        from app.services.rag.llm_provider import LLMProvider

        # Mock response without tool calls
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I don't need any tools for this."
        mock_response.choices[0].message.tool_calls = None

        mock_openai.return_value.chat.completions.create.return_value = mock_response

        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_market_prices",
                    "description": "Get BTC prices",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        result = provider.llm.invoke_with_tools("What is Bisq?", tools)

        assert result.content == "I don't need any tools for this."
        assert result.tool_calls_made == []
        assert result.iterations == 0


class TestToolCallResult:
    """Tests for ToolCallResult dataclass."""

    def test_tool_call_result_exists(self):
        """ToolCallResult should be importable from llm_provider."""
        from app.services.rag.llm_provider import ToolCallResult

        result = ToolCallResult(
            content="Test content", tool_calls_made=[{"tool": "test"}], iterations=1
        )

        assert result.content == "Test content"
        assert result.tool_calls_made == [{"tool": "test"}]
        assert result.iterations == 1


class TestToolSchemaValidation:
    """Tests for MCP tool schema compliance."""

    @pytest.mark.asyncio
    async def test_tool_schemas_are_valid_json_schema(self, mock_bisq_service):
        """All tool input schemas should be valid JSON Schema."""
        import jsonschema
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()

        for tool in tools:
            # Should not raise - validates schema is well-formed
            jsonschema.Draft7Validator.check_schema(tool.inputSchema)

    @pytest.mark.asyncio
    async def test_required_fields_documented(self, mock_bisq_service):
        """Required fields should be in the required array."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()
        reputation_tool = next(t for t in tools if t.name == "get_reputation")

        # profile_id is required
        assert "profile_id" in reputation_tool.inputSchema.get("required", [])


class TestMCPToolDefinitionConversion:
    """Tests for converting MCP tools to OpenAI function format."""

    @pytest.mark.asyncio
    async def test_convert_mcp_tools_to_openai_format(self, mock_bisq_service):
        """Should convert MCP tools to OpenAI function calling format."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        server = create_mcp_server(mock_bisq_service)
        mcp_tools = await server.list_tools()

        openai_tools = convert_mcp_tools_to_openai_format(mcp_tools)

        assert len(openai_tools) == 4  # 4 Bisq tools
        for tool in openai_tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    @pytest.mark.asyncio
    async def test_converted_tools_have_correct_names(self, mock_bisq_service):
        """Converted tools should have correct names."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        server = create_mcp_server(mock_bisq_service)
        mcp_tools = await server.list_tools()

        openai_tools = convert_mcp_tools_to_openai_format(mcp_tools)
        tool_names = [t["function"]["name"] for t in openai_tools]

        assert "get_market_prices" in tool_names
        assert "get_offerbook" in tool_names
        assert "get_reputation" in tool_names
        assert "get_markets" in tool_names
