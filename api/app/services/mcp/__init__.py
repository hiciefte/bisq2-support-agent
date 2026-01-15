"""MCP (Model Context Protocol) server package for Bisq 2 APIs.

This package provides a real MCP server that exposes Bisq 2 data
(prices, offers, reputation) as tools that LLMs can autonomously invoke.
"""

from app.services.mcp.bisq_mcp_server import create_mcp_server, get_mcp_server

__all__ = ["create_mcp_server", "get_mcp_server"]
