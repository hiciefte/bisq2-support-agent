"""Tests for MatrixReactionHandler.

Covers:
- Handler construction and properties
- Callback registration via start_listening / stop_listening
- Reaction event processing (m.reaction events)
- Emoji-to-rating mapping
- Redaction handling (reaction removal)
- Error handling for malformed events
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.reactions import (
    ReactionHandlerProtocol,
    ReactionProcessor,
    ReactionRating,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_runtime():
    """ChannelRuntime mock."""
    runtime = MagicMock()
    runtime.resolve = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)
    return runtime


@pytest.fixture()
def mock_processor():
    """ReactionProcessor mock with async process/revoke."""
    processor = MagicMock(spec=ReactionProcessor)
    processor.process = AsyncMock(return_value=True)
    processor.revoke_reaction = AsyncMock(return_value=True)
    return processor


@pytest.fixture()
def handler(mock_runtime, mock_processor):
    """MatrixReactionHandler instance."""
    from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler

    return MatrixReactionHandler(runtime=mock_runtime, processor=mock_processor)


# ---------------------------------------------------------------------------
# Construction & Properties
# ---------------------------------------------------------------------------


class TestMatrixReactionHandlerConstruction:
    """Test handler construction and basic properties."""

    def test_channel_id_is_matrix(self, handler):
        """channel_id is 'matrix'."""
        assert handler.channel_id == "matrix"

    def test_implements_protocol(self, handler):
        """Handler satisfies ReactionHandlerProtocol."""
        assert isinstance(handler, ReactionHandlerProtocol)

    def test_stores_runtime(self, handler, mock_runtime):
        """Runtime is stored."""
        assert handler.runtime is mock_runtime

    def test_stores_processor(self, handler, mock_processor):
        """Processor is stored."""
        assert handler.processor is mock_processor

    def test_custom_emoji_map(self, mock_runtime, mock_processor):
        """Custom emoji map overrides defaults."""
        from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler

        custom = {"\U0001f44d": ReactionRating.NEGATIVE}
        h = MatrixReactionHandler(
            runtime=mock_runtime, processor=mock_processor, emoji_rating_map=custom
        )
        assert h.map_emoji_to_rating("\U0001f44d") == ReactionRating.NEGATIVE


# ---------------------------------------------------------------------------
# Callback Registration (start/stop listening)
# ---------------------------------------------------------------------------


class TestMatrixReactionHandlerListening:
    """Test start_listening / stop_listening lifecycle."""

    @pytest.mark.asyncio
    async def test_start_listening_registers_callback(self, handler, mock_runtime):
        """start_listening registers an event callback on the Matrix client."""
        mock_client = MagicMock()
        mock_client.add_event_callback = MagicMock()
        mock_runtime.resolve.return_value = mock_client

        await handler.start_listening()

        mock_runtime.resolve.assert_called_with("matrix_client")
        mock_client.add_event_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_listening_callback_target(self, handler, mock_runtime):
        """Callback is registered for the handler's _on_reaction_event."""
        mock_client = MagicMock()
        mock_client.add_event_callback = MagicMock()
        mock_runtime.resolve.return_value = mock_client

        await handler.start_listening()

        cb_args = mock_client.add_event_callback.call_args
        # First arg should be the handler's callback method
        assert callable(cb_args[0][0])

    @pytest.mark.asyncio
    async def test_stop_listening_removes_callback(self, handler, mock_runtime):
        """stop_listening removes the callback from the client."""
        mock_client = MagicMock()
        mock_client.add_event_callback = MagicMock()
        mock_client.remove_event_callback = MagicMock()
        mock_runtime.resolve_optional.return_value = mock_client

        # Start first to register
        mock_runtime.resolve.return_value = mock_client
        await handler.start_listening()

        await handler.stop_listening()

        mock_client.remove_event_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_listening_noop_when_not_started(self, handler, mock_runtime):
        """stop_listening is safe to call when not started."""
        mock_runtime.resolve_optional.return_value = None
        # Should not raise
        await handler.stop_listening()

    @pytest.mark.asyncio
    async def test_start_listening_handles_missing_client(self, handler, mock_runtime):
        """start_listening handles missing matrix_client gracefully."""
        mock_runtime.resolve.side_effect = KeyError("matrix_client")

        # Should not raise, just log
        with pytest.raises(KeyError):
            await handler.start_listening()


# ---------------------------------------------------------------------------
# Reaction Event Processing
# ---------------------------------------------------------------------------


