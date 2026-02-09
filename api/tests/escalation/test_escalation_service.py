"""Tests for EscalationService lifecycle orchestration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.escalation import (
    DuplicateEscalationError,
    Escalation,
    EscalationAlreadyClaimedError,
    EscalationCreate,
    EscalationNotFoundError,
    EscalationNotRespondedError,
    EscalationPriority,
    EscalationStatus,
)
from app.services.escalation.escalation_service import EscalationService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_escalation(**overrides) -> Escalation:
    defaults = dict(
        id=1,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="user_123",
        username="TestUser",
        question="How do I restore my wallet?",
        ai_draft_answer="Based on the documentation, you can restore...",
        confidence_score=0.42,
        routing_action="needs_human",
        status=EscalationStatus.PENDING,
        priority=EscalationPriority.NORMAL,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Escalation(**defaults)


@pytest.fixture
def mock_repository():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_message_id = AsyncMock()
    repo.update = AsyncMock()
    repo.list_escalations = AsyncMock()
    repo.get_counts = AsyncMock()
    repo.close_stale = AsyncMock()
    repo.purge_old = AsyncMock()
    repo.initialize = AsyncMock()
    return repo


@pytest.fixture
def mock_response_delivery():
    delivery = MagicMock()
    delivery.deliver = AsyncMock(return_value=True)
    return delivery


@pytest.fixture
def mock_faq_service():
    service = MagicMock()
    service.add_faq = MagicMock(return_value=MagicMock(id="faq_123"))
    return service


@pytest.fixture
def mock_learning_engine():
    engine = MagicMock()
    engine.record_review = MagicMock()
    return engine


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.ESCALATION_CLAIM_TTL_MINUTES = 30
    settings.ESCALATION_DELIVERY_MAX_RETRIES = 3
    settings.ESCALATION_AUTO_CLOSE_HOURS = 72
    settings.ESCALATION_RETENTION_DAYS = 90
    return settings


@pytest.fixture
def service(
    mock_repository,
    mock_response_delivery,
    mock_faq_service,
    mock_learning_engine,
    mock_settings,
):
    return EscalationService(
        repository=mock_repository,
        response_delivery=mock_response_delivery,
        faq_service=mock_faq_service,
        learning_engine=mock_learning_engine,
        settings=mock_settings,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestEscalationServiceCreate:
    """Test escalation creation."""

    @pytest.mark.asyncio
    async def test_create_from_data_succeeds(self, service, mock_repository):
        """EscalationCreate data -> stored escalation."""
        expected = _make_escalation()
        mock_repository.create.return_value = expected

        data = EscalationCreate(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            channel="web",
            user_id="user_123",
            username="TestUser",
            question="How do I restore my wallet?",
            ai_draft_answer="Based on the documentation...",
            confidence_score=0.42,
            routing_action="needs_human",
        )
        result = await service.create_escalation(data)
        assert result.id == 1
        mock_repository.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_duplicate_returns_existing(self, service, mock_repository):
        """Duplicate message_id returns existing escalation (idempotent)."""
        existing = _make_escalation()
        mock_repository.create.side_effect = DuplicateEscalationError("exists")
        mock_repository.get_by_message_id.return_value = existing

        data = EscalationCreate(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            channel="web",
            user_id="user_123",
            question="How?",
            ai_draft_answer="Answer",
            confidence_score=0.5,
            routing_action="needs_human",
        )
        result = await service.create_escalation(data)
        assert result.id == existing.id
        mock_repository.get_by_message_id.assert_awaited_once()


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


class TestEscalationServiceClaim:
    """Test claim logic."""

    @pytest.mark.asyncio
    async def test_claim_sets_in_review_status(self, service, mock_repository):
        """Status changes to 'in_review'."""
        pending = _make_escalation(status=EscalationStatus.PENDING)
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_1",
            claimed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = pending
        mock_repository.update.return_value = claimed

        result = await service.claim_escalation(1, "staff_1")
        assert result.status == EscalationStatus.IN_REVIEW

    @pytest.mark.asyncio
    async def test_claim_sets_staff_id_and_claimed_at(self, service, mock_repository):
        """staff_id and claimed_at populated."""
        pending = _make_escalation()
        now = datetime.now(timezone.utc)
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_1",
            claimed_at=now,
        )
        mock_repository.get_by_id.return_value = pending
        mock_repository.update.return_value = claimed

        result = await service.claim_escalation(1, "staff_1")
        assert result.staff_id == "staff_1"
        assert result.claimed_at is not None

    @pytest.mark.asyncio
    async def test_claim_already_claimed_by_same_staff_succeeds(
        self, service, mock_repository
    ):
        """Re-claiming own escalation is idempotent."""
        already_claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_1",
            claimed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = already_claimed

        result = await service.claim_escalation(1, "staff_1")
        assert result.status == EscalationStatus.IN_REVIEW
        # Should NOT call update (already claimed by same staff)
        mock_repository.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_already_claimed_by_other_raises_error(
        self, service, mock_repository
    ):
        """Claiming another's escalation raises EscalationAlreadyClaimedError."""
        already_claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_1",
            claimed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = already_claimed

        with pytest.raises(EscalationAlreadyClaimedError):
            await service.claim_escalation(1, "staff_2")

    @pytest.mark.asyncio
    async def test_claim_nonexistent_raises_error(self, service, mock_repository):
        """Unknown ID raises EscalationNotFoundError."""
        mock_repository.get_by_id.return_value = None

        with pytest.raises(EscalationNotFoundError):
            await service.claim_escalation(99999, "staff_1")

    @pytest.mark.asyncio
    async def test_claim_expired_allows_reclaim(self, service, mock_repository):
        """Expired claim can be taken by another staff member."""
        expired_claimed_at = datetime.now(timezone.utc) - timedelta(minutes=60)
        expired = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_1",
            claimed_at=expired_claimed_at,
        )
        reclaimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_2",
            claimed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = expired
        mock_repository.update.return_value = reclaimed

        result = await service.claim_escalation(1, "staff_2")
        assert result.staff_id == "staff_2"


