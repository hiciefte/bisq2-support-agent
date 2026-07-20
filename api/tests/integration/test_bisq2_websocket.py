"""Tests for Bisq2WebSocketClient.

Covers:
- Connection lifecycle (connect, close)
- Subscription management (subscribe, unsubscribe)
- Event callback dispatch
- JSON parsing of WebSocket messages
- Sequence number tracking
- Error handling
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.channels.plugins.bisq2.client.websocket import (
    Bisq2WebSocketClient,
    is_valid_subscription_response,
)


def _subscription_ack(request_id: str, payload: str | None = "[]") -> str:
    return json.dumps(
        {
            "type": "SubscriptionResponse",
            "requestId": request_id,
            "payload": payload,
            "errorMessage": None,
        }
    )


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

    def test_url_stored(self):
        """URL is stored on construction."""
        client = Bisq2WebSocketClient(url="ws://example:9090/websocket")
        assert client.url == "ws://example:9090/websocket"


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
            "app.channels.plugins.bisq2.client.websocket.websockets_connect",
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
        mock_ws.recv = AsyncMock(return_value=_subscription_ack("1"))
        client._ws = mock_ws
        client._connected = True

        response = await client.subscribe("SUPPORT_CHAT_REACTIONS")

        mock_ws.send.assert_called_once()
        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["requestType"] == "Subscribe"
        assert sent_msg["topic"] == "SUPPORT_CHAT_REACTIONS"
        assert is_valid_subscription_response(response, "1")
        assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS") is True

    @pytest.mark.asyncio
    async def test_subscribe_with_parameter(self):
        """subscribe() includes parameter when provided."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=_subscription_ack("1"))
        client._ws = mock_ws
        client._connected = True

        await client.subscribe("SUPPORT_CHAT_MESSAGES", parameter="channel-123")

        sent_msg = json.loads(mock_ws.send.call_args[0][0])
        assert sent_msg["parameter"] == "channel-123"
        assert client.has_active_subscription("SUPPORT_CHAT_MESSAGES", "channel-123")

    @pytest.mark.asyncio
    async def test_subscribe_buffers_event_until_valid_ack(self):
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        callback = AsyncMock()
        client.on_event(callback)
        event = {
            "type": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "payload": "{}",
        }

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(
            side_effect=[json.dumps(event), _subscription_ack("1")]
        )
        client._ws = mock_ws
        client._connected = True

        await client.subscribe("SUPPORT_CHAT_REACTIONS")

        callback.assert_awaited_once()
        assert callback.call_args.args[0]["topic"] == "SUPPORT_CHAT_REACTIONS"
        assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS")

    @pytest.mark.asyncio
    async def test_snapshot_reconciles_before_buffered_incremental(self):
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        order: list[str] = []

        async def on_snapshot(
            topic: str,
            parameter: str | None,
            payload: str | None,
        ) -> None:
            assert topic == "SUPPORT_CHAT_REACTIONS"
            assert parameter is None
            assert payload == '[{"messageId":"snapshot-message"}]'
            assert not client.has_active_subscription("SUPPORT_CHAT_REACTIONS")
            order.append("snapshot")

        async def on_event(_event: dict[str, object]) -> None:
            assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS")
            order.append("incremental")

        client.on_subscription_snapshot(on_snapshot)
        client.on_event(on_event)
        buffered_event = {
            "type": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": "{}",
        }
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(
            side_effect=[
                json.dumps(buffered_event),
                _subscription_ack(
                    "1",
                    '[{"messageId":"snapshot-message"}]',
                ),
            ]
        )
        client._ws = mock_ws
        client._connected = True

        await client.subscribe("SUPPORT_CHAT_REACTIONS")

        assert order == ["snapshot", "incremental"]

    @pytest.mark.asyncio
    async def test_snapshot_failure_keeps_subscription_inactive(self):
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        callback = AsyncMock(side_effect=ValueError("invalid snapshot"))
        client.on_subscription_snapshot(callback)
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=_subscription_ack("1"))
        client._ws = mock_ws
        client._connected = True

        with pytest.raises(ConnectionError, match="was not acknowledged"):
            await client.subscribe("SUPPORT_CHAT_REACTIONS")

        callback.assert_awaited_once_with("SUPPORT_CHAT_REACTIONS", None, "[]")
        assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS") is False

    @pytest.mark.asyncio
    async def test_subscribe_drops_buffered_event_on_invalid_ack(self):
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        callback = AsyncMock()
        client.on_event(callback)
        event = {
            "type": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "payload": "{}",
        }
        invalid_ack = json.dumps(
            {
                "type": "SubscriptionResponse",
                "requestId": "1",
                "payload": "[]",
                "errorMessage": "rejected",
            }
        )

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=[json.dumps(event), invalid_ack])
        client._ws = mock_ws
        client._connected = True

        with pytest.raises(ConnectionError, match="was not acknowledged"):
            await client.subscribe("SUPPORT_CHAT_REACTIONS")

        callback.assert_not_awaited()
        assert not client.has_active_subscription("SUPPORT_CHAT_REACTIONS")

    @pytest.mark.asyncio
    async def test_external_subscribe_rejected_while_listener_active(self):
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        client._connected = True
        client._ws = AsyncMock()
        client._listening = True

        with pytest.raises(RuntimeError, match="listener is active"):
            await client.subscribe("SUPPORT_CHAT_REACTIONS")

        client._ws.recv.assert_not_awaited()


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
    async def test_parse_valid_json_with_type_field(self):
        """Valid JSON with Bisq2 'type' field is parsed and dispatched."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb = AsyncMock()
        client.on_event(cb)

        msg = json.dumps(
            {
                "type": "WebSocketEvent",
                "sequenceNumber": 1,
                "payload": '{"reaction":"THUMBS_UP"}',
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
        """SubscriptionResponse messages are not dispatched as events (type key)."""
        client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
        cb = AsyncMock()
        client.on_event(cb)

        msg = json.dumps(
            {
                "type": "SubscriptionResponse",
                "requestId": "1",
                "payload": "[]",
                "errorMessage": None,
            }
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
        # Return matching requestId for each subscribe call
        mock_ws.recv = AsyncMock(
            side_effect=[
                _subscription_ack("1"),
                _subscription_ack("2"),
            ]
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

    @pytest.mark.asyncio
    async def test_connect_error_does_not_expose_url_or_exception(self, caplog):
        sensitive_url = "ws://sensitive-host.invalid/websocket?token=sentinel-token"
        client = Bisq2WebSocketClient(url=sensitive_url)

        with patch(
            "app.channels.plugins.bisq2.client.websocket.websockets_connect",
            new=AsyncMock(side_effect=RuntimeError("sentinel-exception")),
        ):
            with pytest.raises(ConnectionError) as exc_info:
                await client.connect()

        combined = caplog.text + str(exc_info.value)
        assert sensitive_url not in combined
        assert "sentinel-token" not in combined
        assert "sentinel-exception" not in combined

    @pytest.mark.asyncio
    async def test_connect_timeout_is_bounded_and_fail_closed(self):
        client = Bisq2WebSocketClient(
            url="ws://localhost:8090/websocket",
            connect_timeout_seconds=0.01,
        )
        never_connected = asyncio.Event()

        with patch(
            "app.channels.plugins.bisq2.client.websocket.websockets_connect",
            new=AsyncMock(side_effect=never_connected.wait),
        ):
            with pytest.raises(ConnectionError, match="Failed to connect"):
                await client.connect()

        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_subscription_ack_timeout_is_bounded_and_inactive(self):
        client = Bisq2WebSocketClient(
            url="ws://localhost:8090/websocket",
            subscription_timeout_seconds=0.01,
        )
        never_acknowledged = asyncio.Event()
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=never_acknowledged.wait)
        client._ws = mock_ws
        client._connected = True

        with pytest.raises(ConnectionError, match="was not acknowledged"):
            await client.subscribe("SUPPORT_CHAT_REACTIONS")

        assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS") is False


@pytest.mark.parametrize(
    "response",
    [
        {
            "type": "SubscriptionResponse",
            "requestId": "",
            "payload": None,
            "errorMessage": None,
        },
        {
            "type": "SubscriptionResponse",
            "requestId": "2",
            "payload": None,
            "errorMessage": None,
        },
        {
            "type": "SubscriptionResponse",
            "requestId": "1",
            "payload": [],
            "errorMessage": None,
        },
        {
            "type": "SubscriptionResponse",
            "requestId": "1",
            "payload": None,
            "errorMessage": "denied",
        },
        {
            "responseType": "SubscriptionResponse",
            "requestId": "1",
            "payload": None,
            "errorMessage": None,
        },
        {"type": "SubscriptionResponse", "requestId": "1", "payload": None},
    ],
)
def test_subscription_response_validator_rejects_invalid_shape(response):
    assert is_valid_subscription_response(response, "1") is False