class TestMatrixReactionEventProcessing:
    """Test _on_reaction_event processing."""

    def _make_reaction_event(
        self,
        event_id="$reaction1:server",
        relates_to_event_id="$msg1:server",
        key="\U0001f44d",
        sender="@user:server",
        origin_server_ts=1704067200000,
    ):
        """Build a mock Matrix reaction event."""
        event = MagicMock()
        event.event_id = event_id
        event.sender = sender
        event.server_timestamp = origin_server_ts
        event.source = {
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": relates_to_event_id,
                    "key": key,
                }
            }
        }
        return event

    def _make_room(self, room_id="!room:server"):
        """Build a mock room."""
        room = MagicMock()
        room.room_id = room_id
        return room

    @pytest.mark.asyncio
    async def test_processes_thumbs_up_reaction(self, handler, mock_processor):
        """Thumbs up emoji creates a POSITIVE reaction event."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44d")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE
        assert reaction_event.channel_id == "matrix"
        assert reaction_event.external_message_id == "$msg1:server"

    @pytest.mark.asyncio
    async def test_processes_thumbs_down_reaction(self, handler, mock_processor):
        """Thumbs down emoji creates a NEGATIVE reaction event."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44e")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.NEGATIVE

    @pytest.mark.asyncio
    async def test_processes_heart_reaction_as_positive(self, handler, mock_processor):
        """Heart emoji maps to POSITIVE."""
        room = self._make_room()
        event = self._make_reaction_event(key="\u2764\ufe0f")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_ignores_unmapped_emoji(self, handler, mock_processor):
        """Unmapped emojis are logged and dropped."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f389")  # party popper

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_extracts_reactor_id_from_sender(self, handler, mock_processor):
        """reactor_id comes from event.sender."""
        room = self._make_room()
        event = self._make_reaction_event(sender="@alice:matrix.org")

        await handler._on_reaction_event(room, event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.reactor_id == "@alice:matrix.org"

    @pytest.mark.asyncio
    async def test_extracts_raw_reaction_key(self, handler, mock_processor):
        """raw_reaction stores the original emoji key."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44d")

        await handler._on_reaction_event(room, event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.raw_reaction == "\U0001f44d"

    @pytest.mark.asyncio
    async def test_handles_missing_relates_to(self, handler, mock_processor):
        """Events without m.relates_to are silently dropped."""
        room = self._make_room()
        event = MagicMock()
        event.event_id = "$evt:server"
        event.sender = "@user:server"
        event.source = {"content": {}}  # No m.relates_to

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_missing_key_in_relates_to(self, handler, mock_processor):
        """Events without 'key' in m.relates_to are silently dropped."""
        room = self._make_room()
        event = MagicMock()
        event.event_id = "$evt:server"
        event.sender = "@user:server"
        event.source = {
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$msg:server",
                    # missing 'key'
                }
            }
        }

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_processor_exception(self, handler, mock_processor):
        """Processor exceptions are caught and don't crash the handler."""
        mock_processor.process = AsyncMock(side_effect=Exception("DB error"))
        room = self._make_room()
        event = self._make_reaction_event()

        # Should not raise
        await handler._on_reaction_event(room, event)


# ---------------------------------------------------------------------------
# Redaction / Reaction Removal
# ---------------------------------------------------------------------------


class TestMatrixReactionRedaction:
    """Test reaction removal via redaction events."""

    @pytest.mark.asyncio
    async def test_on_redaction_calls_revoke(self, handler, mock_processor):
        """Redaction events trigger revoke_reaction."""
        room = MagicMock()
        room.room_id = "!room:server"

        event = MagicMock()
        event.redacts = "$reaction1:server"
        event.sender = "@user:server"

        # Track the reaction event_id -> message mapping
        handler._reaction_to_message = {"$reaction1:server": "$msg1:server"}
        handler._reaction_to_sender = {"$reaction1:server": "@user:server"}

        await handler._on_redaction_event(room, event)

        mock_processor.revoke_reaction.assert_called_once_with(
            channel_id="matrix",
            external_message_id="$msg1:server",
            reactor_id="@user:server",
        )

    @pytest.mark.asyncio
    async def test_on_redaction_ignores_unknown(self, handler, mock_processor):
        """Redaction of unknown reaction is silently ignored."""
        room = MagicMock()
        room.room_id = "!room:server"

        event = MagicMock()
        event.redacts = "$unknown:server"
        event.sender = "@user:server"

        handler._reaction_to_message = {}
        handler._reaction_to_sender = {}

        await handler._on_redaction_event(room, event)

        mock_processor.revoke_reaction.assert_not_called()
