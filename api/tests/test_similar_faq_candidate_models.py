"""
Tests for Similar FAQ Candidate Pydantic models (Phase 7.1).

TDD: Write tests first, then implement models to pass these tests.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


class TestSimilarFaqCandidateCreate:
    """Tests for SimilarFaqCandidateCreate model validation."""

    def test_valid_candidate_create(self):
        """Test creating a valid candidate with all required fields."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        candidate = SimilarFaqCandidateCreate(
            extracted_question="How do I buy bitcoin on Bisq?",
            extracted_answer="Use Bisq Easy to purchase bitcoin safely.",
            matched_faq_id=42,
            similarity=0.92,
        )

        assert candidate.extracted_question == "How do I buy bitcoin on Bisq?"
        assert candidate.extracted_answer == "Use Bisq Easy to purchase bitcoin safely."
        assert candidate.matched_faq_id == 42
        assert candidate.similarity == 0.92
        assert candidate.extracted_category is None  # Optional field

    def test_candidate_with_category(self):
        """Test creating a candidate with optional category."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        candidate = SimilarFaqCandidateCreate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            extracted_category="Trading",
            matched_faq_id=1,
            similarity=0.85,
        )

        assert candidate.extracted_category == "Trading"

    def test_question_min_length_validation(self):
        """Test that question must be at least 5 characters."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Hi",  # Too short
                extracted_answer="Answer text",
                matched_faq_id=1,
                similarity=0.85,
            )

        assert "extracted_question" in str(exc_info.value)

    def test_question_max_length_validation(self):
        """Test that question must be at most 2000 characters."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Q" * 2001,  # Too long
                extracted_answer="Answer text",
                matched_faq_id=1,
                similarity=0.85,
            )

        assert "extracted_question" in str(exc_info.value)

    def test_answer_min_length_validation(self):
        """Test that answer must be at least 1 character."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Valid question here",
                extracted_answer="",  # Empty
                matched_faq_id=1,
                similarity=0.85,
            )

        assert "extracted_answer" in str(exc_info.value)

    def test_answer_max_length_validation(self):
        """Test that answer must be at most 10000 characters."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Valid question here",
                extracted_answer="A" * 10001,  # Too long
                matched_faq_id=1,
                similarity=0.85,
            )

        assert "extracted_answer" in str(exc_info.value)

    def test_similarity_range_validation_min(self):
        """Test that similarity must be >= 0.0."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Valid question here",
                extracted_answer="Valid answer",
                matched_faq_id=1,
                similarity=-0.1,  # Below minimum
            )

        assert "similarity" in str(exc_info.value)

    def test_similarity_range_validation_max(self):
        """Test that similarity must be <= 1.0."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Valid question here",
                extracted_answer="Valid answer",
                matched_faq_id=1,
                similarity=1.1,  # Above maximum
            )

        assert "similarity" in str(exc_info.value)

    def test_matched_faq_id_required(self):
        """Test that matched_faq_id is required."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateCreate

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidateCreate(
                extracted_question="Valid question here",
                extracted_answer="Valid answer",
                # matched_faq_id missing
                similarity=0.85,
            )

        assert "matched_faq_id" in str(exc_info.value)


