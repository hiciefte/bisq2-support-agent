from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.arbitration.coordinator import ArbitrationCoordinator
from app.channels.models import (
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


def _incoming(
    *,
    message_id: str = "$m1",
    question: str = "Need help",
    room_id: str = "!room:server",
) -> IncomingMessage:
    return IncomingMessage(
        message_id=message_id,
        channel=ChannelType.MATRIX,
        question=question,
        user=UserContext(
            user_id="@user:server",
            session_id=None,
            channel_user_id="@user:server",
            auth_token=None,
        ),
        channel_metadata={"room_id": room_id},
    )


def _outgoing(
    incoming: IncomingMessage, *, answer: str = "AI draft"
) -> OutgoingMessage:
    return OutgoingMessage(
        message_id=f"out-{incoming.message_id}",
        in_reply_to=incoming.message_id,
        channel=incoming.channel,
        answer=answer,
        sources=[],
        user=incoming.user,
        metadata=ResponseMetadata(
            processing_time_ms=12.0,
            rag_strategy="retrieval",
            model_name="test-model",
            confidence_score=0.8,
            routing_action="auto_send",
            routing_reason=None,
        ),
        original_question=incoming.question,
        requires_human=False,
    )


def _policy_service(
    *,
    delay: int = 60,
    mode: str = "autonomous",
    cooldown: int = 300,
    hitl_timeout: int = 120,
) -> SimpleNamespace:
    policy = SimpleNamespace(
        first_response_delay_seconds=delay,
        ai_response_mode=mode,
        staff_active_cooldown_seconds=cooldown,
        hitl_approval_timeout_seconds=hitl_timeout,
        enabled=True,
    )
    return SimpleNamespace(get_policy=lambda _channel_id: policy)


@pytest.mark.asyncio
async def test_enqueue_with_zero_delay_dispatches_immediately() -> None:
    incoming = _incoming()
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(policy_service=_policy_service(delay=0))

    sent = await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
    )

    assert sent is True
    on_release.assert_awaited_once_with(incoming)
    on_dispatch.assert_awaited_once_with(incoming, response)
    assert coordinator._threads == {}


@pytest.mark.asyncio
async def test_wait_timer_releases_and_dispatches_in_autonomous_mode() -> None:
    incoming = _incoming()
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(
        policy_service=_policy_service(mode="autonomous")
    )

    await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
    )

    await coordinator._on_wait_timer_elapsed(
        thread_id="!room:server::@user:server",
        generation=1,
    )

    on_release.assert_awaited_once()
    on_dispatch.assert_awaited_once()
    assert coordinator._threads == {}


@pytest.mark.asyncio
async def test_staff_activity_suppresses_pending_thread() -> None:
    incoming = _incoming()
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(policy_service=_policy_service())

    await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
    )

    await coordinator.record_staff_activity(
        room_or_conversation_id="!room:server",
        staff_id="@staff:server",
    )
    await coordinator._on_wait_timer_elapsed(
        thread_id="!room:server::@user:server",
        generation=1,
    )

    on_release.assert_not_awaited()
    on_dispatch.assert_not_awaited()
    entry = coordinator._threads.get("!room:server::@user:server")
    assert entry is not None
    assert entry.state == "deferred_by_room_activity"


@pytest.mark.asyncio
async def test_hitl_timeout_escalates_and_notifies_user_without_auto_dispatch() -> None:
    incoming = _incoming()
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=99)
    )
    channel = MagicMock()
    channel.runtime = None
    channel.get_delivery_target = MagicMock(return_value="!room:server")
    channel.send_message = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(
        policy_service=_policy_service(mode="hitl", hitl_timeout=60),
        escalation_service=escalation_service,
    )

    await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
        channel=channel,
    )
    await coordinator._on_wait_timer_elapsed(
        thread_id="!room:server::@user:server",
        generation=1,
    )

    # Manually fire timeout handler to avoid waiting.
    await coordinator._on_hitl_timeout(
        thread_id="!room:server::@user:server",
        generation=1,
        incoming=incoming,
        response=response,
        channel=channel,
    )

    on_release.assert_awaited_once()
    on_dispatch.assert_not_awaited()
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    sent_notice = channel.send_message.call_args.args[1]
    assert "team member's attention" in sent_notice.answer
    assert coordinator._threads == {}


