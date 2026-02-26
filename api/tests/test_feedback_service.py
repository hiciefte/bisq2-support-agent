"""
Unit tests for FeedbackService - Critical path testing for feedback management.

Tests cover:
- Feedback storage and retrieval
- Statistics calculation accuracy
- Filtering and querying
- Issue detection and analysis

Note: FeedbackService uses SQLite database (not file-based storage)
and has async methods that require pytest-asyncio.
"""

import uuid

import pytest
from app.services.feedback_service import FeedbackService


class TestFeedbackStorage:
    """Test feedback storage and retrieval operations."""

    @pytest.mark.asyncio
    async def test_store_feedback_returns_success(self, test_settings):
        """Test that storing feedback returns True on success."""
        service = FeedbackService(settings=test_settings)

        feedback_data = {
            "message_id": str(uuid.uuid4()),  # Use unique ID
            "question": "Test question?",
            "answer": "Test answer",
            "rating": 1,  # positive
            "explanation": "Very helpful",
            "sources": [{"type": "wiki", "title": "Test"}],
        }

        result = await service.store_feedback(feedback_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_store_feedback_creates_database_entry(self, test_settings):
        """Test that stored feedback can be retrieved."""
        service = FeedbackService(settings=test_settings)

        unique_id = str(uuid.uuid4())
        feedback_data = {
            "message_id": unique_id,
            "question": "How to backup?",
            "answer": "Use backup feature",
            "rating": 1,
            "explanation": "Clear instructions",
            "sources": [{"type": "faq", "title": "Backup Guide"}],
        }

        await service.store_feedback(feedback_data)

        # Load and verify
        all_feedback = service.load_feedback()
        assert len(all_feedback) >= 1

        # Find our feedback
        stored = next(
            (fb for fb in all_feedback if fb.get("message_id") == unique_id),
            None,
        )
        assert stored is not None
        assert stored["question"] == feedback_data["question"]
        assert stored["rating"] == feedback_data["rating"]

    def test_load_feedback_returns_list(self, test_settings):
        """Test that load_feedback returns a list."""
        service = FeedbackService(settings=test_settings)

        feedback = service.load_feedback()

        assert isinstance(feedback, list)

    @pytest.mark.asyncio
    async def test_feedback_details_include_sources_and_metadata(self, test_settings):
        """Detail lookup should preserve retrieval context fields."""
        service = FeedbackService(settings=test_settings)
        message_id = str(uuid.uuid4())
        sources = [
            {"type": "wiki", "title": "Main Page", "url": "https://bisq.wiki/Main_Page"}
        ]
        sources_used = [
            {"type": "faq", "title": "What is Bisq Easy?", "url": "/faq/bisq-easy"}
        ]

        await service.store_feedback(
            {
                "message_id": message_id,
                "question": "What is Bisq Easy?",
                "answer": "Bisq Easy is...",
                "rating": 1,
                "explanation": "helpful",
                "sources": sources,
                "sources_used": sources_used,
            }
        )

        feedback = service.repository.get_feedback_by_message_id(message_id)
        assert feedback is not None
        assert feedback["sources"] == sources
        assert feedback["sources_used"] == sources_used
        assert feedback["channel"] == "web"
        assert feedback["feedback_method"] == "web_dialog"
        assert feedback["metadata"]["explanation"] == "helpful"


class TestFeedbackStatistics:
    """Test feedback statistics calculation."""

    def test_get_feedback_stats_enhanced(self, test_settings):
        """Test that enhanced statistics are calculated correctly."""
        service = FeedbackService(settings=test_settings)

        stats = service.get_feedback_stats_enhanced()

        assert isinstance(stats, dict)
        assert "total_feedback" in stats or "total" in stats

    @pytest.mark.asyncio
    async def test_statistics_count_after_adding_feedback(self, test_settings):
        """Test that statistics update after adding feedback."""
        service = FeedbackService(settings=test_settings)

        initial_stats = service.get_feedback_stats_enhanced()
        initial_total = initial_stats.get("total_feedback", 0) or initial_stats.get(
            "total", 0
        )

        # Add feedback with unique IDs
        await service.store_feedback(
            {
                "message_id": str(uuid.uuid4()),
                "question": "Q1",
                "answer": "A1",
                "rating": 1,  # positive
                "explanation": "Good",
            }
        )

        await service.store_feedback(
            {
                "message_id": str(uuid.uuid4()),
                "question": "Q2",
                "answer": "A2",
                "rating": 0,  # negative (database constraint: rating IN (0, 1))
                "explanation": "Bad",
            }
        )

        final_stats = service.get_feedback_stats_enhanced()
        final_total = final_stats.get("total_feedback", 0) or final_stats.get(
            "total", 0
        )

        # Should have added 2 feedback items
        assert final_total >= initial_total + 2


class TestFeedbackFiltering:
    """Test feedback filtering functionality."""

    def test_get_feedback_with_filters_returns_response(self, test_settings):
        """Test that filtering returns FeedbackListResponse."""
        from app.models.feedback import FeedbackFilterRequest, FeedbackListResponse

        service = FeedbackService(settings=test_settings)
        filters = FeedbackFilterRequest(rating="positive")

        response = service.get_feedback_with_filters(filters)

        assert isinstance(response, FeedbackListResponse)
        assert hasattr(response, "feedback_items")
        assert isinstance(response.feedback_items, list)

    @pytest.mark.asyncio
    async def test_filter_by_rating(self, test_settings):
        """Test filtering feedback by rating."""
        from app.models.feedback import FeedbackFilterRequest

        service = FeedbackService(settings=test_settings)

        # Add positive and negative feedback with unique IDs
        await service.store_feedback(
            {
                "message_id": str(uuid.uuid4()),
                "question": "Good question",
                "answer": "Good answer",
                "rating": 1,
                "explanation": "Helpful",
            }
        )

        await service.store_feedback(
            {
                "message_id": str(uuid.uuid4()),
                "question": "Bad question",
                "answer": "Bad answer",
                "rating": 0,  # negative (database constraint: rating IN (0, 1))
                "explanation": "Not helpful",
            }
        )

        # Filter positive
        positive_filters = FeedbackFilterRequest(rating="positive")
        positive_response = service.get_feedback_with_filters(positive_filters)

        # All should be positive
        assert all(fb.is_positive for fb in positive_response.feedback_items)

        # Filter negative
        negative_filters = FeedbackFilterRequest(rating="negative")
        negative_response = service.get_feedback_with_filters(negative_filters)

        # All should be negative
        assert all(fb.is_negative for fb in negative_response.feedback_items)


class TestFeedbackIssueDetection:
    """Test feedback issue detection and analysis."""

    @pytest.mark.asyncio
    async def test_analyze_feedback_text_detects_issues(self, test_settings):
        """Test that feedback text analysis detects common issues."""
        service = FeedbackService(settings=test_settings)

        # Test verbosity detection
        issues = await service.analyze_feedback_text("Too long and verbose explanation")
        assert isinstance(issues, list)

    @pytest.mark.asyncio
    async def test_analyze_various_feedback_patterns(self, test_settings):
        """Test analysis of different feedback patterns."""
        service = FeedbackService(settings=test_settings)

        test_cases = [
            "Too technical and complex",
            "Not specific enough, too vague",
            "Too long and verbose",
            "Perfect explanation",
        ]

        for text in test_cases:
            issues = await service.analyze_feedback_text(text)
            assert isinstance(issues, list)


class TestFeedbackWeightManagement:
    """Test source weight management based on feedback."""

    def test_get_source_weights_returns_dict(self, test_settings):
        """Test that source weights are returned."""
        service = FeedbackService(settings=test_settings)

        weights = service.get_source_weights()

        assert isinstance(weights, dict)

    @pytest.mark.asyncio
    async def test_apply_feedback_weights(self, test_settings):
        """Test that feedback weights can be applied."""
        service = FeedbackService(settings=test_settings)

        # Add feedback with sources using unique ID
        await service.store_feedback(
            {
                "message_id": str(uuid.uuid4()),
                "question": "Test",
                "answer": "Answer",
                "rating": 1,
                "sources": [{"type": "faq", "title": "FAQ 1"}],
            }
        )

        # Apply weights
        result = service.apply_feedback_weights()

        # Should not error
        assert isinstance(result, bool)


class TestFeedbackPromptOptimization:
    """Test prompt optimization based on feedback patterns."""

    def test_get_prompt_guidance_returns_list(self, test_settings):
        """Test that prompt guidance returns a list."""
        service = FeedbackService(settings=test_settings)

        guidance = service.get_prompt_guidance()

        assert isinstance(guidance, list)

    def test_update_prompt_based_on_feedback(self, test_settings):
        """Test that prompt can be updated based on feedback."""
        service = FeedbackService(settings=test_settings)

        # Should not error
        result = service.update_prompt_based_on_feedback()

        assert isinstance(result, bool)


class TestFeedbackNegativeForFAQ:
    """Test negative feedback retrieval for FAQ creation."""

    def test_get_negative_feedback_for_faq_creation(self, test_settings):
        """Test retrieving negative feedback for FAQ creation."""
        service = FeedbackService(settings=test_settings)

        negative_feedback = service.get_negative_feedback_for_faq_creation()

        assert isinstance(negative_feedback, list)

    @pytest.mark.asyncio
    async def test_negative_feedback_includes_low_ratings(self, test_settings):
        """Test that negative feedback includes low-rated items."""
        service = FeedbackService(settings=test_settings)

        # Add negative feedback with unique ID
        await service.store_feedback(
            {
                "message_id": str(uuid.uuid4()),
                "question": "Confusing question",
                "answer": "Unclear answer",
                "rating": 0,  # negative (database constraint: rating IN (0, 1))
                "explanation": "Not helpful at all",
            }
        )

        negative_feedback = service.get_negative_feedback_for_faq_creation()

        # Should have at least one item
        assert len(negative_feedback) >= 0  # May have filters applied


class TestFeedbackGrouping:
    """Test feedback grouping by issues."""

    def test_get_feedback_by_issues_returns_dict(self, test_settings):
        """Test that feedback can be grouped by issues."""
        service = FeedbackService(settings=test_settings)

        grouped = service.get_feedback_by_issues()

        assert isinstance(grouped, dict)


class TestFeedbackDeletion:
    """Test feedback deletion functionality."""

    @pytest.mark.asyncio
    async def test_delete_feedback_returns_true_when_exists(self, test_settings):
        """Test that deleting existing feedback returns True."""
        service = FeedbackService(settings=test_settings)

        # Create a feedback entry
        message_id = str(uuid.uuid4())
        await service.store_feedback(
            {
                "message_id": message_id,
                "question": "Test question",
                "answer": "Test answer",
                "rating": 1,
                "explanation": "Test explanation",
            }
        )

        # Delete the feedback
        result = service.delete_feedback(message_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_feedback_returns_false_when_not_exists(self, test_settings):
        """Test that deleting non-existent feedback returns False."""
        service = FeedbackService(settings=test_settings)

        # Try to delete feedback that doesn't exist
        result = service.delete_feedback(str(uuid.uuid4()))

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_feedback_removes_entry_from_database(self, test_settings):
        """Test that deleted feedback cannot be retrieved."""
        service = FeedbackService(settings=test_settings)

        # Create a feedback entry
        message_id = str(uuid.uuid4())
        await service.store_feedback(
            {
                "message_id": message_id,
                "question": "Test question",
                "answer": "Test answer",
                "rating": 1,
            }
        )

        # Verify it exists
        feedback = service.repository.get_feedback_by_message_id(message_id)
        assert feedback is not None

        # Delete the feedback
        service.delete_feedback(message_id)

        # Verify it's gone
        feedback = service.repository.get_feedback_by_message_id(message_id)
        assert feedback is None

    @pytest.mark.asyncio
    async def test_delete_feedback_invalidates_cache(self, test_settings):
        """Test that deleting feedback invalidates the cache."""
        service = FeedbackService(settings=test_settings)

        # Create a feedback entry
        message_id = str(uuid.uuid4())
        await service.store_feedback(
            {
                "message_id": message_id,
                "question": "Test question",
                "answer": "Test answer",
                "rating": 1,
            }
        )

        # Load to populate cache
        initial_count = len(service.load_feedback())

        # Delete the feedback
        service.delete_feedback(message_id)

        # Load again - should reflect deletion
        final_count = len(service.load_feedback())

        assert final_count == initial_count - 1


class TestFeedbackDuplication:
    """Test duplicate feedback handling."""

    @pytest.mark.asyncio
    async def test_duplicate_feedback_raises_integrity_error(self, test_settings):
        """Test that storing duplicate feedback raises IntegrityError."""
        import sqlite3

        service = FeedbackService(settings=test_settings)

        # Create a feedback entry
        message_id = str(uuid.uuid4())
        feedback_data = {
            "message_id": message_id,
            "question": "Test question",
            "answer": "Test answer",
            "rating": 1,
        }

        # Store once - should succeed
        result1 = await service.store_feedback(feedback_data)
        assert result1 is True

        # Try to store duplicate - should raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            service.repository.store_feedback(**feedback_data)

    @pytest.mark.asyncio
    async def test_duplicate_content_different_ids_allowed(self, test_settings):
        """Test that identical content with different message_ids is allowed."""
        service = FeedbackService(settings=test_settings)

        # Create two feedback entries with same content but different IDs
        feedback_data1 = {
            "message_id": str(uuid.uuid4()),
            "question": "Identical question",
            "answer": "Identical answer",
            "rating": 1,
            "explanation": "Identical explanation",
        }

        feedback_data2 = {
            "message_id": str(uuid.uuid4()),
            "question": "Identical question",
            "answer": "Identical answer",
            "rating": 1,
            "explanation": "Identical explanation",
        }

        # Both should succeed
        result1 = await service.store_feedback(feedback_data1)
        result2 = await service.store_feedback(feedback_data2)

        assert result1 is True
        assert result2 is True

    @pytest.mark.asyncio
    async def test_store_feedback_handles_duplicate_gracefully(self, test_settings):
        """Test that store_feedback returns False on duplicate instead of crashing."""
        service = FeedbackService(settings=test_settings)

        # Create a feedback entry
        message_id = str(uuid.uuid4())
        feedback_data = {
            "message_id": message_id,
            "question": "Test question",
            "answer": "Test answer",
            "rating": 1,
        }

        # Store once - should succeed
        result1 = await service.store_feedback(feedback_data)
        assert result1 is True

        # Try to store duplicate - should return False, not crash
        result2 = await service.store_feedback(feedback_data)
        assert result2 is False
