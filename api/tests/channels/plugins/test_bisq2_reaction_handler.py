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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.reactions import (
    ReactionHandlerProtocol,
    ReactionProcessor,
    ReactionRating,
)


def _subscription_ack() -> dict[str, object]:
    return {
        "type": "SubscriptionResponse",
        "requestId": "1",
        "payload": "[]",
        "errorMessage": None,
    }


def _configure_snapshot_subscription(
    mock_ws_client: MagicMock,
    payload: str = "[]",
) -> None:
    snapshot_callbacks = []

    def on_snapshot(callback) -> None:
        snapshot_callbacks.append(callback)

    def off_snapshot(callback) -> None:
        if callback in snapshot_callbacks:
            snapshot_callbacks.remove(callback)

    async def subscribe(topic: str) -> dict[str, object]:
        for callback in list(snapshot_callbacks):
            await callback(topic, None, payload)
        return {
            **_subscription_ack(),
            "payload": payload,
        }

    mock_ws_client.on_subscription_snapshot = MagicMock(side_effect=on_snapshot)
    mock_ws_client.off_subscription_snapshot = MagicMock(side_effect=off_snapshot)
    mock_ws_client.subscribe = AsyncMock(side_effect=subscribe)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_runtime():
    """ChannelRuntime mock."""
    runtime = MagicMock()
    runtime.settings = SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=["support.fixture"],
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=[
            "nested-user-1",
            "user-1",
            "user-abc",
            "user-java-1",
            "user-java-2",
            "user-ordinal-1",
            "user-removed-1",
            "user-xyz",
        ],
        BISQ2_CHATOPS_CHANNEL_IDS=[],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )
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
        """Unknown reactions remain unmapped."""
        assert handler.map_emoji_to_rating("UNKNOWN_REACTION") is None


# ---------------------------------------------------------------------------
# Start / Stop Listening
# ---------------------------------------------------------------------------


