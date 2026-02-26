"""Tests for Bisq2ReactionHandler.

Covers:
- Handler construction and properties
- WebSocket subscription via start_listening / stop_listening
- Event processing for ADDED and REMOVED modification types
- Bisq2 reaction enum mapping (THUMBS_UP, THUMBS_DOWN, HAPPY, HEART, PARTY)
- Unmapped reaction handling (LAUGH)
- Error handling for malformed events
"""

import json
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
    """ReactionProcessor mock."""
    processor = MagicMock(spec=ReactionProcessor)
    processor.process = AsyncMock(return_value=True)
    processor.revoke_reaction = AsyncMock(return_value=True)
    return processor


@pytest.fixture()
def handler(mock_runtime, mock_processor):
    """Bisq2ReactionHandler instance."""
    from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler

    return Bisq2ReactionHandler(runtime=mock_runtime, processor=mock_processor)


# ---------------------------------------------------------------------------
# Construction & Properties
# ---------------------------------------------------------------------------


class TestBisq2ReactionHandlerConstruction:
    """Test handler construction."""

    def test_channel_id_is_bisq2(self, handler):
        """channel_id is 'bisq2'."""
        assert handler.channel_id == "bisq2"

    def test_implements_protocol(self, handler):
        """Handler satisfies ReactionHandlerProtocol."""
        assert isinstance(handler, ReactionHandlerProtocol)

    def test_stores_runtime(self, handler, mock_runtime):
        """Runtime is stored."""
        assert handler.runtime is mock_runtime

    def test_stores_processor(self, handler, mock_processor):
        """Processor is stored."""
        assert handler.processor is mock_processor

    def test_bisq2_emoji_map(self, handler):
        """Default emoji map includes Bisq2 reaction names."""
        assert handler.map_emoji_to_rating("THUMBS_UP") == ReactionRating.POSITIVE
        assert handler.map_emoji_to_rating("THUMBS_DOWN") == ReactionRating.NEGATIVE
        assert handler.map_emoji_to_rating("HAPPY") == ReactionRating.POSITIVE
        assert handler.map_emoji_to_rating("HEART") == ReactionRating.POSITIVE
        assert handler.map_emoji_to_rating("PARTY") == ReactionRating.POSITIVE

    def test_unmapped_reactions_return_none(self, handler):
        """LAUGH remains intentionally unmapped."""
        assert handler.map_emoji_to_rating("LAUGH") is None


# ---------------------------------------------------------------------------
# Start / Stop Listening
# ---------------------------------------------------------------------------


class TestBisq2ReactionHandlerListening:
    """Test start_listening / stop_listening lifecycle."""

    @pytest.mark.asyncio
    async def test_start_listening_connects_and_subscribes(self, handler, mock_runtime):
        """start_listening connects WS client and subscribes to topic."""
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock()
        mock_ws_client.subscribe = AsyncMock(
            return_value={"success": True, "payload": []}
        )
        mock_ws_client.on_event = MagicMock()

        mock_runtime.resolve_optional.return_value = mock_ws_client

        await handler.start_listening()

        mock_ws_client.connect.assert_called_once()
        mock_ws_client.subscribe.assert_called_once_with("SUPPORT_CHAT_REACTIONS")
        mock_ws_client.on_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_listening_closes_client(self, handler, mock_runtime):
        """stop_listening closes the WS client."""
        mock_ws_client = MagicMock()
        mock_ws_client.close = AsyncMock()

        handler._ws_client = mock_ws_client

        await handler.stop_listening()

        mock_ws_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_listening_noop_when_not_started(self, handler):
        """stop_listening is safe to call when not started."""
        await handler.stop_listening()


# ---------------------------------------------------------------------------
# Event Processing: ADDED
# ---------------------------------------------------------------------------


