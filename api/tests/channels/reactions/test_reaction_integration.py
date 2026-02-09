"""Integration tests for channel wiring with reaction support.

Covers:
- OutgoingMessage has original_question field
- ChannelCapability.REACTIONS exists
- MatrixChannel includes REACTIONS capability
- MatrixChannel.send_message() tracks sent messages via SentMessageTracker
- MatrixChannel.start()/stop() wire reaction handler
- Bisq2Channel includes REACTIONS and SEND_RESPONSES capabilities
- Bisq2Channel.send_message() sends via REST and tracks messages
- Bisq2Channel.start()/stop() wire reaction handler
- ChannelBase.handle_incoming() sets original_question
- ChannelGateway._build_outgoing_message() sets original_question
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import ChannelCapability, ChannelType, OutgoingMessage

# ---------------------------------------------------------------------------
# OutgoingMessage.original_question
# ---------------------------------------------------------------------------


class TestOutgoingMessageOriginalQuestion:
    """Test original_question field on OutgoingMessage."""

    def _make_outgoing(self, **kwargs):
        from app.channels.models import ResponseMetadata, UserContext

        defaults = dict(
            message_id="m1",
            in_reply_to="m0",
            channel=ChannelType.WEB,
            answer="A",
            user=UserContext(user_id="user1"),
            metadata=ResponseMetadata(
                processing_time_ms=10.0,
                rag_strategy="test",
                model_name="test",
            ),
        )
        defaults.update(kwargs)
        return OutgoingMessage(**defaults)

    def test_original_question_default_none(self):
        """original_question defaults to None."""
        msg = self._make_outgoing()
        assert msg.original_question is None

    def test_original_question_can_be_set(self):
        """original_question can be set explicitly."""
        msg = self._make_outgoing(original_question="What is Bisq?")
        assert msg.original_question == "What is Bisq?"


# ---------------------------------------------------------------------------
# ChannelCapability.REACTIONS
# ---------------------------------------------------------------------------


class TestReactionsCapability:
    """Test REACTIONS capability enum value."""

    def test_reactions_capability_exists(self):
        """REACTIONS is a valid ChannelCapability."""
        assert hasattr(ChannelCapability, "REACTIONS")
        assert ChannelCapability.REACTIONS.value == "reactions"


# ---------------------------------------------------------------------------
# MatrixChannel REACTIONS capability
# ---------------------------------------------------------------------------


class TestMatrixChannelReactionsCapability:
    """Test MatrixChannel includes REACTIONS in capabilities."""

    def test_matrix_has_reactions_capability(self):
        """MatrixChannel capabilities include REACTIONS."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.REACTIONS in channel.capabilities


# ---------------------------------------------------------------------------
# MatrixChannel.send_message() tracking
# ---------------------------------------------------------------------------