class TestSimilarFaqCandidate:
    """Tests for SimilarFaqCandidate response model."""

    def test_candidate_includes_all_fields(self):
        """Test that response model includes all expected fields."""
        from app.models.similar_faq_candidate import SimilarFaqCandidate

        now = datetime.now(timezone.utc)
        candidate = SimilarFaqCandidate(
            id="uuid-123",
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            extracted_category="Trading",
            matched_faq_id=42,
            similarity=0.92,
            status="pending",
            extracted_at=now,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        assert candidate.id == "uuid-123"
        assert candidate.status == "pending"
        assert candidate.extracted_at == now
        assert candidate.resolved_at is None
        assert candidate.resolved_by is None
        assert candidate.matched_question == "How can I purchase BTC?"
        assert candidate.matched_answer == "Use Bisq Easy for safe purchases."

    def test_status_enum_validation(self):
        """Test that status must be one of allowed values."""
        from app.models.similar_faq_candidate import SimilarFaqCandidate

        now = datetime.now(timezone.utc)

        # Valid statuses
        for valid_status in ["pending", "approved", "merged", "dismissed"]:
            candidate = SimilarFaqCandidate(
                id="uuid-123",
                extracted_question="Valid question here",
                extracted_answer="Valid answer",
                matched_faq_id=1,
                similarity=0.85,
                status=valid_status,
                extracted_at=now,
                matched_question="Matched question",
                matched_answer="Matched answer",
            )
            assert candidate.status == valid_status

    def test_invalid_status_rejected(self):
        """Test that invalid status values are rejected."""
        from app.models.similar_faq_candidate import SimilarFaqCandidate

        now = datetime.now(timezone.utc)

        with pytest.raises(ValidationError) as exc_info:
            SimilarFaqCandidate(
                id="uuid-123",
                extracted_question="Valid question here",
                extracted_answer="Valid answer",
                matched_faq_id=1,
                similarity=0.85,
                status="invalid_status",  # Not in enum
                extracted_at=now,
                matched_question="Matched",
                matched_answer="Matched",
            )

        assert "status" in str(exc_info.value)

    def test_resolved_fields_optional(self):
        """Test that resolved_at, resolved_by, and dismiss_reason are optional."""
        from app.models.similar_faq_candidate import SimilarFaqCandidate

        now = datetime.now(timezone.utc)
        candidate = SimilarFaqCandidate(
            id="uuid-123",
            extracted_question="Valid question here",
            extracted_answer="Valid answer",
            matched_faq_id=1,
            similarity=0.85,
            status="pending",
            extracted_at=now,
            matched_question="Matched",
            matched_answer="Matched",
        )

        assert candidate.resolved_at is None
        assert candidate.resolved_by is None
        assert candidate.dismiss_reason is None

    def test_resolved_fields_populated(self):
        """Test that resolved fields can be populated."""
        from app.models.similar_faq_candidate import SimilarFaqCandidate

        extracted_at = datetime.now(timezone.utc)
        resolved_at = datetime.now(timezone.utc)

        candidate = SimilarFaqCandidate(
            id="uuid-123",
            extracted_question="Valid question here",
            extracted_answer="Valid answer",
            matched_faq_id=1,
            similarity=0.85,
            status="dismissed",
            extracted_at=extracted_at,
            resolved_at=resolved_at,
            resolved_by="admin@example.com",
            dismiss_reason="Exact duplicate",
            matched_question="Matched",
            matched_answer="Matched",
        )

        assert candidate.resolved_at == resolved_at
        assert candidate.resolved_by == "admin@example.com"
        assert candidate.dismiss_reason == "Exact duplicate"


class TestSimilarFaqCandidateListResponse:
    """Tests for SimilarFaqCandidateListResponse model."""

    def test_empty_list_response(self):
        """Test response with empty items list."""
        from app.models.similar_faq_candidate import SimilarFaqCandidateListResponse

        response = SimilarFaqCandidateListResponse(items=[], total=0)

        assert response.items == []
        assert response.total == 0

    def test_list_response_with_items(self):
        """Test response with candidate items."""
        from app.models.similar_faq_candidate import (
            SimilarFaqCandidate,
            SimilarFaqCandidateListResponse,
        )

        now = datetime.now(timezone.utc)
        candidate = SimilarFaqCandidate(
            id="uuid-123",
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=42,
            similarity=0.92,
            status="pending",
            extracted_at=now,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
        )

        response = SimilarFaqCandidateListResponse(items=[candidate], total=1)

        assert len(response.items) == 1
        assert response.total == 1
        assert response.items[0].id == "uuid-123"


class TestMergeRequest:
    """Tests for MergeRequest model."""

    def test_valid_merge_modes(self):
        """Test that merge mode accepts valid values."""
        from app.models.similar_faq_candidate import MergeRequest

        for mode in ["replace", "append"]:
            request = MergeRequest(mode=mode)
            assert request.mode == mode

    def test_invalid_merge_mode_rejected(self):
        """Test that invalid merge mode is rejected."""
        from app.models.similar_faq_candidate import MergeRequest

        with pytest.raises(ValidationError) as exc_info:
            MergeRequest(mode="invalid")

        assert "mode" in str(exc_info.value)


class TestDismissRequest:
    """Tests for DismissRequest model."""

    def test_dismiss_without_reason(self):
        """Test dismiss request without reason."""
        from app.models.similar_faq_candidate import DismissRequest

        request = DismissRequest()
        assert request.reason is None

    def test_dismiss_with_reason(self):
        """Test dismiss request with reason."""
        from app.models.similar_faq_candidate import DismissRequest

        request = DismissRequest(reason="Exact duplicate of existing FAQ")
        assert request.reason == "Exact duplicate of existing FAQ"
