"""Tests for MatrixReactionHandler.

Covers:
- Handler construction and properties
- Callback registration via start_listening / stop_listening
- Reaction event processing (m.reaction events)
- Emoji-to-rating mapping
- Redaction handling (reaction removal)
- Error handling for malformed events
"""

from types import SimpleNamespace
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

    return MatrixReactionHandler(
        runtime=mock_runtime,
        processor=mock_processor,
        allowed_room_ids=["!room:server"],
    )


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
            runtime=mock_runtime,
            processor=mock_processor,
            allowed_room_ids=["!room:server"],
            emoji_rating_map=custom,
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
        # Two callbacks registered: reaction + redaction
        assert mock_client.add_event_callback.call_count == 2

    @pytest.mark.asyncio
    async def test_start_listening_callback_targets(self, handler, mock_runtime):
        """Callbacks are registered for reaction and redaction events."""
        from app.channels.plugins.matrix import reaction_handler as rh

        mock_client = MagicMock()
        mock_client.add_event_callback = MagicMock()
        mock_runtime.resolve.return_value = mock_client

        await handler.start_listening()

        calls = mock_client.add_event_callback.call_args_list
        assert len(calls) == 2
        # Both should be callable handlers
        assert callable(calls[0][0][0])
        assert callable(calls[1][0][0])
        # Verify event classes (nio expects type filters, not string names)
        assert calls[0][0][1] is rh.NioReactionEvent
        assert calls[1][0][1] is rh.NioRedactionEvent

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

        # Two callbacks removed: reaction + redaction
        assert mock_client.remove_event_callback.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_listening_noop_when_not_started(self, handler, mock_runtime):
        """stop_listening is safe to call when not started."""
        mock_runtime.resolve_optional.return_value = None
        # Should not raise
        await handler.stop_listening()

    @pytest.mark.asyncio
    async def test_start_listening_raises_on_missing_client(
        self, handler, mock_runtime
    ):
        """start_listening propagates KeyError when matrix_client not registered."""
        mock_runtime.resolve.side_effect = KeyError("matrix_client")

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
        event = self._make_reaction_event(key="\U0001f921")  # clown face

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_party_reaction_as_positive(self, handler, mock_processor):
        """Party emoji maps to POSITIVE for quick-reaction parity."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f389")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_staff_escalation_reaction_uses_current_room_for_confirmation(
        self, handler, mock_runtime
    ):
        room = self._make_room(room_id="!room:server")
        event = self._make_reaction_event(
            relates_to_event_id="$staff-notice:server",
            key="\U0001f44d",
            sender="@staff:server",
        )

        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-42",
            answer="Escalation #42",
            delivery_target="",
        )
        escalation_service = MagicMock()
        escalation_service.respond_to_escalation = AsyncMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(
            return_value=SimpleNamespace(ai_draft_answer="AI draft")
        )
        client = MagicMock()
        client.room_send = AsyncMock()
        runtime_settings = SimpleNamespace(MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES=True)

        def resolve_optional(name: str):
            if name == "sent_message_tracker":
                return tracker
            if name == "staff_resolver":
                resolver = MagicMock()
                resolver.is_staff.return_value = True
                return resolver
            if name == "escalation_service":
                return escalation_service
            if name == "matrix_client":
                return client
            return None

        mock_runtime.resolve_optional.side_effect = resolve_optional
        mock_runtime.settings = runtime_settings

        await handler._on_reaction_event(room, event)

        client = mock_runtime.resolve_optional("matrix_client")
        client.room_send.assert_awaited_once()
        assert client.room_send.await_args.kwargs["room_id"] == "!room:server"

    @pytest.mark.asyncio
    async def test_processes_rocket_reaction_as_positive(self, handler, mock_processor):
        """Rocket emoji maps to POSITIVE for quick-reaction parity."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f680")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_processes_skin_tone_thumbs_up_as_positive(
        self, handler, mock_processor
    ):
        """Skin tone variants of thumbs up map to POSITIVE."""
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44d\U0001f3fd")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

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

    @pytest.mark.asyncio
    async def test_ignores_reaction_from_non_sync_room(self, handler, mock_processor):
        """Reactions from rooms outside MATRIX_SYNC_ROOMS are ignored."""
        room = self._make_room(room_id="!other:server")
        event = self._make_reaction_event()

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_not_called()


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
        handler._reaction_to_key = {"$reaction1:server": "\U0001f44d"}

        await handler._on_redaction_event(room, event)

        mock_processor.revoke_reaction.assert_called_once_with(
            channel_id="matrix",
            external_message_id="$msg1:server",
            reactor_id="@user:server",
            raw_reaction="\U0001f44d",
        )

    @pytest.mark.asyncio
    async def test_on_redaction_ignores_non_sync_room(self, handler, mock_processor):
        """Reaction redactions from non-sync rooms are ignored."""
        room = MagicMock()
        room.room_id = "!other:server"

        event = MagicMock()
        event.redacts = "$reaction1:server"
        event.sender = "@user:server"

        handler._reaction_to_message = {"$reaction1:server": "$msg1:server"}
        handler._reaction_to_sender = {"$reaction1:server": "@user:server"}
        handler._reaction_to_key = {"$reaction1:server": "\U0001f44d"}

        await handler._on_redaction_event(room, event)

        mock_processor.revoke_reaction.assert_not_called()


