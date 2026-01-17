"""MCP (Model Context Protocol) server package for Bisq 2 APIs.

This package provides an MCP HTTP server (JSON-RPC 2.0 over HTTP) that exposes
Bisq 2 data (prices, offers, reputation) as tools that LLMs can autonomously invoke
via AISuite's native MCP support.
"""

from app.services.mcp.mcp_http_server import router as mcp_router

__all__ = ["mcp_router"]
