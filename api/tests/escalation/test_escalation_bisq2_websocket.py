"""Tests for Bisq2 WebSocket client and delivery integration."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelType,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)
from app.channels.plugins.bisq2.channel import Bisq2Channel
from app.integrations.bisq2_websocket import Bisq2WebSocketClient

# ---------------------------------------------------------------------------
# Bisq2WebSocketClient interface tests
# ---------------------------------------------------------------------------


class TestBisq2WebSocketClientBasics:
    """Test that Bisq2WebSocketClient has the expected interface."""

    def test_client_initializes_with_url(self):
        """Client can be initialized with WebSocket URL."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        assert client.url == "ws://localhost:8090/websocket"

    def test_client_starts_disconnected(self):
        """Client starts in disconnected state."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        assert client.is_connected is False

    def test_ws_client_has_connect_method(self):
        """WebSocket client has connect() coroutine."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        assert hasattr(client, "connect")

    def test_ws_client_has_close_method(self):
        """WebSocket client has close() coroutine."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        assert hasattr(client, "close")

    def test_ws_client_has_on_event_method(self):
        """WebSocket client has on_event() callback registration."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        assert hasattr(client, "on_event")
        assert callable(client.on_event)

    @pytest.mark.asyncio
    async def test_close_resets_connected_state(self):
        """close() sets is_connected to False."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        client._connected = True
        client._ws = MagicMock()
        client._ws.close = AsyncMock()

        await client.close()

        assert client.is_connected is False


# ---------------------------------------------------------------------------
# Bisq2Channel REST delivery tests
# ---------------------------------------------------------------------------


def _make_outgoing(**overrides):
    defaults = dict(
        message_id="test-001",
        in_reply_to="original-001",
        channel=ChannelType.BISQ2,
        answer="Staff answer",
        user=UserContext(user_id="user-123"),
        metadata=ResponseMetadata(
            processing_time_ms=0.0,
            rag_strategy="escalation",
            model_name="staff",
        ),
    )
    defaults.update(overrides)
    return OutgoingMessage(**defaults)


class TestBisq2DeliveryViaREST:
    """Test Bisq2Channel.send_message() via existing REST API path."""

    @pytest.mark.asyncio
    async def test_bisq2_send_uses_rest_api(self):
        """send_message() calls bisq2_api.send_support_message()."""
        runtime = MagicMock()
        bisq_api = AsyncMock()
        bisq_api.send_support_message = AsyncMock(return_value={"messageId": "msg-001"})

        def _resolve(name):
            if name == "bisq2_api":
                return bisq_api
            return None

        runtime.resolve_optional.side_effect = _resolve

        channel = Bisq2Channel(runtime)
        msg = _make_outgoing()
        result = await channel.send_message("conv-123", msg)

        assert result is True
        bisq_api.send_support_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_bisq2_send_returns_false_when_api_unavailable(self):
        """No bisq2_api registered -> returns False."""
        runtime = MagicMock()
        runtime.resolve_optional.return_value = None

        channel = Bisq2Channel(runtime)
        msg = _make_outgoing()
        result = await channel.send_message("conv-123", msg)

        assert result is False


class TestBisq2WebSocketComposition:
    """Test that WS client can be composed into delivery transport."""

    def test_ws_client_importable(self):
        """Bisq2WebSocketClient is importable from integrations."""
        assert Bisq2WebSocketClient is not None

    def test_ws_client_has_subscribe(self):
        """WebSocket client supports subscribe() for event topics."""
        client = Bisq2WebSocketClient("ws://localhost:8090/websocket")
        assert hasattr(client, "subscribe")
