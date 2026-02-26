"""Bisq2 channel utility helpers."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def build_bisq_websocket_url(api_url: str) -> str:
    """Convert BISQ_API_URL to websocket endpoint URL."""
    parsed = urlparse(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "ws://host.docker.internal:8090/websocket"

    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse(
        parsed._replace(
            scheme=ws_scheme, path="/websocket", params="", query="", fragment=""
        )
    )
