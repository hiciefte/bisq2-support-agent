"""MCP HTTP Server - JSON-RPC 2.0 over HTTP for AISuite integration.

This module provides an HTTP-based MCP server endpoint that can be used
by AISuite's native MCP support with HTTP transport. It exposes Bisq 2
data tools via the standard MCP JSON-RPC 2.0 protocol.
"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# Singleton service instance
_bisq_service = None


def get_bisq_service():
    """Get or create the Bisq MCP service singleton.

    Returns:
        Bisq2MCPService instance
    """
    global _bisq_service
    if _bisq_service is None:
        from app.core.config import get_settings
        from app.services.bisq_mcp_service import Bisq2MCPService

        settings = get_settings()
        _bisq_service = Bisq2MCPService(settings)
        logger.info("Bisq2MCPService initialized for MCP HTTP server")
    return _bisq_service


def set_bisq_service(service):
    """Set the Bisq service (for testing).

    Args:
        service: Bisq2MCPService instance or mock
    """
    global _bisq_service
    _bisq_service = service


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request format."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] | None = None
    id: int | str | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response format."""

    jsonrpc: str = "2.0"
    result: Any = None
    error: dict[str, Any] | None = None
    id: int | str | None = None


# Tool definitions following MCP protocol
TOOL_DEFINITIONS = [
    {
        "name": "get_market_prices",
        "description": "Get current Bitcoin market prices from the Bisq 2 network. Returns real-time BTC prices in various fiat currencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "currency": {
                    "type": "string",
                    "description": "Optional 3-letter currency code (e.g., EUR, USD, CHF). If not specified, returns all available prices.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_offerbook",
        "description": "Get current buy/sell offers from the Bisq 2 offerbook. Returns active trading offers on the Bisq 2 network. Use direction='SELL' to find offers where user can BUY BTC, use direction='BUY' to find offers where user can SELL BTC.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "currency": {
                    "type": "string",
                    "description": "3-letter currency code to filter offers (e.g., EUR, USD).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["BUY", "SELL"],
                    "description": "Filter by maker's direction. 'SELL' = user can BUY BTC, 'BUY' = user can SELL BTC.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_reputation",
        "description": "Get reputation score for a Bisq 2 user profile. Returns the reputation score, star rating, and profile age.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_id": {
                    "type": "string",
                    "description": "The unique identifier of the Bisq 2 user profile.",
                }
            },
            "required": ["profile_id"],
        },
    },
    {
        "name": "get_markets",
        "description": "Get list of available trading markets on Bisq 2. Returns all currency markets available for trading.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


@router.post("")
async def handle_jsonrpc(request: JsonRpcRequest) -> JsonRpcResponse:
    """Handle JSON-RPC 2.0 requests for MCP protocol.

    Supports the following methods:
    - tools/list: Return list of available tools
    - tools/call: Execute a tool with given arguments

    Args:
        request: JSON-RPC 2.0 request

    Returns:
        JSON-RPC 2.0 response with result or error
    """
    try:
        if request.method == "tools/list":
            return JsonRpcResponse(
                id=request.id,
                result={"tools": TOOL_DEFINITIONS},
            )

        elif request.method == "tools/call":
            params = request.params or {}
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if not tool_name:
                return JsonRpcResponse(
                    id=request.id,
                    error={"code": -32602, "message": "Missing tool name in params"},
                )

            result = await _execute_tool(tool_name, tool_args)
            return JsonRpcResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": result}]},
            )

        else:
            return JsonRpcResponse(
                id=request.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {request.method}",
                },
            )

    except Exception as e:
        logger.exception(f"MCP request failed: {e}")
        return JsonRpcResponse(
            id=request.id,
            error={"code": -32603, "message": f"Internal error: {str(e)}"},
        )


async def _execute_tool(name: str, args: dict) -> str:
    """Execute an MCP tool and return the result.

    Args:
        name: Tool name to execute
        args: Tool arguments

    Returns:
        String result from the tool execution
    """
    service = get_bisq_service()

    if name == "get_market_prices":
        currency = args.get("currency")
        return await service.get_market_prices_formatted(currency)

    elif name == "get_offerbook":
        currency = args.get("currency")
        direction = args.get("direction")
        return await service.get_offerbook_formatted(currency, direction)

    elif name == "get_reputation":
        profile_id = args.get("profile_id")
        if not profile_id:
            return "Error: profile_id is required for get_reputation tool"
        return await service.get_reputation_formatted(profile_id)

    elif name == "get_markets":
        return await service.get_markets_formatted()

    else:
        return f"Unknown tool: {name}"
