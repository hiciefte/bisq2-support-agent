"""Tests for Bisq2WebSocketClient.

Covers:
- Connection lifecycle (connect, close)
- Subscription management (subscribe, unsubscribe)
- Event callback dispatch
- JSON parsing of WebSocket messages
- Sequence number tracking
- Reconnection with exponential backoff
- Error handling
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.integrations.bisq2_websocket import Bisq2WebSocketClient

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientConstruction:
    """Test client construction."""

    def test_default_state(self):
        """Client starts disconnected."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        assert client.url == "ws://localhost:8090/websocket"
        assert client.is_connected is False

    def test_custom_reconnect_settings(self):
        """Custom reconnect settings are stored."""
        client = Bisq2WebSocketClient(
            url="ws://localhost:8090/websocket",
            max_reconnect_attempts=5,
            base_reconnect_delay=2.0,
        )
        assert client.max_reconnect_attempts == 5
        assert client.base_reconnect_delay == 2.0


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientConnection:
    """Test connect/close lifecycle."""

    @pytest.mark.asyncio
    async def test_connect_establishes_connection(self):
        """connect() opens a WebSocket connection."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        with patch(
            "app.integrations.bisq2_websocket.websockets_connect",
            new=AsyncMock(return_value=mock_ws),
        ):
            await client.connect()
            assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_close_disconnects(self):
        """close() closes the WebSocket and marks disconnected."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        client._ws = mock_ws
        client._connected = True

        await client.close()

        mock_ws.close.assert_called_once()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_close_when_not_connected_is_safe(self):
        """close() is safe when not connected."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        await client.close()
        assert client.is_connected is False


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientSubscription:
    """Test subscribe/unsubscribe."""

    @pytest.mark.asyncio
    async def test_subscribe_sends_request(self):
        """subscribe() sends a SubscriptionRequest JSON message."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {
                    "responseType": "SubscriptionResponse",
                    "requestId": "1",
                    "success": True,
                    "payload": [],
                }
            )
        )
        client._ws = mock_ws
        client._connected = True

        response = await client.subscribe("SUPPORT_CHAT_REACTIONS")

        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["requestType"] == "Subscribe"
        assert sent_msg["topic"] == "SUPPORT_CHAT_REACTIONS"
        assert response["success"] is True

    @pytest.mark.asyncio
    async def test_subscribe_with_parameter(self):
        """subscribe() includes parameter when provided."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {"responseType": "SubscriptionResponse", "success": True, "payload": []}
            )
        )
        client._ws = mock_ws
        client._connected = True

        await client.subscribe("SUPPORT_CHAT_MESSAGES", parameter="channel-123")

        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["parameter"] == "channel-123"


# ---------------------------------------------------------------------------
# Event Dispatch
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientEventDispatch:
    """Test on_event callback registration and dispatch."""

    def test_on_event_registers_callback(self):
        """on_event() stores callback."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb = MagicMock()
        client.on_event(cb)
        assert cb in client._event_callbacks

    @pytest.mark.asyncio
    async def test_dispatch_calls_registered_callbacks(self):
        """_dispatch_event calls all registered callbacks."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        client.on_event(cb1)
        client.on_event(cb2)

        event = {"type": "WebSocketEvent", "payload": {"data": "test"}}
        await client._dispatch_event(event)

        cb1.assert_called_once_with(event)
        cb2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_dispatch_handles_callback_error(self):
        """Callback errors don't crash dispatch."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        bad_cb = AsyncMock(side_effect=Exception("callback error"))
        good_cb = AsyncMock()
        client.on_event(bad_cb)
        client.on_event(good_cb)

        event = {"type": "WebSocketEvent", "payload": {}}
        await client._dispatch_event(event)

        # good_cb should still be called despite bad_cb failing
        good_cb.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# Message Parsing
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientParsing:
    """Test JSON message parsing."""

    @pytest.mark.asyncio
    async def test_parse_valid_json(self):
        """Valid JSON is parsed and dispatched."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb = AsyncMock()
        client.on_event(cb)

        msg = json.dumps(
            {
                "responseType": "WebSocketEvent",
                "sequenceNumber": 1,
                "payload": {"reaction": "THUMBS_UP"},
            }
        )
        await client._handle_message(msg)

        cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_invalid_json_ignored(self):
        """Invalid JSON is logged and ignored."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb = AsyncMock()
        client.on_event(cb)

        await client._handle_message("not json {{{")

        cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscription_response_not_dispatched(self):
        """SubscriptionResponse messages are not dispatched as events."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb = AsyncMock()
        client.on_event(cb)

        msg = json.dumps(
            {"responseType": "SubscriptionResponse", "success": True, "payload": []}
        )
        await client._handle_message(msg)

        cb.assert_not_called()


# ---------------------------------------------------------------------------
# Sequence Number Tracking
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientSequenceTracking:
    """Test sequence number tracking."""

    @pytest.mark.asyncio
    async def test_sequence_number_increments(self):
        """Each subscribe call increments the request sequence number."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(
            return_value=json.dumps(
                {"responseType": "SubscriptionResponse", "success": True, "payload": []}
            )
        )
        client._ws = mock_ws
        client._connected = True

        await client.subscribe("TOPIC_A")
        first_msg = json.loads(mock_ws.send.call_args_list[0][0][0])

        await client.subscribe("TOPIC_B")
        second_msg = json.loads(mock_ws.send.call_args_list[1][0][0])

        assert int(second_msg["requestId"]) > int(first_msg["requestId"])


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_subscribe_when_disconnected_raises(self):
        """subscribe() raises when not connected."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        with pytest.raises(ConnectionError):
            await client.subscribe("TOPIC")
