"""Bisq2 WebSocket client for real-time event subscriptions.

Provides async WebSocket connectivity to the Bisq2 API for receiving
support chat reactions and messages in real-time.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple

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


class ConnectionClosed(Exception):
    """Fallback exception and monkeypatch target for websocket disconnects."""


_WS_CONNECTION_CLOSED: type[BaseException] = ConnectionClosed
try:
    from websockets.exceptions import ConnectionClosed as _WebSocketConnectionClosed

    _WS_CONNECTION_CLOSED = _WebSocketConnectionClosed
except ImportError:  # pragma: no cover - tested via monkeypatch fallback
    pass


EventCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]
SubscriptionSnapshotCallback = Callable[
    [str, Optional[str], Optional[str]],
    Coroutine[Any, Any, None],
]
Subscription = Tuple[str, Optional[str]]

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
_DEFAULT_SUBSCRIPTION_TIMEOUT_SECONDS = 10.0


def is_valid_subscription_response(
    response: Any,
    expected_request_id: Optional[str] = None,
) -> bool:
    """Validate the current Bisq SubscriptionResponse wire contract."""
    if not isinstance(response, dict):
        return False
    if response.get("type") != "SubscriptionResponse":
        return False

    request_id = response.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        return False
    if expected_request_id is not None and request_id != expected_request_id:
        return False

    if "payload" not in response or "errorMessage" not in response:
        return False
    payload = response.get("payload")
    if payload is not None and not isinstance(payload, str):
        return False
    error_message = response.get("errorMessage")
    if error_message is not None and (
        not isinstance(error_message, str) or bool(error_message.strip())
    ):
        return False
    return True


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
        *,
        connect_timeout_seconds: float = _DEFAULT_CONNECT_TIMEOUT_SECONDS,
        subscription_timeout_seconds: float = _DEFAULT_SUBSCRIPTION_TIMEOUT_SECONDS,
    ):
        self.url = url
        self._connect_timeout_seconds = max(float(connect_timeout_seconds), 0.001)
        self._subscription_timeout_seconds = max(
            float(subscription_timeout_seconds),
            0.001,
        )
        self._ws: Any = None
        self._connected = False
        self._sequence: int = 0
        self._event_callbacks: List[EventCallback] = []
        self._subscription_snapshot_callbacks: List[SubscriptionSnapshotCallback] = []
        self._subscriptions: List[Subscription] = []
        self._active_subscriptions: Set[Subscription] = set()
        self._listening = False
        self._lifecycle_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected."""
        return self._connected

    @property
    def is_listening(self) -> bool:
        """Whether the persistent receive loop is running."""
        return self._listening

    def has_active_subscription(
        self, topic: str, parameter: Optional[str] = None
    ) -> bool:
        """Return whether the current socket acknowledged a subscription."""
        return (topic, parameter) in self._active_subscriptions

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        self._active_subscriptions.clear()
        try:
            self._ws = await asyncio.wait_for(
                websockets_connect(self.url),
                timeout=self._connect_timeout_seconds,
            )
            self._connected = True
            logger.info("Connected to Bisq2 WebSocket")
        except Exception as exc:
            self._ws = None
            self._connected = False
            logger.warning(
                "Failed to connect to Bisq2 WebSocket (%s)", type(exc).__name__
            )
            raise ConnectionError("Failed to connect to Bisq2 WebSocket") from None

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._listening = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as exc:
                logger.debug("Error closing Bisq2 WebSocket (%s)", type(exc).__name__)
            finally:
                self._ws = None
        self._connected = False
        self._active_subscriptions.clear()
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
        async with self._lifecycle_lock:
            if self._listening:
                raise RuntimeError(
                    "Cannot subscribe while the Bisq2 WebSocket listener is active"
                )
            return await self._subscribe(topic, parameter, remember=True)

    async def _subscribe(
        self,
        topic: str,
        parameter: Optional[str],
        *,
        remember: bool,
    ) -> Dict[str, Any]:
        """Subscribe while the caller owns the receive lifecycle."""
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

        expected_id = str(self._sequence)
        buffered_messages: List[str] = []

        async def complete_subscription() -> Dict[str, Any]:
            async with self._receive_lock:
                await self._ws.send(json.dumps(request))
                logger.debug("Sent Bisq2 WebSocket subscribe request")

                while True:
                    raw = await self._ws.recv()
                    response = json.loads(raw)
                    if not isinstance(response, dict):
                        raise ValueError("Unexpected WebSocket response")

                    if response.get("type") == "SubscriptionResponse":
                        if not is_valid_subscription_response(response, expected_id):
                            raise ValueError("Invalid subscription acknowledgement")
                        break

                    buffered_messages.append(raw)

            # The acknowledgement payload is an authoritative topic snapshot.
            # Reconcile it before marking this socket's subscription active and
            # before replaying incrementals that raced ahead of the ack.
            await self._dispatch_subscription_snapshot(
                topic,
                parameter,
                response.get("payload"),
            )

            subscription = (topic, parameter)
            self._active_subscriptions.add(subscription)
            if remember and subscription not in self._subscriptions:
                self._subscriptions.append(subscription)

            for buffered_raw in buffered_messages:
                await self._handle_message(buffered_raw)
            return response

        try:
            response = await asyncio.wait_for(
                complete_subscription(),
                timeout=self._subscription_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._active_subscriptions.discard((topic, parameter))
            logger.warning(
                "Bisq2 WebSocket subscription failed (%s)", type(exc).__name__
            )
            raise ConnectionError(
                "Bisq2 WebSocket subscription was not acknowledged"
            ) from None
        return response

    def on_event(self, callback: EventCallback) -> None:
        """Register an event callback.

        Args:
            callback: Async callable receiving parsed event dicts.
        """
        if callback not in self._event_callbacks:
            self._event_callbacks.append(callback)

    def off_event(self, callback: EventCallback) -> None:
        """Unregister an event callback if present."""
        try:
            self._event_callbacks.remove(callback)
        except ValueError:
            return

    def on_subscription_snapshot(
        self,
        callback: SubscriptionSnapshotCallback,
    ) -> None:
        """Register a strict acknowledgement-snapshot callback."""
        if callback not in self._subscription_snapshot_callbacks:
            self._subscription_snapshot_callbacks.append(callback)

    def off_subscription_snapshot(
        self,
        callback: SubscriptionSnapshotCallback,
    ) -> None:
        """Unregister an acknowledgement-snapshot callback if present."""
        try:
            self._subscription_snapshot_callbacks.remove(callback)
        except ValueError:
            return

    async def _dispatch_subscription_snapshot(
        self,
        topic: str,
        parameter: Optional[str],
        payload: Optional[str],
    ) -> None:
        """Reconcile a subscription snapshot before readiness can become active.

        Unlike incremental event dispatch, snapshot callback failures propagate.
        Treating a failed reconciliation as a successful subscription could leave
        stale reactions active after reconnect.
        """
        for callback in self._subscription_snapshot_callbacks:
            await callback(topic, parameter, payload)

    async def _dispatch_event(self, event: Dict[str, Any]) -> None:
        """Dispatch an event to all registered callbacks."""
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception as exc:
                logger.warning("Bisq2 event callback failed (%s)", type(exc).__name__)

    async def _handle_message(self, raw: str) -> None:
        """Parse and route an incoming WebSocket message."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received invalid JSON from Bisq2 WebSocket")
            return

        # Bisq2 currently uses "type"; keep "responseType" for compatibility.
        response_type = data.get("responseType") or data.get("type", "")

        # Subscription responses are handled inline by subscribe()
        if response_type == "SubscriptionResponse":
            return

        payload = data.get("payload")
        if isinstance(payload, str):
            try:
                decoded_payload = json.loads(payload)
                if isinstance(decoded_payload, (dict, list)):
                    data["payload"] = decoded_payload
            except json.JSONDecodeError:
                logger.debug("Received non-JSON payload string from Bisq2 WebSocket")

        # Everything else is dispatched as an event
        await self._dispatch_event(data)

    async def _resubscribe_existing_topics(self) -> None:
        """Re-subscribe to topics after reconnect."""
        subscriptions = list(self._subscriptions)
        for topic, parameter in subscriptions:
            await self._subscribe(topic, parameter, remember=False)

    async def _discard_socket_for_retry(self) -> None:
        """Close a failed socket without stopping the persistent listener."""
        socket = self._ws
        self._ws = None
        self._connected = False
        self._active_subscriptions.clear()
        if socket is None:
            return
        try:
            await asyncio.wait_for(
                socket.close(),
                timeout=self._connect_timeout_seconds,
            )
        except Exception as exc:
            logger.debug("Error discarding Bisq2 WebSocket (%s)", type(exc).__name__)

    async def listen_forever(self, reconnect_delay_seconds: float = 5.0) -> None:
        """Run persistent receive loop with reconnect on connection close."""
        async with self._lifecycle_lock:
            if self._listening:
                raise RuntimeError("Bisq2 WebSocket listener is already active")
            self._listening = True

        while self._listening:
            try:
                if not self._connected or self._ws is None:
                    await self.connect()
                    await self._resubscribe_existing_topics()

                raw = await self._ws.recv()
                await self._handle_message(raw)

            except asyncio.CancelledError:
                self._listening = False
                raise
            except (ConnectionClosed, _WS_CONNECTION_CLOSED):
                if not self._listening:
                    break
                logger.warning("Bisq2 WebSocket closed, reconnecting")
                await self._discard_socket_for_retry()
                await asyncio.sleep(reconnect_delay_seconds)
            except Exception as exc:
                if not self._listening:
                    break
                logger.warning(
                    "Bisq2 listen loop error, reconnecting (%s)",
                    type(exc).__name__,
                )
                await self._discard_socket_for_retry()
                await asyncio.sleep(reconnect_delay_seconds)

    async def stop_listening(self) -> None:
        """Stop persistent receive loop and close socket."""
        self._listening = False
        await self.close()
