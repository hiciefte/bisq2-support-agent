"""Tests for ChatOps command dispatching."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.chatops import ChatOpsCommand, ChatOpsCommandName, ChatOpsDispatcher
from app.models.escalation import (
    Escalation,
    EscalationAlreadyClaimedError,
    EscalationDeliveryStatus,
    EscalationListResponse,
    EscalationPriority,
    EscalationStatus,
)


def _command(
    name: ChatOpsCommandName,
    *,
    case_id: int | None = None,
    options: dict[str, str] | None = None,
    message: str | None = None,
    source_message_id: str = "$event",
) -> ChatOpsCommand:
    return ChatOpsCommand(
        name=name,
        actor_id="@staff:server",
        source_message_id=source_message_id,
        room_id="!staff:server",
        raw_text=f"!case {name.value}",
        case_id=case_id,
        options=options or {},
        message=message,
    )


def _escalation(
    escalation_id: int,
    *,
    status: EscalationStatus = EscalationStatus.PENDING,
    priority: EscalationPriority = EscalationPriority.NORMAL,
    question: str = "How can I buy BTC?",
    ai_draft_answer: str = "Use Bisq Easy.",
    staff_id: str | None = None,
    created_at: datetime | None = None,
    channel_metadata: dict[str, str] | None = None,
    staff_answer: str | None = None,
) -> Escalation:
    now = created_at or datetime.now(timezone.utc)
    return Escalation(
        id=escalation_id,
        message_id=f"msg-{escalation_id}",
        channel="matrix",
        user_id="@user:server",
        username="user",
        channel_metadata=channel_metadata or {},
        question_original=question,
        question=question,
        ai_draft_answer_original=ai_draft_answer,
        ai_draft_answer=ai_draft_answer,
        user_language="en",
        translation_applied=False,
        confidence_score=0.8,
        routing_action="needs_human",
        routing_reason="test",
        sources=[],
        staff_answer=staff_answer,
        staff_id=staff_id,
        edit_distance=None,
        staff_answer_rating=None,
        delivery_status=EscalationDeliveryStatus.NOT_REQUIRED,
        delivery_error=None,
        delivery_attempts=0,
        last_delivery_at=None,
        generated_faq_id=None,
        status=status,
        priority=priority,
        created_at=now,
        claimed_at=None,
        responded_at=None,
        closed_at=None,
    )


def _service() -> MagicMock:
    service = MagicMock()
    service.repository = MagicMock()
    service.repository.get_by_id = AsyncMock()
    service.list_escalations = AsyncMock()
    service.claim_escalation = AsyncMock()
    service.unclaim_escalation = AsyncMock()
    service.respond_to_escalation = AsyncMock()
    service.prioritize_escalation = AsyncMock()
    service.close_escalation = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_dispatch_list_formats_matching_cases() -> None:
    service = _service()
    escalations = [
        _escalation(11, question="How do I buy BTC with EUR on Bisq Easy?"),
        _escalation(12, priority=EscalationPriority.HIGH, question="Second question"),
    ]
    service.list_escalations.return_value = EscalationListResponse(
        escalations=escalations,
        total=2,
        limit=20,
        offset=0,
    )
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    result = await dispatcher.dispatch(_command(ChatOpsCommandName.LIST))

    assert result.ok is True
    assert "Cases:" in result.message
    assert (
        '#11 [new] channel=matrix user=@user:server q="How do I buy BTC with EUR on Bisq Easy?"'
        in result.message
    )
    assert "#12 [escalated]" in result.message


@pytest.mark.asyncio
async def test_dispatch_claim_and_unclaim_delegate_to_service() -> None:
    service = _service()
    claimed = _escalation(
        21, status=EscalationStatus.IN_REVIEW, staff_id="@staff:server"
    )
    unclaimed = _escalation(21)
    service.claim_escalation.return_value = claimed
    service.unclaim_escalation.return_value = unclaimed
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    claim_result = await dispatcher.dispatch(
        _command(ChatOpsCommandName.CLAIM, case_id=21)
    )
    unclaim_result = await dispatcher.dispatch(
        _command(ChatOpsCommandName.UNCLAIM, case_id=21, source_message_id="$event-2")
    )

    service.claim_escalation.assert_awaited_once_with(21, "@staff:server")
    service.unclaim_escalation.assert_awaited_once_with(21, "@staff:server")
    assert claim_result.message == "Claimed case #21."
    assert unclaim_result.message == "Released case #21."


@pytest.mark.asyncio
async def test_dispatch_send_uses_ai_draft_and_cancels_arbitration_when_thread_is_known() -> (
    None
):
    service = _service()
    escalation = _escalation(
        31,
        channel_metadata={"thread_id": "!public:server"},
        ai_draft_answer="Draft answer",
    )
    sent = _escalation(31, status=EscalationStatus.RESPONDED, staff_id="@staff:server")
    service.repository.get_by_id.return_value = escalation
    service.respond_to_escalation.return_value = sent
    arbitration = SimpleNamespace(cancel_for_chatops_send=AsyncMock())
    dispatcher = ChatOpsDispatcher(
        escalation_service=service,
        arbitration_service=arbitration,
    )

    result = await dispatcher.dispatch(_command(ChatOpsCommandName.SEND, case_id=31))

    arbitration.cancel_for_chatops_send.assert_awaited_once_with("!public:server")
    service.respond_to_escalation.assert_awaited_once_with(
        31, "Draft answer", "@staff:server"
    )
    assert result.message == "Sent case #31 to the user."


@pytest.mark.asyncio
async def test_dispatch_edit_send_uses_custom_message() -> None:
    service = _service()
    escalation = _escalation(32)
    sent = _escalation(32, status=EscalationStatus.RESPONDED, staff_id="@staff:server")
    service.repository.get_by_id.return_value = escalation
    service.respond_to_escalation.return_value = sent
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    result = await dispatcher.dispatch(
        _command(
            ChatOpsCommandName.EDIT_SEND,
            case_id=32,
            message="Edited response",
        )
    )

    service.respond_to_escalation.assert_awaited_once_with(
        32, "Edited response", "@staff:server"
    )
    assert result.message == "Edited and sent case #32."


@pytest.mark.asyncio
async def test_dispatch_edit_send_rejects_empty_message() -> None:
    service = _service()
    escalation = _escalation(32)
    service.repository.get_by_id.return_value = escalation
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    result = await dispatcher.dispatch(
        _command(
            ChatOpsCommandName.EDIT_SEND,
            case_id=32,
            message="   ",
        )
    )

    service.respond_to_escalation.assert_not_awaited()
    assert result.ok is False
    assert result.message == "Case #32 requires a non-empty edited message."


@pytest.mark.asyncio
async def test_dispatch_claim_returns_domain_error_result() -> None:
    service = _service()
    service.claim_escalation.side_effect = EscalationAlreadyClaimedError(
        "Escalation 21 already claimed"
    )
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    result = await dispatcher.dispatch(_command(ChatOpsCommandName.CLAIM, case_id=21))

    assert result.ok is False
    assert result.message == "Escalation 21 already claimed"


@pytest.mark.asyncio
async def test_dispatch_escalate_and_resolve_delegate_to_service() -> None:
    service = _service()
    high = _escalation(41, priority=EscalationPriority.HIGH)
    closed = _escalation(41, status=EscalationStatus.CLOSED)
    service.prioritize_escalation.return_value = high
    service.close_escalation.return_value = closed
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    escalate_result = await dispatcher.dispatch(
        _command(
            ChatOpsCommandName.ESCALATE,
            case_id=41,
            options={"reason": "vip"},
        )
    )
    resolve_result = await dispatcher.dispatch(
        _command(
            ChatOpsCommandName.RESOLVE,
            case_id=41,
            options={"note": "done"},
            source_message_id="$event-2",
        )
    )

    service.prioritize_escalation.assert_awaited_once_with(41, EscalationPriority.HIGH)
    service.close_escalation.assert_awaited_once_with(41)
    assert "Reason: vip" in escalate_result.message
    assert "Note: done" in resolve_result.message


@pytest.mark.asyncio
async def test_dispatch_returns_idempotent_result_for_same_source_message() -> None:
    service = _service()
    service.list_escalations.return_value = EscalationListResponse(
        escalations=[],
        total=0,
        limit=20,
        offset=0,
    )
    dispatcher = ChatOpsDispatcher(escalation_service=service)
    command = _command(ChatOpsCommandName.LIST, source_message_id="$same")

    first = await dispatcher.dispatch(command)
    second = await dispatcher.dispatch(command)

    service.list_escalations.assert_awaited_once()
    assert first.idempotent is False
    assert second.idempotent is True
    assert second.message == first.message


@pytest.mark.asyncio
async def test_dispatch_concurrent_idempotent_result_calls_service_once() -> None:
    service = _service()
    blocker = asyncio.Event()

    async def delayed_list_escalations(**_: object) -> EscalationListResponse:
        await blocker.wait()
        return EscalationListResponse(
            escalations=[],
            total=0,
            limit=20,
            offset=0,
        )

    service.list_escalations = AsyncMock(side_effect=delayed_list_escalations)
    dispatcher = ChatOpsDispatcher(escalation_service=service)
    command = _command(ChatOpsCommandName.LIST, source_message_id="$same")

    first_task = asyncio.create_task(dispatcher.dispatch(command))
    second_task = asyncio.create_task(dispatcher.dispatch(command))
    await asyncio.sleep(0)
    blocker.set()

    first, second = await asyncio.gather(first_task, second_task)

    service.list_escalations.assert_awaited_once()
    assert first.ok is True
    assert second.ok is True
    assert first.message == second.message
    assert first.idempotent is False
    assert second.idempotent is True


@pytest.mark.asyncio
async def test_dispatch_without_source_message_id_skips_idempotent_cache() -> None:
    service = _service()
    service.list_escalations.return_value = EscalationListResponse(
        escalations=[],
        total=0,
        limit=20,
        offset=0,
    )
    dispatcher = ChatOpsDispatcher(escalation_service=service)
    command = _command(ChatOpsCommandName.LIST, source_message_id="")

    first = await dispatcher.dispatch(command)
    second = await dispatcher.dispatch(command)

    assert first.idempotent is False
    assert second.idempotent is False
    assert service.list_escalations.await_count == 2


@pytest.mark.asyncio
async def test_dispatch_stale_filters_old_pending_cases() -> None:
    service = _service()
    now = datetime.now(timezone.utc)
    service.list_escalations.return_value = EscalationListResponse(
        escalations=[
            _escalation(51, created_at=now - timedelta(minutes=45)),
            _escalation(52, created_at=now - timedelta(minutes=5)),
        ],
        total=2,
        limit=20,
        offset=0,
    )
    dispatcher = ChatOpsDispatcher(escalation_service=service, stale_after_minutes=30)

    result = await dispatcher.dispatch(
        _command(ChatOpsCommandName.LIST, options={"scope": "stale"})
    )

    assert "#51 [new]" in result.message
    assert "#52" not in result.message


@pytest.mark.asyncio
async def test_dispatch_escalated_filters_high_priority_pending_cases() -> None:
    service = _service()
    service.list_escalations.return_value = EscalationListResponse(
        escalations=[
            _escalation(61, priority=EscalationPriority.HIGH),
            _escalation(62, priority=EscalationPriority.NORMAL),
        ],
        total=2,
        limit=20,
        offset=0,
    )
    dispatcher = ChatOpsDispatcher(escalation_service=service)

    result = await dispatcher.dispatch(
        _command(ChatOpsCommandName.LIST, options={"scope": "escalated"})
    )

    assert "#61 [escalated]" in result.message
    assert "#62" not in result.message
