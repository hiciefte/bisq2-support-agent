"""Tests for Matrix Channel Plugin.

TDD tests for the Matrix channel plugin that wraps existing matrix integration.

Note: Matrix channel wraps the existing Matrix integration components:
- ConnectionManager for connection lifecycle
- SessionManager for authentication
- Matrix nio AsyncClient for room operations
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)
from app.channels.plugins.matrix.channel import MatrixChannel
from app.channels.runtime import ChannelRuntime


class TestMatrixChannelProperties:
    """Test MatrixChannel properties and identification."""

    @pytest.mark.unit
    def test_channel_id_is_matrix(self):
        """MatrixChannel has channel_id 'matrix'."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert channel.channel_id == "matrix"

    @pytest.mark.unit
    def test_capabilities_include_text_messages(self):
        """MatrixChannel supports text message capability."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.TEXT_MESSAGES in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_include_persistent_connection(self):
        """MatrixChannel supports persistent connection capability."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.PERSISTENT_CONNECTION in channel.capabilities

    @pytest.mark.unit
    def test_staff_notification_target_prefers_matrix_staff_room(self):
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_STAFF_ROOM="!staff:matrix.org",
            MATRIX_ALERT_ROOM="!alert:matrix.org",
        )
        channel = MatrixChannel(runtime)

        target = channel.get_staff_notification_target({})

        assert target == "!staff:matrix.org"

    @pytest.mark.unit
    def test_staff_notification_target_falls_back_to_alert_room(self):
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_STAFF_ROOM="",
            MATRIX_ALERT_ROOM="!alert:matrix.org",
        )
        channel = MatrixChannel(runtime)

        target = channel.get_staff_notification_target({})

        assert target == "!alert:matrix.org"


