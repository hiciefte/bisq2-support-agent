"""
Tests for Similar FAQ Pydantic models.

TDD Phase 1: Write tests for SimilarFAQRequest, SimilarFAQItem, and SimilarFAQResponse models.
"""

import pytest
from pydantic import ValidationError


class TestSimilarFAQRequest:
    """Tests for SimilarFAQRequest model validation."""

    def test_valid_request_minimal(self):
        """Test valid request with only required field."""
        from app.models.faq import SimilarFAQRequest

        request = SimilarFAQRequest(question="How do I buy bitcoin?")

        assert request.question == "How do I buy bitcoin?"
        assert request.threshold == 0.65  # Default value
        assert request.limit == 5  # Default value
        assert request.exclude_id is None

    def test_valid_request_all_fields(self):
        """Test valid request with all optional fields."""
        from app.models.faq import SimilarFAQRequest

        request = SimilarFAQRequest(
            question="How do I buy bitcoin safely?",
            threshold=0.75,
            limit=10,
            exclude_id=42,
        )

        assert request.question == "How do I buy bitcoin safely?"
        assert request.threshold == 0.75
        assert request.limit == 10
        assert request.exclude_id == 42

    def test_question_too_short(self):
        """Test that question shorter than 5 characters is rejected."""
        from app.models.faq import SimilarFAQRequest

        with pytest.raises(ValidationError) as exc_info:
            SimilarFAQRequest(question="Hi")

        errors = exc_info.value.errors()
        assert any("min_length" in str(e) or "at least 5" in str(e) for e in errors)

    def test_question_exactly_5_chars(self):
        """Test that question with exactly 5 characters is accepted."""
        from app.models.faq import SimilarFAQRequest

        request = SimilarFAQRequest(question="Hello")
        assert len(request.question) == 5

    def test_question_max_length(self):
        """Test that question longer than 1000 characters is rejected."""
        from app.models.faq import SimilarFAQRequest

        long_question = "x" * 1001

        with pytest.raises(ValidationError) as exc_info:
            SimilarFAQRequest(question=long_question)

        errors = exc_info.value.errors()
        assert any("max_length" in str(e) or "at most 1000" in str(e) for e in errors)

    def test_threshold_below_minimum(self):
        """Test that threshold below 0 is rejected."""
        from app.models.faq import SimilarFAQRequest

        with pytest.raises(ValidationError) as exc_info:
            SimilarFAQRequest(question="Valid question here", threshold=-0.1)

        errors = exc_info.value.errors()
        assert any("greater than or equal" in str(e) for e in errors)

    def test_threshold_above_maximum(self):
        """Test that threshold above 1 is rejected."""
        from app.models.faq import SimilarFAQRequest

        with pytest.raises(ValidationError) as exc_info:
            SimilarFAQRequest(question="Valid question here", threshold=1.5)

        errors = exc_info.value.errors()
        assert any("less than or equal" in str(e) for e in errors)

    def test_threshold_boundary_values(self):
        """Test threshold at boundary values (0 and 1)."""
        from app.models.faq import SimilarFAQRequest

        request_zero = SimilarFAQRequest(question="Valid question", threshold=0.0)
        assert request_zero.threshold == 0.0

        request_one = SimilarFAQRequest(question="Valid question", threshold=1.0)
        assert request_one.threshold == 1.0

    def test_limit_below_minimum(self):
        """Test that limit below 1 is rejected."""
        from app.models.faq import SimilarFAQRequest

        with pytest.raises(ValidationError) as exc_info:
            SimilarFAQRequest(question="Valid question here", limit=0)

        errors = exc_info.value.errors()
        assert any("greater than or equal" in str(e) for e in errors)

    def test_limit_above_maximum(self):
        """Test that limit above 20 is rejected."""
        from app.models.faq import SimilarFAQRequest

        with pytest.raises(ValidationError) as exc_info:
            SimilarFAQRequest(question="Valid question here", limit=21)

        errors = exc_info.value.errors()
        assert any("less than or equal" in str(e) for e in errors)


