"""Tests for MCP HTTP Server - Written FIRST (TDD Red Phase).

These tests define the expected behavior of the MCP HTTP Server
before the implementation exists.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestMCPHttpServerContract:
    """Test the MCP HTTP server contract - these tests define expected behavior."""

    @pytest.fixture
    def mock_bisq_service(self):
        """Mock Bisq2MCPService for isolated testing."""
        service = MagicMock()
        service.get_market_prices_formatted = AsyncMock(
            return_value="[LIVE MARKET PRICES]\n  BTC/USD: 50,000.00"
        )
        service.get_offerbook_formatted = AsyncMock(
            return_value="[LIVE OFFERBOOK]\n  BUY: 0.1 BTC @ 50,000"
        )
        service.get_reputation_formatted = AsyncMock(
            return_value="[REPUTATION DATA]\n  Total Score: 100"
        )
        service.get_markets_formatted = AsyncMock(
            return_value="[AVAILABLE MARKETS]\n  BTC/USD, BTC/EUR"
        )
        service.get_transaction_formatted = AsyncMock(
            return_value="[TRANSACTION DETAILS]\n  TX ID: abc123\n  Status: CONFIRMED"
        )
        return service

    @pytest.fixture
    def test_client(self, mock_bisq_service):
        """Create test client with mocked service."""
        from app.services.mcp import mcp_http_server
        from app.services.mcp.mcp_http_server import router

        # Inject the mock service
        mcp_http_server.set_bisq_service(mock_bisq_service)

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        yield client

        # Reset service after test
        mcp_http_server.set_bisq_service(None)

    def test_tools_list_returns_all_five_tools(self, test_client):
        """MCP server must expose exactly 5 tools."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "tools" in data["result"]
        assert len(data["result"]["tools"]) == 5

        tool_names = {t["name"] for t in data["result"]["tools"]}
        assert tool_names == {
            "get_market_prices",
            "get_offerbook",
            "get_reputation",
            "get_markets",
            "get_transaction",
        }

    def test_tools_list_includes_input_schemas(self, test_client):
        """Each tool must have a valid inputSchema."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        for tool in response.json()["result"]["tools"]:
            assert "inputSchema" in tool
            assert "type" in tool["inputSchema"]
            assert tool["inputSchema"]["type"] == "object"

    def test_tools_list_includes_descriptions(self, test_client):
        """Each tool must have a description."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        for tool in response.json()["result"]["tools"]:
            assert "description" in tool
            assert len(tool["description"]) > 10

    def test_tool_call_get_market_prices(self, test_client, mock_bisq_service):
        """get_market_prices tool must return price data."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_market_prices",
                    "arguments": {"currency": "USD"},
                },
                "id": 2,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "content" in data["result"]
        assert len(data["result"]["content"]) > 0
        assert data["result"]["content"][0]["type"] == "text"
        mock_bisq_service.get_market_prices_formatted.assert_called_once_with("USD")

    def test_tool_call_get_market_prices_no_currency(
        self, test_client, mock_bisq_service
    ):
        """get_market_prices without currency should pass None."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_market_prices", "arguments": {}},
                "id": 3,
            },
        )

        assert response.status_code == 200
        mock_bisq_service.get_market_prices_formatted.assert_called_once_with(None)

    def test_tool_call_get_offerbook(self, test_client, mock_bisq_service):
        """get_offerbook tool must return offer data."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_offerbook",
                    "arguments": {"currency": "EUR", "direction": "BUY"},
                },
                "id": 4,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        mock_bisq_service.get_offerbook_formatted.assert_called_once_with("EUR", "BUY")

    def test_tool_call_get_offerbook_normalizes_lowercase_arguments(
        self, test_client, mock_bisq_service
    ):
        """get_offerbook should normalize lowercase currency/direction for robust tool calls."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_offerbook",
                    "arguments": {"currency": "usd", "direction": "sell"},
                },
                "id": 4_1,
            },
        )

        assert response.status_code == 200
        mock_bisq_service.get_offerbook_formatted.assert_called_once_with("USD", "SELL")

    def test_tool_call_get_offerbook_accepts_alias_currency_key(
        self, test_client, mock_bisq_service
    ):
        """get_offerbook should accept common alias keys for currency from model tool calls."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_offerbook",
                    "arguments": {"quote_currency": "usd"},
                },
                "id": 4_2,
            },
        )

        assert response.status_code == 200
        mock_bisq_service.get_offerbook_formatted.assert_called_once_with("USD", None)

    def test_tool_call_get_offerbook_accepts_market_pair_alias(
        self, test_client, mock_bisq_service
    ):
        """get_offerbook should resolve quote fiat from market pair aliases."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_offerbook",
                    "arguments": {"market": "BTC/USD"},
                },
                "id": 4_4,
            },
        )

        assert response.status_code == 200
        mock_bisq_service.get_offerbook_formatted.assert_called_once_with("USD", None)

    def test_tool_call_get_offerbook_rejects_btc_currency(
        self, test_client, mock_bisq_service
    ):
        """get_offerbook should reject BTC as a currency argument."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_offerbook",
                    "arguments": {"currency": "BTC"},
                },
                "id": 4_5,
            },
        )

        assert response.status_code == 200
        text = response.json()["result"]["content"][0]["text"].lower()
        assert "currency is required" in text or "fiat" in text
        mock_bisq_service.get_offerbook_formatted.assert_not_called()

    def test_tool_call_get_offerbook_requires_currency(
        self, test_client, mock_bisq_service
    ):
        """get_offerbook should return explicit validation error if currency is missing."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_offerbook",
                    "arguments": {"direction": "BUY"},
                },
                "id": 4_3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        text = data["result"]["content"][0]["text"]
        assert "currency is required" in text.lower()
        mock_bisq_service.get_offerbook_formatted.assert_not_called()

    def test_tool_call_get_reputation_requires_profile_id(self, test_client):
        """get_reputation must require profile_id."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_reputation", "arguments": {}},
                "id": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should return error in content
        text = data["result"]["content"][0]["text"]
        assert "required" in text.lower() or "error" in text.lower()

    def test_tool_call_get_reputation_with_profile_id(
        self, test_client, mock_bisq_service
    ):
        """get_reputation with valid profile_id must call service."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_reputation",
                    "arguments": {"profile_id": "abc123xyz"},
                },
                "id": 6,
            },
        )

        assert response.status_code == 200
        mock_bisq_service.get_reputation_formatted.assert_called_once_with("abc123xyz")

    def test_tool_call_get_markets(self, test_client, mock_bisq_service):
        """get_markets tool must return market list."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_markets", "arguments": {}},
                "id": 7,
            },
        )

        assert response.status_code == 200
        mock_bisq_service.get_markets_formatted.assert_called_once()

    def test_tool_call_get_transaction_requires_tx_id(self, test_client):
        """get_transaction must require tx_id."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_transaction", "arguments": {}},
                "id": 12,
            },
        )

        assert response.status_code == 200
        data = response.json()
        # Should return error in content
        text = data["result"]["content"][0]["text"]
        assert "required" in text.lower() or "error" in text.lower()

    def test_tool_call_get_transaction_with_tx_id(self, test_client, mock_bisq_service):
        """get_transaction with valid tx_id must call service."""
        # Valid Bitcoin transaction ID (64 hex characters)
        valid_tx_id = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "get_transaction",
                    "arguments": {"tx_id": valid_tx_id},
                },
                "id": 13,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "content" in data["result"]
        mock_bisq_service.get_transaction_formatted.assert_called_once_with(valid_tx_id)

    def test_unknown_method_returns_error(self, test_client):
        """Unknown JSON-RPC method must return error code -32601."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "unknown/method", "id": 8},
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32601

    def test_missing_tool_name_returns_error(self, test_client):
        """tools/call without tool name must return error code -32602."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"arguments": {}},
                "id": 9,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602

    def test_unknown_tool_returns_error_message(self, test_client):
        """Calling unknown tool must return error in content."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "nonexistent_tool", "arguments": {}},
                "id": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "Unknown tool" in data["result"]["content"][0]["text"]

    def test_jsonrpc_response_format(self, test_client):
        """All responses must follow JSON-RPC 2.0 format."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 11},
        )

        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 11
        assert "result" in data or "error" in data

    def test_jsonrpc_request_without_id(self, test_client):
        """Request without id should still work (notification style)."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data

    def test_tools_call_preserves_request_id(self, test_client, mock_bisq_service):
        """Response id must match request id."""
        response = test_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_markets", "arguments": {}},
                "id": "custom-id-123",
            },
        )

        data = response.json()
        assert data["id"] == "custom-id-123"


class TestMCPToolSchemas:
    """Test that tool schemas are correctly defined."""

    @pytest.fixture
    def test_client(self):
        """Create test client without mocking to check static schemas."""
        from app.services.mcp import mcp_http_server
        from app.services.mcp.mcp_http_server import router

        # Inject mock service (not used for schema tests)
        mcp_http_server.set_bisq_service(MagicMock())

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        yield client

        # Reset service after test
        mcp_http_server.set_bisq_service(None)

    def test_get_market_prices_schema(self, test_client):
        """get_market_prices schema should have optional currency parameter."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        tools = {t["name"]: t for t in response.json()["result"]["tools"]}
        schema = tools["get_market_prices"]["inputSchema"]

        assert "currency" in schema.get("properties", {})
        # Currency should NOT be required
        assert "currency" not in schema.get("required", [])

    def test_get_offerbook_schema(self, test_client):
        """get_offerbook schema should have currency and direction parameters."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        tools = {t["name"]: t for t in response.json()["result"]["tools"]}
        schema = tools["get_offerbook"]["inputSchema"]

        assert "currency" in schema.get("properties", {})
        assert "direction" in schema.get("properties", {})
        assert "currency" in schema.get("required", [])

    def test_get_reputation_schema(self, test_client):
        """get_reputation schema should require profile_id parameter."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        tools = {t["name"]: t for t in response.json()["result"]["tools"]}
        schema = tools["get_reputation"]["inputSchema"]

        assert "profile_id" in schema.get("properties", {})
        assert "profile_id" in schema.get("required", [])

    def test_get_markets_schema(self, test_client):
        """get_markets schema should have no required parameters."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        tools = {t["name"]: t for t in response.json()["result"]["tools"]}
        schema = tools["get_markets"]["inputSchema"]

        assert schema.get("required", []) == []

    def test_get_transaction_schema(self, test_client):
        """get_transaction schema should require tx_id parameter."""
        response = test_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )

        tools = {t["name"]: t for t in response.json()["result"]["tools"]}
        schema = tools["get_transaction"]["inputSchema"]

        assert "tx_id" in schema.get("properties", {})
        assert "tx_id" in schema.get("required", [])