@pytest.mark.asyncio
async def test_hitl_timeout_routes_to_staff_room_only_when_user_notice_mode_is_none() -> (
    None
):
    incoming = _incoming(room_id="!support:server")
    incoming = incoming.model_copy(
        update={
            "channel_metadata": {
                "room_id": "!support:server",
                "staff_room_id": "!staff:server",
            },
        }
    )
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=101)
    )
    policy = SimpleNamespace(
        first_response_delay_seconds=60,
        ai_response_mode="hitl",
        staff_active_cooldown_seconds=300,
        hitl_approval_timeout_seconds=60,
        enabled=True,
        public_escalation_notice_enabled=False,
        escalation_notification_channel="staff_room",
        escalation_user_notice_mode="none",
        escalation_user_notice_template="this needs a team member's attention. someone will follow up.",
    )
    policy_service = SimpleNamespace(get_policy=lambda _channel_id: policy)
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )
    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target = MagicMock(return_value="!support:server")
    channel.send_message = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(
        policy_service=policy_service,
        escalation_service=escalation_service,
    )

    await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!support:server", "@user:server"),
        room_or_conversation_id="!support:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
        channel=channel,
    )
    await coordinator._on_wait_timer_elapsed(
        thread_id="!support:server::@user:server",
        generation=1,
    )

    await coordinator._on_hitl_timeout(
        thread_id="!support:server::@user:server",
        generation=1,
        incoming=incoming,
        response=response,
        channel=channel,
    )

    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    assert channel.send_message.call_args.args[0] == "!staff:server"
    sent_notice = channel.send_message.call_args.args[1]
    assert "Escalation #101" in sent_notice.answer
    assert "Reply to user (copy-ready):" in sent_notice.answer
    assert "AI draft" in sent_notice.answer
    assert coordinator._threads == {}


@pytest.mark.asyncio
async def test_followup_messages_are_accumulated_for_single_release() -> None:
    first = _incoming(message_id="$m1", question="first question")
    second = _incoming(message_id="$m2", question="second question")
    response = _outgoing(second)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(
        policy_service=_policy_service(mode="autonomous")
    )

    await coordinator.enqueue(
        incoming=first,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
    )
    await coordinator.enqueue(
        incoming=second,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
    )

    await coordinator._on_wait_timer_elapsed(
        thread_id="!room:server::@user:server",
        generation=2,
    )

    merged_incoming = on_release.await_args.args[0]
    assert merged_incoming.message_id == "$m1"
    assert merged_incoming.question == "first question\n---\nsecond question"


@pytest.mark.asyncio
async def test_autonomous_dispatch_retries_once_before_dead_letter_escalation() -> None:
    incoming = _incoming()
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(side_effect=[False, False])
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=100)
    )
    channel = MagicMock()
    channel.get_delivery_target = MagicMock(return_value="!room:server")
    channel.send_message = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(
        policy_service=_policy_service(mode="autonomous"),
        escalation_service=escalation_service,
    )

    await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
        channel=channel,
    )

    await coordinator._on_wait_timer_elapsed(
        thread_id="!room:server::@user:server",
        generation=1,
    )

    assert on_dispatch.await_count == 2
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    failure_notice = channel.send_message.call_args.args[1]
    assert "follow up" in failure_notice.answer.lower()
    assert coordinator._threads == {}


@pytest.mark.asyncio
async def test_room_staff_activity_defers_pending_thread_until_cooldown_expires() -> (
    None
):
    incoming = _incoming()
    response = _outgoing(incoming)
    on_release = AsyncMock(return_value=response)
    on_dispatch = AsyncMock(return_value=True)
    coordinator = ArbitrationCoordinator(policy_service=_policy_service(cooldown=60))

    await coordinator.enqueue(
        incoming=incoming,
        thread_id=("!room:server", "@user:server"),
        room_or_conversation_id="!room:server",
        on_release=on_release,
        on_dispatch=on_dispatch,
    )
    await coordinator.record_staff_activity(
        room_or_conversation_id="!room:server",
        staff_id="@staff:server",
    )

    entry = coordinator._threads.get("!room:server::@user:server")
    assert entry is not None
    assert entry.state == "deferred_by_room_activity"

    coordinator._last_staff_activity_by_room["!room:server"] = 0.0
    await coordinator._on_deferred_timer_elapsed(
        thread_id="!room:server::@user:server",
        generation=1,
    )

    on_release.assert_awaited_once()
    on_dispatch.assert_awaited_once()
    assert coordinator._threads == {}