class TestMatrixReactionStaffActions:
    """Test staff-room escalation actions via thumbs reactions."""

    def _make_reaction_event(
        self,
        *,
        key="\U0001f44d",
        target_event_id="$staff-msg:server",
        sender="@staff:server",
    ):
        event = MagicMock()
        event.event_id = "$reaction-staff:server"
        event.sender = sender
        event.server_timestamp = 1704067200000
        event.source = {
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": target_event_id,
                    "key": key,
                }
            }
        }
        return event

    def _make_room(self, room_id="!room:server"):
        room = MagicMock()
        room.room_id = room_id
        return room

    @pytest.mark.asyncio
    async def test_thumbs_up_approves_staff_escalation_notice(
        self, handler, mock_runtime, mock_processor
    ):
        staff_resolver = SimpleNamespace(
            is_staff=lambda sender: str(sender or "").strip() == "@staff:server"
        )
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-321",
            answer="Escalation #321 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(
            return_value=SimpleNamespace(ai_draft_answer="AI draft response")
        )
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else staff_resolver if name == "staff_resolver" else None
                )
            )
        )
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44d")

        await handler._on_reaction_event(room, event)

        escalation_service.respond_to_escalation.assert_awaited_once_with(
            321, "AI draft response", "@staff:server"
        )
        escalation_service.close_escalation.assert_not_awaited()
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_thumbs_down_dismisses_staff_escalation_notice(
        self, handler, mock_runtime, mock_processor
    ):
        staff_resolver = SimpleNamespace(
            is_staff=lambda sender: str(sender or "").strip() == "@staff:server"
        )
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-654",
            answer="Escalation #654 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(return_value=MagicMock())
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else staff_resolver if name == "staff_resolver" else None
                )
            )
        )
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44e")

        await handler._on_reaction_event(room, event)

        escalation_service.close_escalation.assert_awaited_once_with(654)
        escalation_service.respond_to_escalation.assert_not_awaited()
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_staff_reaction_falls_back_to_feedback_for_non_staff_notice(
        self, handler, mock_runtime, mock_processor
    ):
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="auto_send",
            internal_message_id="msg-1",
            answer="Regular answer",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(return_value=MagicMock())
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())
        staff_resolver = SimpleNamespace(
            is_staff=lambda sender: str(sender or "").strip() == "@staff:server"
        )

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else staff_resolver if name == "staff_resolver" else None
                )
            )
        )
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44d")

        await handler._on_reaction_event(room, event)

        mock_processor.process.assert_called_once()
        escalation_service.respond_to_escalation.assert_not_awaited()
        escalation_service.close_escalation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_staff_reaction_on_staff_notice_is_ignored(
        self, handler, mock_runtime, mock_processor
    ):
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-700",
            answer="Escalation #700 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(return_value=MagicMock())
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())
        staff_resolver = SimpleNamespace(is_staff=lambda _sender: False)

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else staff_resolver if name == "staff_resolver" else None
                )
            )
        )
        room = self._make_room()
        event = self._make_reaction_event(key="\U0001f44d", sender="@alice:server")

        await handler._on_reaction_event(room, event)

        escalation_service.respond_to_escalation.assert_not_awaited()
        escalation_service.close_escalation.assert_not_awaited()
        mock_processor.process.assert_not_called()

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

    @pytest.mark.asyncio
    async def test_staff_command_send_uses_custom_reply_text(
        self, handler, mock_runtime
    ):
        staff_resolver = SimpleNamespace(
            is_staff=lambda sender: str(sender or "").strip() == "@staff:server"
        )
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-111",
            answer="Escalation #111 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(
            return_value=SimpleNamespace(ai_draft_answer="Draft from AI")
        )
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())
        matrix_client = MagicMock()
        matrix_client.room_send = AsyncMock(
            return_value=SimpleNamespace(event_id="$ok")
        )

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else (
                        matrix_client
                        if name == "matrix_client"
                        else staff_resolver if name == "staff_resolver" else None
                    )
                )
            )
        )

        handled = await handler.handle_staff_command(
            room_id="!staff:server",
            reply_to_event_id="$staff-msg:server",
            command_text="/send Edited reply from staff",
            sender="@staff:server",
        )

        assert handled is True
        escalation_service.respond_to_escalation.assert_awaited_once_with(
            111, "Edited reply from staff", "@staff:server"
        )
        escalation_service.close_escalation.assert_not_awaited()
        matrix_client.room_send.assert_awaited_once()
        sent_content = matrix_client.room_send.call_args.kwargs["content"]
        assert sent_content["msgtype"] == "m.notice"
        assert sent_content["m.relates_to"]["rel_type"] == "m.thread"
        assert (
            sent_content["m.relates_to"]["m.in_reply_to"]["event_id"]
            == "$staff-msg:server"
        )

    @pytest.mark.asyncio
    async def test_staff_command_send_without_text_uses_ai_draft(
        self, handler, mock_runtime
    ):
        staff_resolver = SimpleNamespace(
            is_staff=lambda sender: str(sender or "").strip() == "@staff:server"
        )
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-112",
            answer="Escalation #112 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(
            return_value=SimpleNamespace(ai_draft_answer="Draft from AI")
        )
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())
        matrix_client = MagicMock()
        matrix_client.room_send = AsyncMock(
            return_value=SimpleNamespace(event_id="$ok")
        )

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else (
                        matrix_client
                        if name == "matrix_client"
                        else staff_resolver if name == "staff_resolver" else None
                    )
                )
            )
        )

        handled = await handler.handle_staff_command(
            room_id="!staff:server",
            reply_to_event_id="$staff-msg:server",
            command_text="/send",
            sender="@staff:server",
        )

        assert handled is True
        escalation_service.respond_to_escalation.assert_awaited_once_with(
            112, "Draft from AI", "@staff:server"
        )
        escalation_service.close_escalation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_staff_command_dismiss_closes_escalation(self, handler, mock_runtime):
        staff_resolver = SimpleNamespace(
            is_staff=lambda sender: str(sender or "").strip() == "@staff:server"
        )
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-113",
            answer="Escalation #113 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(return_value=MagicMock())
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())
        matrix_client = MagicMock()
        matrix_client.room_send = AsyncMock(
            return_value=SimpleNamespace(event_id="$ok")
        )

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else (
                        matrix_client
                        if name == "matrix_client"
                        else staff_resolver if name == "staff_resolver" else None
                    )
                )
            )
        )

        handled = await handler.handle_staff_command(
            room_id="!staff:server",
            reply_to_event_id="$staff-msg:server",
            command_text="/dismiss",
            sender="@staff:server",
        )

        assert handled is True
        escalation_service.close_escalation.assert_awaited_once_with(113)
        escalation_service.respond_to_escalation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_staff_command_returns_false_for_non_command(self, handler):
        handled = await handler.handle_staff_command(
            room_id="!staff:server",
            reply_to_event_id="$staff-msg:server",
            command_text="plain staff chat message",
            sender="@staff:server",
        )
        assert handled is False

    @pytest.mark.asyncio
    async def test_non_staff_command_on_staff_notice_is_ignored(
        self, handler, mock_runtime
    ):
        tracker = MagicMock()
        tracker.lookup.return_value = SimpleNamespace(
            routing_action="staff_escalation_notice",
            internal_message_id="staff-escalation-114",
            answer="Escalation #114 queued",
        )
        escalation_service = MagicMock()
        escalation_service.repository = MagicMock()
        escalation_service.repository.get_by_id = AsyncMock(return_value=MagicMock())
        escalation_service.respond_to_escalation = AsyncMock(return_value=MagicMock())
        escalation_service.close_escalation = AsyncMock(return_value=MagicMock())
        staff_resolver = SimpleNamespace(is_staff=lambda _sender: False)

        mock_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                tracker
                if name == "sent_message_tracker"
                else (
                    escalation_service
                    if name == "escalation_service"
                    else staff_resolver if name == "staff_resolver" else None
                )
            )
        )

        handled = await handler.handle_staff_command(
            room_id="!staff:server",
            reply_to_event_id="$staff-msg:server",
            command_text="/send",
            sender="@alice:server",
        )

        assert handled is True
        escalation_service.respond_to_escalation.assert_not_awaited()
        escalation_service.close_escalation.assert_not_awaited()
