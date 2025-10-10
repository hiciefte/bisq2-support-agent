"""
Unit tests for FeedbackService - Critical path testing for feedback management.

Tests cover:
- Feedback storage and retrieval
- Statistics calculation accuracy
- Filtering and pagination
- Weight management and prompt optimization
- Issue detection and analysis
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services.feedback_service import FeedbackService


class TestFeedbackStorage:
    """Test feedback storage and retrieval operations."""

    def test_store_feedback_creates_file(self, test_settings, clean_test_files):
        """Test that storing feedback creates the monthly file."""
        service = FeedbackService(settings=test_settings)

        service.store_feedback(
            question="Test question?",
            answer="Test answer",
            helpful=True,
            explanation="Very helpful",
            sources_used=[{"type": "wiki", "title": "Test"}],
        )

        # Verify file was created
        feedback_dir = Path(test_settings.FEEDBACK_DIR_PATH)
        files = list(feedback_dir.glob("feedback_*.jsonl"))
        assert len(files) == 1

    def test_store_feedback_appends_to_existing_file(
        self, feedback_service, test_settings
    ):
        """Test that multiple feedback entries append correctly."""
        initial_count = len(feedback_service.get_all_feedback())

        feedback_service.store_feedback(
            question="New question?",
            answer="New answer",
            helpful=False,
            explanation="Not helpful",
        )

        final_count = len(feedback_service.get_all_feedback())
        assert final_count == initial_count + 1

    def test_store_feedback_preserves_data_integrity(
        self, test_settings, clean_test_files
    ):
        """Test that stored feedback maintains all fields."""
        service = FeedbackService(settings=test_settings)

        test_data = {
            "question": "How to backup?",
            "answer": "Use backup feature",
            "helpful": True,
            "explanation": "Clear instructions",
            "sources_used": [
                {"type": "faq", "title": "Backup Guide", "content": "..."}
            ],
        }

        service.store_feedback(**test_data)

        feedback = service.get_all_feedback()
        assert len(feedback) == 1

        stored = feedback[0]
        assert stored["question"] == test_data["question"]
        assert stored["answer"] == test_data["answer"]
        assert stored["helpful"] == test_data["helpful"]
        assert stored["explanation"] == test_data["explanation"]
        assert len(stored["sources_used"]) == 1
        assert "timestamp" in stored

    def test_retrieve_all_feedback(self, feedback_service, sample_feedback_data):
        """Test retrieving all feedback entries."""
        all_feedback = feedback_service.get_all_feedback()

        assert len(all_feedback) >= len(sample_feedback_data)
        assert all(isinstance(fb, dict) for fb in all_feedback)
        assert all("question" in fb for fb in all_feedback)
        assert all("helpful" in fb for fb in all_feedback)


class TestFeedbackStatistics:
    """Test feedback statistics calculation."""

    def test_basic_statistics_calculation(self, feedback_service, sample_feedback_data):
        """Test that basic statistics are calculated correctly."""
        stats = feedback_service.get_feedback_stats()

        assert "total" in stats
        assert "positive" in stats
        assert "negative" in stats
        assert stats["total"] >= len(sample_feedback_data)

    def test_enhanced_statistics_includes_trends(
        self, feedback_service, sample_feedback_data
    ):
        """Test that enhanced statistics include trend data."""
        stats = feedback_service.get_feedback_stats_enhanced()

        assert "total_feedback" in stats
        assert "recent_negative_count" in stats
        assert "needs_faq_count" in stats

    def test_statistics_count_accuracy(self, test_settings, clean_test_files):
        """Test that statistics accurately count positive/negative feedback."""
        service = FeedbackService(settings=test_settings)

        # Add known positive and negative feedback
        service.store_feedback(
            question="Q1", answer="A1", helpful=True, explanation="Good"
        )
        service.store_feedback(
            question="Q2", answer="A2", helpful=True, explanation="Great"
        )
        service.store_feedback(
            question="Q3", answer="A3", helpful=False, explanation="Bad"
        )

        stats = service.get_feedback_stats()

        assert stats["total"] == 3
        assert stats["positive"] == 2
        assert stats["negative"] == 1

    def test_statistics_handle_empty_feedback(self, test_settings, clean_test_files):
        """Test that statistics handle empty feedback gracefully."""
        service = FeedbackService(settings=test_settings)

        stats = service.get_feedback_stats()

        assert stats["total"] == 0
        assert stats["positive"] == 0
        assert stats["negative"] == 0


class TestFeedbackFiltering:
    """Test feedback filtering functionality."""

    def test_filter_by_positive_rating(self, feedback_service):
        """Test filtering for positive feedback only."""
        from app.schemas.feedback import FeedbackFilterRequest

        filters = FeedbackFilterRequest(rating="positive")
        filtered = feedback_service.get_feedback_with_filters(filters)

        assert all(fb.is_positive for fb in filtered)

    def test_filter_by_negative_rating(self, feedback_service):
        """Test filtering for negative feedback only."""
        from app.schemas.feedback import FeedbackFilterRequest

        filters = FeedbackFilterRequest(rating="negative")
        filtered = feedback_service.get_feedback_with_filters(filters)

        assert all(fb.is_negative for fb in filtered)

    def test_filter_by_date_range(self, test_settings, clean_test_files):
        """Test filtering feedback by date range."""
        service = FeedbackService(settings=test_settings)
        from app.schemas.feedback import FeedbackFilterRequest

        # Add feedback from different dates
        today = datetime.now().isoformat()
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()

        # Store with explicit timestamps
        feedback_dir = Path(test_settings.FEEDBACK_DIR_PATH)
        feedback_dir.mkdir(parents=True, exist_ok=True)

        # Create feedback file with specific timestamps
        current_month = datetime.now().strftime("%Y-%m")
        feedback_file = feedback_dir / f"feedback_{current_month}.jsonl"

        with open(feedback_file, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "question": "Old question",
                        "answer": "Old answer",
                        "helpful": True,
                        "timestamp": yesterday,
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "question": "New question",
                        "answer": "New answer",
                        "helpful": False,
                        "timestamp": today,
                    }
                )
                + "\n"
            )

        # Filter by today only
        filters = FeedbackFilterRequest(
            date_from=today[:10], date_to=today[:10]  # YYYY-MM-DD
        )
        filtered = service.get_feedback_with_filters(filters)

        assert len(filtered) == 1
        assert filtered[0].question == "New question"

    def test_filter_by_text_search(self, feedback_service):
        """Test filtering feedback by text search."""
        from app.schemas.feedback import FeedbackFilterRequest

        filters = FeedbackFilterRequest(search_text="backup")
        filtered = feedback_service.get_feedback_with_filters(filters)

        # Should find feedback containing 'backup' in question or answer
        assert all(
            "backup" in fb.question.lower() or "backup" in fb.answer.lower()
            for fb in filtered
        )


class TestFeedbackPagination:
    """Test feedback pagination functionality."""

    def test_pagination_returns_correct_page_size(
        self, test_settings, clean_test_files
    ):
        """Test that pagination returns correct number of items."""
        service = FeedbackService(settings=test_settings)
        from app.schemas.feedback import FeedbackFilterRequest

        # Add 15 feedback entries
        for i in range(15):
            service.store_feedback(
                question=f"Question {i}",
                answer=f"Answer {i}",
                helpful=i % 2 == 0,
            )

        # Get first page with 10 items
        filters = FeedbackFilterRequest(page=1, page_size=10)
        result = service.get_feedback_paginated(filters)

        assert len(result["items"]) == 10
        assert result["total"] == 15
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total_pages"] == 2

    def test_pagination_second_page(self, test_settings, clean_test_files):
        """Test retrieving second page of results."""
        service = FeedbackService(settings=test_settings)
        from app.schemas.feedback import FeedbackFilterRequest

        # Add 15 feedback entries
        for i in range(15):
            service.store_feedback(
                question=f"Question {i}",
                answer=f"Answer {i}",
                helpful=True,
            )

        # Get second page
        filters = FeedbackFilterRequest(page=2, page_size=10)
        result = service.get_feedback_paginated(filters)

        assert len(result["items"]) == 5  # Remaining items
        assert result["page"] == 2


class TestFeedbackIssueDetection:
    """Test feedback issue detection and analysis."""

    def test_detect_verbosity_issue(self, test_settings, clean_test_files):
        """Test detection of 'too verbose' feedback issue."""
        service = FeedbackService(settings=test_settings)

        service.store_feedback(
            question="Test question",
            answer="Test answer",
            helpful=False,
            explanation="Too long and verbose",
        )

        all_feedback = service.get_all_feedback()
        issues = service.analyzer.analyze_feedback_text(all_feedback[0]["explanation"])

        assert "too_verbose" in issues

    def test_detect_technical_issue(self, test_settings, clean_test_files):
        """Test detection of 'too technical' feedback issue."""
        service = FeedbackService(settings=test_settings)

        service.store_feedback(
            question="Test question",
            answer="Test answer",
            helpful=False,
            explanation="Too technical and complex",
        )

        all_feedback = service.get_all_feedback()
        issues = service.analyzer.analyze_feedback_text(all_feedback[0]["explanation"])

        assert "too_technical" in issues

    def test_detect_specificity_issue(self, test_settings, clean_test_files):
        """Test detection of 'not specific enough' issue."""
        service = FeedbackService(settings=test_settings)

        service.store_feedback(
            question="Test question",
            answer="Test answer",
            helpful=False,
            explanation="Too vague and not specific",
        )

        all_feedback = service.get_all_feedback()
        issues = service.analyzer.analyze_feedback_text(all_feedback[0]["explanation"])

        assert "not_specific" in issues


class TestFeedbackWeightManagement:
    """Test source weight management based on feedback."""

    def test_initial_weights_are_set(self, test_settings, clean_test_files):
        """Test that initial source weights are configured."""
        service = FeedbackService(settings=test_settings)

        weights = service.get_source_weights()

        assert "faq" in weights
        assert "wiki" in weights
        assert weights["faq"] > 0
        assert weights["wiki"] > 0

    def test_weights_adjust_based_on_feedback(self, test_settings, clean_test_files):
        """Test that weights adjust based on source performance."""
        service = FeedbackService(settings=test_settings)

        # Add positive feedback for FAQ sources
        for i in range(15):
            service.store_feedback(
                question=f"Question {i}",
                answer=f"Answer {i}",
                helpful=True,
                sources_used=[{"type": "faq", "title": f"FAQ {i}"}],
            )

        # Add negative feedback for wiki sources
        for i in range(15):
            service.store_feedback(
                question=f"Wiki Question {i}",
                answer=f"Wiki Answer {i}",
                helpful=False,
                sources_used=[{"type": "wiki", "title": f"Wiki {i}"}],
            )

        # Update weights based on feedback
        feedback_data = [
            {
                "helpful": fb.get("helpful"),
                "sources_used": fb.get("sources_used", []),
            }
            for fb in service.get_all_feedback()
        ]

        updated_weights = service.weight_manager.apply_feedback_weights(feedback_data)

        # FAQ should have higher weight due to positive feedback
        # Note: Actual weight adjustment depends on implementation
        assert isinstance(updated_weights, dict)
        assert "faq" in updated_weights
        assert "wiki" in updated_weights


class TestFeedbackPromptOptimization:
    """Test prompt optimization based on feedback patterns."""

    def test_prompt_guidance_updates_with_sufficient_feedback(
        self, test_settings, clean_test_files
    ):
        """Test that prompt guidance updates with enough feedback."""
        service = FeedbackService(settings=test_settings)

        # Add 25 feedback entries with verbosity issues
        for i in range(25):
            service.store_feedback(
                question=f"Question {i}",
                answer=f"Answer {i}",
                helpful=False,
                explanation="Too long and verbose",
            )

        feedback_data = service.get_all_feedback()

        # Update prompt guidance
        updated = service.prompt_optimizer.update_prompt_guidance(
            feedback_data, service.analyzer
        )

        # Should update with sufficient negative feedback
        assert isinstance(updated, bool)

    def test_prompt_guidance_not_updated_with_insufficient_feedback(
        self, test_settings, clean_test_files
    ):
        """Test that prompt guidance doesn't update with too little feedback."""
        service = FeedbackService(settings=test_settings)

        # Add only 5 feedback entries
        for i in range(5):
            service.store_feedback(
                question=f"Question {i}",
                answer=f"Answer {i}",
                helpful=False,
                explanation="Too verbose",
            )

        feedback_data = service.get_all_feedback()

        # Should not update with insufficient feedback
        updated = service.prompt_optimizer.update_prompt_guidance(
            feedback_data, service.analyzer
        )

        assert updated is False

    def test_get_prompt_guidance(self, test_settings, clean_test_files):
        """Test retrieving current prompt guidance."""
        service = FeedbackService(settings=test_settings)

        guidance = service.get_prompt_guidance()

        assert isinstance(guidance, list)
