"""Bisq2 WebSocket client for real-time event subscriptions.

Provides async WebSocket connectivity to the Bisq2 API for receiving
support chat reactions and messages in real-time.
"""

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# Use a wrapper to make patching easier in tests
try:
    from websockets.asyncio.client import connect as _ws_connect

    async def websockets_connect(url: str, **kwargs: Any) -> Any:
        """Connect wrapper for testability."""
        return await _ws_connect(url, **kwargs)

except ImportError:
    # websockets not installed - provide stub for testing
    async def websockets_connect(url: str, **kwargs: Any) -> Any:
        """Stub when websockets is not installed."""
        raise ImportError("websockets package is required")


EventCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class Bisq2WebSocketClient:
    """Async WebSocket client for Bisq2 API subscriptions.

    Connects to the Bisq2 WebSocket endpoint, manages subscriptions,
    and dispatches incoming events to registered callbacks.

    Example:
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        await client.connect()
        client.on_event(my_handler)
        await client.subscribe("SUPPORT_CHAT_REACTIONS")
    """

    def __init__(
        self,
        url: str,
        max_reconnect_attempts: int = 10,
        base_reconnect_delay: float = 1.0,
    ):
        self.url = url
        self.max_reconnect_attempts = max_reconnect_attempts
        self.base_reconnect_delay = base_reconnect_delay
        self._ws: Any = None
        self._connected = False
        self._sequence: int = 0
        self._event_callbacks: List[EventCallback] = []
        self._subscriptions: List[str] = []

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        try:
            self._ws = await websockets_connect(self.url)
            self._connected = True
            logger.info("Connected to Bisq2 WebSocket at %s", self.url)
        except Exception:
            self._connected = False
            logger.exception("Failed to connect to Bisq2 WebSocket at %s", self.url)
            raise

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("Error closing WebSocket", exc_info=True)
            finally:
                self._ws = None
        self._connected = False
        logger.info("Bisq2 WebSocket connection closed")

    async def subscribe(
        self, topic: str, parameter: Optional[str] = None
    ) -> Dict[str, Any]:
        """Subscribe to a topic.

        Args:
            topic: Topic name (e.g., "SUPPORT_CHAT_REACTIONS").
            parameter: Optional subscription parameter.

        Returns:
            Parsed SubscriptionResponse dict.

        Raises:
            ConnectionError: If not connected.
        """
        if not self._connected or not self._ws:
            raise ConnectionError("Not connected to Bisq2 WebSocket")

        self._sequence += 1
        request = {
            "requestType": "Subscribe",
            "requestId": str(self._sequence),
            "topic": topic,
        }
        if parameter is not None:
            request["parameter"] = parameter

        await self._ws.send(json.dumps(request))
        logger.debug(
            "Sent subscribe request for topic %s (seq=%d)", topic, self._sequence
        )

        # Wait for subscription response
        raw = await self._ws.recv()
        response = json.loads(raw)
        self._subscriptions.append(topic)
        return response

    def on_event(self, callback: EventCallback) -> None:
        """Register an event callback.

        Args:
            callback: Async callable receiving parsed event dicts.
        """
        self._event_callbacks.append(callback)

    async def _dispatch_event(self, event: Dict[str, Any]) -> None:
        """Dispatch an event to all registered callbacks."""
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("Error in event callback")

    async def _handle_message(self, raw: str) -> None:
        """Parse and route an incoming WebSocket message."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON from Bisq2 WebSocket")
            return

        response_type = data.get("responseType", "")

        # Subscription responses are handled inline by subscribe()
        if response_type == "SubscriptionResponse":
            return

        # Everything else is dispatched as an event
        await self._dispatch_event(data)
