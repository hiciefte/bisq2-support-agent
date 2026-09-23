"""Persisted policy + real adapter boundaries; transport is the only mocked layer."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)
from app.channels.plugins.matrix.channel import MatrixChannel
from app.channels.plugins.matrix.chatops_adapter import MatrixChatOpsAdapter
from app.channels.plugins.matrix.message_handler import MatrixMessageHandler
from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler
from app.channels.plugins.matrix.room_filter import (
    resolve_allowed_context_source_rooms,
    resolve_allowed_responder_rooms,
)
from app.channels.runtime import ChannelRuntime
from app.core.config import Settings
from app.models.escalation import Escalation, EscalationStatus
from app.services.channel_autoresponse_policy_service import (
    ChannelAutoResponsePolicyService,
)
from app.services.escalation.response_delivery import ResponseDelivery

SOURCE = "!source:example.invalid"
STAFF = "!staff:example.invalid"
DM = "!direct:example.invalid"


def setup_boundary(tmp_path):
    service = ChannelAutoResponsePolicyService(str(tmp_path / "policy.db"))
    service.set_policy(
        "matrix",
        generation_enabled=True,
        enabled=False,
        ai_response_mode="hitl",
        response_kind="public_context",
        delivery_audience="staff_room",
    )
    settings = SimpleNamespace(
        MATRIX_SYNC_ENABLED=True,
        MATRIX_RESPONDER_ROOMS=[SOURCE, STAFF, DM],
        MATRIX_CONTEXT_SOURCE_ROOMS=[SOURCE],
        MATRIX_STAFF_ROOM=STAFF,
        MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES=True,
    )
    runtime = ChannelRuntime(settings=settings, rag_service=MagicMock())
    client = SimpleNamespace(
        room_send=AsyncMock(return_value=SimpleNamespace(event_id="$delivered"))
    )
    runtime.register("matrix_client", client)
    runtime.register("channel_autoresponse_policy_service", service)
    channel = MatrixChannel(runtime)
    channel._is_connected = True
    return service, runtime, client, channel


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [SOURCE, DM, STAFF])
async def test_staff_policy_blocks_all_generic_writes_even_if_legacy_scope_allows(
    tmp_path, target
):
    _, runtime, client, channel = setup_boundary(tmp_path)
    message = OutgoingMessage(
        message_id="draft",
        in_reply_to="$question",
        channel=ChannelType.MATRIX,
        answer="Synthetic",
        user=UserContext(user_id="test"),
        metadata={
            "processing_time_ms": 0,
            "rag_strategy": "test",
            "model_name": "test",
            "routing_action": "auto_send",
        },
    )
    assert not await channel.send_message(target, message)
    assert not await channel.send_reaction(target, "$question", "👍")
    await MatrixChatOpsAdapter(
        runtime=runtime, enabled=True, allowed_room_ids={target}, dispatcher=MagicMock()
    )._send_notice(room_id=target, root_event_id="$question", body="Synthetic notice")
    await MatrixReactionHandler(
        runtime, MagicMock(), allowed_room_ids=[target]
    )._send_staff_thread_notice(
        room_id=target, root_event_id="$question", body="Synthetic notice"
    )
    client.room_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_publisher_fixed_target_native_thread_and_transaction(tmp_path):
    _, runtime, client, channel = setup_boundary(tmp_path)
    runtime.settings.MATRIX_RESPONDER_ROOMS = []
    result = await channel.send_staff_context(
        "AI context · Synthetic fact.",
        transaction_id="case-note",
        thread_root_event_id="$staff-root",
        expected_room_id=STAFF,
    )
    assert result.external_message_id == "$delivered"
    sent = client.room_send.await_args.kwargs
    assert sent["room_id"] == STAFF
    assert sent["tx_id"] == "case-note"
    assert sent["ignore_unverified_devices"] is True
    assert sent["content"]["msgtype"] == "m.notice"
    assert sent["content"]["m.relates_to"] == {
        "rel_type": "m.thread",
        "event_id": "$staff-root",
        "is_falling_back": True,
        "m.in_reply_to": {"event_id": "$staff-root"},
    }
    assert sent["content"]["body"] == "AI context · Synthetic fact."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition",
    [
        "generation_off",
        "wrong_mode",
        "missing_target",
        "source_target",
        "invalid_target",
        "policy_error",
    ],
)
async def test_explicit_publisher_rechecks_policy_and_target(tmp_path, condition):
    service, runtime, client, channel = setup_boundary(tmp_path)
    if condition == "generation_off":
        service.set_policy("matrix", generation_enabled=False)
    elif condition == "wrong_mode":
        service.set_policy(
            "matrix",
            response_kind="answer",
            delivery_audience="source_room",
            ai_response_mode="autonomous",
        )
    elif condition == "policy_error":
        service.get_policy = MagicMock(side_effect=RuntimeError("unavailable"))
    else:
        runtime.settings.MATRIX_STAFF_ROOM = {
            "missing_target": "",
            "source_target": SOURCE,
            "invalid_target": "@direct:example.invalid",
        }[condition]
    assert not await channel.send_staff_context("Synthetic", transaction_id="case-root")
    client.room_send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker",
    [{"response_kind": "public_context"}, {"delivery_audience": "staff_room"}, {}],
)
async def test_saved_approval_cannot_publish_private_content(tmp_path, marker):
    service, _, client, channel = setup_boundary(tmp_path)
    if marker:
        # Historical private rows remain private even after an operator changes policy.
        service.set_policy(
            "matrix",
            response_kind="answer",
            delivery_audience="source_room",
            ai_response_mode="autonomous",
        )
    case = Escalation(
        id=1,
        message_id="$question",
        channel="matrix",
        user_id="test",
        question="Synthetic",
        ai_draft_answer="Synthetic",
        confidence_score=0.5,
        routing_action="needs_human",
        status=EscalationStatus.RESPONDED,
        created_at=datetime.now(timezone.utc),
        channel_metadata={"room_id": SOURCE, **marker},
    )
    delivery = ResponseDelivery(SimpleNamespace(get=lambda _: channel))
    assert not await delivery.deliver(case, "Synthetic staff edit")
    client.room_send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,room,expected", [(True, SOURCE, 1), (False, SOURCE, 0), (True, DM, 0)]
)
async def test_context_source_is_read_only_and_requires_generation(
    tmp_path, enabled, room, expected
):
    service, runtime, client, channel = setup_boundary(tmp_path)
    runtime.settings.MATRIX_RESPONDER_ROOMS = []
    service.set_policy("matrix", generation_enabled=enabled)
    handler = MatrixMessageHandler(
        client=client,
        connection_manager=MagicMock(),
        channel=channel,
        autoresponse_policy_service=service,
        allowed_room_ids=[],
    )
    incoming = IncomingMessage(
        message_id="$question",
        channel=ChannelType.MATRIX,
        question="Synthetic question",
        user=UserContext(user_id="test"),
        channel_metadata={"room_id": room},
    )
    handler._resolve_event = AsyncMock(return_value=object())
    handler._to_incoming_message = MagicMock(return_value=incoming)
    handler._is_self_sender = MagicMock(return_value=False)
    handler._is_staff_sender = MagicMock(return_value=False)
    handler._record_trust_event = AsyncMock()
    processor = SimpleNamespace(process_incoming=AsyncMock())
    handler._get_orchestrator = lambda: processor
    await handler._on_message(SimpleNamespace(room_id=room), object())
    assert processor.process_incoming.await_count == expected
    assert resolve_allowed_context_source_rooms(runtime.settings) == {SOURCE}
    assert resolve_allowed_responder_rooms(runtime.settings) == set()
    client.room_send.assert_not_awaited()


@pytest.mark.parametrize("value", [None, "@direct:example.invalid", "!bad", "[null]"])
def test_context_source_settings_reject_non_room_scope(value):
    with pytest.raises(ValueError):
        Settings(MATRIX_CONTEXT_SOURCE_ROOMS=value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition", ["changed_destination", "sync_off", "disconnected"]
)
async def test_publisher_cannot_continue_after_destination_or_lifecycle_change(
    tmp_path, condition
):
    _, runtime, client, channel = setup_boundary(tmp_path)
    if condition == "changed_destination":
        runtime.settings.MATRIX_STAFF_ROOM = "!otherstaff:example.invalid"
    elif condition == "sync_off":
        runtime.settings.MATRIX_SYNC_ENABLED = False
    else:
        channel._is_connected = False
    assert not await channel.send_staff_context(
        "Synthetic",
        transaction_id="case-note",
        thread_root_event_id="$staff-root",
        expected_room_id=STAFF,
    )
    client.room_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_drains_context_work_before_client_disconnect(tmp_path):
    _, runtime, _, channel = setup_boundary(tmp_path)
    calls = []

    async def close_context():
        calls.append("context")

    async def stop_transport(*, strict=False):
        calls.append("transport")

    runtime.register("matrix_context_runtime", SimpleNamespace(close=close_context))
    channel._stop_unlocked = stop_transport
    await channel.stop()
    assert calls == ["context", "transport"]


@pytest.mark.asyncio
async def test_start_reopens_context_before_message_ingress(tmp_path):
    _, runtime, _, channel = setup_boundary(tmp_path)
    calls = []

    def start_context():
        calls.append("context")

    async def start_handler():
        calls.append("handler")

    runtime.register("matrix_context_runtime", SimpleNamespace(start=start_context))
    runtime.register("matrix_connection_manager", SimpleNamespace(connect=AsyncMock()))
    runtime.register("matrix_message_handler", SimpleNamespace(start=start_handler))
    channel.join_room = AsyncMock(return_value=True)
    await channel.start()
    assert calls == ["context", "handler"]
