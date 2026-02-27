"""MCP HTTP Server - JSON-RPC 2.0 over HTTP for AISuite integration.

This module provides an HTTP-based MCP server endpoint that can be used
by AISuite's native MCP support with HTTP transport. It exposes Bisq 2
data tools via the standard MCP JSON-RPC 2.0 protocol.
"""

import logging
import re
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


def make_json_rpc_response(
    id: int | str | None,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a JSON-RPC 2.0 response dict.

    Important: Only includes 'error' field when error is not None.
    AISuite MCP client breaks if "error": null is present (tries to call .get() on None).

    Args:
        id: Request ID to echo back
        result: Successful result data
        error: Error object (only included if not None)

    Returns:
        JSON-RPC 2.0 compliant response dict
    """
    response: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": id,
    }
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    return response


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
        "description": """Get current buy/sell offers from the Bisq 2 offerbook.

IMPORTANT - Currency parameter:
- Use FIAT currency codes (EUR, USD, GBP, CHF, etc.), NOT "BTC"
- Common payment method → currency mappings:
  * Faster Payments, UK Bank Transfer → GBP
  * SEPA, SEPA Instant → EUR
  * Zelle, ACH, Cash App, Venmo, Strike → USD
  * Revolut → EUR, USD, or GBP (check user's context)
  * TWINT → CHF
  * Bizum → EUR

Understanding the response:
- 'total_count' = ALL offers for this currency (e.g., 56 EUR offers total)
- 'filtered_count' = subset matching direction filter (e.g., 14 offers user can buy from)
- When user asks "how many offers?" → ALWAYS report the TOTAL count
- When user asks "how many offers to buy from?" → report the filtered count for that direction

Direction filter (from MAKER's perspective):
- direction='SELL' = offers where user can BUY BTC (makers are selling)
- direction='BUY' = offers where user can SELL BTC (makers are buying)
- Omit direction to get ALL offers for the currency

Example: If there are 56 EUR offers total (42 sell-to, 14 buy-from):
- User asks "Are there EUR offers?" → Answer: "Yes, 56 EUR offers are available"
- User asks "Can I buy BTC with EUR?" → Answer: "Yes, 14 offers to buy BTC from"
- User says "I see no offers" → Check total_count first, troubleshoot if > 0""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "currency": {
                    "type": "string",
                    "description": "3-letter FIAT currency code (EUR, USD, GBP, CHF, etc.). NOT 'BTC'. REQUIRED for useful results.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["BUY", "SELL"],
                    "description": "Optional: Filter by direction. SELL=user buys BTC, BUY=user sells BTC. Omit to get ALL offers.",
                },
            },
            "required": ["currency"],
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
    {
        "name": "get_transaction",
        "description": """Look up a Bitcoin transaction using Bisq 2's block explorer integration.

Use this tool when users ask about:
- Transaction confirmation status
- Whether a payment was received/confirmed
- Transaction details (outputs, amounts)
- Troubleshooting trade payment issues

Returns:
- Transaction ID
- Confirmation status (confirmed/unconfirmed)
- Output addresses and amounts
- Total output value in BTC and satoshis

Note: This queries Bisq 2's configured block explorer. The transaction must be broadcast to the Bitcoin network to be found.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tx_id": {
                    "type": "string",
                    "description": "Bitcoin transaction ID (txid) - 64 hexadecimal characters",
                }
            },
            "required": ["tx_id"],
        },
    },
]


# Server capabilities for MCP protocol
SERVER_INFO = {
    "name": "bisq2-mcp-server",
    "version": "1.0.0",
}

SERVER_CAPABILITIES: dict[str, Any] = {
    "tools": {},  # We support tools
}


@router.post("")
async def handle_jsonrpc(request: JsonRpcRequest) -> dict[str, Any]:
    """Handle JSON-RPC 2.0 requests for MCP protocol.

    Supports the following methods:
    - initialize: Initialize the MCP session (required first)
    - notifications/initialized: Client confirms initialization complete
    - tools/list: Return list of available tools
    - tools/call: Execute a tool with given arguments

    Args:
        request: JSON-RPC 2.0 request

    Returns:
        JSON-RPC 2.0 response dict (excludes 'error' field when no error)
    """
    try:
        # MCP Protocol: initialize handshake (required first)
        if request.method == "initialize":
            params = request.params or {}
            client_version = params.get("protocolVersion", "2024-11-05")
            logger.info(
                f"MCP initialize from client (version: {client_version}): "
                f"{params.get('clientInfo', {})}"
            )
            return make_json_rpc_response(
                id=request.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": SERVER_CAPABILITIES,
                    "serverInfo": SERVER_INFO,
                },
            )

        # MCP Protocol: initialized notification (client confirms ready)
        elif request.method == "notifications/initialized":
            logger.info("MCP client confirmed initialization complete")
            # Notifications don't require a response, but we return success for consistency
            return make_json_rpc_response(id=request.id, result={})

        elif request.method == "tools/list":
            return make_json_rpc_response(
                id=request.id,
                result={"tools": TOOL_DEFINITIONS},
            )

        elif request.method == "tools/call":
            params = request.params or {}
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            if not tool_name:
                return make_json_rpc_response(
                    id=request.id,
                    error={"code": -32602, "message": "Missing tool name in params"},
                )

            result = await _execute_tool(tool_name, tool_args)
            return make_json_rpc_response(
                id=request.id,
                result={"content": [{"type": "text", "text": result}]},
            )

        else:
            return make_json_rpc_response(
                id=request.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {request.method}",
                },
            )

    except Exception as e:
        logger.exception(f"MCP request failed: {e}")
        return make_json_rpc_response(
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
        currency = _extract_currency_arg(args)
        direction = _extract_direction_arg(args)
        logger.info(
            "MCP get_offerbook args normalized (has_currency=%s, direction=%s, keys=%s)",
            bool(currency),
            direction,
            sorted(args.keys()),
        )
        if not currency:
            return "Error: currency is required for get_offerbook tool (e.g., EUR, USD, CHF)"
        return await service.get_offerbook_formatted(currency, direction)

    elif name == "get_reputation":
        profile_id = args.get("profile_id")
        if not profile_id:
            return "Error: profile_id is required for get_reputation tool"
        return await service.get_reputation_formatted(profile_id)

    elif name == "get_markets":
        return await service.get_markets_formatted()

    elif name == "get_transaction":
        tx_id = args.get("tx_id")
        if not tx_id:
            return "Error: tx_id is required for get_transaction tool"
        return await service.get_transaction_formatted(tx_id)

    else:
        return f"Unknown tool: {name}"


def _extract_currency_arg(args: dict[str, Any]) -> str | None:
    """Extract and normalize currency from tool args with common key aliases."""
    aliases = (
        "currency",
        "currency_code",
        "currencyCode",
        "quote_currency",
        "quoteCurrency",
        "market",
    )
    for key in aliases:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip().upper()
            if key == "market":
                quote_currency = _extract_quote_currency_from_market(candidate)
                if quote_currency:
                    return quote_currency
            match = re.search(r"\b[A-Z]{2,5}\b", candidate)
            if match:
                token = match.group(0)
                if token == "BTC":
                    continue
                return token
    return None


def _extract_quote_currency_from_market(market: str) -> str | None:
    normalized = market.strip().upper()
    if not normalized:
        return None

    compact = re.sub(r"\s+", "", normalized)
    if compact.startswith("BTC") and len(compact) > 3:
        quote = compact[3:]
        if re.fullmatch(r"[A-Z]{2,5}", quote) and quote not in {"BTC", "XBT"}:
            return quote
    if compact.startswith("XBT") and len(compact) > 3:
        quote = compact[3:]
        if re.fullmatch(r"[A-Z]{2,5}", quote) and quote not in {"BTC", "XBT"}:
            return quote

    for separator in ("/", "_", "-", ":"):
        if separator in normalized:
            parts = [
                part.strip() for part in normalized.split(separator) if part.strip()
            ]
            if len(parts) >= 2:
                quote = parts[1]
                if re.fullmatch(r"[A-Z]{2,5}", quote) and quote not in {"BTC", "XBT"}:
                    return quote
            return None

    spaced_pair = re.match(r"^(?:BTC|XBT)\s+([A-Z]{2,5})$", normalized)
    if spaced_pair:
        quote = spaced_pair.group(1)
        if quote not in {"BTC", "XBT"}:
            return quote
    return None


def _extract_direction_arg(args: dict[str, Any]) -> str | None:
    """Extract and normalize direction from tool args with common key aliases."""
    aliases = ("direction", "side")
    for key in aliases:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip().upper()
            if normalized in {"BUY", "SELL"}:
                return normalized
    return None
