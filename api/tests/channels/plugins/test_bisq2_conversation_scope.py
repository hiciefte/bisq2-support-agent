"""Tests for the Bisq2 production-test channel and identity boundary."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _settings(
    *,
    channels: object = ("channel-allowed",),
    senders: object = ("profile-allowed",),
) -> SimpleNamespace:
    return SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=channels,
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=senders,
        BISQ2_STAFF_PROFILE_IDS=[],
        BISQ2_CHATOPS_ENABLED=False,
        BISQ2_CHATOPS_CHANNEL_IDS=[],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )


@pytest.mark.unit
def test_scope_normalizes_exact_ids_and_preserves_case():
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    scope = resolve_bisq2_test_scope(
        _settings(
            channels=" channel-alpha,Channel-Beta,channel-alpha ",
            senders=" profile-alpha,Profile-Beta,profile-alpha ",
        )
    )

    assert scope.valid is True
    assert scope.channel_count == 2
    assert scope.sender_profile_count == 2
    assert scope.allows_channel("channel-alpha") is True
    assert scope.allows_channel("Channel-Beta") is True
    assert scope.allows_channel("channel-beta") is False
    assert scope.allows_channel(" channel-alpha ") is False
    assert scope.allows_sender_profile("Profile-Beta") is True
    assert scope.allows_sender_profile("profile-beta") is False
    assert scope.allows_sender_profile(" Profile-Beta ") is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        {
            "channelId": " channel-allowed ",
            "senderUserProfileId": "profile-allowed",
        },
        {
            "channelId": "channel-allowed",
            "senderUserProfileId": " profile-allowed ",
        },
        {
            "channelId": "channel-allowed",
            "conversationId": " channel-allowed ",
            "senderUserProfileId": "profile-allowed",
        },
        {
            "channelId": "channel-allowed",
            "senderUserProfileId": "profile-allowed",
            "authorId": " profile-allowed ",
        },
    ],
)
def test_scope_rejects_noncanonical_runtime_identifiers(payload):
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    scope = resolve_bisq2_test_scope(_settings())

    assert scope.allows_payload(payload) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "configured",
    [
        "",
        "   ",
        "*",
        "value-good,*",
        ".",
        "..",
        "value/good",
        "value?good",
        "value-good\nother",
        "value-good\x7f",
    ],
)
@pytest.mark.parametrize("dimension", ["channels", "senders"])
def test_scope_empty_or_malformed_dimension_denies_all(configured, dimension):
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    values = {"channels": ("channel-allowed",), "senders": ("profile-allowed",)}
    values[dimension] = configured
    scope = resolve_bisq2_test_scope(_settings(**values))

    assert scope.allows_outbound("channel-allowed", "profile-allowed") is False
    assert scope.ready is False


@pytest.mark.unit
def test_scope_rejects_conflicting_channel_and_sender_aliases():
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    scope = resolve_bisq2_test_scope(
        _settings(
            channels=("channel-allowed", "channel-legacy"),
            senders=("profile-allowed", "profile-legacy"),
        )
    )

    assert scope.resolve_payload_channel({"channelId": "channel-allowed"}) == (
        "channel-allowed"
    )
    assert (
        scope.resolve_payload_sender_profile({"senderUserProfileId": "profile-allowed"})
        == "profile-allowed"
    )
    assert (
        scope.resolve_payload_channel(
            {
                "channelId": "channel-allowed",
                "conversation_id": "channel-legacy",
            }
        )
        == ""
    )
    assert (
        scope.resolve_payload_sender_profile(
            {
                "senderUserProfileId": "profile-allowed",
                "author_id": "profile-legacy",
            }
        )
        == ""
    )
    assert (
        scope.resolve_payload_channel(
            {"channelId": "channel-allowed", "conversationId": 42}
        )
        == ""
    )
    assert (
        scope.resolve_payload_sender_profile(
            {"senderUserProfileId": "profile-allowed", "authorId": ["bad"]}
        )
        == ""
    )
    assert scope.allows_payload({}) is False


@pytest.mark.unit
def test_scope_requires_chatops_and_staff_targets_in_channel_allowlist():
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    chatops_values = vars(_settings()).copy()
    chatops_values["BISQ2_CHATOPS_CHANNEL_IDS"] = ["channel-other"]
    chatops_scope = resolve_bisq2_test_scope(SimpleNamespace(**chatops_values))
    staff_values = vars(_settings()).copy()
    staff_values["BISQ2_STAFF_NOTIFICATION_TARGET"] = "channel-other"
    staff_scope = resolve_bisq2_test_scope(SimpleNamespace(**staff_values))

    assert chatops_scope.valid is False
    assert staff_scope.valid is False
    assert chatops_scope.allows_channel("channel-allowed") is False
    assert staff_scope.allows_channel("channel-allowed") is False


@pytest.mark.unit
def test_live_citation_drops_unapproved_nested_author_and_text() -> None:
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    private_text = "private cited participant text"
    outer = {
        "messageId": "message-approved",
        "channelId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Approved",
        "message": "Approved outer reply",
        "citation": {
            "messageId": "message-private",
            "authorId": "profile-private",
            "text": private_text,
        },
    }

    sanitized = channel._sanitize_message_citation(outer, {})
    channel._cache_message(sanitized)

    assert "citation" not in sanitized
    assert "citationMessageId" not in sanitized
    cached = channel._message_cache_by_id["message-approved"]
    assert private_text not in repr(cached)
    incoming = channel._transform_bisq_message(sanitized)
    assert incoming is not None
    assert private_text not in repr(incoming.channel_metadata)
    assert incoming.channel_metadata["delivery_target"] == "channel-allowed"
    assert incoming.channel_metadata["origin_sender_profile_id"] == "profile-allowed"


@pytest.mark.unit
def test_live_citation_keeps_only_exact_same_channel_in_scope_reference() -> None:
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    referenced = {
        "messageId": "message-earlier",
        "channelId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Approved",
        "message": "Earlier question",
    }
    outer = {
        "messageId": "message-later",
        "channelId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Approved",
        "message": "Later question",
        "citation": {
            "messageId": "message-earlier",
            "authorId": "profile-allowed",
            "text": "Earlier question",
        },
    }

    sanitized = channel._sanitize_message_citation(
        outer,
        {"message-earlier": referenced},
    )

    assert sanitized["citationMessageId"] == "message-earlier"
    assert "citation" not in sanitized


@pytest.mark.unit
def test_exact_profile_ids_never_fall_back_to_shared_display_alias() -> None:
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings(
        senders=("Profile+A", "Profile+B"),
    )
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    first = channel._derive_user_id("Profile+A", "Shared Alias")
    second = channel._derive_user_id("Profile+B", "Shared Alias")

    assert first != second
    assert first.startswith("bisq2-user-")
    assert second.startswith("bisq2-user-")
    assert "Shared Alias" not in {first, second}


@pytest.mark.unit
def test_model_unsafe_profile_id_retains_exact_staff_authority() -> None:
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime
    from app.channels.staff import StaffResolver, staff_resolver_service_key

    settings = _settings(
        senders=("Staff+X", "profile-allowed"),
    )
    settings.BISQ2_STAFF_PROFILE_IDS = ["Staff+X"]
    resolver = StaffResolver(["Staff+X"], case_sensitive=True)
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            resolver if name == staff_resolver_service_key("bisq2") else None
        )
    )
    channel = Bisq2Channel(runtime)
    raw = {
        "messageId": "message-staff",
        "channelId": "channel-allowed",
        "senderUserProfileId": "Staff+X",
        "author": "Shared Alias",
        "message": "Exact staff answer",
    }

    normalized = channel._to_conversation_message(raw, "channel-allowed")

    assert normalized is not None
    assert normalized.sender_id.startswith("bisq2-user-")
    assert normalized.immutable_sender_id == "Staff+X"
    assert channel._is_staff_conversation_message(normalized) is True


@pytest.mark.unit
def test_enabled_chatops_requires_a_nonempty_channel_scope():
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    values = vars(_settings()).copy()
    values["BISQ2_CHATOPS_ENABLED"] = True

    scope = resolve_bisq2_test_scope(SimpleNamespace(**values))

    assert scope.valid is False
    assert scope.ready is False
    assert scope.reason == "empty_enabled_chatops_scope"


@pytest.mark.unit
def test_staff_profiles_must_be_safe_and_inside_sender_allowlist():
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    outside_values = vars(_settings()).copy()
    outside_values["BISQ2_STAFF_PROFILE_IDS"] = ["profile-outside"]
    malformed_values = vars(_settings()).copy()
    malformed_values["BISQ2_STAFF_PROFILE_IDS"] = ["*"]

    outside_scope = resolve_bisq2_test_scope(SimpleNamespace(**outside_values))
    malformed_scope = resolve_bisq2_test_scope(SimpleNamespace(**malformed_values))

    assert outside_scope.reason == "staff_profiles_outside_sender_allowlist"
    assert malformed_scope.reason == "invalid_staff_profile_scope"
    assert outside_scope.ready is False
    assert malformed_scope.ready is False


@pytest.mark.unit
def test_enabled_chatops_requires_an_in_scope_staff_profile():
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope

    values = vars(_settings()).copy()
    values["BISQ2_CHATOPS_ENABLED"] = True
    values["BISQ2_CHATOPS_CHANNEL_IDS"] = ["channel-allowed"]
    empty_staff_scope = resolve_bisq2_test_scope(SimpleNamespace(**values))

    values["BISQ2_STAFF_PROFILE_IDS"] = ["profile-allowed"]
    configured_scope = resolve_bisq2_test_scope(SimpleNamespace(**values))

    assert empty_staff_scope.reason == "empty_enabled_chatops_staff_scope"
    assert empty_staff_scope.ready is False
    assert configured_scope.ready is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_channel_unapproved_sender_is_dropped_before_state_and_prefilter():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    channel._question_prefilter = MagicMock()
    channel._question_prefilter.evaluate_text.return_value = SimpleNamespace(
        should_process=True,
        reason="question",
    )

    incoming = await channel._process_raw_messages(
        [
            {
                "messageId": "message-allowed",
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-allowed",
                "author": "Test User",
                "message": "How do I test this?",
            },
            {
                "messageId": "message-blocked",
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-blocked",
                "author": "Other User",
                "message": "How do I test this?",
            },
        ],
        source_name="fixture",
    )

    assert [message.message_id for message in incoming] == ["message-allowed"]
    assert "message-allowed" in channel._message_cache_by_id
    assert "message-blocked" not in channel._message_cache_by_id
    assert "message-blocked" not in channel._seen_message_ids
    assert channel._question_prefilter.evaluate_text.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_undurable_claim_blocks_user_and_staff_side_effects():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    settings = _settings(senders=("profile-allowed", "profile-staff"))
    settings.BISQ2_STAFF_PROFILE_IDS = ["profile-staff"]

    class _FailingSyncState:
        scope_fingerprint = resolve_bisq2_test_scope(settings).fingerprint
        scope_rebaseline_complete = True
        last_sync_timestamp = datetime.now(UTC) - timedelta(minutes=1)

        @staticmethod
        def get_processed_ids_in_order():
            return []

        @staticmethod
        def register_prune_listener(_listener):
            return None

        @staticmethod
        def claim_processed_and_save(_message_ids):
            raise OSError("fixture write failure")

    question_prefilter = MagicMock()
    question_prefilter.evaluate_text.return_value = SimpleNamespace(
        should_process=True,
        reason="question",
    )
    chatops_adapter = SimpleNamespace(handle_message=AsyncMock())
    arbitration_service = SimpleNamespace(record_staff_activity=AsyncMock())
    staff_resolver = SimpleNamespace(
        is_staff=lambda sender_id: sender_id == "profile-staff"
    )
    dependencies = {
        "bisq2_sync_state_manager": _FailingSyncState(),
        "question_prefilter": question_prefilter,
        "bisq2_chatops_adapter": chatops_adapter,
        "arbitration_service": arbitration_service,
        "staff_resolver:bisq2": staff_resolver,
    }
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(side_effect=dependencies.get)
    channel = Bisq2Channel(runtime)

    incoming = await channel._process_raw_messages(
        [
            {
                "messageId": "message-user",
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-allowed",
                "author": "Test user",
                "message": "How do I complete this trade?",
            },
            {
                "messageId": "message-staff",
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-staff",
                "author": "Test staff",
                "message": "!case claim 12",
            },
        ],
        source_name="fixture",
    )

    assert incoming == []
    assert channel.test_scope_persistence_healthy is False
    question_prefilter.evaluate_text.assert_called_once_with(
        "How do I complete this trade?"
    )
    chatops_adapter.handle_message.assert_not_awaited()
    arbitration_service.record_staff_activity.assert_not_awaited()
    assert channel._seen_message_ids == set()
    assert channel._message_cache_by_id == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_drops_unapproved_or_conflicting_events_before_buffering():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)

    payloads = (
        {
            "messageId": "message-wrong-channel",
            "channelId": "channel-blocked",
            "senderUserProfileId": "profile-allowed",
            "text": "Blocked fixture",
        },
        {
            "messageId": "message-wrong-sender",
            "channelId": "channel-allowed",
            "senderUserProfileId": "profile-blocked",
            "text": "Blocked fixture",
        },
        {
            "messageId": "message-conflict",
            "channelId": "channel-allowed",
            "conversationId": "channel-blocked",
            "senderUserProfileId": "profile-allowed",
            "text": "Conflicting fixture",
        },
        {
            "messageId": "message-padded-channel",
            "channelId": " channel-allowed ",
            "senderUserProfileId": "profile-allowed",
            "text": "Noncanonical fixture",
        },
        {
            "messageId": "message-padded-sender",
            "channelId": "channel-allowed",
            "senderUserProfileId": " profile-allowed ",
            "text": "Noncanonical fixture",
        },
    )
    for payload in payloads:
        await channel._on_websocket_event(
            {
                "topic": "SUPPORT_CHAT_MESSAGES",
                "modificationType": "ADDED",
                "payload": payload,
            }
        )
        assert payload["messageId"] not in channel._message_cache_by_id
        assert payload["messageId"] not in channel._seen_message_ids

    assert list(channel._ws_message_buffer) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_scope_prevents_api_and_websocket_startup():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    bisq_api = SimpleNamespace(setup=AsyncMock())
    websocket = SimpleNamespace(connect=AsyncMock(), subscribe=AsyncMock())
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings(senders="")
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: {
            "bisq2_api": bisq_api,
            "bisq2_websocket_client": websocket,
        }.get(name)
    )
    channel = Bisq2Channel(runtime)

    await channel.start()

    assert channel.is_connected is False
    bisq_api.setup.assert_not_awaited()
    websocket.connect.assert_not_awaited()
    websocket.subscribe.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_scope_poll_denies_without_api_io():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    bisq_api = SimpleNamespace(export_chat_messages=AsyncMock())
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings(senders="")
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    messages = await channel.poll_conversations()

    assert messages == []
    bisq_api.export_chat_messages.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enabled_channel_without_durable_sync_manager_stays_unready():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    settings = _settings()
    settings.BISQ2_CHANNEL_ENABLED = True
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            return_value={
                "exportDate": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                "messages": [],
            }
        ),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    await channel.start()
    ready = await channel.maintain_readiness()
    messages = await channel.poll_conversations()

    assert ready is False
    assert messages == []
    assert channel.test_scope_rebaseline_complete is False
    assert channel.test_scope_persistence_healthy is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_claim_failure_stays_unhealthy_and_requeues(
    tmp_path,
):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    settings = _settings()
    settings.BISQ2_CHANNEL_ENABLED = True
    scope = resolve_bisq2_test_scope(settings)
    manager = BisqSyncStateManager(str(tmp_path / "bisq-state.json"))
    manager.begin_scope_rebaseline(scope.fingerprint)
    manager.update_last_sync(datetime.now(UTC) - timedelta(minutes=1))
    manager.mark_scope_rebaseline_complete()
    manager.save_state()

    def fail_claim(_message_ids):
        raise OSError("fixture claim failure")

    manager.claim_processed_and_save = fail_claim  # type: ignore[method-assign]
    bisq_api = SimpleNamespace(export_chat_messages=AsyncMock())
    websocket = SimpleNamespace()
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: {
            "bisq2_api": bisq_api,
            "bisq2_sync_state_manager": manager,
            "bisq2_websocket_client": websocket,
        }.get(name)
    )
    channel = Bisq2Channel(runtime)
    await channel._on_websocket_event(
        {
            "topic": "SUPPORT_CHAT_MESSAGES",
            "modificationType": "ADDED",
            "payload": {
                "messageId": "message-retry",
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-allowed",
                "text": "How do I test this?",
                "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            },
        }
    )

    messages = await channel.poll_conversations()

    assert messages == []
    assert channel.test_scope_persistence_healthy is False
    assert [message["messageId"] for message in channel._ws_message_buffer] == [
        "message-retry"
    ]
    bisq_api.export_chat_messages.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prefilter_failure_before_claim_retries_websocket_message(tmp_path):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    settings = _settings()
    settings.BISQ2_CHANNEL_ENABLED = True
    scope = resolve_bisq2_test_scope(settings)
    manager = BisqSyncStateManager(str(tmp_path / "bisq-state.json"))
    manager.begin_scope_rebaseline(scope.fingerprint)
    manager.update_last_sync(datetime.now(UTC) - timedelta(minutes=1))
    manager.mark_scope_rebaseline_complete()
    manager.save_state()
    question_prefilter = MagicMock()
    question_prefilter.evaluate_text.side_effect = [
        RuntimeError("fixture transient failure"),
        SimpleNamespace(should_process=True, reason="question"),
    ]
    bisq_api = SimpleNamespace(
        export_chat_messages=AsyncMock(
            return_value={"exportDate": datetime.now(UTC).isoformat(), "messages": []}
        )
    )
    websocket = SimpleNamespace()
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: {
            "bisq2_api": bisq_api,
            "bisq2_sync_state_manager": manager,
            "bisq2_websocket_client": websocket,
            "question_prefilter": question_prefilter,
        }.get(name)
    )
    channel = Bisq2Channel(runtime)
    channel._last_rest_fallback_poll_at = float("inf")
    await channel._on_websocket_event(
        {
            "topic": "SUPPORT_CHAT_MESSAGES",
            "modificationType": "ADDED",
            "payload": {
                "messageId": "message-retry",
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-allowed",
                "text": "How do I test this?",
                "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            },
        }
    )

    first = await channel.poll_conversations()
    second = await channel.poll_conversations()

    assert first == []
    assert [message.message_id for message in second] == ["message-retry"]
    assert manager.is_processed("message-retry") is True
    assert question_prefilter.evaluate_text.call_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reaction_listener_refuses_startup_without_complete_scope():
    from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler

    websocket = SimpleNamespace(connect=AsyncMock(), subscribe=AsyncMock())
    runtime = MagicMock()
    runtime.settings = _settings(channels="")
    runtime.resolve_optional.return_value = websocket
    handler = Bisq2ReactionHandler(runtime=runtime, processor=MagicMock())

    with pytest.raises(RuntimeError, match="scope is unavailable"):
        await handler.start_listening()

    websocket.connect.assert_not_awaited()
    websocket.subscribe.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "sender"),
    [
        ("channel-blocked", "profile-allowed"),
        ("channel-allowed", "profile-blocked"),
        ("channel-allowed", ""),
    ],
)
async def test_channel_blocks_out_of_scope_send_without_transport(target, sender):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    bisq_api = SimpleNamespace(send_support_message=AsyncMock())
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    outgoing = SimpleNamespace(
        user=SimpleNamespace(user_id=sender, metadata={}),
    )

    result = await channel.send_message(target, outgoing)

    assert result.sent is False
    assert result.error == "bisq2_test_scope_not_allowed"
    bisq_api.send_support_message.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "metadata"),
    [
        ("channel-allowed", {}),
        (
            " channel-allowed ",
            {"bisq2_sender_profile_id": "profile-allowed"},
        ),
        (
            "channel-allowed",
            {"bisq2_sender_profile_id": " profile-allowed "},
        ),
    ],
)
async def test_channel_requires_exact_dedicated_sender_provenance(target, metadata):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    bisq_api = SimpleNamespace(send_support_message=AsyncMock())
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    outgoing = SimpleNamespace(
        user=SimpleNamespace(user_id="profile-allowed", metadata=metadata),
    )

    result = await channel.send_message(target, outgoing)

    assert result.sent is False
    assert result.error == "bisq2_test_scope_not_allowed"
    bisq_api.send_support_message.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_channel_send_failure_log_hides_transport_exception(caplog):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    sensitive_values = ("private-endpoint", "sentinel-secret", "profile-allowed")
    sensitive_detail = " ".join(sensitive_values)
    bisq_api = SimpleNamespace(
        send_support_message=AsyncMock(side_effect=RuntimeError(sensitive_detail))
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    outgoing = SimpleNamespace(
        answer="Fixture answer",
        sources=[],
        metadata=SimpleNamespace(confidence_score=None),
        original_question=None,
        in_reply_to=None,
        user=SimpleNamespace(
            user_id="unrelated-generic-id",
            metadata={"bisq2_sender_profile_id": "profile-allowed"},
        ),
    )

    with caplog.at_level(logging.WARNING):
        result = await channel.send_message("channel-allowed", outgoing)

    assert result.sent is False
    assert result.error == "bisq2_send_failed"
    for sensitive_value in sensitive_values:
        assert sensitive_value not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", ["", "   ", 7, None])
async def test_channel_never_confirms_malformed_send_response(message_id):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    bisq_api = SimpleNamespace(
        send_support_message=AsyncMock(return_value={"messageId": message_id})
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    outgoing = SimpleNamespace(
        answer="Fixture answer",
        sources=[],
        metadata=SimpleNamespace(confidence_score=None),
        original_question=None,
        in_reply_to="message-original",
        message_id="message-response",
        requires_human=False,
        user=SimpleNamespace(
            user_id="profile-allowed",
            metadata={"bisq2_sender_profile_id": "profile-allowed"},
        ),
    )

    result = await channel.send_message("channel-allowed", outgoing)

    assert result.sent is False
    assert result.error == "missing_external_message_id"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {
            "bisq2_sender_profile_id": "profile-allowed",
            "sender_profile_id": "profile-blocked",
        },
        {
            "bisq2_sender_profile_id": 42,
            "sender_profile_id": "profile-allowed",
        },
    ],
)
async def test_channel_rejects_conflicting_or_malformed_outbound_sender_aliases(
    metadata,
):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    bisq_api = SimpleNamespace(send_support_message=AsyncMock())
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    outgoing = SimpleNamespace(
        user=SimpleNamespace(user_id="profile-allowed", metadata=metadata),
    )

    result = await channel.send_message("channel-allowed", outgoing)

    assert result.sent is False
    assert result.error == "bisq2_test_scope_not_allowed"
    bisq_api.send_support_message.assert_not_awaited()


@pytest.mark.unit
def test_delivery_target_rejects_conflicting_metadata():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings(channels=("channel-allowed", "channel-legacy"))
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)

    assert (
        channel.get_delivery_target(
            {
                "conversation_id": "channel-legacy",
                "channel_id": "channel-allowed",
            }
        )
        == ""
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_same_channel_unapproved_reactor_has_no_processor_side_effects():
    from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler

    processor = MagicMock()
    processor.process = AsyncMock()
    runtime = MagicMock()
    runtime.settings = _settings()
    handler = Bisq2ReactionHandler(runtime=runtime, processor=processor)

    await handler._on_websocket_event(
        {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "channel-allowed",
                "messageId": "message-fixture",
                "senderUserProfileId": "profile-blocked",
                "reaction": "THUMBS_UP",
            },
        }
    )

    processor.process.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "channelId": " channel-allowed ",
            "messageId": "message-fixture",
            "senderUserProfileId": "profile-allowed",
            "reaction": "THUMBS_UP",
        },
        {
            "channelId": "channel-allowed",
            "messageId": "message-fixture",
            "senderUserProfileId": " profile-allowed ",
            "reaction": "THUMBS_UP",
        },
    ],
)
async def test_noncanonical_reaction_scope_has_no_processor_side_effects(payload):
    from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler

    processor = MagicMock()
    processor.process = AsyncMock()
    runtime = MagicMock()
    runtime.settings = _settings()
    handler = Bisq2ReactionHandler(runtime=runtime, processor=processor)

    await handler._on_websocket_event(
        {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": payload,
        }
    )

    processor.process.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nested_reaction_scope_conflict_has_no_processor_side_effects():
    from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler

    processor = MagicMock()
    processor.process = AsyncMock()
    runtime = MagicMock()
    runtime.settings = _settings()
    handler = Bisq2ReactionHandler(runtime=runtime, processor=processor)

    await handler._on_websocket_event(
        {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "modificationType": "ADDED",
            "payload": {
                "channelId": "channel-allowed",
                "senderUserProfileId": "profile-allowed",
                "messageId": "message-fixture",
                "reactionDto": {
                    "senderUserProfileId": "profile-blocked",
                    "reactionId": 0,
                },
            },
        }
    )

    processor.process.assert_not_awaited()


@pytest.mark.unit
def test_runtime_assets_keep_bisq_dark_and_allowlists_blank():
    compose = (REPO_ROOT / "docker" / "docker-compose.yml").read_text()
    env_example = (REPO_ROOT / "docker" / ".env.example").read_text()

    assert "BISQ2_CHANNEL_ENABLED=${BISQ2_CHANNEL_ENABLED:-false}" in compose
    assert "BISQ2_ALLOWED_CHANNEL_IDS=${BISQ2_ALLOWED_CHANNEL_IDS:-}" in compose
    assert (
        "BISQ2_ALLOWED_SENDER_PROFILE_IDS=${BISQ2_ALLOWED_SENDER_PROFILE_IDS:-}"
        in compose
    )
    assert "BISQ2_STAFF_PROFILE_IDS=${BISQ2_STAFF_PROFILE_IDS:-}" in compose
    assert (
        "BISQ2_STAFF_NOTIFICATION_TARGET=${BISQ2_STAFF_NOTIFICATION_TARGET:-}"
        in compose
    )
    assert "BISQ2_CHANNEL_ENABLED=false\n" in env_example
    assert "BISQ2_ALLOWED_CHANNEL_IDS=\n" in env_example
    assert "BISQ2_ALLOWED_SENDER_PROFILE_IDS=\n" in env_example
    assert "BISQ2_STAFF_PROFILE_IDS=\n" in env_example
    assert "BISQ2_STAFF_NOTIFICATION_TARGET=\n" in env_example


@pytest.mark.unit
def test_rest_cursor_never_rewinds_after_filtered_batch():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    sync_state = MagicMock()
    sync_state.last_sync_timestamp = None
    sync_state.get_processed_ids_in_order.return_value = []
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            sync_state if name == "bisq2_sync_state_manager" else None
        )
    )
    channel = Bisq2Channel(runtime)
    current = datetime.now(UTC)
    channel._last_poll_since = current

    channel._update_rest_cursor(current - timedelta(hours=1))

    assert channel._last_poll_since == current
    sync_state.update_last_sync.assert_called_once_with(current)


@pytest.mark.unit
def test_rest_cursor_filter_prevents_replay_after_scope_expansion():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    cursor = datetime(2026, 1, 2, tzinfo=UTC)

    filtered = channel._filter_rest_messages_at_or_after_cursor(
        [
            {
                "messageId": "message-old",
                "timestamp": int((cursor - timedelta(days=1)).timestamp() * 1000),
            },
            {"messageId": "message-no-time"},
            {
                "messageId": "message-live",
                "timestamp": int(cursor.timestamp() * 1000),
            },
        ],
        cursor,
    )

    assert [message["messageId"] for message in filtered] == ["message-live"]


@pytest.mark.unit
def test_rest_boundary_uses_bisq_message_timestamp_precision():
    from app.channels.plugins.bisq2.channel import Bisq2Channel

    boundary = Bisq2Channel._rest_boundary_now()

    assert boundary.tzinfo is not None
    assert boundary.microsecond % 1000 == 0


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("expanded_dimension", ["channel", "sender"])
async def test_scope_expansion_resets_and_primes_before_old_history_is_eligible(
    tmp_path,
    expanded_dimension,
):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    if expanded_dimension == "channel":
        old_settings = _settings(
            channels=("channel-original-private",),
            senders=("profile-shared-private",),
        )
        new_settings = _settings(
            channels=("channel-original-private", "channel-expanded-private"),
            senders=("profile-shared-private",),
        )
        message_channel = "channel-expanded-private"
        message_sender = "profile-shared-private"
    else:
        old_settings = _settings(
            channels=("channel-shared-private",),
            senders=("profile-original-private",),
        )
        new_settings = _settings(
            channels=("channel-shared-private",),
            senders=("profile-original-private", "profile-expanded-private"),
        )
        message_channel = "channel-shared-private"
        message_sender = "profile-expanded-private"

    old_scope = resolve_bisq2_test_scope(old_settings)
    new_scope = resolve_bisq2_test_scope(new_settings)
    assert old_scope.fingerprint != new_scope.fingerprint

    state_path = tmp_path / "bisq-live-state.json"
    old_cursor = datetime.now(UTC) - timedelta(hours=2)
    message_time = datetime.now(UTC) - timedelta(hours=1)
    old_state = BisqSyncStateManager(str(state_path))
    old_state.bind_scope(old_scope.fingerprint)
    old_state.update_last_sync(old_cursor)
    old_state.mark_processed("message-from-old-scope")
    old_state.save_state()

    historical_message = {
        "messageId": "newly-allowed-historical-message",
        "channelId": message_channel,
        "senderUserProfileId": message_sender,
        "author": "Production test user",
        "message": "How can I complete this trade?",
        "timestamp": int(message_time.timestamp() * 1000),
    }
    export_date = (
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            side_effect=[
                {"exportDate": export_date, "messages": [historical_message]},
                {"exportDate": export_date, "messages": [historical_message]},
            ]
        ),
    )
    restarted_state = BisqSyncStateManager(str(state_path))
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = new_settings
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: {
            "bisq2_api": bisq_api,
            "bisq2_sync_state_manager": restarted_state,
        }.get(name)
    )

    channel = Bisq2Channel(runtime)

    assert channel._last_poll_since is None
    assert "message-from-old-scope" not in channel._seen_message_ids

    await channel.start()
    messages = await channel.poll_conversations()

    assert messages == []
    assert restarted_state.scope_fingerprint == new_scope.fingerprint
    assert "newly-allowed-historical-message" in channel._seen_message_ids
    assert bisq_api.export_chat_messages.await_count == 2
    assert bisq_api.export_chat_messages.await_args_list[0].kwargs == {"since": None}
    fresh_cursor = bisq_api.export_chat_messages.await_args_list[1].kwargs["since"]
    assert fresh_cursor > message_time

    persisted_state = state_path.read_text(encoding="utf-8")
    for private_scope_value in (
        old_scope.allowed_channel_ids
        | old_scope.allowed_sender_profile_ids
        | new_scope.allowed_channel_ids
        | new_scope.allowed_sender_profile_ids
    ):
        assert private_scope_value not in persisted_state


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_scope_rebaseline_keeps_polling_closed_until_snapshot_succeeds():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    historical_message = {
        "messageId": "historical-message",
        "channelId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Production test user",
        "message": "This predates the new scope.",
        "timestamp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp() * 1000),
    }
    fresh_export_date = (
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            side_effect=[
                RuntimeError("snapshot unavailable"),
                {
                    "exportDate": fresh_export_date,
                    "messages": [historical_message],
                },
                {
                    "exportDate": fresh_export_date,
                    "messages": [historical_message],
                },
            ]
        ),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    await channel.start()

    assert channel.test_scope_rebaseline_complete is False

    messages = await channel.poll_conversations()

    assert messages == []
    assert channel.test_scope_rebaseline_complete is True
    assert "historical-message" in channel._seen_message_ids
    assert bisq_api.export_chat_messages.await_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_cached_snapshot_cannot_complete_scope_rebaseline():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    now = datetime.now(UTC)
    historical_message = {
        "messageId": "cached-history",
        "channelId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Production test user",
        "message": "This predates the new scope.",
        "timestamp": int((now - timedelta(hours=1)).timestamp() * 1000),
    }
    stale_export_date = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    fresh_export_date = (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            side_effect=[
                {
                    "exportDate": stale_export_date,
                    "messages": [],
                },
                {
                    "exportDate": fresh_export_date,
                    "messages": [historical_message],
                },
                {
                    "exportDate": fresh_export_date,
                    "messages": [historical_message],
                },
            ]
        ),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    await channel.start()

    assert channel.test_scope_rebaseline_complete is False
    assert "cached-history" not in channel._seen_message_ids

    messages = await channel.poll_conversations()

    assert messages == []
    assert channel.test_scope_rebaseline_complete is True
    assert "cached-history" in channel._seen_message_ids
    assert bisq_api.export_chat_messages.await_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_future_dated_snapshot_history_keeps_scope_fail_closed():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    ambiguous_history = {
        "messageId": "ambiguous-future-history",
        "channelId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Production test user",
        "message": "This row cannot be proven to predate activation.",
        "timestamp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp() * 1000),
    }
    fresh_export_date = (
        (datetime.now(UTC) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    )
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            return_value={
                "exportDate": fresh_export_date,
                "messages": [ambiguous_history],
            }
        ),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    channel._question_prefilter = MagicMock()

    await channel.start()
    messages = await channel.poll_conversations()

    assert messages == []
    assert channel.test_scope_rebaseline_complete is False
    assert "ambiguous-future-history" not in channel._seen_message_ids
    assert "ambiguous-future-history" not in channel._message_cache_by_id
    channel._question_prefilter.evaluate_text.assert_not_called()
    assert bisq_api.export_chat_messages.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ambiguous_startup_message_self_heals_at_a_fresh_retry_boundary():
    import asyncio

    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    message_time: datetime | None = None
    call_count = 0

    async def export_chat_messages(*, since):
        nonlocal call_count, message_time
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(0.005)
            message_time = datetime.now(UTC)
        assert message_time is not None
        message = {
            "messageId": "arrived-during-failed-activation",
            "channelId": "channel-allowed",
            "senderUserProfileId": "profile-allowed",
            "author": "Production test user",
            "message": "Sent before readiness became green.",
            "timestamp": int(message_time.timestamp() * 1000),
        }
        return {
            "exportDate": (datetime.now(UTC) + timedelta(seconds=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "messages": [message],
        }

    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(side_effect=export_chat_messages),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    await channel.start()
    assert channel.test_scope_rebaseline_complete is False

    await asyncio.sleep(0.005)
    messages = await channel.poll_conversations()

    assert messages == []
    assert channel.test_scope_rebaseline_complete is True
    assert "arrived-during-failed-activation" in channel._seen_message_ids
    assert bisq_api.export_chat_messages.await_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebaseline_replay_safety_does_not_depend_on_seen_cache_capacity():
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    historical_time = datetime.now(UTC) - timedelta(hours=1)
    historical_messages = [
        {
            "messageId": f"historical-message-{index}",
            "channelId": "channel-allowed",
            "senderUserProfileId": "profile-allowed",
            "author": "Production test user",
            "message": "This row predates activation.",
            "timestamp": int(historical_time.timestamp() * 1000),
        }
        for index in range(3)
    ]
    fresh_export_date = (
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(
            side_effect=[
                {
                    "exportDate": fresh_export_date,
                    "messages": historical_messages,
                },
                {
                    "exportDate": fresh_export_date,
                    "messages": historical_messages,
                },
            ]
        ),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)
    channel._max_seen_message_ids = 2

    await channel.start()
    messages = await channel.poll_conversations()

    assert channel.test_scope_rebaseline_complete is True
    assert "historical-message-0" not in channel._seen_message_ids
    assert messages == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_message_omitted_during_fresh_snapshot_remains_eligible():
    import asyncio

    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    message_time: datetime | None = None

    async def export_chat_messages(*, since):
        nonlocal message_time
        if since is None:
            await asyncio.sleep(0.01)
            message_time = datetime.now(UTC)
            return {
                "exportDate": (message_time + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "messages": [],
            }
        assert message_time is not None
        return {
            "exportDate": (message_time + timedelta(seconds=2))
            .isoformat()
            .replace("+00:00", "Z"),
            "messages": [
                {
                    "messageId": "arrived-during-export",
                    "channelId": "channel-allowed",
                    "senderUserProfileId": "profile-allowed",
                    "author": "Production test user",
                    "message": "This arrived while the snapshot was built.",
                    "timestamp": int(message_time.timestamp() * 1000),
                }
            ],
        }

    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(side_effect=export_chat_messages),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    await channel.start()
    messages = await channel.poll_conversations()

    assert [message.message_id for message in messages] == ["arrived-during-export"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_regular_poll_keeps_pre_request_cursor_when_export_build_omits_message():
    import asyncio

    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    message_time: datetime | None = None
    regular_poll_count = 0

    async def export_chat_messages(*, since):
        nonlocal message_time, regular_poll_count
        if since is None:
            return {
                "exportDate": (datetime.now(UTC) + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "messages": [],
            }
        regular_poll_count += 1
        if regular_poll_count == 1:
            await asyncio.sleep(0.01)
            message_time = datetime.now(UTC)
            return {
                "exportDate": (message_time + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "messages": [],
            }
        assert message_time is not None
        return {
            "exportDate": (datetime.now(UTC) + timedelta(seconds=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "messages": [
                {
                    "messageId": "omitted-during-regular-export",
                    "channelId": "channel-allowed",
                    "senderUserProfileId": "profile-allowed",
                    "author": "Production test user",
                    "message": "How do I complete this trade?",
                    "timestamp": int(message_time.timestamp() * 1000),
                }
            ],
        }

    bisq_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(side_effect=export_chat_messages),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: bisq_api if name == "bisq2_api" else None
    )
    channel = Bisq2Channel(runtime)

    await channel.start()
    first_poll = await channel.poll_conversations()
    second_poll = await channel.poll_conversations()

    assert first_poll == []
    assert [message.message_id for message in second_poll] == [
        "omitted-during-regular-export"
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incomplete_scope_marker_survives_external_save_and_restart(tmp_path):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
    from app.channels.runtime import ChannelRuntime

    state_path = tmp_path / "bisq-live-state.json"
    state = BisqSyncStateManager(str(state_path))
    failing_api = SimpleNamespace(
        setup=AsyncMock(),
        export_chat_messages=AsyncMock(side_effect=RuntimeError("unavailable")),
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = _settings()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: {
            "bisq2_api": failing_api,
            "bisq2_sync_state_manager": state,
        }.get(name)
    )
    channel = Bisq2Channel(runtime)

    await channel.start()
    state.save_state()

    restarted_state = BisqSyncStateManager(str(state_path))
    restarted_runtime = MagicMock(spec=ChannelRuntime)
    restarted_runtime.settings = _settings()
    restarted_runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            restarted_state if name == "bisq2_sync_state_manager" else None
        )
    )
    restarted_channel = Bisq2Channel(restarted_runtime)

    assert restarted_state.scope_rebaseline_complete is False
    assert restarted_channel.test_scope_rebaseline_complete is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scope_values_are_absent_from_repr_and_decision_logs(caplog):
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
    from app.channels.runtime import ChannelRuntime

    channel_sentinel = "channel-sentinel-private"
    sender_sentinel = "profile-sentinel-private"
    settings = _settings(
        channels=(channel_sentinel,),
        senders=(sender_sentinel,),
    )
    scope = resolve_bisq2_test_scope(settings)
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    outgoing = SimpleNamespace(
        user=SimpleNamespace(user_id="profile-blocked", metadata={})
    )

    with caplog.at_level(logging.WARNING):
        result = await channel.send_message(channel_sentinel, outgoing)

    output = repr(scope) + caplog.text
    assert result.sent is False
    assert channel_sentinel not in output
    assert sender_sentinel not in output
