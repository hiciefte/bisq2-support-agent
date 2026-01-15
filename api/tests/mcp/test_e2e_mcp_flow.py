"""End-to-end tests for complete MCP flow.

These tests verify the full integration from user question
through RAG service to MCP tool execution and response.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestEndToEndMCPFlow:
    """End-to-end tests for complete MCP flow."""

    @pytest.fixture
    def mock_llm_with_tool_calls(self):
        """Create a mock LLM that simulates tool calling."""
        mock_client = MagicMock()

        def create_tool_call_response(tool_name: str, args: str):
            """Create a mock response with a tool call."""
            mock_tool_call = MagicMock()
            mock_tool_call.id = "call_123"
            mock_tool_call.function.name = tool_name
            mock_tool_call.function.arguments = args

            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = None
            mock_response.choices[0].message.tool_calls = [mock_tool_call]
            return mock_response

        def create_final_response(content: str):
            """Create a mock final response without tool calls."""
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = content
            mock_response.choices[0].message.tool_calls = None
            return mock_response

        return mock_client, create_tool_call_response, create_final_response

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_price_question_triggers_tool_call(
        self,
        mock_ai_client,
        mock_openai,
        mock_settings,
        mock_bisq_service,
        mock_llm_with_tool_calls,
    ):
        """User asking about BTC price should trigger get_market_prices tool."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        _, create_tool_call, create_final = mock_llm_with_tool_calls

        # Create MCP server
        mcp_server = create_mcp_server(mock_bisq_service)

        # Setup mock responses: tool call -> final response
        mock_openai.return_value.chat.completions.create.side_effect = [
            create_tool_call("get_market_prices", '{"currency": "EUR"}'),
            create_final("The current BTC price in EUR is 95,000.00"),
        ]

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools from MCP server
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)

        # Invoke with tools
        result = provider.llm.invoke_with_tools(
            "What is the current BTC price in EUR?", openai_tools
        )

        # Verify tool was called
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["tool"] == "get_market_prices"
        assert "EUR" in result.tool_calls_made[0]["args"]
        mock_bisq_service.get_market_prices_formatted.assert_called_once_with("EUR")

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_offer_question_triggers_offerbook_tool(
        self,
        mock_ai_client,
        mock_openai,
        mock_settings,
        mock_bisq_service,
        mock_llm_with_tool_calls,
    ):
        """User asking about offers should trigger get_offerbook tool."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        _, create_tool_call, create_final = mock_llm_with_tool_calls

        # Create MCP server
        mcp_server = create_mcp_server(mock_bisq_service)

        # Setup mock responses
        mock_openai.return_value.chat.completions.create.side_effect = [
            create_tool_call(
                "get_offerbook", '{"currency": "USD", "direction": "BUY"}'
            ),
            create_final("There are 5 BUY offers available for USD."),
        ]

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools from MCP server
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)

        # Invoke with tools
        result = provider.llm.invoke_with_tools(
            "What BUY offers are available for USD?", openai_tools
        )

        # Verify tool was called
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["tool"] == "get_offerbook"
        mock_bisq_service.get_offerbook_formatted.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_reputation_question_triggers_reputation_tool(
        self,
        mock_ai_client,
        mock_openai,
        mock_settings,
        mock_bisq_service,
        mock_llm_with_tool_calls,
    ):
        """User asking about reputation should trigger get_reputation tool."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        _, create_tool_call, create_final = mock_llm_with_tool_calls

        # Create MCP server
        mcp_server = create_mcp_server(mock_bisq_service)

        # Setup mock responses
        mock_openai.return_value.chat.completions.create.side_effect = [
            create_tool_call("get_reputation", '{"profile_id": "user123"}'),
            create_final("The user has a reputation score of 85,000."),
        ]

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools from MCP server
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)

        # Invoke with tools
        result = provider.llm.invoke_with_tools(
            "What is the reputation of user123?", openai_tools
        )

        # Verify tool was called
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["tool"] == "get_reputation"
        mock_bisq_service.get_reputation_formatted.assert_called_once_with("user123")

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_non_live_question_skips_tools(
        self,
        mock_ai_client,
        mock_openai,
        mock_settings,
        mock_bisq_service,
        mock_llm_with_tool_calls,
    ):
        """Questions not needing live data should not use tools."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        _, _, create_final = mock_llm_with_tool_calls

        # Create MCP server
        mcp_server = create_mcp_server(mock_bisq_service)

        # Setup mock to return direct response (no tool calls)
        mock_openai.return_value.chat.completions.create.return_value = create_final(
            "Bisq is a decentralized Bitcoin exchange that allows peer-to-peer trading."
        )

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools from MCP server
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)

        # Invoke with tools
        result = provider.llm.invoke_with_tools("What is Bisq?", openai_tools)

        # Verify no tools were called
        assert result.tool_calls_made == []
        assert result.iterations == 0
        assert "Bisq is a decentralized" in result.content

        # Bisq service should not have been called
        mock_bisq_service.get_market_prices_formatted.assert_not_called()
        mock_bisq_service.get_offerbook_formatted.assert_not_called()
        mock_bisq_service.get_reputation_formatted.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_markets_question_triggers_markets_tool(
        self,
        mock_ai_client,
        mock_openai,
        mock_settings,
        mock_bisq_service,
        mock_llm_with_tool_calls,
    ):
        """User asking about available markets should trigger get_markets tool."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        _, create_tool_call, create_final = mock_llm_with_tool_calls

        # Create MCP server
        mcp_server = create_mcp_server(mock_bisq_service)

        # Setup mock responses
        mock_openai.return_value.chat.completions.create.side_effect = [
            create_tool_call("get_markets", "{}"),
            create_final("Available markets include EUR, USD, CHF, and GBP."),
        ]

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools from MCP server
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)

        # Invoke with tools
        result = provider.llm.invoke_with_tools(
            "What currencies can I trade on Bisq?", openai_tools
        )

        # Verify tool was called
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["tool"] == "get_markets"
        mock_bisq_service.get_markets_formatted.assert_called_once()