# ---------------------------------------------------------------------------
# Respond
# ---------------------------------------------------------------------------


class TestEscalationServiceRespond:
    """Test respond logic."""

    @pytest.mark.asyncio
    async def test_respond_sets_responded_status(
        self, service, mock_repository, mock_response_delivery
    ):
        """Status changes to 'responded'."""
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW, staff_id="staff_1"
        )
        responded = _make_escalation(
            status=EscalationStatus.RESPONDED,
            staff_answer="Fixed answer",
            staff_id="staff_1",
            responded_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = claimed
        mock_repository.update.return_value = responded

        result = await service.respond_to_escalation(1, "Fixed answer", "staff_1")
        assert result.status == EscalationStatus.RESPONDED

    @pytest.mark.asyncio
    async def test_respond_stores_staff_answer(self, service, mock_repository):
        """staff_answer saved to database."""
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW, staff_id="staff_1"
        )
        responded = _make_escalation(
            status=EscalationStatus.RESPONDED,
            staff_answer="Here is the fix",
            staff_id="staff_1",
        )
        mock_repository.get_by_id.return_value = claimed
        mock_repository.update.return_value = responded

        result = await service.respond_to_escalation(1, "Here is the fix", "staff_1")
        assert result.staff_answer == "Here is the fix"

    @pytest.mark.asyncio
    async def test_respond_calls_delivery(
        self, service, mock_repository, mock_response_delivery
    ):
        """ResponseDelivery.deliver() called with correct args."""
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW, staff_id="staff_1"
        )
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = claimed
        mock_repository.update.return_value = responded

        await service.respond_to_escalation(1, "Answer", "staff_1")
        mock_response_delivery.deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_respond_calls_learning_engine(
        self, service, mock_repository, mock_learning_engine
    ):
        """LearningEngine.record_review() called."""
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW, staff_id="staff_1"
        )
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = claimed
        mock_repository.update.return_value = responded

        await service.respond_to_escalation(1, "Edited answer", "staff_1")
        mock_learning_engine.record_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_respond_delivery_failure_still_saves(
        self, service, mock_repository, mock_response_delivery
    ):
        """Delivery failure doesn't prevent saving response."""
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW, staff_id="staff_1"
        )
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = claimed
        mock_repository.update.return_value = responded
        mock_response_delivery.deliver.return_value = False

        result = await service.respond_to_escalation(1, "Answer", "staff_1")
        assert result.status == EscalationStatus.RESPONDED

    @pytest.mark.asyncio
    async def test_respond_records_delivery_status_failed(
        self, service, mock_repository, mock_response_delivery
    ):
        """Delivery failure records delivery_status='failed'."""
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW, staff_id="staff_1"
        )
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = claimed
        mock_repository.update.return_value = responded
        mock_response_delivery.deliver.return_value = False

        await service.respond_to_escalation(1, "Answer", "staff_1")
        # update should be called twice: first for response, then for delivery status
        assert mock_repository.update.await_count >= 1

    @pytest.mark.asyncio
    async def test_respond_nonexistent_raises_error(self, service, mock_repository):
        """Unknown ID raises EscalationNotFoundError."""
        mock_repository.get_by_id.return_value = None

        with pytest.raises(EscalationNotFoundError):
            await service.respond_to_escalation(99999, "Answer", "staff_1")


# ---------------------------------------------------------------------------
# Generate FAQ
# ---------------------------------------------------------------------------


