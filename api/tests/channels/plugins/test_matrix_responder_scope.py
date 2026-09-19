"""Isolate a live pilot without changing historical training ingestion."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import ChannelType, OutgoingMessage, UserContext
from app.channels.plugins.matrix.channel import MatrixChannel
from app.channels.plugins.matrix.chatops_adapter import MatrixChatOpsAdapter
from app.channels.plugins.matrix.message_handler import MatrixMessageHandler
from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler
from app.channels.plugins.matrix.room_filter import (
    is_responder_room_allowed,
    resolve_allowed_reaction_rooms,
    resolve_allowed_responder_rooms,
)
from app.channels.runtime import ChannelRuntime
from app.core.config import Settings
from app.models.escalation import Escalation, EscalationStatus
from app.services.escalation.response_delivery import ResponseDelivery
from app.services.training.ingest.matrix_sync_service import MatrixSyncService

PILOT = "!pilot:example.invalid"
PUBLIC = "!support:example.invalid"
DM = "!direct:example.invalid"


def _runtime(scope):
    settings = SimpleNamespace(
        MATRIX_RESPONDER_ROOMS=scope,
        MATRIX_SYNC_ROOMS=[PUBLIC],
        MATRIX_STAFF_ROOM=PILOT,
        MATRIX_ALERT_ROOM=PUBLIC,
        MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES=True,
    )
    runtime = ChannelRuntime(settings=settings, rag_service=MagicMock())
    client = SimpleNamespace(
        room_send=AsyncMock(return_value=SimpleNamespace(event_id="$sent")),
        join=AsyncMock(return_value=SimpleNamespace(room_id=PILOT)),
    )
    runtime.register("matrix_client", client)
    return runtime, client


@pytest.mark.parametrize("scope", ["", [], [PILOT]])
def test_explicit_scope_preserves_training_source_and_excludes_other_rooms(scope):
    runtime, _ = _runtime(scope)
    expected = frozenset({PILOT}) if scope else frozenset()
    assert resolve_allowed_responder_rooms(runtime.settings) == expected
    assert resolve_allowed_reaction_rooms(runtime.settings) == expected
    assert MatrixSyncService._get_sync_rooms(runtime.settings) == [PUBLIC]
    assert not is_responder_room_allowed(runtime.settings, PUBLIC)
    assert not is_responder_room_allowed(runtime.settings, DM)


def test_unset_scope_preserves_legacy_behavior():
    runtime, _ = _runtime(None)
    assert resolve_allowed_responder_rooms(runtime.settings) == frozenset({PUBLIC})
    assert resolve_allowed_reaction_rooms(runtime.settings) == frozenset(
        {PUBLIC, PILOT}
    )
    assert is_responder_room_allowed(runtime.settings, PILOT)


@pytest.mark.parametrize("value", ["", [], PILOT, [PILOT]])
def test_settings_preserve_explicit_empty_or_exact_scope(value):
    settings = Settings(MATRIX_RESPONDER_ROOMS=value)
    assert settings.MATRIX_RESPONDER_ROOMS == ([PILOT] if value else [])
    assert Settings().MATRIX_RESPONDER_ROOMS is None


@pytest.mark.parametrize(
    "value", ["@user:example.invalid", "!missing-server", "!bad :x", [None]]
)
def test_settings_reject_invalid_scope(value):
    with pytest.raises(ValueError, match="exact Matrix room IDs"):
        Settings(MATRIX_RESPONDER_ROOMS=value)


@pytest.mark.parametrize("value", ["null", "[null]", "[", "true", "42"])
def test_invalid_environment_value_cannot_restore_legacy_scope(monkeypatch, value):
    monkeypatch.setenv("MATRIX_RESPONDER_ROOMS", value)
    with pytest.raises(ValueError, match="exact Matrix room IDs"):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["", "[]", PILOT, '["' + PILOT + '"]'])
def test_environment_preserves_empty_and_explicit_scope(monkeypatch, value):
    monkeypatch.setenv("MATRIX_RESPONDER_ROOMS", value)
    settings = Settings(_env_file=None)
    assert settings.MATRIX_RESPONDER_ROOMS == ([] if value in ("", "[]") else [PILOT])


def test_bootstrap_applies_scope_to_all_live_handlers(tmp_path):
    settings = Settings(
        DATA_DIR=str(tmp_path),
        MATRIX_SYNC_USER="@bot:example.invalid",
        MATRIX_SYNC_PASSWORD="test-only",
        MATRIX_HOMESERVER_URL="https://example.invalid",
        MATRIX_SYNC_ROOMS=[PUBLIC],
        MATRIX_RESPONDER_ROOMS=[PILOT],
        MATRIX_STAFF_ROOM=PILOT,
        MATRIX_CHATOPS_ROOM_IDS=[PILOT, PUBLIC],
        TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=[PILOT, PUBLIC],
    )
    runtime = ChannelRuntime(settings=settings, rag_service=MagicMock())
    runtime.register("trust_monitor_service", SimpleNamespace())
    runtime.register("reaction_processor", MagicMock())
    MatrixChannel.setup_dependencies(runtime, settings)
    handler = runtime.resolve("matrix_message_handler")
    assert handler.allowed_room_ids == frozenset({PILOT})
    assert handler.staff_command_room_ids == frozenset({PILOT})
    assert runtime.resolve("matrix_reaction_handler").allowed_room_ids == frozenset(
        {PILOT}
    )
    assert runtime.resolve(
        "matrix_trust_monitor_handler"
    ).allowed_room_ids == frozenset({PILOT})
    assert runtime.resolve("matrix_chatops_adapter").allowed_room_ids == {PILOT}
    assert MatrixSyncService._get_sync_rooms(settings) == [PUBLIC]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [PUBLIC, DM, PILOT])
@pytest.mark.parametrize("scope", [[PILOT], []])
async def test_transport_applies_scope_to_answers_reactions_and_joins(scope, target):
    runtime, client = _runtime(scope)
    channel = MatrixChannel(runtime)
    answer = OutgoingMessage(
        message_id="test-answer",
        in_reply_to="$question",
        metadata={
            "processing_time_ms": 0,
            "rag_strategy": "test",
            "model_name": "test",
        },
        channel=ChannelType.MATRIX,
        answer="Synthetic pilot answer",
        user=UserContext(user_id="test-user"),
    )
    allowed = target in scope
    assert bool(await channel.send_message(target, answer)) is allowed
    assert bool(await channel.send_reaction(target, "$question", "👍")) is allowed
    assert bool(await channel.join_room(target)) is allowed
    assert client.room_send.await_count == (2 if allowed else 0)
    assert client.join.await_count == (1 if allowed else 0)


@pytest.mark.asyncio
async def test_out_of_scope_ingress_has_no_staff_trust_or_generation_effects():
    runtime, _ = _runtime([PILOT])
    handler = MatrixMessageHandler(
        client=SimpleNamespace(user_id="@bot:example.invalid"),
        connection_manager=MagicMock(),
        channel=MatrixChannel(runtime),
        allowed_room_ids=[PUBLIC, PILOT],
        staff_command_room_ids=[PUBLIC, PILOT],
    )
    handler._record_trust_event = AsyncMock()
    handler._record_staff_activity = AsyncMock()
    handler._maybe_handle_staff_command = AsyncMock()
    handler._get_orchestrator = MagicMock()
    await handler._on_message(SimpleNamespace(room_id=PUBLIC), MagicMock())
    handler._record_trust_event.assert_not_awaited()
    handler._record_staff_activity.assert_not_awaited()
    handler._maybe_handle_staff_command.assert_not_awaited()
    handler._get_orchestrator.assert_not_called()


@pytest.mark.asyncio
async def test_chatops_and_legacy_notices_cannot_escape_scope():
    runtime, client = _runtime([PILOT])
    dispatcher = SimpleNamespace(dispatch=AsyncMock())
    adapter = MatrixChatOpsAdapter(
        runtime=runtime,
        enabled=True,
        allowed_room_ids={PUBLIC, PILOT},
        dispatcher=dispatcher,
    )
    assert not await adapter.handle_event(
        room_id=PUBLIC,
        event_id="$command",
        sender="@staff:example.invalid",
        text="!case send 12",
    )
    await adapter._send_notice(
        room_id=PUBLIC, root_event_id="$root", body="Synthetic notice"
    )
    reaction_handler = MatrixReactionHandler(
        runtime, MagicMock(), allowed_room_ids=[PUBLIC, PILOT]
    )
    assert not await reaction_handler.handle_staff_command(
        room_id=PUBLIC,
        sender="@staff:example.invalid",
        command_text="/send",
        reply_to_event_id="$root",
    )
    await reaction_handler._send_staff_thread_notice(
        room_id=PUBLIC, root_event_id="$root", body="Synthetic notice"
    )
    dispatcher.dispatch.assert_not_awaited()
    client.room_send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [PUBLIC, PILOT])
async def test_staff_review_delivery_respects_transport_scope(target):
    runtime, client = _runtime([PILOT])
    registry = SimpleNamespace(get=lambda _: MatrixChannel(runtime))
    delivery = ResponseDelivery(registry)
    escalation = Escalation(
        id=42,
        message_id="$question",
        channel="matrix",
        user_id="test-user",
        question="Synthetic question",
        ai_draft_answer="Synthetic answer",
        confidence_score=0.5,
        routing_action="needs_human",
        status=EscalationStatus.RESPONDED,
        created_at=datetime.now(timezone.utc),
        channel_metadata={"room_id": target},
    )
    assert bool(await delivery.deliver(escalation, "Synthetic answer")) is (
        target == PILOT
    )
    assert client.room_send.await_count == (1 if target == PILOT else 0)


def test_staff_notice_metadata_cannot_override_scope():
    runtime, _ = _runtime([PILOT])
    channel = MatrixChannel(runtime)
    assert channel.get_staff_notification_target({}) == PILOT
    assert channel.get_staff_notification_target({"staff_room_id": PUBLIC}) == ""
