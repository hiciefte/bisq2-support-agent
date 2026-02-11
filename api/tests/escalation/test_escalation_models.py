"""Tests for escalation Pydantic models."""

import pytest
from app.models.escalation import (
    EscalationCreate,
    EscalationPriority,
    GenerateFAQRequest,
    RespondRequest,
)
from pydantic import ValidationError


class TestEscalationCreate:
    """Validate EscalationCreate model."""

    def test_valid_escalation_create_succeeds(self):
        """All required fields present -> success."""
        esc = EscalationCreate(
            message_id="550e8400-e29b-41d4-a716-446655440000",
            channel="web",
            user_id="user_123",
            question="How do I restore my wallet?",
            ai_draft_answer="You can restore by...",
            confidence_score=0.42,
            routing_action="needs_human",
        )
        assert esc.message_id == "550e8400-e29b-41d4-a716-446655440000"
        assert esc.channel == "web"
        assert esc.priority == EscalationPriority.NORMAL

    def test_empty_question_rejected(self):
        """Empty or whitespace-only question raises ValidationError."""
        with pytest.raises(ValidationError):
            EscalationCreate(
                message_id="msg-001",
                channel="web",
                user_id="user_123",
                question="",
                ai_draft_answer="Answer",
                confidence_score=0.5,
                routing_action="needs_human",
            )

    def test_question_max_length_enforced(self):
        """Question > 4000 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            EscalationCreate(
                message_id="msg-001",
                channel="web",
                user_id="user_123",
                question="x" * 4001,
                ai_draft_answer="Answer",
                confidence_score=0.5,
                routing_action="needs_human",
            )

    def test_invalid_channel_rejected(self):
        """Empty channel raises ValidationError."""
        with pytest.raises(ValidationError):
            EscalationCreate(
                message_id="msg-001",
                channel="   ",
                user_id="user_123",
                question="How?",
                ai_draft_answer="Answer",
                confidence_score=0.5,
                routing_action="needs_human",
            )

    def test_confidence_score_bounds(self):
        """Confidence outside [0.0, 1.0] raises ValidationError."""
        with pytest.raises(ValidationError):
            EscalationCreate(
                message_id="msg-001",
                channel="web",
                user_id="user_123",
                question="How?",
                ai_draft_answer="Answer",
                confidence_score=1.5,
                routing_action="needs_human",
            )
        with pytest.raises(ValidationError):
            EscalationCreate(
                message_id="msg-001",
                channel="web",
                user_id="user_123",
                question="How?",
                ai_draft_answer="Answer",
                confidence_score=-0.1,
                routing_action="needs_human",
            )

    def test_question_whitespace_stripped(self):
        """Leading/trailing whitespace removed from question."""
        esc = EscalationCreate(
            message_id="msg-001",
            channel="web",
            user_id="user_123",
            question="  How do I restore?  ",
            ai_draft_answer="Answer",
            confidence_score=0.5,
            routing_action="needs_human",
        )
        assert esc.question == "How do I restore?"


class TestRespondRequest:
    """Validate RespondRequest model."""

    def test_valid_respond_request_succeeds(self):
        """Valid staff_answer + staff_id -> success."""
        req = RespondRequest(
            staff_answer="Here's how to fix your issue...",
            staff_id="staff_42",
        )
        assert req.staff_answer == "Here's how to fix your issue..."
        assert req.staff_id == "staff_42"

    def test_empty_staff_answer_rejected(self):
        """Empty answer raises ValidationError."""
        with pytest.raises(ValidationError):
            RespondRequest(staff_answer="", staff_id="staff_42")
        with pytest.raises(ValidationError):
            RespondRequest(staff_answer="   ", staff_id="staff_42")

    def test_staff_answer_max_length_enforced(self):
        """Answer > 10000 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            RespondRequest(staff_answer="x" * 10001, staff_id="staff_42")


class TestGenerateFAQRequest:
    """Validate GenerateFAQRequest model."""

    def test_valid_faq_request_succeeds(self):
        """Valid question + answer + category -> success."""
        req = GenerateFAQRequest(
            question="How do I restore my wallet?",
            answer="Navigate to Settings > Wallet > Restore.",
            category="Bisq 2",
            protocol="bisq_easy",
        )
        assert req.category == "Bisq 2"
        assert req.protocol == "bisq_easy"

    def test_custom_category_accepted(self):
        """Categories are intentionally flexible for escalation-generated FAQs."""
        req = GenerateFAQRequest(
            question="How?",
            answer="Like this.",
            category="Invalid Category",
        )
        assert req.category == "Invalid Category"

    def test_overlong_category_rejected(self):
        """Category > 128 chars raises ValidationError."""
        with pytest.raises(ValidationError):
            GenerateFAQRequest(
                question="How?",
                answer="Like this.",
                category="x" * 129,
            )

    def test_invalid_protocol_rejected(self):
        """Protocol not in allowed set raises ValidationError."""
        with pytest.raises(ValidationError):
            GenerateFAQRequest(
                question="How?",
                answer="Like this.",
                protocol="invalid_protocol",
            )

    def test_null_protocol_accepted(self):
        """protocol=None is a valid value (means all protocols)."""
        req = GenerateFAQRequest(
            question="How?",
            answer="Like this.",
            protocol=None,
        )
        assert req.protocol is None
