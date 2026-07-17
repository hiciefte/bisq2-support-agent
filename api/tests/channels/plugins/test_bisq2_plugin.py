"""Tests for Bisq2 Channel Plugin.

TDD tests for the Bisq2 channel plugin that wraps existing bisq_api.py logic.

Note: FAQ extraction is handled by the training pipeline (Bisq2SyncService),
not by the channel plugin. Bisq2 sends responses via REST API.
"""

import asyncio
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)


def _fresh_export_date(*, seconds: int = 60) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


def _subscription_ack(request_id: str = "fixture-request") -> dict[str, object]:
    """Build the nullable-string SubscriptionResponse emitted by Bisq2."""
    return {
        "type": "SubscriptionResponse",
        "requestId": request_id,
        "payload": "[]",
        "errorMessage": None,
    }


class _LifecycleWebSocket:
    """Stateful websocket double that rejects concurrent subscription reads."""

    def __init__(self, *, fail_first_support_subscription: bool = False) -> None:
        self.is_connected = False
        self.is_listening = False
        self.fail_first_support_subscription = fail_first_support_subscription
        self.subscribe_calls: list[str] = []
        self._active_subscriptions: set[tuple[str, object]] = set()
        self._callbacks: list[object] = []
        self._snapshot_callbacks: list[object] = []
        self._listener_stop = asyncio.Event()

    async def connect(self) -> None:
        self.is_connected = True
        self._listener_stop = asyncio.Event()

    async def close(self) -> None:
        self.is_connected = False
        self.is_listening = False
        self._active_subscriptions.clear()
        self._listener_stop.set()

    async def subscribe(
        self, topic: str, parameter: object = None
    ) -> dict[str, object]:
        if self.is_listening:
            raise AssertionError("subscription attempted with an active listener")
        self.subscribe_calls.append(topic)
        if topic == "SUPPORT_CHAT_MESSAGES" and self.fail_first_support_subscription:
            self.fail_first_support_subscription = False
            return {
                "type": "SubscriptionResponse",
                "requestId": "fixture-request",
                "payload": None,
                "errorMessage": "fixture rejection",
            }
        response = _subscription_ack()
        for callback in self._snapshot_callbacks:
            await callback(topic, parameter, response["payload"])
        self._active_subscriptions.add((topic, parameter))
        return response

    async def listen_forever(self) -> None:
        self.is_listening = True
        await self._listener_stop.wait()
        self.is_listening = False

    def has_active_subscription(self, topic: str, parameter: object = None) -> bool:
        return (topic, parameter) in self._active_subscriptions

    def on_event(self, callback: object) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def off_event(self, callback: object) -> None:
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def on_subscription_snapshot(self, callback: object) -> None:
        if callback not in self._snapshot_callbacks:
            self._snapshot_callbacks.append(callback)

    def off_subscription_snapshot(self, callback: object) -> None:
        if callback in self._snapshot_callbacks:
            self._snapshot_callbacks.remove(callback)


class _RetryingReactionHandler:
    def __init__(self, ws_client: _LifecycleWebSocket) -> None:
        self.ws_client = ws_client
        self.start_attempts = 0
        self._subscription_started = False

    @property
    def is_listening(self) -> bool:
        return bool(
            self._subscription_started
            and self.ws_client.is_connected
            and self.ws_client.is_listening
            and self.ws_client.has_active_subscription("SUPPORT_CHAT_REACTIONS")
        )

    async def start_listening(self) -> None:
        self.start_attempts += 1
        self._subscription_started = False
        if self.start_attempts == 1:
            raise RuntimeError("fixture transient failure")
        if not self.ws_client.is_connected:
            await self.ws_client.connect()
        await self.ws_client.subscribe("SUPPORT_CHAT_REACTIONS")
        self._subscription_started = True

    async def stop_listening(self) -> None:
        self._subscription_started = False
        await self.ws_client.close()


@pytest.fixture(autouse=True)
def _configure_test_scope(monkeypatch):
    """Supply the mandatory scope to legacy Bisq channel behavior tests."""
    from app.channels.plugins.bisq2.channel import Bisq2Channel

    original_init = Bisq2Channel.__init__
    allowed_channel_ids = [
        "bisq2-conversation-id",
        "conv-001",
        "conversation",
        "support.conv-1",
        "support.staff",
        "support.support",
    ]
    allowed_sender_profile_ids = [
        "profile-stable-123",
        "author-id-legacy",
        "bisq2-user",
        "live-user",
        "new-user",
        "old-user",
        "other-user-001",
        "sender-id-current",
        "sender-user-123",
        "staff-001",
        "user-1",
        "user-123",
        "user123",
        "user456",
    ]

    def configured_init(self, runtime):
        settings = getattr(runtime, "settings", None)
        if settings is None:
            settings = SimpleNamespace()
            runtime.settings = settings
        explicit = vars(settings)
        if "BISQ2_ALLOWED_CHANNEL_IDS" not in explicit:
            settings.BISQ2_ALLOWED_CHANNEL_IDS = allowed_channel_ids
        if "BISQ2_ALLOWED_SENDER_PROFILE_IDS" not in explicit:
            settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = allowed_sender_profile_ids
        if "BISQ2_CHATOPS_CHANNEL_IDS" not in explicit:
            settings.BISQ2_CHATOPS_CHANNEL_IDS = []
        if "BISQ2_STAFF_PROFILE_IDS" not in explicit:
            settings.BISQ2_STAFF_PROFILE_IDS = []
        if "BISQ2_STAFF_NOTIFICATION_TARGET" not in explicit:
            settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
        original_init(self, runtime)

    monkeypatch.setattr(Bisq2Channel, "__init__", configured_init)


