"""Tests for Bisq2 Channel Plugin.

TDD tests for the Bisq2 channel plugin that wraps existing bisq_api.py logic.

Note: FAQ extraction is handled by the training pipeline (Bisq2SyncService),
not by the channel plugin. Bisq2 sends responses via REST API.
"""

import asyncio
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
    def test_capabilities_include_send_responses(self):
        """Bisq2Channel supports sending responses via REST API."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.SEND_RESPONSES in channel.capabilities

    @pytest.mark.unit
    def test_get_delivery_target_prefers_conversation_id(self):
        """Delivery target uses conversation_id when present."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        target = channel.get_delivery_target(
            {
                "conversation_id": "support.conv-1",
                "channel_id": "support.support",
            }
        )
        assert target == "support.conv-1"

    @pytest.mark.unit
    def test_get_delivery_target_falls_back_to_channel_id(self):
        """Delivery target falls back to channel_id for legacy metadata rows."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        target = channel.get_delivery_target(
            {
                "conversation_id": "",
                "channel_id": "support.support",
            }
        )
        assert target == "support.support"


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

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

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

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

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
    @pytest.mark.asyncio
    async def test_start_subscribes_to_support_chat_websocket_topics(self):
        """When WS client is present, channel subscribes to support message topic."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": "2026-02-20T12:00:00Z", "messages": []}
        )
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(return_value={"success": True})
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()
        await channel.stop()

        mock_ws_client.connect.assert_awaited_once()
        mock_ws_client.subscribe.assert_awaited_once_with("SUPPORT_CHAT_MESSAGES")
        mock_bisq_api.export_chat_messages.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_primes_rest_fallback_cursor_when_websocket_enabled(self):
        """WS startup primes REST cursor to avoid replaying full history on fallback polls."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={
                "exportDate": "2026-02-20T12:00:00Z",
                "messages": [
                    {
                        "messageId": "old-msg-1",
                        "author": "old-user",
                        "message": "stale",
                        "conversationId": "support.support",
                    }
                ],
            }
        )
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(return_value={"success": True})
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel._last_poll_since is not None
        mock_bisq_api.export_chat_messages.assert_awaited_once()
        mock_bisq_api.export_chat_messages.assert_awaited_with(since=None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_does_not_prime_rest_cursor_without_websocket(self):
        """Without WS, startup should not trigger REST export prefetch."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": "2026-02-20T12:00:00Z", "messages": []}
        )

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel._last_poll_since is None
        mock_bisq_api.export_chat_messages.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_does_not_hang_when_websocket_subscribe_stalls(self):
        """WS subscribe stall should not block channel startup indefinitely."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        async def stalled_subscribe(*_args, **_kwargs):
            await asyncio.sleep(10)
            return {"success": True}

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(side_effect=stalled_subscribe)
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_WS_STARTUP_TIMEOUT_SECONDS = 0.01

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await asyncio.wait_for(channel.start(), timeout=0.2)

        assert channel.is_connected is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_primes_seen_ids_to_prevent_rest_replay_when_since_is_ignored(
        self,
    ):
        """Startup prime should seed seen IDs so fallback poll won't replay old messages."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        replay_message = {
            "messageId": "old-msg-1",
            "author": "old-user",
            "message": "stale replay candidate",
            "conversationId": "support.support",
            "date": "2026-02-20T12:00:00Z",
        }

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            side_effect=[
                {
                    "exportDate": "2026-02-20T12:00:01.000Z",
                    "messages": [replay_message],
                },
                {
                    "exportDate": "2026-02-20T12:00:02.000Z",
                    "messages": [replay_message],
                },
            ]
        )
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(return_value={"success": True})
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_WS_REST_FALLBACK_INTERVAL_SECONDS = 0

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()
        messages = await channel.poll_conversations()

        assert messages == []
        assert mock_bisq_api.export_chat_messages.await_count == 2

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
    async def test_send_message_returns_false_without_api(self):
        """send_message returns False when bisq2_api is not registered."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
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
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
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
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
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
    async def test_poll_conversations_uses_author_id_for_user_context(self):
        """poll_conversations should use authorId when author contains spaces."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={
                "messages": [
                    {
                        "messageId": "msg-ask-ai-001",
                        "author": "Dumb User",
                        "authorId": "5afc36130d02d81d7130e6a6cc4dc5fc19526f05",
                        "message": "What is Bisq Easy?",
                        "conversationId": "support.support",
                        "date": "2026-02-19T20:17:39.218Z",
                    }
                ]
            }
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert messages[0].user.user_id == "5afc36130d02d81d7130e6a6cc4dc5fc19526f05"
        assert messages[0].user.channel_user_id == "Dumb User"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_uses_sender_profile_id_when_author_id_missing(
        self,
    ):
        """senderUserProfileId should be used as stable user identity when present."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={
                "messages": [
                    {
                        "messageId": "msg-sender-id-001",
                        "author": "Dumb User",
                        "senderUserProfileId": "sender-user-123",
                        "message": "Is this user identity stable?",
                        "conversationId": "support.support",
                        "date": "2026-02-25T10:00:00Z",
                    }
                ]
            }
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert messages[0].user.user_id == "sender-user-123"
        assert messages[0].user.channel_user_id == "Dumb User"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_prefers_sender_profile_id_over_author_id(self):
        """senderUserProfileId should win when both sender and author IDs are provided."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={
                "messages": [
                    {
                        "messageId": "msg-both-id-001",
                        "author": "Dumb User",
                        "authorId": "author-id-legacy",
                        "senderUserProfileId": "sender-id-current",
                        "message": "Which identifier is preferred?",
                        "conversationId": "support.support",
                        "date": "2026-02-25T10:00:00Z",
                    }
                ]
            }
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert messages[0].user.user_id == "sender-id-current"

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
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
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
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
        channel = Bisq2Channel(runtime)

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert messages[0].message_id == "msg-002"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_prefers_websocket_buffer_over_rest_export(self):
        """Buffered SUPPORT_CHAT_MESSAGES should be consumed before REST fallback."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(return_value={"messages": []})
        mock_ws_client = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "ws-msg-001",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "5afc36130d02d81d7130e6a6cc4dc5fc19526f05",
                    "text": "What is Bisq Easy?",
                    "timestamp": 1760000000000,
                },
            }
        )

        messages = await channel.poll_conversations()

        assert len(messages) == 1
        assert messages[0].message_id == "ws-msg-001"
        assert messages[0].question == "What is Bisq Easy?"
        mock_bisq_api.export_chat_messages.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_deduplicates_seen_messages(self):
        """Seen message IDs should not be emitted again on a follow-up poll."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        repeated_message = {
            "messageId": "msg-repeat-1",
            "author": "Dumb User",
            "authorId": "user-123",
            "message": "Repeated question?",
            "conversationId": "support.support",
            "date": "2026-02-20T15:33:23.966Z",
        }
        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(
            side_effect=[
                {
                    "exportDate": "2026-02-20T15:33:24.000Z",
                    "messages": [repeated_message],
                },
                {
                    "exportDate": "2026-02-20T15:34:25.000Z",
                    "messages": [repeated_message],
                },
            ]
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
        channel = Bisq2Channel(runtime)

        first_poll = await channel.poll_conversations()
        second_poll = await channel.poll_conversations()

        assert len(first_poll) == 1
        assert first_poll[0].message_id == "msg-repeat-1"
        assert second_poll == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_support_reaction_events_do_not_create_incoming_messages(self):
        """Support reactions are ignored as incoming-question triggers."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_REACTIONS",
                "modificationType": "ADDED",
                "payload": {
                    "reaction": "ROBOT",
                    "messageId": "msg-1",
                    "senderUserProfileId": "user-1",
                },
            }
        )

        messages = await channel.poll_conversations()
        assert messages == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_builds_thread_history_for_follow_up(self):
        """Follow-up user message should include prior user/staff context but exclude unrelated users."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        author_id = "user-123"
        staff_id = "staff-001"
        other_user_id = "other-user-001"

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value in {
            staff_id,
            "Support Staff",
        }

        def resolve_optional(name: str):
            if name == "staff_resolver":
                return staff_resolver
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "ctx-user-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": author_id,
                    "author": "Dumb User",
                    "text": "What is the best payment method for EUR?",
                    "timestamp": 1760000000000,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "ctx-other-user",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": other_user_id,
                    "author": "Another User",
                    "text": "Completely unrelated question",
                    "timestamp": 1760000000200,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "ctx-staff-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": staff_id,
                    "author": "Support Staff",
                    "text": "SEPA is usually best for EUR.",
                    "citationMessageId": "ctx-user-1",
                    "timestamp": 1760000000300,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "ctx-follow-up",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": author_id,
                    "author": "Dumb User",
                    "text": "And what about USD?",
                    "timestamp": 1760000000400,
                },
            }
        )

        messages = await channel.poll_conversations()
        by_id = {message.message_id: message for message in messages}
        follow_up = by_id["ctx-follow-up"]

        assert follow_up.chat_history is not None
        history_text = [item.content for item in follow_up.chat_history or []]
        assert "What is the best payment method for EUR?" in history_text
        assert "SEPA is usually best for EUR." in history_text
        assert "And what about USD?" in history_text
        assert "Completely unrelated question" not in history_text

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_filters_staff_messages_from_incoming_queue(self):
        """Trusted staff messages must not be forwarded as incoming user questions."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value in {
            "staff-001",
            "Support Staff",
        }

        def resolve_optional(name: str):
            if name == "staff_resolver":
                return staff_resolver
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "staff-msg-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "staff-001",
                    "author": "Support Staff",
                    "text": "Please provide logs.",
                    "timestamp": 1760000000000,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "user-msg-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-123",
                    "author": "Dumb User",
                    "text": "Here are my logs.",
                    "timestamp": 1760000000100,
                },
            }
        )

        messages = await channel.poll_conversations()
        assert [message.message_id for message in messages] == ["user-msg-1"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_filters_non_question_noise_messages(self):
        """Non-question chatter should be dropped before invoking RAG."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "noise-greeting",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Dumb User",
                    "text": "Hello",
                    "timestamp": 1760000000000,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "noise-emoji",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Dumb User",
                    "text": "👍",
                    "timestamp": 1760000000100,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "real-question",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Dumb User",
                    "text": "How do I back up Bisq2?",
                    "timestamp": 1760000000200,
                },
            }
        )

        messages = await channel.poll_conversations()
        assert [message.message_id for message in messages] == ["real-question"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_keeps_short_follow_up_messages(self):
        """Short follow-up messages should remain eligible for context-aware answers."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "base-question",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Dumb User",
                    "text": "What is the best EUR payment method?",
                    "timestamp": 1760000000000,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "short-follow-up",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Dumb User",
                    "text": "USD",
                    "citationMessageId": "base-question",
                    "timestamp": 1760000000100,
                },
            }
        )

        messages = await channel.poll_conversations()
        assert [message.message_id for message in messages] == [
            "base-question",
            "short-follow-up",
        ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_marks_self_sent_message_as_seen():
    """Self-sent Bisq2 messages are marked seen to avoid re-processing."""
    from app.channels.models import ResponseMetadata
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    mock_bisq_api = MagicMock()
    mock_bisq_api.send_support_message = AsyncMock(
        return_value={"messageId": "self-msg-1"}
    )

    runtime = MagicMock(spec=ChannelRuntime)

    def resolve_optional(name: str):
        if name == "bisq2_api":
            return mock_bisq_api
        if name == "sent_message_tracker":
            return None
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
    channel = Bisq2Channel(runtime)

    outgoing = OutgoingMessage(
        message_id="out-1",
        in_reply_to="in-1",
        channel=ChannelType.BISQ2,
        answer="Here is your answer.",
        sources=[],
        user=UserContext(user_id="user-1"),
        metadata=ResponseMetadata(
            processing_time_ms=1.0,
            rag_strategy="retrieval",
            model_name="test-model",
        ),
        original_question="Question?",
    )

    sent = await channel.send_message("support.support", outgoing)

    assert sent is True
    assert "self-msg-1" in channel._seen_message_ids
