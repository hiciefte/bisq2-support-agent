"""Tests for LearningEngine integration in escalation pipeline."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.escalation import (
    Escalation,
    EscalationNotRespondedError,
    EscalationStatus,
)
from app.services.escalation.escalation_service import EscalationService


def _make_service(
    repo=None,
    delivery=None,
    faq_service=None,
    learning_engine=None,
    settings=None,
):
    """Create EscalationService with mock dependencies."""
    return EscalationService(
        repository=repo or AsyncMock(),
        response_delivery=delivery or AsyncMock(),
        faq_service=faq_service or MagicMock(),
        learning_engine=learning_engine or MagicMock(),
        settings=settings or MagicMock(),
    )


def _make_escalation(**overrides):
    """Build a realistic Escalation for test assertions."""
    defaults = dict(
        id=1,
        message_id="550e8400-e29b-41d4-a716-446655440000",
        channel="web",
        user_id="web_user_123",
        username="TestUser",
        question="How do I restore my wallet?",
        ai_draft_answer="Navigate to Settings > Wallet > Restore.",
        confidence_score=0.42,
        routing_action="needs_human",
        routing_reason="Low confidence",
        status=EscalationStatus.IN_REVIEW,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        sources=[],
        channel_metadata={},
        staff_id="staff_1",
        claimed_at=datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return Escalation(**defaults)


# ---------------------------------------------------------------------------
# LearningEngine Integration
# ---------------------------------------------------------------------------


class TestEscalationLearningIntegration:
    """Test LearningEngine recording on resolution."""

    @pytest.mark.asyncio
    async def test_record_review_called_on_respond(self):
        """LearningEngine.record_review() called when staff responds."""
        learning = MagicMock()
        learning.record_review = MagicMock()
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=_make_escalation())
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        await service.respond_to_escalation(1, "Staff answer", "staff_1")

        learning.record_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_review_correct_parameters(self):
        """Parameters: question_id, confidence, action, routing_action."""
        learning = MagicMock()
        learning.record_review = MagicMock()
        esc = _make_escalation(
            confidence_score=0.42,
            routing_action="needs_human",
            ai_draft_answer="AI draft",
        )
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        await service.respond_to_escalation(1, "Different answer", "staff_1")

        call_kwargs = learning.record_review.call_args
        assert call_kwargs[1]["confidence"] == 0.42 or call_kwargs[0][1] == 0.42

    @pytest.mark.asyncio
    async def test_record_review_includes_metadata(self):
        """Metadata includes channel and staff_id."""
        learning = MagicMock()
        learning.record_review = MagicMock()
        esc = _make_escalation(channel="matrix")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        # Use same staff_id as the claim owner to avoid claim conflict
        await service.respond_to_escalation(1, "Staff answer", "staff_1")

        call_kwargs = learning.record_review.call_args
        metadata = call_kwargs[1].get("metadata") or call_kwargs[0][-1]
        assert metadata["channel"] == "matrix"
        assert metadata["staff_id"] == "staff_1"

    @pytest.mark.asyncio
    async def test_learning_failure_does_not_block_respond(self):
        """LearningEngine error doesn't prevent response delivery."""
        learning = MagicMock()
        learning.record_review = MagicMock(side_effect=RuntimeError("boom"))
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=_make_escalation())
        updated = _make_escalation(
            status=EscalationStatus.RESPONDED, staff_answer="answer"
        )
        repo.update = AsyncMock(return_value=updated)
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        result = await service.respond_to_escalation(1, "answer", "staff_1")

        assert result.status == EscalationStatus.RESPONDED

    @pytest.mark.asyncio
    async def test_record_review_action_is_edited_when_answer_changed(self):
        """admin_action is 'edited' when staff_answer differs from ai_draft_answer."""
        learning = MagicMock()
        learning.record_review = MagicMock()
        esc = _make_escalation(ai_draft_answer="AI original draft")
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        await service.respond_to_escalation(1, "Completely different answer", "staff_1")

        call_kwargs = learning.record_review.call_args
        admin_action = call_kwargs[1].get("admin_action") or call_kwargs[0][2]
        assert admin_action == "edited"

    @pytest.mark.asyncio
    async def test_record_review_action_is_approved_when_answer_unchanged(self):
        """admin_action is 'approved' when staff_answer matches ai_draft_answer."""
        learning = MagicMock()
        learning.record_review = MagicMock()
        ai_answer = "Navigate to Settings > Wallet > Restore."
        esc = _make_escalation(ai_draft_answer=ai_answer)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        await service.respond_to_escalation(1, ai_answer, "staff_1")

        call_kwargs = learning.record_review.call_args
        admin_action = call_kwargs[1].get("admin_action") or call_kwargs[0][2]
        assert admin_action == "approved"

    @pytest.mark.asyncio
    async def test_record_review_question_id_format(self):
        """question_id format is 'escalation_{id}'."""
        learning = MagicMock()
        learning.record_review = MagicMock()
        esc = _make_escalation(id=42)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(
            return_value=_make_escalation(status=EscalationStatus.RESPONDED)
        )
        delivery = AsyncMock()
        delivery.deliver = AsyncMock(return_value=True)

        service = _make_service(repo=repo, delivery=delivery, learning_engine=learning)
        await service.respond_to_escalation(42, "Staff answer", "staff_1")

        call_kwargs = learning.record_review.call_args
        question_id = call_kwargs[1].get("question_id") or call_kwargs[0][0]
        assert question_id == "escalation_42"