class TestBisq2ReactionHandlerListening:
    """Test start_listening / stop_listening lifecycle."""

    @pytest.mark.asyncio
    async def test_start_listening_connects_and_subscribes(self, handler, mock_runtime):
        """start_listening connects WS client and subscribes to topic."""
        mock_ws_client = MagicMock()
        mock_ws_client.is_connected = False

        async def connect() -> None:
            mock_ws_client.is_connected = True

        mock_ws_client.connect = AsyncMock(side_effect=connect)
        _configure_snapshot_subscription(mock_ws_client)
        mock_ws_client.on_event = MagicMock()
        mock_ws_client.off_event = MagicMock()
        mock_ws_client.is_listening = False
        mock_ws_client.has_active_subscription = MagicMock(return_value=True)

        mock_runtime.resolve_optional.return_value = mock_ws_client

        assert handler.is_listening is False
        await handler.start_listening()

        mock_ws_client.connect.assert_called_once()
        mock_ws_client.subscribe.assert_called_once_with("SUPPORT_CHAT_REACTIONS")
        mock_ws_client.on_event.assert_called_once()
        mock_ws_client.on_subscription_snapshot.assert_called_once()
        assert handler.is_listening is False

        mock_ws_client.is_listening = True
        assert handler.is_listening is True

        mock_ws_client.has_active_subscription.return_value = False
        assert handler.is_listening is False

    @pytest.mark.asyncio
    async def test_failed_subscription_does_not_report_listening(
        self, handler, mock_runtime
    ):
        """A failed subscription must keep readiness fail-closed."""
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock()
        mock_ws_client.subscribe = AsyncMock(side_effect=RuntimeError("unavailable"))
        mock_ws_client.on_event = MagicMock()
        mock_ws_client.off_event = MagicMock()
        mock_runtime.resolve_optional.return_value = mock_ws_client

        with pytest.raises(RuntimeError, match="unavailable"):
            await handler.start_listening()

        assert handler.is_listening is False
        mock_ws_client.off_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscription_without_snapshot_does_not_report_listening(
        self, handler, mock_runtime
    ):
        """An ack without authoritative snapshot delivery is fail-closed."""
        mock_ws_client = MagicMock()
        mock_ws_client.is_connected = True
        mock_ws_client.subscribe = AsyncMock(return_value=_subscription_ack())
        mock_ws_client.on_event = MagicMock()
        mock_ws_client.off_event = MagicMock()
        mock_ws_client.on_subscription_snapshot = MagicMock()
        mock_ws_client.off_subscription_snapshot = MagicMock()
        mock_ws_client.has_active_subscription = MagicMock(return_value=True)
        mock_runtime.resolve_optional.return_value = mock_ws_client

        with pytest.raises(RuntimeError, match="snapshot was not reconciled"):
            await handler.start_listening()

        assert handler.is_listening is False
        mock_ws_client.off_event.assert_called_once()
        mock_ws_client.off_subscription_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_negative_subscription_ack_does_not_report_listening(
        self, handler, mock_runtime
    ):
        """A negative acknowledgement must not activate the listener."""
        mock_ws_client = MagicMock()
        mock_ws_client.is_connected = True
        mock_ws_client.connect = AsyncMock()
        mock_ws_client.subscribe = AsyncMock(
            return_value={
                "type": "SubscriptionResponse",
                "requestId": "1",
                "payload": None,
                "errorMessage": "rejected",
            }
        )
        mock_ws_client.on_event = MagicMock()
        mock_ws_client.off_event = MagicMock()
        mock_runtime.resolve_optional.return_value = mock_ws_client

        with pytest.raises(RuntimeError, match="was not acknowledged"):
            await handler.start_listening()

        mock_ws_client.connect.assert_not_awaited()
        mock_ws_client.on_event.assert_called_once()
        mock_ws_client.off_event.assert_called_once()
        assert handler.is_listening is False

    def test_reconnect_without_active_reaction_subscription_is_not_ready(self, handler):
        mock_ws_client = MagicMock()
        mock_ws_client.is_connected = True
        mock_ws_client.is_listening = True
        mock_ws_client.has_active_subscription.return_value = False
        handler._ws_client = mock_ws_client
        handler._is_listening = True

        assert handler.is_listening is False

    @pytest.mark.asyncio
    async def test_stop_listening_closes_client(self, handler, mock_runtime):
        """stop_listening closes the WS client."""
        mock_ws_client = MagicMock()
        mock_ws_client.close = AsyncMock()

        handler._ws_client = mock_ws_client
        handler._is_listening = True

        await handler.stop_listening()

        mock_ws_client.close.assert_called_once()
        mock_ws_client.off_subscription_snapshot.assert_called_once()
        assert handler.is_listening is False

    @pytest.mark.asyncio
    async def test_stop_listening_noop_when_not_started(self, handler):
        """stop_listening is safe to call when not started."""
        await handler.stop_listening()


# ---------------------------------------------------------------------------
# Subscription snapshot reconciliation
# ---------------------------------------------------------------------------