class TestSimilarFAQItem:
    """Tests for SimilarFAQItem model validation."""

    def test_valid_item_minimal(self):
        """Test valid item with required fields only."""
        from app.models.faq import SimilarFAQItem

        item = SimilarFAQItem(
            id=1,
            question="How do I buy bitcoin?",
            answer="Use Bisq Easy to buy bitcoin safely.",
            similarity=0.85,
        )

        assert item.id == 1
        assert item.question == "How do I buy bitcoin?"
        assert item.answer == "Use Bisq Easy to buy bitcoin safely."
        assert item.similarity == 0.85
        assert item.category is None
        assert item.protocol is None

    def test_valid_item_all_fields(self):
        """Test valid item with all fields."""
        from app.models.faq import SimilarFAQItem

        item = SimilarFAQItem(
            id=42,
            question="How do I buy bitcoin?",
            answer="Use Bisq Easy to buy bitcoin safely.",
            similarity=0.92,
            category="Trading",
            protocol="bisq_easy",
        )

        assert item.id == 42
        assert item.category == "Trading"
        assert item.protocol == "bisq_easy"

    def test_similarity_boundary_values(self):
        """Test similarity at boundary values."""
        from app.models.faq import SimilarFAQItem

        item_zero = SimilarFAQItem(
            id=1,
            question="Question",
            answer="Answer",
            similarity=0.0,
        )
        assert item_zero.similarity == 0.0

        item_one = SimilarFAQItem(
            id=1,
            question="Question",
            answer="Answer",
            similarity=1.0,
        )
        assert item_one.similarity == 1.0

    def test_protocol_valid_values(self):
        """Test all valid protocol values."""
        from app.models.faq import SimilarFAQItem

        valid_protocols = ["multisig_v1", "bisq_easy", "musig", "all"]

        for protocol in valid_protocols:
            item = SimilarFAQItem(
                id=1,
                question="Question",
                answer="Answer",
                similarity=0.8,
                protocol=protocol,
            )
            assert item.protocol == protocol


class TestSimilarFAQResponse:
    """Tests for SimilarFAQResponse model validation."""

    def test_empty_response(self):
        """Test response with empty similar_faqs list."""
        from app.models.faq import SimilarFAQResponse

        response = SimilarFAQResponse(similar_faqs=[])

        assert response.similar_faqs == []
        assert len(response.similar_faqs) == 0

    def test_response_with_items(self):
        """Test response with multiple SimilarFAQItem entries."""
        from app.models.faq import SimilarFAQItem, SimilarFAQResponse

        items = [
            SimilarFAQItem(
                id=1,
                question="How do I buy bitcoin?",
                answer="Use Bisq Easy.",
                similarity=0.92,
            ),
            SimilarFAQItem(
                id=2,
                question="What's the safest way to buy?",
                answer="Choose reputable sellers.",
                similarity=0.78,
            ),
        ]

        response = SimilarFAQResponse(similar_faqs=items)

        assert len(response.similar_faqs) == 2
        assert response.similar_faqs[0].similarity == 0.92
        assert response.similar_faqs[1].similarity == 0.78

    def test_response_serialization(self):
        """Test that response can be serialized to dict/JSON."""
        from app.models.faq import SimilarFAQItem, SimilarFAQResponse

        items = [
            SimilarFAQItem(
                id=1,
                question="Question one",
                answer="Answer one",
                similarity=0.9,
                category="General",
                protocol="bisq_easy",
            )
        ]

        response = SimilarFAQResponse(similar_faqs=items)
        data = response.model_dump()

        assert "similar_faqs" in data
        assert len(data["similar_faqs"]) == 1
        assert data["similar_faqs"][0]["id"] == 1
        assert data["similar_faqs"][0]["similarity"] == 0.9
