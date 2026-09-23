"""Durable internal-review boundaries using the real escalation repository."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.models.escalation import (
    EscalationAlreadyClaimedError,
    EscalationClosedError,
    EscalationCreate,
    EscalationDeliveryStatus,
    EscalationInvalidStateError,
    EscalationStatus,
    EscalationUpdate,
)
from app.services.escalation.escalation_repository import EscalationRepository
from app.services.escalation.escalation_service import EscalationService

pytestmark = pytest.mark.unit

METADATA = {
    "response_kind": "public_context",
    "delivery_audience": "staff_room",
    "room_id": "!public:example.org",
    "source_url": "https://matrix.to/#/!public:example.org/$source",
    "staff_thread_url": "https://matrix.to/#/!staff:example.org/$root",
    "context_status": "delivered",
}


def data(**overrides):
    fields = dict(
        message_id="matrix_context_source",
        channel="matrix",
        user_id="@questioner:example.org",
        question="Where is mediation opened after the trade period?",
        ai_draft_answer="The trade screen provides the mediation entry point.",
        confidence_score=0.8,
        routing_action="needs_human",
        channel_metadata=dict(METADATA),
    )
    fields.update(overrides)
    return EscalationCreate(**fields)


@pytest.fixture
async def runtime(tmp_path):
    repository = EscalationRepository(str(tmp_path / "escalations.db"))
    await repository.initialize()
    delivery = SimpleNamespace(deliver=AsyncMock(return_value=True))
    learning = SimpleNamespace(record_review=Mock())
    faq = SimpleNamespace(add_faq=Mock())
    feedback = SimpleNamespace(record_user_rating=Mock())
    embeddings = SimpleNamespace(
        embed_query=Mock(side_effect=AssertionError("Unexpected embedding call"))
    )
    service = EscalationService(
        repository=repository,
        response_delivery=delivery,
        faq_service=faq,
        learning_engine=learning,
        feedback_orchestrator=feedback,
        embeddings=embeddings,
        settings=SimpleNamespace(
            ESCALATION_CLAIM_TTL_MINUTES=30,
            ESCALATION_DELIVERY_MAX_RETRIES=3,
        ),
    )
    return SimpleNamespace(
        service=service,
        repository=repository,
        delivery=delivery,
        learning=learning,
        faq=faq,
        feedback=feedback,
        embeddings=embeddings,
    )


def assert_no_side_effects(runtime):
    runtime.delivery.deliver.assert_not_awaited()
    runtime.learning.record_review.assert_not_called()
    runtime.faq.add_faq.assert_not_called()
    runtime.feedback.record_user_rating.assert_not_called()
    runtime.embeddings.embed_query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        METADATA,
        {"response_kind": "public_context"},
        {"delivery_audience": "staff_room"},
    ],
)
async def test_review_persists_internally_across_repository_restart(
    runtime, monkeypatch, metadata
):
    hybrid = AsyncMock(
        side_effect=AssertionError("Review must not call hybrid distance")
    )
    monkeypatch.setattr(
        "app.services.escalation.escalation_service.compute_hybrid_distance", hybrid
    )
    case = await runtime.service.create_escalation(data(channel_metadata=metadata))
    await runtime.service.claim_escalation(case.id, "reviewer")
    answer = "Use the documented mediation entry point when the trade period expires."
    result = await runtime.service.respond_to_escalation(case.id, answer, "reviewer")

    restarted = EscalationRepository(runtime.repository.db_path)
    persisted = await restarted.get_by_id(case.id)
    assert result == persisted
    assert persisted.staff_answer == answer and persisted.staff_id == "reviewer"
    assert persisted.status == EscalationStatus.RESPONDED
    assert persisted.delivery_status == EscalationDeliveryStatus.NOT_REQUIRED
    assert persisted.delivery_attempts == 0 and persisted.last_delivery_at is None
    assert persisted.channel_metadata == metadata
    assert persisted.responded_at is not None and persisted.edit_distance > 0
    hybrid.assert_not_awaited()
    assert_no_side_effects(runtime)


@pytest.mark.asyncio
async def test_duplicate_creation_and_review_preserve_original_case(runtime):
    case = await runtime.service.create_escalation(data())
    duplicate = await runtime.service.create_escalation(data(question="Changed input"))
    assert duplicate.id == case.id and duplicate.question == case.question
    first = await runtime.service.respond_to_escalation(
        case.id, "Reviewed context", "staff"
    )
    repeated = await runtime.service.respond_to_escalation(
        case.id, "Reviewed context", "staff"
    )
    assert repeated == first
    assert len(runtime.service._delivery_locks) == 0
    with pytest.raises(EscalationAlreadyClaimedError):
        await runtime.service.respond_to_escalation(case.id, "Another answer", "other")
    assert_no_side_effects(runtime)


@pytest.mark.asyncio
async def test_claim_and_closed_case_protection_still_apply(runtime):
    case = await runtime.service.create_escalation(data())
    await runtime.service.claim_escalation(case.id, "owner")
    with pytest.raises(EscalationAlreadyClaimedError):
        await runtime.service.respond_to_escalation(case.id, "Review", "other")
    await runtime.service.close_escalation(case.id)
    with pytest.raises(EscalationClosedError):
        await runtime.service.respond_to_escalation(case.id, "Review", "owner")
    assert_no_side_effects(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [EscalationDeliveryStatus.PENDING, EscalationDeliveryStatus.FAILED]
)
async def test_internal_case_never_retries_even_with_legacy_delivery_state(
    runtime, status
):
    case = await runtime.service.create_escalation(data())
    case = await runtime.repository.update(
        case.id,
        EscalationUpdate(
            staff_answer="Internal note",
            status=EscalationStatus.RESPONDED,
            delivery_status=status,
        ),
    )
    with pytest.raises(EscalationInvalidStateError, match="Internal staff context"):
        await runtime.service.retry_delivery(case.id)
    with pytest.raises(EscalationInvalidStateError, match="Internal staff context"):
        await runtime.service._attempt_delivery(case, "Internal note", channel="web")
    persisted = await runtime.repository.get_by_id(case.id)
    assert persisted.delivery_attempts == 0 and persisted.delivery_status == status
    assert_no_side_effects(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_internal_case_cannot_create_faq_even_when_forced(
    runtime, monkeypatch, force
):
    case = await runtime.service.create_escalation(data())
    await runtime.service.respond_to_escalation(case.id, "Reviewed context", "staff")
    similarity = AsyncMock(side_effect=AssertionError("No FAQ retrieval allowed"))
    monkeypatch.setattr(
        "app.services.escalation.escalation_service.find_similar_faqs", similarity
    )
    with pytest.raises(EscalationInvalidStateError, match="cannot generate FAQs"):
        await runtime.service.generate_faq_from_escalation(
            case.id, "Question", "Answer", force=force
        )
    similarity.assert_not_awaited()
    assert_no_side_effects(runtime)


@pytest.mark.asyncio
async def test_public_rating_and_service_polling_cannot_learn_or_expose_internal_review(
    runtime,
):
    case = await runtime.service.create_escalation(data())
    assert await runtime.service.get_user_response(case.message_id) is None
    reviewed = await runtime.service.respond_to_escalation(
        case.id, "Internal review", "staff"
    )
    assert not await runtime.service.record_staff_answer_rating(
        reviewed, rating=1, rater_id="public-rater", trusted=True
    )
    assert await runtime.service.get_user_response(case.message_id) is None
    await runtime.service.close_escalation(case.id)
    assert await runtime.service.get_user_response(case.message_id) is None
    persisted = await runtime.repository.get_by_id(case.id)
    assert persisted.staff_answer_rating is None
    assert_no_side_effects(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {"room_id": "!public:example.org"},
        {"response_kind": "answer"},
        {"delivery_audience": "source_room"},
    ],
)
async def test_ordinary_matrix_response_keeps_delivery_and_learning(runtime, metadata):
    case = await runtime.service.create_escalation(data(channel_metadata=metadata))
    result = await runtime.service.respond_to_escalation(
        case.id, case.ai_draft_answer, "staff"
    )
    assert result.status == EscalationStatus.RESPONDED
    assert result.delivery_status == EscalationDeliveryStatus.DELIVERED
    assert result.delivery_attempts == 1
    runtime.delivery.deliver.assert_awaited_once()
    runtime.learning.record_review.assert_called_once()
    assert runtime.learning.record_review.call_args.kwargs["admin_action"] == "approved"


@pytest.mark.asyncio
async def test_rejection_waits_for_same_case_delivery_lock(runtime, monkeypatch):
    case = await runtime.service.create_escalation(data())
    sending_lock = await runtime.service._acquire_delivery_lock(case.id)
    acquire = runtime.service._acquire_delivery_lock
    rejection_started = asyncio.Event()

    async def enter_rejection(case_id):
        rejection_started.set()
        return await acquire(case_id)

    monkeypatch.setattr(runtime.service, "_acquire_delivery_lock", enter_rejection)
    rejection = asyncio.create_task(runtime.service.close_escalation(case.id))
    await rejection_started.wait()
    assert not rejection.done()
    assert (
        await runtime.repository.get_by_id(case.id)
    ).status == EscalationStatus.PENDING
    await runtime.service._release_delivery_lock(case.id, sending_lock)
    closed = await rejection
    assert closed.status == EscalationStatus.CLOSED
    assert closed.closed_at is not None
    assert runtime.service._delivery_locks == {}
    assert runtime.service._delivery_lock_refs == {}
    assert_no_side_effects(runtime)
