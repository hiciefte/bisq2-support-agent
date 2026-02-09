"""Tests for Web Channel Plugin.

TDD tests for the Web channel plugin that wraps existing chat.py logic.
"""

from unittest.mock import MagicMock

import pytest
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    ChatMessage,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)


class TestWebChannelProperties:
    """Test WebChannel properties and identification."""

    @pytest.mark.unit
    def test_channel_id_is_web(self):
        """WebChannel has channel_id 'web'."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)
        assert channel.channel_id == "web"

    @pytest.mark.unit
    def test_capabilities_include_text_messages(self):
        """WebChannel supports text message capability."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)
        assert ChannelCapability.TEXT_MESSAGES in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_include_chat_history(self):
        """WebChannel supports chat history capability."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)
        assert ChannelCapability.CHAT_HISTORY in channel.capabilities


class TestWebChannelLifecycle:
    """Test WebChannel lifecycle methods."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_succeeds(self):
        """WebChannel starts successfully."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)
        await channel.start()
        assert channel.is_connected is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds(self):
        """WebChannel stops successfully."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)
        await channel.start()
        await channel.stop()
        assert channel.is_connected is False

    @pytest.mark.unit
    def test_health_check_returns_healthy_when_connected(self):
        """Health check returns healthy when connected."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)
        channel._is_connected = True
        status = channel.health_check()
        assert status.healthy is True


class TestWebChannelMessageHandling:
    """Test WebChannel message handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_calls_rag_service(self, mock_rag_service):
        """handle_incoming delegates to RAG service."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = WebChannel(runtime)

        message = IncomingMessage(
            message_id="test-001",
            channel=ChannelType.WEB,
            question="How do I backup my wallet?",
            user=UserContext(user_id="test-user"),
        )

        await channel.handle_incoming(message)

        mock_rag_service.query.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_passes_chat_history(self, mock_rag_service):
        """Chat history passed to RAG service."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = WebChannel(runtime)

        message = IncomingMessage(
            message_id="test-001",
            channel=ChannelType.WEB,
            question="What about Bisq 2?",
            user=UserContext(user_id="test-user"),
            chat_history=[
                ChatMessage(role="user", content="How do I backup?"),
                ChatMessage(role="assistant", content="You can backup by..."),
            ],
        )

        await channel.handle_incoming(message)

        call_args = mock_rag_service.query.call_args
        assert call_args is not None
        # Verify chat_history was passed
        assert call_args.kwargs.get("chat_history") == [
            {"role": msg.role, "content": msg.content}
            for msg in message.chat_history or []
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_returns_outgoing_message(self, mock_rag_service):
        """handle_incoming returns OutgoingMessage."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = WebChannel(runtime)

        message = IncomingMessage(
            message_id="test-001",
            channel=ChannelType.WEB,
            question="How do I backup my wallet?",
            user=UserContext(user_id="test-user"),
        )

        result = await channel.handle_incoming(message)

        assert isinstance(result, OutgoingMessage)
        assert result.in_reply_to == message.message_id
        assert result.channel == ChannelType.WEB

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_returns_true(self):
        """send_message returns True on success."""
        from app.channels.plugins.web.channel import WebChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = WebChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        result = await channel.send_message("web_user", outgoing)

        # Web channel doesn't actively push, so send_message is a no-op
        assert result is True