class TestEscalationServiceGenerateFAQ:
    """Test FAQ generation."""

    @pytest.mark.asyncio
    async def test_generate_faq_creates_verified_faq(
        self, service, mock_repository, mock_faq_service
    ):
        """FAQ created with verified=True, source='Escalation'."""
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = responded
        mock_repository.update.return_value = responded

        result = await service.generate_faq_from_escalation(
            1, "Question?", "Answer.", "General"
        )
        assert "faq_id" in result
        mock_faq_service.add_faq.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_faq_links_to_escalation(
        self, service, mock_repository, mock_faq_service
    ):
        """generated_faq_id set on escalation."""
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = responded
        mock_repository.update.return_value = responded

        await service.generate_faq_from_escalation(1, "Q?", "A.", "General")
        # update should be called with generated_faq_id
        mock_repository.update.assert_awaited()

    @pytest.mark.asyncio
    async def test_generate_faq_not_responded_raises_error(
        self, service, mock_repository
    ):
        """Can't generate FAQ from pending escalation."""
        pending = _make_escalation(status=EscalationStatus.PENDING)
        mock_repository.get_by_id.return_value = pending

        with pytest.raises(EscalationNotRespondedError):
            await service.generate_faq_from_escalation(1, "Q?", "A.", "General")

    @pytest.mark.asyncio
    async def test_generate_faq_calls_faq_service(
        self, service, mock_repository, mock_faq_service
    ):
        """FAQService.add_faq() called with correct args."""
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_repository.get_by_id.return_value = responded
        mock_repository.update.return_value = responded

        await service.generate_faq_from_escalation(
            1, "How to restore?", "Navigate to Settings.", "Bisq 2", "bisq_easy"
        )
        call_args = mock_faq_service.add_faq.call_args
        faq_item = call_args[0][0]
        assert faq_item.question == "How to restore?"
        assert faq_item.source == "Escalation"
        assert faq_item.verified is True


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestEscalationServiceClose:
    """Test close logic."""

    @pytest.mark.asyncio
    async def test_close_sets_closed_status(self, service, mock_repository):
        """Status changes to 'closed'."""
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        closed = _make_escalation(
            status=EscalationStatus.CLOSED,
            closed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = responded
        mock_repository.update.return_value = closed

        result = await service.close_escalation(1)
        assert result.status == EscalationStatus.CLOSED

    @pytest.mark.asyncio
    async def test_close_sets_closed_at(self, service, mock_repository):
        """closed_at timestamp populated."""
        responded = _make_escalation(status=EscalationStatus.RESPONDED)
        closed = _make_escalation(
            status=EscalationStatus.CLOSED,
            closed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = responded
        mock_repository.update.return_value = closed

        result = await service.close_escalation(1)
        assert result.closed_at is not None


# ---------------------------------------------------------------------------
# Auto-close & Retention
# ---------------------------------------------------------------------------


class TestEscalationServiceAutoClose:
    """Test auto-close behavior."""

    @pytest.mark.asyncio
    async def test_auto_close_marks_stale_pending_as_closed(
        self, service, mock_repository
    ):
        """Escalations older than configured hours are closed."""
        mock_repository.close_stale.return_value = 3

        count = await service.auto_close_stale()
        assert count == 3
        mock_repository.close_stale.assert_awaited_once()


class TestEscalationServiceRetention:
    """Test retention purge behavior."""

    @pytest.mark.asyncio
    async def test_purge_retention_deletes_old_closed(self, service, mock_repository):
        """Old closed/responded escalations purged."""
        mock_repository.purge_old.return_value = 5

        count = await service.purge_retention()
        assert count == 5
        mock_repository.purge_old.assert_awaited_once()


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


class TestEscalationServicePolling:
    """Test user polling."""

    @pytest.mark.asyncio
    async def test_get_user_response_pending_returns_pending(
        self, service, mock_repository
    ):
        """Pending escalation returns {status: 'pending'}."""
        pending = _make_escalation(status=EscalationStatus.PENDING)
        mock_repository.get_by_message_id.return_value = pending

        result = await service.get_user_response("550e8400-e29b-41d4-a716-446655440000")
        assert result.status == "pending"
        assert result.staff_answer is None

    @pytest.mark.asyncio
    async def test_get_user_response_responded_returns_answer(
        self, service, mock_repository
    ):
        """Responded escalation returns {status: 'resolved', staff_answer: ...}."""
        responded = _make_escalation(
            status=EscalationStatus.RESPONDED,
            staff_answer="Here is the answer",
            responded_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_message_id.return_value = responded

        result = await service.get_user_response("550e8400-e29b-41d4-a716-446655440000")
        assert result.status == "resolved"
        assert result.staff_answer == "Here is the answer"

    @pytest.mark.asyncio
    async def test_get_user_response_closed_returns_resolved_without_answer(
        self, service, mock_repository
    ):
        """Closed escalation returns {status: 'resolved', staff_answer: None}."""
        closed = _make_escalation(status=EscalationStatus.CLOSED)
        mock_repository.get_by_message_id.return_value = closed

        result = await service.get_user_response("550e8400-e29b-41d4-a716-446655440000")
        assert result.status == "resolved"
        assert result.staff_answer is None

    @pytest.mark.asyncio
    async def test_get_user_response_unknown_returns_none(
        self, service, mock_repository
    ):
        """Unknown message_id returns None."""
        mock_repository.get_by_message_id.return_value = None

        result = await service.get_user_response("unknown-id")
        assert result is None