# ---------------------------------------------------------------------------
# FAQ Generation Integration
# ---------------------------------------------------------------------------


class TestEscalationFAQGeneration:
    """Test FAQ generation from resolved escalations."""

    @pytest.mark.asyncio
    async def test_generate_faq_creates_verified_faq(self):
        """Generated FAQ has verified=True and source='Escalation'."""
        faq_service = MagicMock()
        faq_item_result = MagicMock()
        faq_item_result.id = "faq-123"
        faq_item_result.verified = True
        faq_service.add_faq = MagicMock(return_value=faq_item_result)

        esc = _make_escalation(status=EscalationStatus.RESPONDED)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(return_value=esc)

        service = _make_service(repo=repo, faq_service=faq_service)
        await service.generate_faq_from_escalation(
            1, "How to restore?", "Go to Settings."
        )

        faq_call = faq_service.add_faq.call_args[0][0]
        assert faq_call.verified is True
        assert faq_call.source == "Escalation"

    @pytest.mark.asyncio
    async def test_generate_faq_links_to_escalation(self):
        """Escalation record updated with generated_faq_id."""
        faq_service = MagicMock()
        faq_item_result = MagicMock()
        faq_item_result.id = "faq-456"
        faq_service.add_faq = MagicMock(return_value=faq_item_result)

        esc = _make_escalation(status=EscalationStatus.RESPONDED)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(return_value=esc)

        service = _make_service(repo=repo, faq_service=faq_service)
        await service.generate_faq_from_escalation(1, "Question?", "Answer.")

        update_call = repo.update.call_args
        update_data = update_call[0][1]
        assert update_data.generated_faq_id == "faq-456"

    @pytest.mark.asyncio
    async def test_generate_faq_not_responded_raises_error(self):
        """Cannot generate FAQ from pending escalation."""
        esc = _make_escalation(status=EscalationStatus.PENDING)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)

        service = _make_service(repo=repo)
        with pytest.raises(EscalationNotRespondedError):
            await service.generate_faq_from_escalation(1, "Question?", "Answer.")

    @pytest.mark.asyncio
    async def test_generate_faq_calls_faq_service(self):
        """FAQService.add_faq() is invoked with correct data."""
        faq_service = MagicMock()
        faq_item_result = MagicMock()
        faq_item_result.id = "faq-789"
        faq_service.add_faq = MagicMock(return_value=faq_item_result)

        esc = _make_escalation(status=EscalationStatus.RESPONDED)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(return_value=esc)

        service = _make_service(repo=repo, faq_service=faq_service)
        await service.generate_faq_from_escalation(
            1,
            "How do I use multisig?",
            "Use the multisig trading protocol.",
            category="Trading",
            protocol="multisig_v1",
        )

        faq_service.add_faq.assert_called_once()
        faq_call = faq_service.add_faq.call_args[0][0]
        assert faq_call.question == "How do I use multisig?"
        assert faq_call.answer == "Use the multisig trading protocol."
        assert faq_call.category == "Trading"
        assert faq_call.protocol == "multisig_v1"

    @pytest.mark.asyncio
    async def test_generate_faq_returns_faq_data(self):
        """Return dict includes faq_id, question, answer."""
        faq_service = MagicMock()
        faq_item_result = MagicMock()
        faq_item_result.id = "faq-abc"
        faq_service.add_faq = MagicMock(return_value=faq_item_result)

        esc = _make_escalation(status=EscalationStatus.RESPONDED)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(return_value=esc)

        service = _make_service(repo=repo, faq_service=faq_service)
        result = await service.generate_faq_from_escalation(1, "Question?", "Answer.")

        assert result["faq_id"] == "faq-abc"
        assert result["question"] == "Question?"
        assert result["answer"] == "Answer."

    @pytest.mark.asyncio
    async def test_generate_faq_allowed_for_closed_escalation(self):
        """FAQ can be generated from closed (already responded) escalation."""
        faq_service = MagicMock()
        faq_item_result = MagicMock()
        faq_item_result.id = "faq-closed"
        faq_service.add_faq = MagicMock(return_value=faq_item_result)

        esc = _make_escalation(status=EscalationStatus.CLOSED)
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(return_value=esc)
        repo.update = AsyncMock(return_value=esc)

        service = _make_service(repo=repo, faq_service=faq_service)
        result = await service.generate_faq_from_escalation(1, "Q?", "A.")

        assert result["faq_id"] == "faq-closed"
