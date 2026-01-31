"""Tests for Matrix Channel Plugin.

TDD tests for the Matrix channel plugin that wraps existing matrix integration.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (ChannelCapability, ChannelType, IncomingMessage,
                                 OutgoingMessage, UserContext)


class TestMatrixChannelProperties:
    """Test MatrixChannel properties and identification."""

    @pytest.mark.unit
    def test_channel_id_is_matrix(self):
        """MatrixChannel has channel_id 'matrix'."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert channel.channel_id == "matrix"

    @pytest.mark.unit
    def test_capabilities_include_text_messages(self):
        """MatrixChannel supports text message capability."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.TEXT_MESSAGES in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_include_persistent_connection(self):
        """MatrixChannel supports persistent connection capability."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.PERSISTENT_CONNECTION in channel.capabilities


class TestMatrixChannelLifecycle:
    """Test MatrixChannel lifecycle methods."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_succeeds(self):
        """MatrixChannel starts successfully."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        runtime.settings.MATRIX_USER_ID = "@bot:matrix.org"
        channel = MatrixChannel(runtime)

        # Mock the client connection
        channel._connect_to_homeserver = AsyncMock()

        await channel.start()
        assert channel.is_connected is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds(self):
        """MatrixChannel stops successfully."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        channel = MatrixChannel(runtime)
        channel._is_connected = True

        # Mock the client disconnection
        channel._disconnect_from_homeserver = AsyncMock()

        await channel.stop()
        assert channel.is_connected is False

    @pytest.mark.unit
    def test_health_check_returns_healthy_when_connected(self):
        """Health check returns healthy when connected."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        channel._is_connected = True
        status = channel.health_check()
        assert status.healthy is True

    @pytest.mark.unit
    def test_health_check_returns_unhealthy_when_disconnected(self):
        """Health check returns unhealthy when disconnected."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

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
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

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

        mock_rag_service.query.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_returns_outgoing_message(self, mock_rag_service):
        """handle_incoming returns OutgoingMessage."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

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
    async def test_send_message_returns_true_on_success(self):
        """send_message returns True when Matrix send succeeds."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)

        # Mock successful send
        channel._send_to_room = AsyncMock(return_value=True)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert result is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_returns_false_on_failure(self):
        """send_message returns False when Matrix send fails."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)

        # Mock failed send
        channel._send_to_room = AsyncMock(return_value=False)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert result is False


class TestMatrixChannelRoomManagement:
    """Test MatrixChannel room management."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_succeeds(self):
        """join_room successfully joins Matrix room."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)

        # Mock room join
        channel._join_matrix_room = AsyncMock(return_value=True)

        result = await channel.join_room("!room:matrix.org")

        assert result is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_succeeds(self):
        """leave_room successfully leaves Matrix room."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)

        # Mock room leave
        channel._leave_matrix_room = AsyncMock(return_value=True)

        result = await channel.leave_room("!room:matrix.org")

        assert result is True