@pytest.mark.unit
def test_retention_prune_evicts_live_seen_message_cache(tmp_path):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    manager = BisqSyncStateManager(str(tmp_path / "bisq-state.json"))
    settings = SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=["conversation"],
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=["user-1"],
        BISQ2_CHATOPS_CHANNEL_IDS=[],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )
    manager.bind_scope(resolve_bisq2_test_scope(settings).fingerprint)
    manager.mark_processed(
        "expired-message",
        processed_at=datetime.now(UTC) - timedelta(days=2),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            manager if name == "bisq2_sync_state_manager" else None
        )
    )
    channel = Bisq2Channel(runtime)
    channel._cache_message(
        {
            "messageId": "expired-message",
            "conversationId": "conversation",
            "authorId": "user-1",
            "message": "fixture",
        }
    )

    assert channel._should_process_message("expired-message") is False

    deleted = manager.prune_before(datetime.now(UTC) - timedelta(days=1))

    assert deleted == 1
    assert channel._should_process_message("expired-message") is True
    assert "expired-message" not in channel._message_cache_by_id
    assert "expired-message" not in channel._seen_message_order


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
    def test_live_channel_uses_state_file_separate_from_training(self, tmp_path):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
        from app.channels.runtime import ChannelRuntime

        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.DATA_RETENTION_DAYS = 7
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ2_CHATOPS_CHANNEL_IDS = []
        settings.BISQ2_STAFF_IDS = []
        settings.BISQ_STAFF_USERS = []
        runtime = ChannelRuntime(settings=settings)

        Bisq2Channel.setup_dependencies(runtime, settings)

        live_state = runtime.resolve("bisq2_sync_state_manager")
        training_state = Path(tmp_path) / "bisq_sync_state.json"
        assert (
            live_state.state_file
            == Path(tmp_path) / "bisq_live_channel_sync_state.json"
        )
        assert live_state.state_file != training_state
        assert live_state.retention_days == 7

        live_state.mark_processed("live-message")
        live_state.save_state()
        training_manager = BisqSyncStateManager(str(training_state))
        assert training_manager.is_processed("live-message") is False
        assert training_manager.last_sync_timestamp is None

    @pytest.mark.unit
    def test_get_delivery_target_rejects_conflicting_ids(self):
        """Delivery target is empty when two identifiers disagree."""
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
        assert target == ""

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

    @pytest.mark.unit
    def test_get_staff_notification_target_prefers_metadata_override(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            BISQ2_ALLOWED_CHANNEL_IDS=["support.staff.override", "support.staff"],
            BISQ2_ALLOWED_SENDER_PROFILE_IDS=["profile.allowed"],
            BISQ2_CHATOPS_CHANNEL_IDS=[],
            BISQ2_STAFF_PROFILE_IDS=[],
            BISQ2_STAFF_NOTIFICATION_TARGET="support.staff",
        )
        channel = Bisq2Channel(runtime)

        target = channel.get_staff_notification_target(
            {"staff_room_id": "support.staff.override"}
        )
        assert target == "support.staff.override"

        assert (
            channel.get_staff_notification_target(
                {"staff_room_id": " support.staff.override "}
            )
            == ""
        )

    @pytest.mark.unit
    def test_get_staff_notification_target_uses_config_fallback(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            BISQ2_ALLOWED_CHANNEL_IDS=["support.staff"],
            BISQ2_ALLOWED_SENDER_PROFILE_IDS=["profile.allowed"],
            BISQ2_CHATOPS_CHANNEL_IDS=[],
            BISQ2_STAFF_PROFILE_IDS=[],
            BISQ2_STAFF_NOTIFICATION_TARGET="support.staff",
        )
        channel = Bisq2Channel(runtime)

        target = channel.get_staff_notification_target({})
        assert target == "support.staff"


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
        mock_bisq_api.setup = AsyncMock(
            side_effect=[Exception("Connection refused"), None]
        )
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel.is_connected is False

        ready = await channel.maintain_readiness()

        assert ready is False
        assert channel.is_connected is True
        assert mock_bisq_api.setup.await_count == 2

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
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(return_value=_subscription_ack())
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            if name == "bisq2_reaction_handler":
                return mock_reaction_handler
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
    async def test_maintenance_retries_reaction_before_starting_shared_listener(self):
        """A transient reaction failure leaves no competing receive loop."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )
        ws_client = _LifecycleWebSocket()
        reaction_handler = _RetryingReactionHandler(ws_client)
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": mock_bisq_api,
                "bisq2_websocket_client": ws_client,
                "bisq2_reaction_handler": reaction_handler,
            }.get(name)
        )

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert reaction_handler.start_attempts == 1
        assert ws_client.subscribe_calls == []
        assert channel._ws_listener_task is None

        ready = await channel.maintain_readiness()

        assert ready is True
        assert reaction_handler.start_attempts == 2
        assert ws_client.subscribe_calls == [
            "SUPPORT_CHAT_REACTIONS",
            "SUPPORT_CHAT_MESSAGES",
        ]
        assert reaction_handler.is_listening is True

        await channel.maintain_readiness()
        assert reaction_handler.start_attempts == 2
        assert len(ws_client.subscribe_calls) == 2
        await channel.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_maintenance_retries_rejected_support_subscription(self):
        """A negative support acknowledgement cannot start the receive loop."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )
        ws_client = _LifecycleWebSocket(fail_first_support_subscription=True)
        reaction_handler = _RetryingReactionHandler(ws_client)
        reaction_handler.start_attempts = 1
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": mock_bisq_api,
                "bisq2_websocket_client": ws_client,
                "bisq2_reaction_handler": reaction_handler,
            }.get(name)
        )

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert ws_client.subscribe_calls == [
            "SUPPORT_CHAT_REACTIONS",
            "SUPPORT_CHAT_MESSAGES",
        ]
        assert channel._ws_listener_task is None

        ready = await channel.maintain_readiness()

        assert ready is True
        assert ws_client.subscribe_calls == [
            "SUPPORT_CHAT_REACTIONS",
            "SUPPORT_CHAT_MESSAGES",
            "SUPPORT_CHAT_REACTIONS",
            "SUPPORT_CHAT_MESSAGES",
        ]
        assert channel._ws_listener_task is not None
        assert channel._ws_listener_task.done() is False
        await channel.stop()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_maintenance_rejects_persistent_support_subscription_failure(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )
        ws_client = _LifecycleWebSocket()
        original_subscribe = ws_client.subscribe

        async def reject_support(topic: str, parameter: object = None):
            if topic == "SUPPORT_CHAT_MESSAGES":
                ws_client.subscribe_calls.append(topic)
                return {
                    "type": "SubscriptionResponse",
                    "requestId": "fixture-request",
                    "payload": None,
                    "errorMessage": "fixture rejection",
                }
            return await original_subscribe(topic, parameter)

        ws_client.subscribe = reject_support  # type: ignore[method-assign]
        reaction_handler = _RetryingReactionHandler(ws_client)
        reaction_handler.start_attempts = 1
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": mock_bisq_api,
                "bisq2_websocket_client": ws_client,
                "bisq2_reaction_handler": reaction_handler,
            }.get(name)
        )

        channel = Bisq2Channel(runtime)
        await channel.start()
        ready = await channel.maintain_readiness()

        assert ready is False
        assert channel.test_scope_websocket_ready is False
        assert channel._ws_listener_task is None
        assert ws_client.subscribe_calls.count("SUPPORT_CHAT_MESSAGES") == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_websocket_readiness_requires_both_current_subscriptions(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        ws_client = _LifecycleWebSocket()
        reaction_handler = SimpleNamespace(is_listening=True)
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_websocket_client": ws_client,
                "bisq2_reaction_handler": reaction_handler,
            }.get(name)
        )
        channel = Bisq2Channel(runtime)

        await ws_client.connect()
        ws_client.on_subscription_snapshot(channel._on_support_subscription_snapshot)
        await ws_client.subscribe("SUPPORT_CHAT_REACTIONS")
        await ws_client.subscribe("SUPPORT_CHAT_MESSAGES")
        channel._ws_listener_task = asyncio.create_task(ws_client.listen_forever())
        await asyncio.sleep(0)

        assert channel.test_scope_websocket_ready is True

        ws_client._active_subscriptions.discard(("SUPPORT_CHAT_MESSAGES", None))
        assert channel.test_scope_websocket_ready is False

        ws_client._active_subscriptions.add(("SUPPORT_CHAT_MESSAGES", None))
        reaction_handler.is_listening = False
        assert channel.test_scope_websocket_ready is False

        reaction_handler.is_listening = True
        await ws_client.close()
        assert channel.test_scope_websocket_ready is False
        await channel._ws_listener_task
        channel._ws_listener_task = None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_support_snapshot_buffers_scoped_messages_before_incrementals(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)
        channel._support_subscription_established = True
        channel._scope_rebaseline_pending = False
        channel._last_poll_since = datetime.fromtimestamp(0.05, tz=UTC)
        snapshot_payload = json.dumps(
            [
                {
                    "messageId": "snapshot-stale",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Allowed user",
                    "text": "Historical snapshot content must not replay.",
                    "timestamp": 40,
                },
                {
                    "messageId": "snapshot-allowed",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Allowed user",
                    "text": "Question from the reconnect snapshot?",
                    "timestamp": 100,
                },
                {
                    "messageId": "snapshot-blocked",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "profile-outside-scope",
                    "author": "Blocked user",
                    "text": "This must not enter the buffer.",
                    "timestamp": 101,
                },
            ]
        )

        await channel._on_support_subscription_snapshot(
            "SUPPORT_CHAT_MESSAGES",
            None,
            snapshot_payload,
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "incremental-allowed",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-1",
                    "author": "Allowed user",
                    "text": "Question received after the snapshot?",
                    "timestamp": 102,
                },
            }
        )

        assert channel._support_snapshot_reconciled is True
        assert [message["messageId"] for message in channel._ws_message_buffer] == [
            "snapshot-allowed",
            "incremental-allowed",
        ]
        assert "snapshot-blocked" not in channel._message_cache_by_id
        assert "snapshot-stale" not in channel._message_cache_by_id

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_initial_support_snapshot_is_suppressed_by_rest_rebaseline(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)
        historical_message = {
            "messageId": "historical-snapshot-message",
            "channelId": "support.support",
            "conversationId": "support.support",
            "senderUserProfileId": "user-1",
            "author": "Allowed user",
            "message": "Old approved history must not become live work.",
            "timestamp": 100,
        }
        initial_ack_payload = json.dumps(
            [{**historical_message, "text": historical_message["message"]}]
        )
        bisq_api = SimpleNamespace(
            export_chat_messages=AsyncMock(
                return_value={
                    "exportDate": _fresh_export_date(),
                    "messages": [historical_message],
                }
            )
        )
        channel._persist_sync_state = AsyncMock(return_value=True)

        await channel._on_support_subscription_snapshot(
            "SUPPORT_CHAT_MESSAGES",
            None,
            initial_ack_payload,
        )
        await channel._prime_rest_fallback_cursor(bisq_api)

        assert channel._support_snapshot_reconciled is True
        assert channel._support_subscription_established is False
        assert list(channel._ws_message_buffer) == []
        assert "historical-snapshot-message" in channel._seen_message_ids
        assert channel.test_scope_rebaseline_complete is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_support_snapshot_keeps_readiness_false(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        with pytest.raises(ValueError, match="payload must be a list"):
            await channel._on_support_subscription_snapshot(
                "SUPPORT_CHAT_MESSAGES",
                None,
                "{}",
            )

        assert channel._support_snapshot_reconciled is False

    @pytest.mark.unit
    def test_websocket_readiness_requires_client_and_reaction_handler(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        assert channel.test_scope_websocket_ready is False

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
                "exportDate": _fresh_export_date(),
                "messages": [
                    {
                        "messageId": "old-msg-1",
                        "author": "old-user",
                        "authorId": "old-user",
                        "message": "stale",
                        "conversationId": "support.support",
                    }
                ],
            }
        )
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(return_value=_subscription_ack())
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            if name == "bisq2_reaction_handler":
                return mock_reaction_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel._last_poll_since is not None
        assert "old-msg-1" in channel._seen_message_ids
        assert "old-msg-1" not in channel._message_cache_by_id
        assert channel.test_scope_rebaseline_complete is True
        mock_bisq_api.export_chat_messages.assert_awaited_once()
        mock_bisq_api.export_chat_messages.assert_awaited_with(since=None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_primes_rest_cursor_without_websocket(self):
        """Polling-only startup must establish a cursor before the first live poll."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )

        runtime = MagicMock(spec=ChannelRuntime)

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel._last_poll_since is not None
        mock_bisq_api.export_chat_messages.assert_awaited_once_with(since=None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_primes_rest_cursor_after_websocket_failure(self):
        """A failed websocket must still leave the REST fallback safely primed."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )
        mock_ws_client = MagicMock()
        mock_ws_client.on_event = MagicMock()
        mock_ws_client.connect = AsyncMock(side_effect=RuntimeError("offline"))
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": mock_bisq_api,
                "bisq2_websocket_client": mock_ws_client,
                "bisq2_reaction_handler": mock_reaction_handler,
            }.get(name)
        )

        channel = Bisq2Channel(runtime)
        await channel.start()

        assert channel._last_poll_since is not None
        mock_bisq_api.export_chat_messages.assert_awaited_once_with(since=None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_scope_rebaseline_opens_live_websocket_before_snapshot(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        call_order: list[str] = []
        historical = {
            "messageId": "old-msg",
            "author": "old-user",
            "authorId": "old-user",
            "message": "How did an old trade work?",
            "conversationId": "support.support",
            "date": "2020-01-01T00:00:00Z",
        }
        live = {
            "messageId": "live-msg",
            "author": "live-user",
            "authorId": "live-user",
            "message": "How do I complete this trade?",
            "conversationId": "support.support",
            "date": "2020-01-02T00:00:00Z",
        }
        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)

        async def export_chat_messages(*, since):
            if since is None:
                call_order.append("prime")
                return {
                    "exportDate": "2099-01-01T00:00:01Z",
                    "messages": [historical, live],
                }
            return {"exportDate": "2099-01-01T00:00:02Z", "messages": []}

        mock_bisq_api.export_chat_messages = AsyncMock(side_effect=export_chat_messages)
        mock_ws_client = MagicMock()

        async def connect():
            call_order.append("websocket")

        mock_ws_client.connect = AsyncMock(side_effect=connect)
        mock_ws_client.subscribe = AsyncMock(return_value=_subscription_ack())
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock()
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": mock_bisq_api,
                "bisq2_websocket_client": mock_ws_client,
                "bisq2_reaction_handler": mock_reaction_handler,
            }.get(name)
        )

        channel = Bisq2Channel(runtime)
        await channel.start()
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "post-baseline-live-msg",
                    "author": "live-user",
                    "authorId": "live-user",
                    "text": "How do I complete this trade?",
                    "conversationId": "support.support",
                    "channelId": "support.support",
                    "timestamp": 4070908800000,
                },
            }
        )

        assert call_order[:2] == ["websocket", "prime"]
        assert "old-msg" in channel._seen_message_ids
        assert "live-msg" in channel._seen_message_ids
        assert "post-baseline-live-msg" not in channel._seen_message_ids

        messages = await channel.poll_conversations()

        assert [message.message_id for message in messages] == [
            "post-baseline-live-msg"
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_restart_loads_persisted_rest_cursor_and_seen_ids(self, tmp_path):
        """A fresh channel process must resume after the last persisted export."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
        from app.channels.runtime import ChannelRuntime

        state_path = tmp_path / "bisq-sync-state.json"
        first_state = BisqSyncStateManager(str(state_path))
        historical_time = (datetime.now(UTC) - timedelta(seconds=2)).replace(
            microsecond=0
        )
        historical = {
            "messageId": "old-msg-1",
            "author": "old-user",
            "authorId": "old-user",
            "message": "old question",
            "conversationId": "support.support",
            "date": historical_time.isoformat().replace("+00:00", "Z"),
        }
        first_api = MagicMock()
        first_api.setup = AsyncMock(return_value=None)
        first_api.export_chat_messages = AsyncMock(
            return_value={
                "exportDate": _fresh_export_date(),
                "messages": [historical],
            }
        )
        first_runtime = MagicMock(spec=ChannelRuntime)
        first_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": first_api,
                "bisq2_sync_state_manager": first_state,
            }.get(name)
        )

        first_channel = Bisq2Channel(first_runtime)
        await first_channel.start()

        restarted_state = BisqSyncStateManager(str(state_path))
        assert restarted_state.last_sync_timestamp is not None
        new_message_time = restarted_state.last_sync_timestamp + timedelta(seconds=1)
        new_message = {
            "messageId": "new-msg-2",
            "author": "new-user",
            "authorId": "new-user",
            "message": "How do I complete this trade?",
            "conversationId": "support.support",
            "date": new_message_time.isoformat().replace("+00:00", "Z"),
        }
        restarted_api = MagicMock()
        restarted_api.setup = AsyncMock(return_value=None)
        restarted_api.export_chat_messages = AsyncMock(
            return_value={
                "exportDate": new_message_time.isoformat().replace("+00:00", "Z"),
                # Simulate a backend that overlaps the incremental window.
                "messages": [historical, new_message],
            }
        )
        restarted_runtime = MagicMock(spec=ChannelRuntime)
        restarted_runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "bisq2_api": restarted_api,
                "bisq2_sync_state_manager": restarted_state,
            }.get(name)
        )

        restarted_channel = Bisq2Channel(restarted_runtime)
        persisted_cursor = restarted_state.last_sync_timestamp
        messages = await restarted_channel.poll_conversations()

        assert [message.message_id for message in messages] == ["new-msg-2"]
        assert restarted_channel._last_poll_since is not None
        restarted_api.export_chat_messages.assert_awaited_once_with(
            since=persisted_cursor
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_does_not_hang_when_websocket_subscribe_stalls(self):
        """WS subscribe stall should not block channel startup indefinitely."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        async def stalled_subscribe(*_args, **_kwargs):
            await asyncio.sleep(10)
            return _subscription_ack()

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(side_effect=stalled_subscribe)
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_WS_STARTUP_TIMEOUT_SECONDS = 0.01

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            if name == "bisq2_reaction_handler":
                return mock_reaction_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await asyncio.wait_for(channel.start(), timeout=0.2)

        assert channel.is_connected is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_does_not_hang_when_reaction_subscription_stalls(self):
        """Reaction subscribe stall must degrade instead of blocking startup."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        async def stalled_reaction_start() -> None:
            await asyncio.sleep(10)

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"exportDate": _fresh_export_date(), "messages": []}
        )
        mock_ws_client = MagicMock()
        mock_ws_client.close = AsyncMock()
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock(
            side_effect=stalled_reaction_start
        )
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            BISQ_WS_STARTUP_TIMEOUT_SECONDS=0.01,
            BISQ2_ALLOWED_CHANNEL_IDS=["support.support"],
            BISQ2_ALLOWED_SENDER_PROFILE_IDS=["profile.allowed"],
            BISQ2_CHATOPS_CHANNEL_IDS=[],
            BISQ2_STAFF_PROFILE_IDS=[],
            BISQ2_STAFF_NOTIFICATION_TARGET="",
        )
        dependencies = {
            "bisq2_api": mock_bisq_api,
            "bisq2_websocket_client": mock_ws_client,
            "bisq2_reaction_handler": mock_reaction_handler,
        }
        runtime.resolve_optional = MagicMock(side_effect=dependencies.get)
        channel = Bisq2Channel(runtime)

        await asyncio.wait_for(channel.start(), timeout=0.2)

        assert channel.is_connected is True
        assert channel.test_scope_websocket_ready is False
        mock_ws_client.close.assert_awaited()

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
            "authorId": "old-user",
            "message": "stale replay candidate",
            "conversationId": "support.support",
            "date": "2026-02-20T12:00:00Z",
        }

        mock_bisq_api = MagicMock()
        mock_bisq_api.setup = AsyncMock(return_value=None)
        mock_bisq_api.export_chat_messages = AsyncMock(
            side_effect=[
                {
                    "exportDate": _fresh_export_date(),
                    "messages": [replay_message],
                },
                {
                    "exportDate": _fresh_export_date(seconds=120),
                    "messages": [replay_message],
                },
            ]
        )
        mock_ws_client = MagicMock()
        mock_ws_client.connect = AsyncMock(return_value=None)
        mock_ws_client.subscribe = AsyncMock(return_value=_subscription_ack())
        mock_ws_client.listen_forever = AsyncMock(return_value=None)
        mock_ws_client.on_event = MagicMock()
        mock_reaction_handler = MagicMock()
        mock_reaction_handler.start_listening = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = MagicMock()
        runtime.settings.BISQ_WS_REST_FALLBACK_INTERVAL_SECONDS = 0

        def resolve_optional(name: str):
            if name == "bisq2_api":
                return mock_bisq_api
            if name == "bisq2_websocket_client":
                return mock_ws_client
            if name == "bisq2_reaction_handler":
                return mock_reaction_handler
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

        channel = Bisq2Channel(runtime)
        await channel.start()
        messages = await channel.poll_conversations()

        assert messages == []
        assert mock_bisq_api.export_chat_messages.await_count == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_concurrent_polls_are_serialized(self):
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        active_exports = 0
        max_active_exports = 0

        async def export_chat_messages(*, since):
            nonlocal active_exports, max_active_exports
            _ = since
            active_exports += 1
            max_active_exports = max(max_active_exports, active_exports)
            await asyncio.sleep(0.01)
            active_exports -= 1
            return {"exportDate": _fresh_export_date(), "messages": []}

        mock_bisq_api = MagicMock()
        mock_bisq_api.export_chat_messages = AsyncMock(side_effect=export_chat_messages)
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: mock_bisq_api if name == "bisq2_api" else None
        )
        channel = Bisq2Channel(runtime)
        channel._scope_rebaseline_pending = False

        await asyncio.gather(
            channel.poll_conversations(),
            channel.poll_conversations(),
        )

        assert max_active_exports == 1

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
        outgoing.user = UserContext(
            user_id="bisq2-user",
            metadata={"bisq2_sender_profile_id": "bisq2-user"},
        )
        result = await channel.send_message("bisq2-conversation-id", outgoing)

        assert bool(result) is False
        assert result.external_message_id is None
        assert result.error == "bisq2_api_unavailable"


class TestBisq2ChannelPolling:
    """Test Bisq2Channel conversation polling."""

    @pytest.fixture(autouse=True)
    def _assume_completed_scope_rebaseline(
        self,
        monkeypatch,
        _configure_test_scope,
    ):
        """Legacy polling cases exercise cycles after startup rebaselining."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel

        _ = _configure_test_scope
        configured_init = Bisq2Channel.__init__

        def rebaselined_init(channel, runtime):
            configured_init(channel, runtime)
            channel._scope_rebaseline_pending = False

        monkeypatch.setattr(Bisq2Channel, "__init__", rebaselined_init)

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
                        "authorId": "user123",
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
                        "authorId": "profile-stable-123",
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
        assert messages[0].user.user_id == "profile-stable-123"
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
    async def test_poll_conversations_rejects_conflicting_sender_ids(self):
        """Conflicting sender aliases must fail closed before processing."""
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

        assert messages == []
        assert "msg-both-id-001" not in channel._seen_message_ids

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
                        "authorId": "user123",
                        "message": "",  # Empty message
                        "conversationId": "conv-001",
                    },
                    {
                        "messageId": "msg-002",
                        "author": "user456",
                        "authorId": "user456",
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
                    "senderUserProfileId": "profile-stable-123",
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
    async def test_process_raw_messages_deduplicates_ids_within_same_batch(self):
        """Duplicate message IDs within one batch should only be processed once."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)

        batch = [
            {
                "messageId": "dup-msg-1",
                "author": "Dumb User",
                "authorId": "user-123",
                "message": "Is Bisq 2 open source?",
                "conversationId": "support.support",
                "channelId": "support.support",
                "date": "2026-02-20T15:33:23.966Z",
            },
            {
                "messageId": "dup-msg-1",
                "author": "Dumb User",
                "authorId": "user-123",
                "message": "Is Bisq 2 open source?",
                "conversationId": "support.support",
                "channelId": "support.support",
                "date": "2026-02-20T15:33:23.966Z",
            },
        ]

        incoming = await channel._process_raw_messages(batch, source_name="batch")
        assert len(incoming) == 1
        assert incoming[0].message_id == "dup-msg-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_websocket_buffer_is_bounded_and_drops_oldest(self):
        """Websocket buffer should drop oldest events once maxlen is reached."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)
        channel._ws_message_buffer = deque(maxlen=2)

        async def push(msg_id: str) -> None:
            await channel._on_websocket_event(
                {
                    "topic": "SUPPORT_CHAT_MESSAGES",
                    "modificationType": "ADDED",
                    "payload": {
                        "messageId": msg_id,
                        "channelId": "support.support",
                        "conversationId": "support.support",
                        "senderUserProfileId": "user-123",
                        "author": "Dumb User",
                        "text": f"Question {msg_id}",
                        "timestamp": 1760000000000,
                    },
                }
            )

        await push("buf-1")
        await push("buf-2")
        await push("buf-3")

        buffered_ids = [item.get("messageId") for item in channel._ws_message_buffer]
        assert buffered_ids == ["buf-2", "buf-3"]

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
    def test_sanitizer_rejects_forward_citation_to_future_staff(self):
        """A future in-scope staff message cannot become current prompt context."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)
        channel = Bisq2Channel(runtime)
        current = {
            "messageId": "current-question",
            "channelId": "support.support",
            "conversationId": "support.support",
            "senderUserProfileId": "user-1",
            "author": "User",
            "message": "What should I do now?",
            "timestamp": 100,
            "citation": {
                "messageId": "future-staff-answer",
                "senderUserProfileId": "staff-001",
            },
        }
        future_staff = {
            "messageId": "future-staff-answer",
            "channelId": "support.support",
            "conversationId": "support.support",
            "senderUserProfileId": "staff-001",
            "author": "Staff",
            "message": "Future staff content must not enter this prompt.",
            "timestamp": 200,
        }

        sanitized = channel._sanitize_message_citation(
            current,
            {"future-staff-answer": future_staff},
        )

        assert "citationMessageId" not in sanitized
        assert "citation" not in sanitized

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_drops_messages_when_profile_ids_missing(self):
        """Display aliases alone cannot satisfy the production-test identity scope."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value in {"Support Staff"}

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
                    "messageId": "alias-user-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "author": "Dumb User",
                    "text": "How does Bisq Easy work?",
                    "timestamp": 1760000010000,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "alias-staff-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "author": "Support Staff",
                    "text": "Bisq Easy helps with simple BTC buys.",
                    "citationMessageId": "alias-user-1",
                    "timestamp": 1760000010100,
                },
            }
        )
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "alias-user-2",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "author": "Dumb User",
                    "text": "Can I use SEPA?",
                    "timestamp": 1760000010200,
                },
            }
        )

        messages = await channel.poll_conversations()

        assert messages == []
        assert list(channel._ws_message_buffer) == []

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
    async def test_poll_conversations_does_not_treat_alias_as_staff(self):
        """Display alias alone must not suppress messages as trusted staff."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value == "staff-001"

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
                    "messageId": "alias-only-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "user-123",
                    "author": "Support Staff",
                    "text": "I am pretending to be staff.",
                    "timestamp": 1760000000000,
                },
            }
        )

        messages = await channel.poll_conversations()
        assert [message.message_id for message in messages] == ["alias-only-1"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_records_staff_activity_for_trusted_staff(self):
        """Trusted staff message should update arbitration staff-activity state."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value == "staff-001"
        arbitration_service = MagicMock()
        arbitration_service.record_staff_activity = AsyncMock()

        def resolve_optional(name: str):
            if name == "staff_resolver":
                return staff_resolver
            if name == "arbitration_service":
                return arbitration_service
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "staff-activity-1",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "staff-001",
                    "author": "Support Staff",
                    "text": "We'll take this one.",
                    "timestamp": 1760000000000,
                },
            }
        )
        await channel.poll_conversations()

        arbitration_service.record_staff_activity.assert_awaited_once_with(
            room_or_conversation_id="support.support",
            staff_id="staff-001",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_executes_staff_chatops_command_when_adapter_registered(
        self,
    ):
        """Trusted staff `!case` commands should be handled in-channel and not enter RAG."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value == "staff-001"
        arbitration_service = MagicMock()
        arbitration_service.record_staff_activity = AsyncMock()
        chatops_adapter = MagicMock()
        chatops_adapter.handle_message = AsyncMock(return_value=True)

        def resolve_optional(name: str):
            if name == "staff_resolver":
                return staff_resolver
            if name == "arbitration_service":
                return arbitration_service
            if name == "bisq2_chatops_adapter":
                return chatops_adapter
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "staff-cmd-1",
                    "channelId": "support.staff",
                    "conversationId": "support.staff",
                    "senderUserProfileId": "staff-001",
                    "author": "Support Staff",
                    "text": "!case claim 241",
                    "timestamp": 1760000000000,
                },
            }
        )

        messages = await channel.poll_conversations()

        assert messages == []
        chatops_adapter.handle_message.assert_awaited_once()
        handled_payload = chatops_adapter.handle_message.await_args.args[0]
        assert handled_payload["messageId"] == "staff-cmd-1"
        assert handled_payload["channelId"] == "support.staff"
        assert handled_payload["conversationId"] == "support.staff"
        assert handled_payload["authorId"] == "staff-001"
        assert handled_payload["message"] == "!case claim 241"
        arbitration_service.record_staff_activity.assert_awaited_once_with(
            room_or_conversation_id="support.staff",
            staff_id="staff-001",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_poll_conversations_keeps_existing_staff_suppression_when_chatops_disabled(
        self,
    ):
        """Trusted staff non-command messages stay suppressed when no adapter is present."""
        from app.channels.plugins.bisq2.channel import Bisq2Channel
        from app.channels.runtime import ChannelRuntime

        runtime = MagicMock(spec=ChannelRuntime)
        staff_resolver = MagicMock()
        staff_resolver.is_staff.side_effect = lambda value: value == "staff-001"
        arbitration_service = MagicMock()
        arbitration_service.record_staff_activity = AsyncMock()

        def resolve_optional(name: str):
            if name == "staff_resolver":
                return staff_resolver
            if name == "arbitration_service":
                return arbitration_service
            return None

        runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
        channel = Bisq2Channel(runtime)

        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": {
                    "messageId": "staff-msg-2",
                    "channelId": "support.support",
                    "conversationId": "support.support",
                    "senderUserProfileId": "staff-001",
                    "author": "Support Staff",
                    "text": "Please share logs.",
                    "timestamp": 1760000000000,
                },
            }
        )

        messages = await channel.poll_conversations()

        assert messages == []
        arbitration_service.record_staff_activity.assert_awaited_once_with(
            room_or_conversation_id="support.support",
            staff_id="staff-001",
        )

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
    sync_state = MagicMock()
    sync_state.last_sync_timestamp = None
    sync_state.get_processed_ids_in_order.return_value = []

    runtime = MagicMock(spec=ChannelRuntime)

    def resolve_optional(name: str):
        if name == "bisq2_api":
            return mock_bisq_api
        if name == "sent_message_tracker":
            return None
        if name == "bisq2_sync_state_manager":
            return sync_state
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)
    channel = Bisq2Channel(runtime)

    outgoing = OutgoingMessage(
        message_id="out-1",
        in_reply_to="in-1",
        channel=ChannelType.BISQ2,
        answer="Here is your answer.",
        sources=[],
        user=UserContext(
            user_id="user-1",
            metadata={"bisq2_sender_profile_id": "user-1"},
        ),
        metadata=ResponseMetadata(
            processing_time_ms=1.0,
            rag_strategy="retrieval",
            model_name="test-model",
        ),
        original_question="Question?",
    )

    sent = await channel.send_message("support.support", outgoing)

    assert bool(sent) is True
    assert "self-msg-1" in channel._seen_message_ids
    sync_state.mark_processed.assert_called_once_with("self-msg-1")
    sync_state.save_state.assert_called_once_with()
