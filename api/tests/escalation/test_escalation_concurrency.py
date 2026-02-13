"""Tests for escalation concurrency scenarios."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.escalation import (
    DuplicateEscalationError,
    Escalation,
    EscalationAlreadyClaimedError,
    EscalationCreate,
    EscalationNotFoundError,
    EscalationPriority,
    EscalationStatus,
)
from app.services.escalation.escalation_service import EscalationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_escalation(**overrides) -> Escalation:
    defaults = dict(
        id=1,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="user_123",
        username="TestUser",
        question="How do I restore my wallet?",
        ai_draft_answer="Based on the documentation...",
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
def service(mock_repository):
    mock_delivery = MagicMock()
    mock_delivery.deliver = AsyncMock(return_value=True)
    mock_faq = MagicMock()
    mock_faq.add_faq = MagicMock(return_value=MagicMock(id="faq_1"))
    mock_learning = MagicMock()
    mock_learning.record_review = MagicMock()
    mock_settings = MagicMock()
    mock_settings.ESCALATION_CLAIM_TTL_MINUTES = 30
    mock_settings.ESCALATION_DELIVERY_MAX_RETRIES = 3
    mock_settings.ESCALATION_AUTO_CLOSE_HOURS = 72
    mock_settings.ESCALATION_RETENTION_DAYS = 90

    return EscalationService(
        repository=mock_repository,
        response_delivery=mock_delivery,
        faq_service=mock_faq,
        learning_engine=mock_learning,
        settings=mock_settings,
    )


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------


class TestEscalationConcurrency:
    """Test race conditions in claim/respond."""

    @pytest.mark.asyncio
    async def test_concurrent_claims_only_one_succeeds(self, service, mock_repository):
        """Two concurrent claims: one succeeds, one fails."""
        pending = _make_escalation(status=EscalationStatus.PENDING)
        claimed = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_1",
            claimed_at=datetime.now(timezone.utc),
        )
        # First call returns pending, second returns claimed by staff_1
        mock_repository.get_by_id.side_effect = [pending, claimed]
        mock_repository.update.return_value = claimed

        # First claim succeeds
        result = await service.claim_escalation(1, "staff_1")
        assert result.staff_id == "staff_1"

        # Second claim by different staff fails
        with pytest.raises(EscalationAlreadyClaimedError):
            await service.claim_escalation(1, "staff_2")

    @pytest.mark.asyncio
    async def test_concurrent_creates_same_message_id(self, service, mock_repository):
        """Duplicate message_id: one succeeds, one returns existing."""
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

    @pytest.mark.asyncio
    async def test_respond_after_close_fails(self, service, mock_repository):
        """Cannot respond to already-closed escalation."""
        closed = _make_escalation(status=EscalationStatus.CLOSED)
        mock_repository.get_by_id.return_value = closed

        with pytest.raises(EscalationNotFoundError):
            await service.respond_to_escalation(1, "Answer", "staff_1")

    @pytest.mark.asyncio
    async def test_double_respond_is_idempotent(self, service, mock_repository):
        """Second respond by same staff returns existing response."""
        already_responded = _make_escalation(
            status=EscalationStatus.RESPONDED,
            staff_answer="First answer",
            staff_id="staff_1",
            responded_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = already_responded

        result = await service.respond_to_escalation(1, "Second answer", "staff_1")
        assert result.staff_answer == "First answer"
        # Should not call update again
        mock_repository.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_claim_then_respond_different_staff_fails(
        self, service, mock_repository
    ):
        """Staff A claims, Staff B tries to respond -> fails."""
        claimed_by_a = _make_escalation(
            status=EscalationStatus.IN_REVIEW,
            staff_id="staff_A",
            claimed_at=datetime.now(timezone.utc),
        )
        mock_repository.get_by_id.return_value = claimed_by_a

        with pytest.raises(EscalationAlreadyClaimedError):
            await service.respond_to_escalation(1, "Answer", "staff_B")