class TestBisq2ReactionSnapshotReconciliation:
    @staticmethod
    def _snapshot_item(
        *,
        reaction: str = "THUMBS_UP",
        message_id: str = "msg-123",
        sender_id: str = "user-abc",
    ) -> dict[str, str]:
        return {
            "channelId": "support.fixture",
            "reaction": reaction,
            "messageId": message_id,
            "senderUserProfileId": sender_id,
        }

    @pytest.mark.asyncio
    async def test_initial_snapshot_adds_active_reactions(
        self, handler, mock_processor
    ):
        item = self._snapshot_item()

        await handler._on_subscription_snapshot(
            "SUPPORT_CHAT_REACTIONS",
            None,
            json.dumps([item]),
        )

        mock_processor.process.assert_awaited_once()
        reaction_event = mock_processor.process.call_args.args[0]
        assert reaction_event.external_message_id == "msg-123"
        assert reaction_event.metadata == {
            "delivery_target": "support.fixture",
            "bisq2_channel_id": "support.fixture",
        }
        assert handler._snapshot_reconciled is True
        assert len(handler._active_reactions) == 1

    @pytest.mark.asyncio
    async def test_reconnect_snapshot_reconciles_absence_and_addition(
        self, handler, mock_processor
    ):
        first = self._snapshot_item()
        replacement = self._snapshot_item(
            reaction="THUMBS_DOWN",
            message_id="msg-456",
            sender_id="user-xyz",
        )
        await handler._on_subscription_snapshot(
            "SUPPORT_CHAT_REACTIONS",
            None,
            json.dumps([first]),
        )
        mock_processor.process.reset_mock()

        await handler._on_subscription_snapshot(
            "SUPPORT_CHAT_REACTIONS",
            None,
            json.dumps([replacement]),
        )

        mock_processor.revoke_reaction.assert_awaited_once_with(
            channel_id="bisq2",
            external_message_id="msg-123",
            reactor_id="user-abc",
            raw_reaction="THUMBS_UP",
            delivery_target="support.fixture",
        )
        mock_processor.process.assert_awaited_once()
        added_event = mock_processor.process.call_args.args[0]
        assert added_event.external_message_id == "msg-456"
        assert added_event.rating == ReactionRating.NEGATIVE
        assert len(handler._active_reactions) == 1

    @pytest.mark.asyncio
    async def test_empty_reconnect_snapshot_revokes_every_prior_reaction(
        self, handler, mock_processor
    ):
        item = self._snapshot_item()
        await handler._on_subscription_snapshot(
            "SUPPORT_CHAT_REACTIONS",
            None,
            json.dumps([item]),
        )

        await handler._on_subscription_snapshot(
            "SUPPORT_CHAT_REACTIONS",
            None,
            "[]",
        )

        mock_processor.revoke_reaction.assert_awaited_once_with(
            channel_id="bisq2",
            external_message_id="msg-123",
            reactor_id="user-abc",
            raw_reaction="THUMBS_UP",
            delivery_target="support.fixture",
        )
        assert handler._active_reactions == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [None, "{}", "not-json", "[1]"])
    async def test_invalid_snapshot_never_becomes_reconciled(self, handler, payload):
        with pytest.raises(ValueError):
            await handler._on_subscription_snapshot(
                "SUPPORT_CHAT_REACTIONS",
                None,
                payload,
            )

        assert handler._snapshot_reconciled is False


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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": modification_type,
            "payload": {
                "channelId": "support.fixture",
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
        assert reaction_event.metadata == {
            "delivery_target": "support.fixture",
            "bisq2_channel_id": "support.fixture",
        }

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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": json.dumps(
                {
                    "channelId": "support.fixture",
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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
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

    @pytest.mark.asyncio
    async def test_equivalent_reaction_aliases_are_accepted_after_normalization(
        self, handler, mock_processor
    ):
        event = self._make_event(reaction=" thumbs_up ")
        event["payload"]["reactionId"] = 0

        await handler._on_websocket_event(event)

        mock_processor.process.assert_awaited_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.raw_reaction == "THUMBS_UP"


# ---------------------------------------------------------------------------
# Unmapped Reactions
# ---------------------------------------------------------------------------


class TestBisq2UnmappedReactions:
    """Test unmapped reaction handling."""

    @pytest.mark.asyncio
    async def test_laugh_is_positive(self, handler, mock_processor):
        """LAUGH reaction is mapped as positive feedback."""
        event = {
            "responseType": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "reaction": "LAUGH",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_called_once()
        reaction_event = mock_processor.process.call_args[0][0]
        assert reaction_event.rating == ReactionRating.POSITIVE

    @pytest.mark.asyncio
    async def test_party_is_positive(self, handler, mock_processor):
        """PARTY reaction is mapped as positive feedback."""
        event = {
            "responseType": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "reaction": "UNKNOWN_REACTION",
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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "REMOVED",
            "payload": {
                "channelId": "support.fixture",
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
            delivery_target="support.fixture",
        )

    @pytest.mark.asyncio
    async def test_removed_does_not_call_process(self, handler, mock_processor):
        """REMOVED events don't call process()."""
        event = {
            "responseType": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "REMOVED",
            "payload": {
                "channelId": "support.fixture",
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
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "REMOVED",
            "payload": json.dumps(
                {
                    "channelId": "support.fixture",
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
            delivery_target="support.fixture",
        )

    @pytest.mark.asyncio
    async def test_is_removed_flag_triggers_revoke(self, handler, mock_processor):
        """Payload isRemoved=true agrees with a REMOVED envelope."""
        event = {
            "type": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "REMOVED",
            "payload": {
                "channelId": "support.fixture",
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
            delivery_target="support.fixture",
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("modification_type", "is_removed"),
        [
            ("ADDED", True),
            ("REMOVED", False),
            ("ADDED", "false"),
            ("REMOVED", 1),
            ("REMOVED", None),
        ],
    )
    async def test_malformed_or_conflicting_is_removed_is_ignored(
        self,
        handler,
        mock_processor,
        modification_type,
        is_removed,
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": modification_type,
            "payload": {
                "channelId": "support.fixture",
                "reaction": "THUMBS_UP",
                "messageId": "msg-removed-1",
                "senderUserProfileId": "user-removed-1",
                "isRemoved": is_removed,
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflicting_nested_is_removed_is_ignored(
        self, handler, mock_processor
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "REMOVED",
            "payload": {
                "channelId": "support.fixture",
                "senderUserProfileId": "user-removed-1",
                "messageId": "msg-removed-1",
                "isRemoved": False,
                "reactionDto": {
                    "reaction": "THUMBS_UP",
                    "isRemoved": True,
                },
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------


class TestBisq2ReactionHandlerErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_missing_payload_ignored(self, handler, mock_processor):
        """Events without payload are silently dropped."""
        event = {
            "responseType": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("topic", "modification_type"),
        [
            ("SUPPORT_CHAT_MESSAGES", "ADDED"),
            ("", "ADDED"),
            ("SUPPORT_CHAT_REACTIONS", "UPDATED"),
            ("SUPPORT_CHAT_REACTIONS", ""),
        ],
    )
    async def test_wrong_topic_or_modification_is_ignored(
        self,
        handler,
        mock_processor,
        topic,
        modification_type,
    ):
        event = {
            "topic": topic,
            "modificationType": modification_type,
            "payload": {
                "channelId": "support.fixture",
                "reaction": "THUMBS_UP",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_called()
        mock_processor.revoke_reaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_reaction_ignored(self, handler, mock_processor):
        """Events without reaction field are silently dropped."""
        event = {
            "responseType": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_json_payload_ignored(self, handler, mock_processor):
        """Malformed JSON string payload is dropped safely."""
        event = {
            "type": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": "{not valid json",
        }
        await handler._on_websocket_event(event)
        mock_processor.process.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message_aliases",
        [
            {"messageId": "message-one", "chatMessageId": "message-two"},
            {"messageId": "message-one", "chatMessageId": 1},
            {"messageId": "message-one", "chatMessageId": ""},
        ],
    )
    async def test_conflicting_or_malformed_payload_message_aliases_are_ignored(
        self,
        handler,
        mock_processor,
        message_aliases,
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "senderUserProfileId": "user-1",
                "reaction": "THUMBS_UP",
                **message_aliases,
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflicting_envelope_and_payload_message_ids_are_ignored(
        self, handler, mock_processor
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "messageId": "envelope-message",
            "payload": {
                "channelId": "support.fixture",
                "senderUserProfileId": "user-1",
                "reaction": "THUMBS_UP",
                "messageId": "payload-message",
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflicting_outer_and_nested_message_ids_are_ignored(
        self, handler, mock_processor
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "senderUserProfileId": "user-1",
                "messageId": "outer-message",
                "reactionDto": {
                    "reactionId": 0,
                    "messageId": "nested-message",
                },
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reaction_aliases",
        [
            {"reaction": "THUMBS_UP", "reactionId": 1},
            {"reaction": "THUMBS_UP", "reactionId": "0"},
            {"reaction": "THUMBS_UP", "reactionId": True},
            {"reaction": 0, "reactionId": 0},
        ],
    )
    async def test_conflicting_or_malformed_reaction_aliases_are_ignored(
        self,
        handler,
        mock_processor,
        reaction_aliases,
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "senderUserProfileId": "user-1",
                "messageId": "message-one",
                **reaction_aliases,
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflicting_outer_and_nested_reaction_aliases_are_ignored(
        self, handler, mock_processor
    ):
        event = {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "senderUserProfileId": "user-1",
                "messageId": "message-one",
                "reaction": "THUMBS_UP",
                "reactionDto": {"reactionId": 1},
            },
        }

        await handler._on_websocket_event(event)

        mock_processor.process.assert_not_awaited()
        mock_processor.revoke_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_processor_exception_caught(self, handler, mock_processor):
        """Processor exceptions don't crash the handler."""
        mock_processor.process = AsyncMock(side_effect=Exception("DB error"))
        event = {
            "responseType": "WebSocketEvent",
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "support.fixture",
                "reaction": "THUMBS_UP",
                "messageId": "msg-1",
                "senderUserProfileId": "user-1",
            },
        }
        await handler._on_websocket_event(event)
