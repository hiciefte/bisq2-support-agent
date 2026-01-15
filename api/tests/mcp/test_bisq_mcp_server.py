"""Unit tests for Bisq MCP server tools.

These tests follow TDD - they are written BEFORE the implementation
to define expected behavior.
"""

import pytest


class TestBisqMCPServerTools:
    """Unit tests for Bisq MCP server tools."""

    @pytest.mark.asyncio
    async def test_get_market_prices_tool_exists(self, mock_bisq_service):
        """Tool should be registered with correct name."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]

        assert "get_market_prices" in tool_names

    @pytest.mark.asyncio
    async def test_get_market_prices_returns_formatted_string(self, mock_bisq_service):
        """Tool should return formatted price data."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        content_list, _ = await server.call_tool(
            "get_market_prices", {"currency": "EUR"}
        )

        assert "BTC/EUR" in content_list[0].text
        mock_bisq_service.get_market_prices_formatted.assert_called_once_with("EUR")

    @pytest.mark.asyncio
    async def test_get_market_prices_no_currency(self, mock_bisq_service):
        """Tool should work without currency parameter."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        content_list, _ = await server.call_tool("get_market_prices", {})

        assert "BTC" in content_list[0].text
        mock_bisq_service.get_market_prices_formatted.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_get_offerbook_tool_exists(self, mock_bisq_service):
        """Offerbook tool should be registered."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]

        assert "get_offerbook" in tool_names

    @pytest.mark.asyncio
    async def test_get_offerbook_returns_offers(self, mock_bisq_service):
        """Offerbook tool should return offer data."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        content_list, _ = await server.call_tool(
            "get_offerbook", {"currency": "EUR", "direction": "BUY"}
        )

        assert "BUY" in content_list[0].text or "offers" in content_list[0].text
        mock_bisq_service.get_offerbook_formatted.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_reputation_tool_exists(self, mock_bisq_service):
        """Reputation tool should be registered."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]

        assert "get_reputation" in tool_names

    @pytest.mark.asyncio
    async def test_get_reputation_requires_profile_id(self, mock_bisq_service):
        """Reputation tool should require profile_id parameter."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()
        reputation_tool = next(t for t in tools if t.name == "get_reputation")

        # Check the inputSchema has profile_id as required
        assert "profile_id" in reputation_tool.inputSchema.get("required", [])

    @pytest.mark.asyncio
    async def test_get_reputation_returns_score(self, mock_bisq_service):
        """Reputation tool should return score data."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        content_list, _ = await server.call_tool(
            "get_reputation", {"profile_id": "abc123"}
        )

        assert "Reputation" in content_list[0].text or "Score" in content_list[0].text
        mock_bisq_service.get_reputation_formatted.assert_called_once_with("abc123")

    @pytest.mark.asyncio
    async def test_get_markets_tool_exists(self, mock_bisq_service):
        """Markets tool should be registered."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()
        tool_names = [t.name for t in tools]

        assert "get_markets" in tool_names

    @pytest.mark.asyncio
    async def test_get_markets_returns_list(self, mock_bisq_service):
        """Markets tool should return market list."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        content_list, _ = await server.call_tool("get_markets", {})

        assert "EUR" in content_list[0].text or "Markets" in content_list[0].text
        mock_bisq_service.get_markets_formatted.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_descriptions_are_clear(self, mock_bisq_service):
        """Each tool should have a descriptive docstring."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service)
        tools = await server.list_tools()

        for tool in tools:
            # Description should be meaningful (more than 20 chars)
            assert len(tool.description) > 20, f"Tool {tool.name} has short description"
            # Description should mention Bisq or BTC
            assert (
                "Bisq" in tool.description
                or "BTC" in tool.description
                or "Bitcoin" in tool.description
            ), f"Tool {tool.name} description doesn't mention Bisq/BTC"


class TestMCPServerSecurity:
    """Security tests for MCP server."""

    @pytest.mark.asyncio
    async def test_error_handling_graceful(self, mock_bisq_service_with_errors):
        """Should handle API errors gracefully without exposing internals."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server

        server = create_mcp_server(mock_bisq_service_with_errors)

        # Should not raise, should return error message
        content_list, _ = await server.call_tool("get_market_prices", {})

        # Error should be sanitized - no stack traces or internal details
        text = content_list[0].text
        assert "Error" in text or "error" in text or "unavailable" in text.lower()
        # Should not contain Python exception details
        assert "Traceback" not in text
        assert 'File "' not in text


class TestMCPServerFactory:
    """Tests for MCP server factory function."""

    def test_create_mcp_server_returns_server(self, mock_bisq_service):
        """create_mcp_server should return a FastMCP instance."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server
        from mcp.server.fastmcp import FastMCP

        server = create_mcp_server(mock_bisq_service)

        assert isinstance(server, FastMCP)

    def test_get_mcp_server_after_create(self, mock_bisq_service):
        """get_mcp_server should return the same server after creation."""
        from app.services.mcp.bisq_mcp_server import create_mcp_server, get_mcp_server

        server = create_mcp_server(mock_bisq_service)
        retrieved = get_mcp_server()

        assert server is retrieved

    def test_get_mcp_server_before_create_raises(self):
        """get_mcp_server should raise if called before create."""
        from app.services.mcp import bisq_mcp_server

        # Reset global state for this test (class-based implementation)
        bisq_mcp_server._mcp_server_instance = None

        with pytest.raises(RuntimeError, match="MCP server not initialized"):
            bisq_mcp_server.get_mcp_server()