class TestMatrixSendMessageTracking:
    """Test send_message() tracks sent messages via SentMessageTracker."""

    @pytest.mark.asyncio
    async def test_send_message_tracks_via_tracker(self):
        """After successful send, tracker.track() is called."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$evt:server"
        mock_client.room_send = AsyncMock(return_value=mock_response)

        mock_tracker = MagicMock()
        mock_tracker.track = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "matrix_client":
                return mock_client
            if name == "sent_message_tracker":
                return mock_tracker
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        outgoing.message_id = "internal-123"
        outgoing.original_question = "What is Bisq?"
        outgoing.user = MagicMock()
        outgoing.user.user_id = "user1"
        outgoing.sources = []

        result = await channel.send_message("!room:server", outgoing)

        assert result is True
        mock_tracker.track.assert_called_once()
        call_kwargs = mock_tracker.track.call_args.kwargs
        assert call_kwargs["channel_id"] == "matrix"
        assert call_kwargs["external_message_id"] == "$evt:server"
        assert call_kwargs["internal_message_id"] == "internal-123"

    @pytest.mark.asyncio
    async def test_send_message_no_tracker_still_succeeds(self):
        """Send succeeds even when tracker is not registered."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$evt:server"
        mock_client.room_send = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "matrix_client":
                return mock_client
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"

        result = await channel.send_message("!room:server", outgoing)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_message_no_tracking_on_failure(self):
        """Tracker is NOT called when send fails."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        mock_client = MagicMock()
        mock_client.room_send = AsyncMock(side_effect=Exception("Network error"))

        mock_tracker = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "matrix_client":
                return mock_client
            if name == "sent_message_tracker":
                return mock_tracker
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"

        result = await channel.send_message("!room:server", outgoing)
        assert result is False
        mock_tracker.track.assert_not_called()


# ---------------------------------------------------------------------------
# MatrixChannel start/stop wiring
# ---------------------------------------------------------------------------


class TestMatrixChannelReactionWiring:
    """Test start()/stop() wire the reaction handler."""

    @pytest.mark.asyncio
    async def test_start_calls_handler_start_listening(self):
        """start() calls reaction handler's start_listening()."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()

        mock_handler = MagicMock()
        mock_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "matrix_connection_manager":
                return mock_conn
            if name == "matrix_reaction_handler":
                return mock_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = MatrixChannel(runtime)
        await channel.start()

        mock_handler.start_listening.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_calls_handler_stop_listening(self):
        """stop() calls reaction handler's stop_listening()."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        mock_conn = MagicMock()
        mock_conn.disconnect = AsyncMock()

        mock_handler = MagicMock()
        mock_handler.stop_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "matrix_connection_manager":
                return mock_conn
            if name == "matrix_reaction_handler":
                return mock_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = MatrixChannel(runtime)
        channel._is_connected = True
        await channel.stop()

        mock_handler.stop_listening.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_without_handler_still_works(self):
        """start() works even without reaction handler registered."""
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        mock_conn = MagicMock()
        mock_conn.connect = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "matrix_connection_manager":
                return mock_conn
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = MatrixChannel(runtime)
        await channel.start()

        assert channel.is_connected is True


# ---------------------------------------------------------------------------
# ChannelBase.handle_incoming sets original_question
# ---------------------------------------------------------------------------


class TestHandleIncomingOriginalQuestion:
    """Test that handle_incoming sets original_question on OutgoingMessage."""

    @pytest.mark.asyncio
    async def test_handle_incoming_sets_original_question(self, mock_rag_service):
        """handle_incoming populates original_question from message.question."""
        from app.channels.models import IncomingMessage, UserContext
        from app.channels.plugins.matrix.channel import MatrixChannel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = MatrixChannel(runtime)

        message = IncomingMessage(
            message_id="msg-1",
            channel=ChannelType.MATRIX,
            question="How do I set up Bisq 2?",
            user=UserContext(user_id="@user:matrix.org"),
        )

        result = await channel.handle_incoming(message)
        assert result.original_question == "How do I set up Bisq 2?"


# ---------------------------------------------------------------------------
# ChannelGateway._build_outgoing_message sets original_question
# ---------------------------------------------------------------------------


class TestGatewayOriginalQuestion:
    """Test that gateway sets original_question."""

    def test_build_outgoing_message_sets_original_question(self):
        """_build_outgoing_message populates original_question."""
        from app.channels.gateway import ChannelGateway
        from app.channels.models import IncomingMessage, UserContext

        rag = MagicMock()
        gw = ChannelGateway(rag_service=rag)

        incoming = IncomingMessage(
            message_id="msg-1",
            channel=ChannelType.WEB,
            question="What is Bisq?",
            user=UserContext(user_id="user1"),
        )

        outgoing = gw._build_outgoing_message(
            incoming=incoming,
            rag_response={"answer": "Bisq is a DEX", "strategy": "retrieval"},
            processing_time_ms=100.0,
            hooks_executed=[],
        )
        assert outgoing.original_question == "What is Bisq?"


# ---------------------------------------------------------------------------
# Bisq2Channel REACTIONS + SEND_RESPONSES capabilities
# ---------------------------------------------------------------------------


class TestBisq2ChannelReactionsCapability:
    """Test Bisq2Channel includes REACTIONS and SEND_RESPONSES capabilities."""

    def test_bisq2_has_reactions_capability(self):
        """Bisq2Channel capabilities include REACTIONS."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.REACTIONS in channel.capabilities

    def test_bisq2_has_send_responses_capability(self):
        """Bisq2Channel capabilities include SEND_RESPONSES."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        channel = Bisq2Channel(runtime)
        assert ChannelCapability.SEND_RESPONSES in channel.capabilities


# ---------------------------------------------------------------------------
# Bisq2Channel.send_message() REST send + tracking
# ---------------------------------------------------------------------------


class TestBisq2SendMessage:
    """Test Bisq2Channel.send_message() sends via REST and tracks."""

    @pytest.mark.asyncio
    async def test_send_message_calls_bisq_api(self):
        """send_message calls bisq_api.send_support_message()."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.send_support_message = AsyncMock(
            return_value={"messageId": "bisq-msg-1", "timestamp": 1700000000}
        )
        mock_tracker = MagicMock()
        mock_tracker.track = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            if name == "sent_message_tracker":
                return mock_tracker
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Bisq is a DEX"
        outgoing.message_id = "internal-42"
        outgoing.original_question = "What is Bisq?"
        outgoing.user = MagicMock()
        outgoing.user.user_id = "user-abc"
        outgoing.sources = []

        result = await channel.send_message("conv-123", outgoing)

        assert result is True
        mock_api.send_support_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_tracks_via_tracker(self):
        """After successful send, tracker.track() is called with correct args."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.send_support_message = AsyncMock(
            return_value={"messageId": "bisq-msg-99", "timestamp": 1700000000}
        )
        mock_tracker = MagicMock()
        mock_tracker.track = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            if name == "sent_message_tracker":
                return mock_tracker
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Answer text"
        outgoing.message_id = "internal-55"
        outgoing.original_question = "Question?"
        outgoing.user = MagicMock()
        outgoing.user.user_id = "user-xyz"
        outgoing.sources = []

        await channel.send_message("conv-1", outgoing)

        mock_tracker.track.assert_called_once()
        call_kwargs = mock_tracker.track.call_args.kwargs
        assert call_kwargs["channel_id"] == "bisq2"
        assert call_kwargs["external_message_id"] == "bisq-msg-99"
        assert call_kwargs["internal_message_id"] == "internal-55"

    @pytest.mark.asyncio
    async def test_send_message_returns_false_on_failure(self):
        """send_message returns False when API call fails."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.send_support_message = AsyncMock(side_effect=Exception("API error"))

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Answer"

        result = await channel.send_message("conv-1", outgoing)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_returns_false_when_no_api(self):
        """send_message returns False when bisq2_api not registered."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Answer"

        result = await channel.send_message("conv-1", outgoing)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_returns_false_on_empty_response(self):
        """send_message returns False when API returns empty dict (404)."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.send_support_message = AsyncMock(return_value={})

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Answer"

        result = await channel.send_message("conv-1", outgoing)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_no_tracking_on_failure(self):
        """Tracker is NOT called when send fails."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.send_support_message = AsyncMock(side_effect=Exception("fail"))
        mock_tracker = MagicMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            if name == "sent_message_tracker":
                return mock_tracker
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Answer"

        await channel.send_message("conv-1", outgoing)
        mock_tracker.track.assert_not_called()


# ---------------------------------------------------------------------------
# Bisq2Channel start/stop wiring
# ---------------------------------------------------------------------------


class TestBisq2ChannelReactionWiring:
    """Test Bisq2 start()/stop() wire the reaction handler."""

    @pytest.mark.asyncio
    async def test_start_calls_handler_start_listening(self):
        """start() calls reaction handler's start_listening()."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.setup = AsyncMock()

        mock_handler = MagicMock()
        mock_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            if name == "bisq2_reaction_handler":
                return mock_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)
        await channel.start()

        mock_handler.start_listening.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_calls_handler_stop_listening(self):
        """stop() calls reaction handler's stop_listening()."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_handler = MagicMock()
        mock_handler.stop_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_reaction_handler":
                return mock_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)
        channel._is_connected = True
        await channel.stop()

        mock_handler.stop_listening.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_without_handler_still_works(self):
        """start() works even without reaction handler registered."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_api = MagicMock()
        mock_api.setup = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional_side_effect(name):
            if name == "bisq2_api":
                return mock_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional_side_effect)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel.is_connected is True