class TestBisq2ReactionEventProcessingAdded:
    """Test ADDED modification type events."""

    def _make_event(
        self,
        reaction="THUMBS_UP",
        message_id="msg-123",
        sender_user_id="user-abc",
        modification_type="ADDED",
    ):
        return {
            "responseType": "WebSocketEvent",
            "modificationType": modification_type,
            "payload": {
                "reaction": reaction,
                "messageId": message_id,
                "senderUserProfileId": sender_user_id,
            },
        }

    @pytest.mark.asyncio
    async def test_thumbs_up_creates_positive_event(self, handler, mock_processor):
        """THUMBS_UP reaction creates POSITIVE rating."""
        event = self._make_event(reaction="THUMBS_UP")
        await handler._on_websocket_event(event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE
        assert reaction_event.channel_id == "bisq2"

    @pytest.mark.asyncio
    async def test_thumbs_down_creates_negative_event(self, handler, mock_processor):
        """THUMBS_DOWN reaction creates NEGATIVE rating."""
        event = self._make_event(reaction="THUMBS_DOWN")
        await handler._on_websocket_event(event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.NEGATIVE

    @pytest.mark.asyncio
    async def test_happy_creates_positive_event(self, handler, mock_processor):
        """HAPPY reaction creates POSITIVE rating."""
        event = self._make_event(reaction="HAPPY")
        await handler._on_websocket_event(event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_heart_creates_positive_event(self, handler, mock_processor):
        """HEART reaction creates POSITIVE rating."""
        event = self._make_event(reaction="HEART")
        await handler._on_websocket_event(event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_extracts_message_id(self, handler, mock_processor):
        """external_message_id comes from payload.messageId."""
        event = self._make_event(message_id="bisq-msg-456")
        await handler._on_websocket_event(event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.external_message_id == "bisq-msg-456"

    @pytest.mark.asyncio
    async def test_extracts_reactor_id(self, handler, mock_processor):
        """reactor_id comes from payload.senderUserProfileId."""
        event = self._make_event(sender_user_id="user-xyz")
        await handler._on_websocket_event(event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.reactor_id == "user-xyz"

    @pytest.mark.asyncio
    async def test_raw_reaction_stores_reaction_name(self, handler, mock_processor):
        """raw_reaction stores the original Bisq2 reaction name."""
        event = self._make_event(reaction="HEART")
        await handler._on_websocket_event(event)

        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.raw_reaction == "HEART"

    @pytest.mark.asyncio
    async def test_parses_java_string_payload_format(self, handler, mock_processor):
        """Java WS events send payload as JSON string; handler must parse it."""
        event = {
            "type": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": json.dumps(
                {
                    "reaction": "THUMBS_UP",
                    "messageId": "msg-java-1",
                    "senderUserProfileId": "user-java-1",
                }
            ),
        }
        await handler._on_websocket_event(event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.external_message_id == "msg-java-1"
        assert reaction_event.reactor_id == "user-java-1"
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_reaction_id_payload_maps_to_rating(self, handler, mock_processor):
        """reactionId ordinal payloads are normalized to reaction names."""
        event = {
            "type": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {
                "reactionId": 1,
                "messageId": "msg-id-ordinal-1",
                "senderUserProfileId": "user-ordinal-1",
            },
        }
        await handler._on_websocket_event(event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.raw_reaction == "THUMBS_DOWN"
        assert reaction_event.rating == ReactionRating.NEGATIVE
        assert reaction_event.external_message_id == "msg-id-ordinal-1"
        assert reaction_event.reactor_id == "user-ordinal-1"

    @pytest.mark.asyncio
    async def test_nested_reaction_dto_payload_is_supported(
        self, handler, mock_processor
    ):
        """Nested reactionDto payloads should still be processed."""
        event = {
            "type": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {
                "messageId": "nested-msg-1",
                "reactionDto": {
                    "reactionId": 0,
                    "senderUserProfileId": "nested-user-1",
                },
            },
        }
        await handler._on_websocket_event(event)

        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.raw_reaction == "THUMBS_UP"
        assert reaction_event.rating == ReactionRating.POSITIVE
        assert reaction_event.external_message_id == "nested-msg-1"
        assert reaction_event.reactor_id == "nested-user-1"


# ---------------------------------------------------------------------------
# Unmapped Reactions
# ---------------------------------------------------------------------------


class TestBisq2UnmappedReactions:
    """Test unmapped reaction handling."""

    @pytest.mark.asyncio
    async def test_laugh_is_dropped(self, handler, mock_processor):
        """LAUGH reaction is logged and dropped."""
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {
                "reaction": "LAUGH",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_party_is_positive(self, handler, mock_processor):
        """PARTY reaction is mapped as positive feedback."""
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {
                "reaction": "PARTY",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_unmapped_increments_counter(self, handler, mock_processor):
        """Unmapped reactions increment the drop counter."""
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {
                "reaction": "LAUGH",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
        await handler._on_websocket_event(event)
        assert handler._unmapped_count == 2


# ---------------------------------------------------------------------------
# Event Processing: REMOVED
# ---------------------------------------------------------------------------


class TestBisq2ReactionEventProcessingRemoved:
    """Test REMOVED modification type events."""

    @pytest.mark.asyncio
    async def test_removed_calls_revoke(self, handler, mock_processor):
        """REMOVED modification type calls processor.revoke_reaction."""
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "REMOVED",
            "payload": {
                "reaction": "THUMBS_UP",
                "messageId": "msg-123",
                "senderUserProfileId": "user-abc",
            },
        }
        await handler._on_websocket_event(event)

        mock_processor.revoke_reaction.assert_called_once_with(
            channel_id="bisq2",
            external_message_id="msg-123",
            reactor_id="user-abc",
            raw_reaction="THUMBS_UP",
        )

    @pytest.mark.asyncio
    async def test_removed_does_not_call_process(self, handler, mock_processor):
        """REMOVED events don't call process()."""
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "REMOVED",
            "payload": {
                "reaction": "THUMBS_UP",
                "messageId": "msg-123",
                "senderUserProfileId": "user-abc",
            },
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_removed_with_java_string_payload_calls_revoke(
        self, handler, mock_processor
    ):
        """REMOVED event with string payload should revoke reaction."""
        event = {
            "type": "WebSocketEvent",
            "modificationType": "REMOVED",
            "payload": json.dumps(
                {
                    "reaction": "THUMBS_UP",
                    "messageId": "msg-java-2",
                    "senderUserProfileId": "user-java-2",
                }
            ),
        }
        await handler._on_websocket_event(event)

        mock_processor.revoke_reaction.assert_called_once_with(
            channel_id="bisq2",
            external_message_id="msg-java-2",
            reactor_id="user-java-2",
            raw_reaction="THUMBS_UP",
        )

    @pytest.mark.asyncio
    async def test_is_removed_flag_triggers_revoke(self, handler, mock_processor):
        """Payload isRemoved=true should be treated as REMOVED even without event flag."""
        event = {
            "type": "WebSocketEvent",
            "payload": {
                "reactionId": 0,
                "chatMessageId": "msg-removed-1",
                "senderUserProfileId": "user-removed-1",
                "isRemoved": True,
            },
        }
        await handler._on_websocket_event(event)

        mock_processor.revoke_reaction.assert_called_once_with(
            channel_id="bisq2",
            external_message_id="msg-removed-1",
            reactor_id="user-removed-1",
            raw_reaction="THUMBS_UP",
        )


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestBisq2ReactionHandlerErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_missing_payload_ignored(self, handler, mock_processor):
        """Events without payload are silently dropped."""
        event = {"responseType": "WebSocketEvent", "modificationType": "ADDED"}
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_reaction_ignored(self, handler, mock_processor):
        """Events without reaction field are silently dropped."""
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {"messageId": "msg-1", "senderUserProfileId": "user-1"},
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_json_payload_ignored(self, handler, mock_processor):
        """Malformed JSON string payload is dropped safely."""
        event = {
            "type": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": "{not valid json",
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_processor_exception_caught(self, handler, mock_processor):
        """Processor exceptions don't crash the handler."""
        mock_processor.process = AsyncMock(side_effect=Exception("DB error"))
        event = {
            "responseType": "WebSocketEvent",
            "modificationType": "ADDED",
            "payload": {
                "reaction": "THUMBS_UP",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
