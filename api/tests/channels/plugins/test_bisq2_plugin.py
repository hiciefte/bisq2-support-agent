"""Tests for Bisq2 Channel Plugin.

TDD tests for the Bisq2 channel plugin that wraps existing bisq_api.py logic.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (ChannelCapability, ChannelType, IncomingMessage,
                                 OutgoingMessage, UserContext)


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
    def test_capabilities_include_extract_faqs(self):
        """Bisq2Channel supports FAQ extraction capability."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.EXTRACT_FAQS in channel.capabilities


class TestBisq2ChannelLifecycle:
    """Test Bisq2Channel lifecycle methods."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_succeeds(self):
        """Bisq2Channel starts successfully."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_API_URL = "http://bisq2-api:8090"
        channel = Bisq2Channel(runtime)
        await channel.start()
        assert channel.is_connected is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds(self):
        """Bisq2Channel stops successfully."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_API_URL = "http://bisq2-api:8090"
        channel = Bisq2Channel(runtime)
        await channel.start()
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

        result = await channel.handle_incoming(message)

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
    async def test_send_message_returns_true(self):
        """send_message returns True (fire-and-forget to Bisq2 API)."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        result = await channel.send_message("bisq2-conversation-id", outgoing)

        assert result is True


class TestBisq2ChannelPolling:
    """Test Bisq2Channel conversation polling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_returns_list(self):
        """poll_conversations returns list of messages."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_API_URL = "http://bisq2-api:8090"
        channel = Bisq2Channel(runtime)

        # Mock the poll method to return empty list
        channel._poll_api = AsyncMock(return_value=[])

        messages = await channel.poll_conversations()

        assert isinstance(messages, list)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_extract_faqs_returns_list(self):
        """extract_faqs returns list of FAQ entries."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        channel = Bisq2Channel(runtime)

        # Mock FAQ extraction
        channel._extract_faqs_from_conversations = AsyncMock(return_value=[])

        faqs = await channel.extract_faqs([])

        assert isinstance(faqs, list)