class TestMCPToolExecutionFlow:
    """Tests for the tool execution flow within LLM wrapper."""

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_tool_result_included_in_conversation(
        self, mock_ai_client, mock_openai, mock_settings, mock_bisq_service
    ):
        """Tool results should be added to conversation for LLM context."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        # Create MCP server
        mcp_server = create_mcp_server(mock_bisq_service)

        # Track messages sent to LLM
        captured_messages = []

        def capture_messages(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]

            if len(captured_messages) == 1:
                # First call: return tool call
                mock_tool_call = MagicMock()
                mock_tool_call.id = "call_456"
                mock_tool_call.function.name = "get_market_prices"
                mock_tool_call.function.arguments = '{"currency": "EUR"}'
                mock_response.choices[0].message.content = None
                mock_response.choices[0].message.tool_calls = [mock_tool_call]
            else:
                # Second call: return final response
                mock_response.choices[0].message.content = "BTC/EUR is 95,000"
                mock_response.choices[0].message.tool_calls = None

            return mock_response

        mock_openai.return_value.chat.completions.create.side_effect = capture_messages

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools and invoke
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)
        provider.llm.invoke_with_tools("What is BTC price?", openai_tools)

        # Verify second call includes tool result
        assert len(captured_messages) == 2
        second_call_messages = captured_messages[1]

        # Should have: user, assistant (with tool calls), tool result
        assert len(second_call_messages) >= 3
        tool_message = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_message) == 1
        assert "BTC/EUR" in tool_message[0]["content"]

    @pytest.mark.asyncio
    @patch("app.services.rag.llm_provider.OpenAI")
    @patch("app.services.rag.llm_provider.ai.Client")
    async def test_error_in_tool_execution_handled_gracefully(
        self, mock_ai_client, mock_openai, mock_settings, mock_bisq_service_with_errors
    ):
        """Errors during tool execution should be handled gracefully."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from app.services.rag.llm_provider import LLMProvider

        # Create MCP server with error-prone service
        mcp_server = create_mcp_server(mock_bisq_service_with_errors)

        # Setup mock to call tool
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_error"
        mock_tool_call.function.name = "get_market_prices"
        mock_tool_call.function.arguments = "{}"

        mock_response_with_tool = MagicMock()
        mock_response_with_tool.choices = [MagicMock()]
        mock_response_with_tool.choices[0].message.content = None
        mock_response_with_tool.choices[0].message.tool_calls = [mock_tool_call]

        mock_final_response = MagicMock()
        mock_final_response.choices = [MagicMock()]
        mock_final_response.choices[0].message.content = (
            "Unable to get prices due to an error."
        )
        mock_final_response.choices[0].message.tool_calls = None

        mock_openai.return_value.chat.completions.create.side_effect = [
            mock_response_with_tool,
            mock_final_response,
        ]

        # Initialize LLM provider
        provider = LLMProvider(mock_settings)
        provider.initialize_llm()

        # Get tools and invoke
        tools = await mcp_server.list_tools()
        from app.services.rag.llm_provider import convert_mcp_tools_to_openai_format

        openai_tools = convert_mcp_tools_to_openai_format(tools)

        # Should not raise - error handled gracefully
        result = provider.llm.invoke_with_tools("What is BTC price?", openai_tools)

        # Tool call should still be recorded
        assert len(result.tool_calls_made) == 1
        # Error message or unavailable message should be in the result
        result_text = result.tool_calls_made[0]["result"].lower()
        assert "error" in result_text or "unavailable" in result_text


class TestRAGServiceMCPIntegration:
    """Tests for MCP integration within the RAG service."""

    def test_rag_service_has_mcp_initialization_method(self):
        """RAG service should have MCP initialization method."""
        from app.services.simplified_rag_service import SimplifiedRAGService

        assert hasattr(SimplifiedRAGService, "_initialize_mcp_tools")

    def test_rag_service_mcp_server_attribute_exists(self):
        """RAG service should define mcp_server attribute."""
        # Verify the class has the expected attribute structure
        # Check the source code has mcp_server initialization
        import inspect

        from app.services.simplified_rag_service import SimplifiedRAGService

        source = inspect.getsource(SimplifiedRAGService.__init__)
        assert "mcp_server" in source
        assert "mcp_tools" in source

    def test_rag_service_uses_mcp_tools_for_live_data(self):
        """RAG service should use MCP tools when live data is needed."""
        # Verify the query method references MCP tools
        import inspect

        from app.services.simplified_rag_service import SimplifiedRAGService

        source = inspect.getsource(SimplifiedRAGService.query)
        # Should have logic for using MCP tools with live data
        assert "mcp_tools" in source or "invoke_with_tools" in source