class TestMatrixChannelLifecycle:
    """Test MatrixChannel lifecycle methods."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_succeeds_with_connection_manager(self):
        """MatrixChannel starts successfully when ConnectionManager is available."""

        # Create mock ConnectionManager
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_conn_manager)

        channel = MatrixChannel(runtime)
        await channel.start()

        assert channel.is_connected is True
        mock_conn_manager.connect.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_joins_trust_monitor_rooms(self):
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock()
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                mock_conn_manager if name == "matrix_connection_manager" else None
            )
        )
        runtime.settings = SimpleNamespace(
            MATRIX_SYNC_ROOMS=["!sync:matrix.org"],
            TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=["!trust:matrix.org"],
            TRUST_MONITOR_MATRIX_STAFF_ROOM="!staff:matrix.org",
        )

        channel = MatrixChannel(runtime)
        channel.join_room = AsyncMock(return_value=True)

        await channel.start()

        joined = {call.args[0] for call in channel.join_room.call_args_list}
        assert joined == {"!sync:matrix.org", "!trust:matrix.org", "!staff:matrix.org"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_degraded_without_connection_manager(self):
        """MatrixChannel starts in degraded mode when ConnectionManager not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        await channel.start()

        # Channel starts but is not connected
        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_handles_connection_failure(self):
        """MatrixChannel handles connection failure gracefully."""

        # Create mock ConnectionManager that fails
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_conn_manager)

        channel = MatrixChannel(runtime)
        await channel.start()

        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds_with_connection_manager(self):
        """MatrixChannel stops successfully when ConnectionManager is available."""

        # Create mock ConnectionManager
        mock_conn_manager = MagicMock()
        mock_conn_manager.disconnect = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_conn_manager)

        channel = MatrixChannel(runtime)
        channel._is_connected = True

        await channel.stop()

        assert channel.is_connected is False
        mock_conn_manager.disconnect.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds_without_connection_manager(self):
        """MatrixChannel stops gracefully when ConnectionManager not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        channel._is_connected = True

        await channel.stop()

        assert channel.is_connected is False

    @pytest.mark.unit
    def test_health_check_returns_healthy_when_connected(self):
        """Health check returns healthy when connected."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        channel._is_connected = True
        status = channel.health_check()
        assert status.healthy is True

    @pytest.mark.unit
    def test_health_check_returns_unhealthy_when_disconnected(self):
        """Health check returns unhealthy when disconnected."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        channel._is_connected = False
        status = channel.health_check()
        assert status.healthy is False


class TestMatrixChannelMessageHandling:
    """Test MatrixChannel message handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_calls_rag_service(self, mock_rag_service):
        """handle_incoming delegates to RAG service."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = MatrixChannel(runtime)

        message = IncomingMessage(
            message_id="matrix-msg-001",
            channel=ChannelType.MATRIX,
            question="How do I run a Bisq node?",
            user=UserContext(user_id="@user:matrix.org"),
        )

        await channel.handle_incoming(message)

        mock_rag_service.query.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_returns_outgoing_message(self, mock_rag_service):
        """handle_incoming returns OutgoingMessage."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = MatrixChannel(runtime)

        message = IncomingMessage(
            message_id="matrix-msg-001",
            channel=ChannelType.MATRIX,
            question="How do I run a Bisq node?",
            user=UserContext(user_id="@user:matrix.org"),
        )

        result = await channel.handle_incoming(message)

        assert isinstance(result, OutgoingMessage)
        assert result.in_reply_to == message.message_id
        assert result.channel == ChannelType.MATRIX

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_with_matrix_client(self):
        """send_message uses Matrix client to send to room."""

        # Create mock Matrix client with successful send
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$event123"
        mock_client.room_send = AsyncMock(return_value=mock_response)
        mock_client.rooms = {"!room:matrix.org": MagicMock()}

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        outgoing.in_reply_to = "$question-event"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        mock_client.room_send.assert_called_once()
        sent_content = mock_client.room_send.call_args.kwargs["content"]
        assert sent_content["format"] == "org.matrix.custom.html"
        assert "formatted_body" in sent_content
        assert (
            sent_content["m.relates_to"]["m.in_reply_to"]["event_id"]
            == "$question-event"
        )
        assert (
            mock_client.room_send.call_args.kwargs["ignore_unverified_devices"] is True
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_recovers_missing_room_and_retries(self):
        """send_message retries once after recovering missing local room state."""

        class MockRoomSendError:
            message = "No such room with id !room:matrix.org found."

        mock_client = MagicMock()
        mock_client.rooms = {}
        success = MagicMock()
        success.event_id = "$event456"
        mock_client.room_send = AsyncMock(side_effect=[MockRoomSendError(), success])
        mock_client.sync = AsyncMock(return_value=MagicMock())
        mock_client.join = AsyncMock(return_value=MagicMock(room_id="!room:matrix.org"))

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        assert mock_client.room_send.await_count == 2
        mock_client.sync.assert_called_once()
        mock_client.join.assert_called_once_with("!room:matrix.org")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_honors_ignore_unverified_toggle(self):
        """send_message can enforce verified devices when explicitly configured."""

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$event123"
        mock_client.room_send = AsyncMock(return_value=mock_response)
        mock_client.rooms = {"!room:matrix.org": MagicMock()}

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)
        runtime.settings = MagicMock()
        runtime.settings.MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES = False

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        assert (
            mock_client.room_send.call_args.kwargs["ignore_unverified_devices"] is False
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_uses_notice_msgtype_for_staff_notice(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$event123"
        mock_client.room_send = AsyncMock(return_value=mock_response)
        mock_client.rooms = {"!room:matrix.org": MagicMock()}

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Escalation #123 queued"
        outgoing.in_reply_to = "$question-event"
        outgoing.metadata = MagicMock()
        outgoing.metadata.routing_action = "staff_escalation_notice"

        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        sent_content = mock_client.room_send.call_args.kwargs["content"]
        assert sent_content["msgtype"] == "m.notice"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_returns_false_without_client(self):
        """send_message returns False when Matrix client not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_handles_send_error(self):
        """send_message handles Matrix send errors gracefully."""

        class MockRoomSendError:
            message = "Permission denied"

        # Create mock Matrix client that returns an error-like response
        # without event_id (matching nio error behavior).
        mock_client = MagicMock()
        mock_client.room_send = AsyncMock(return_value=MockRoomSendError())

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_reaction_sends_matrix_reaction_event(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$reaction123"
        mock_client.room_send = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        sent = await channel.send_reaction(
            room_id="!room:matrix.org",
            event_id="$target123",
            key="👀",
        )

        assert bool(sent) is True
        call_kwargs = mock_client.room_send.call_args.kwargs
        assert call_kwargs["room_id"] == "!room:matrix.org"
        assert call_kwargs["message_type"] == "m.reaction"
        assert call_kwargs["content"]["m.relates_to"]["event_id"] == "$target123"
        assert call_kwargs["content"]["m.relates_to"]["key"] == "👀"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_reaction_returns_false_without_matrix_client(self):
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)

        sent = await channel.send_reaction(
            room_id="!room:matrix.org",
            event_id="$target123",
            key="👀",
        )
        assert sent is False


class TestMatrixChannelRoomManagement:
    """Test MatrixChannel room management."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_with_matrix_client(self):
        """join_room uses Matrix client to join room."""

        # Create mock Matrix client with successful join
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.room_id = "!room:matrix.org"
        mock_client.join = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.join_room("!room:matrix.org")

        assert bool(result) is True
        mock_client.join.assert_called_once_with("!room:matrix.org")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_returns_false_without_client(self):
        """join_room returns False when Matrix client not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        result = await channel.join_room("!room:matrix.org")

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_handles_join_error(self):
        """join_room handles Matrix join errors gracefully."""

        # Create mock Matrix client that returns error
        mock_client = MagicMock()
        mock_error = MagicMock()
        mock_error.room_id = None  # Error responses don't have room_id
        mock_error.message = "Room not found"
        mock_client.join = AsyncMock(return_value=mock_error)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.join_room("!room:matrix.org")

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_with_matrix_client(self):
        """leave_room uses Matrix client to leave room."""

        # Create mock Matrix client with successful leave
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.room_id = "!room:matrix.org"  # Has room_id on success
        mock_client.room_leave = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.leave_room("!room:matrix.org")

        assert bool(result) is True
        mock_client.room_leave.assert_called_once_with("!room:matrix.org")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_returns_false_without_client(self):
        """leave_room returns False when Matrix client not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        result = await channel.leave_room("!room:matrix.org")

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_handles_leave_error(self):
        """leave_room handles Matrix leave errors gracefully."""

        # Create mock Matrix client that returns error
        mock_client = MagicMock()
        mock_error = MagicMock()
        mock_error.room_id = None  # Error responses don't have room_id
        mock_error.message = "Not a member"
        mock_client.room_leave = AsyncMock(return_value=mock_error)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.leave_room("!room:matrix.org")

        assert bool(result) is False
