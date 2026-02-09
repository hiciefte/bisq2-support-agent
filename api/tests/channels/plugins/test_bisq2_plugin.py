"""Tests for Bisq2 Channel Plugin.

TDD tests for the Bisq2 channel plugin that wraps existing bisq_api.py logic.

Note: FAQ extraction is handled by the training pipeline (Bisq2SyncService),
not by the channel plugin. The Bisq2 API is read-only (export/polling only).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)


class TestBisq2ChannelProperties:
    """Test Bisq2Channel properties and identification."""

    @pytest.mark.unit
    def test_channel_id_is_bisq2(self):
        """Bisq2Channel has channel_id 'bisq2'."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert channel.channel_id == "bisq2"

    @pytest.mark.unit
    def test_capabilities_include_poll_conversations(self):
        """Bisq2Channel supports poll conversations capability."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.POLL_CONVERSATIONS in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_include_receive_messages(self):
        """Bisq2Channel supports receive messages capability."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.RECEIVE_MESSAGES in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_exclude_extract_faqs(self):
        """Bisq2Channel does NOT support FAQ extraction (handled by training pipeline)."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.EXTRACT_FAQS not in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_exclude_send_responses(self):
        """Bisq2Channel does NOT support sending responses (API is read-only)."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.SEND_RESPONSES not in channel.capabilities


class TestBisq2ChannelLifecycle:
    """Test Bisq2Channel lifecycle methods."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_succeeds_with_api(self):
        """Bisq2Channel starts successfully when Bisq2API is available."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        # Create mock Bisq2API
        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_bisq_api)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel.is_connected is True
        mock_bisq_api.setup.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_degraded_without_api(self):
        """Bisq2Channel starts in degraded mode when Bisq2API is not available."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = Bisq2Channel(runtime)
        await channel.start()

        # Channel starts but is not connected
        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_handles_api_connection_failure(self):
        """Bisq2Channel handles API connection failure gracefully."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        # Create mock Bisq2API that fails to connect
        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(side_effect=Exception("Connection refused"))

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_bisq_api)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds(self):
        """Bisq2Channel stops successfully."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        channel._is_connected = True
        await channel.stop()
        assert channel.is_connected is False

    @pytest.mark.unit
    def test_health_check_returns_healthy_when_connected(self):
        """Health check returns healthy when connected."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        channel._is_connected = True
        status = channel.health_check()
        assert status.healthy is True

    @pytest.mark.unit
    def test_health_check_returns_unhealthy_when_disconnected(self):
        """Health check returns unhealthy when disconnected."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        channel._is_connected = False
        status = channel.health_check()
        assert status.healthy is False


class TestBisq2ChannelMessageHandling:
    """Test Bisq2Channel message handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_calls_rag_service(self, mock_rag_service):
        """handle_incoming delegates to RAG service."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = Bisq2Channel(runtime)

        message = IncomingMessage(
            message_id="bisq2-msg-001",
            channel=ChannelType.BISQ2,
            question="How do I complete a trade?",
            user=UserContext(user_id="bisq2-user"),
        )

        await channel.handle_incoming(message)

        mock_rag_service.query.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_returns_outgoing_message(self, mock_rag_service):
        """handle_incoming returns OutgoingMessage."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = Bisq2Channel(runtime)

        message = IncomingMessage(
            message_id="bisq2-msg-001",
            channel=ChannelType.BISQ2,
            question="How do I complete a trade?",
            user=UserContext(user_id="bisq2-user"),
        )

        result = await channel.handle_incoming(message)

        assert isinstance(result, OutgoingMessage)
        assert result.in_reply_to == message.message_id
        assert result.channel == ChannelType.BISQ2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_returns_false(self):
        """send_message returns False (Bisq2 API is read-only)."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        result = await channel.send_message("bisq2-conversation-id", outgoing)

        assert result is False


class TestBisq2ChannelPolling:
    """Test Bisq2Channel conversation polling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_returns_list(self):
        """poll_conversations returns list of messages."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        # Mock Bisq2API
        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(return_value={"messages": []})

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_bisq_api)
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert isinstance(messages, list)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_without_api_returns_empty(self):
        """poll_conversations returns empty list when API not available."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert messages == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_transforms_messages(self):
        """poll_conversations transforms Bisq2 messages to IncomingMessage."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        # Mock Bisq2API with sample messages
        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={
                "messages": [
                    {
                        "messageId": "msg-001",
                        "author": "user123",
                        "message": "How do I start trading?",
                        "conversationId": "conv-001",
                        "date": "2024-01-15T10:30:00Z",
                    }
                ]
            }
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_bisq_api)
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert isinstance(messages[0], IncomingMessage)
        assert messages[0].message_id == "msg-001"
        assert messages[0].question == "How do I start trading?"
        assert messages[0].user.user_id == "user123"
        assert messages[0].channel == ChannelType.BISQ2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_handles_api_error(self):
        """poll_conversations handles API errors gracefully."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        # Mock Bisq2API that raises an error
        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            side_effect=Exception("API timeout")
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_bisq_api)
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert messages == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_skips_empty_messages(self):
        """poll_conversations skips messages with empty text."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        # Mock Bisq2API with some empty messages
        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={
                "messages": [
                    {
                        "messageId": "msg-001",
                        "author": "user123",
                        "message": "",  # Empty message
                        "conversationId": "conv-001",
                    },
                    {
                        "messageId": "msg-002",
                        "author": "user456",
                        "message": "Valid question",
                        "conversationId": "conv-001",
                    },
                ]
            }
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_bisq_api)
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert messages[0].message_id == "msg-002"
