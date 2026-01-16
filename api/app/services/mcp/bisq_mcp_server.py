"""
Real MCP Server for Bisq 2 APIs.

Exposes Bisq 2 data (prices, offers, reputation) as MCP tools
that the LLM can autonomously invoke via the Model Context Protocol.

This replaces the previous keyword-based intent detection approach
with true LLM-driven tool selection.
"""

import logging
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


class BisqMCPServer:
    """Class-based MCP server for Bisq 2 APIs.

    Encapsulates the MCP server instance and Bisq service,
    avoiding global mutable state for better testability.
    """

    def __init__(self, bisq_service: Any):
        """Initialize the MCP server with Bisq service.

        Args:
            bisq_service: Bisq2MCPService instance for API calls
        """
        self._bisq_service = bisq_service
        self._server = FastMCP("Bisq 2 Data Service")
        self._register_tools()
        logger.info("BisqMCPServer initialized with 4 Bisq tools")

    def _register_tools(self) -> None:
        """Register all Bisq tools with the MCP server."""
        # Register tools with the server
        self._register_get_market_prices()
        self._register_get_offerbook()
        self._register_get_reputation()
        self._register_get_markets()

    def _create_error_handler(
        self, tool_name: str, error_message: str
    ) -> Callable[[Exception], str]:
        """Create a reusable error handler for tool execution.

        Args:
            tool_name: Name of the tool for logging
            error_message: User-friendly error message to return

        Returns:
            Error handler function that logs and returns appropriate message
        """

        def handler(e: Exception) -> str:
            logger.error(f"Error in {tool_name}: {e}")
            return error_message

        return handler

    def _register_get_market_prices(self) -> None:
        """Register the get_market_prices tool."""
        error_handler = self._create_error_handler(
            "get_market_prices",
            "Market prices are currently unavailable. Please try again later.",
        )

        @self._server.tool()
        async def get_market_prices(currency: str | None = None) -> str:
            """Get current BTC market prices from the Bisq 2 network.

            Returns real-time Bitcoin prices in various fiat currencies.
            Use this when users ask about current BTC prices or exchange rates.

            Args:
                currency: Optional 3-letter currency code (e.g., EUR, USD, CHF).
                         If not specified, returns all available prices.

            Returns:
                Formatted string with BTC prices, e.g., "BTC/EUR: 95,000.00"
            """
            try:
                return await self._bisq_service.get_market_prices_formatted(currency)
            except Exception as e:
                return error_handler(e)

    def _register_get_offerbook(self) -> None:
        """Register the get_offerbook tool."""
        error_handler = self._create_error_handler(
            "get_offerbook",
            "Offerbook is currently unavailable. Please try again later.",
        )

        @self._server.tool()
        async def get_offerbook(
            currency: str | None = None, direction: str | None = None
        ) -> str:
            """Get current buy/sell offers from the Bisq 2 offerbook.

            Returns active trading offers on the Bisq 2 network.
            Use this when users ask about available offers to buy or sell BTC.

            IMPORTANT - Direction logic (from MAKER's perspective):
            - direction="SELL": Makers selling BTC → user can BUY BTC from them
            - direction="BUY": Makers buying BTC → user can SELL BTC to them

            So if user asks "offers to buy BTC" → use direction="SELL"
            If user asks "offers to sell BTC" → use direction="BUY"

            Args:
                currency: Optional 3-letter currency code to filter offers.
                direction: Optional "BUY" or "SELL" to filter by MAKER's direction.
                          To show offers where user can BUY BTC, use "SELL".
                          To show offers where user can SELL BTC, use "BUY".

            Returns:
                Formatted string listing available offers with prices and amounts.
            """
            try:
                return await self._bisq_service.get_offerbook_formatted(
                    currency, direction
                )
            except Exception as e:
                return error_handler(e)

    def _register_get_reputation(self) -> None:
        """Register the get_reputation tool."""
        error_handler = self._create_error_handler(
            "get_reputation",
            "Reputation data is currently unavailable. Please try again later.",
        )

        @self._server.tool()
        async def get_reputation(profile_id: str) -> str:
            """Get reputation score for a Bisq 2 user profile.

            Returns the reputation score and history for a specific user.
            Use this when users ask about a trader's reputation or trustworthiness.

            Args:
                profile_id: The unique identifier of the Bisq 2 user profile.

            Returns:
                Formatted string with reputation score, age, and trade history.
            """
            try:
                return await self._bisq_service.get_reputation_formatted(profile_id)
            except Exception as e:
                return error_handler(e)

    def _register_get_markets(self) -> None:
        """Register the get_markets tool."""
        error_handler = self._create_error_handler(
            "get_markets",
            "Market list is currently unavailable. Please try again later.",
        )

        @self._server.tool()
        async def get_markets() -> str:
            """Get list of available trading markets on Bisq 2.

            Returns all currency markets available for trading.
            Use this when users ask what currencies are supported.

            Returns:
                Formatted string listing available fiat currencies and markets.
            """
            try:
                return await self._bisq_service.get_markets_formatted()
            except Exception as e:
                return error_handler(e)

    @property
    def server(self) -> FastMCP:
        """Get the underlying FastMCP server instance."""
        return self._server

    async def list_tools(self):
        """List all registered tools.

        Returns:
            List of registered MCP tools
        """
        return await self._server.list_tools()

    async def call_tool(self, name: str, arguments: dict):
        """Call a registered tool by name.

        Args:
            name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Result from the tool execution
        """
        return await self._server.call_tool(name, arguments)


# Module-level instance for backward compatibility
_mcp_server_instance: BisqMCPServer | None = None


def create_mcp_server(bisq_service: Any) -> FastMCP:
    """Create and configure the MCP server with Bisq tools.

    This function provides backward compatibility with existing code
    while using the new class-based implementation internally.

    Args:
        bisq_service: Bisq2MCPService instance for API calls

    Returns:
        Configured FastMCP server with all Bisq tools registered
    """
    global _mcp_server_instance
    _mcp_server_instance = BisqMCPServer(bisq_service)
    return _mcp_server_instance.server


def get_mcp_server() -> FastMCP:
    """Get the global MCP server instance.

    Returns:
        The initialized FastMCP server

    Raises:
        RuntimeError: If create_mcp_server hasn't been called yet
    """
    if _mcp_server_instance is None:
        raise RuntimeError("MCP server not initialized. Call create_mcp_server first.")
    return _mcp_server_instance.server


def get_mcp_server_instance() -> BisqMCPServer:
    """Get the BisqMCPServer instance for direct access.

    Returns:
        The initialized BisqMCPServer instance

    Raises:
        RuntimeError: If create_mcp_server hasn't been called yet
    """
    if _mcp_server_instance is None:
        raise RuntimeError("MCP server not initialized. Call create_mcp_server first.")
    return _mcp_server_instance
