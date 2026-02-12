"""
TDD tests for FeedbackAnalyzer field bug fix.

The bug: analyze_feedback_issues() checks `item.get("helpful", True)` but
feedback entries use `rating` (int 0/1), not `helpful` (bool). This causes
ALL negative feedback to be silently skipped.
"""

from app.services.feedback.feedback_analyzer import FeedbackAnalyzer


class TestFeedbackAnalyzerFieldFix:
    """Tests for the helpful → rating field fix."""

    def test_negative_feedback_detected_with_rating_zero(self):
        """Entries with rating=0 should be counted as negative feedback."""
        analyzer = FeedbackAnalyzer()
        feedback = [
            {"rating": 0, "too_verbose": True},
            {"rating": 0, "too_technical": True},
            {"rating": 1},  # positive — should be skipped
        ]
        issues = analyzer.analyze_feedback_issues(feedback)
        assert issues.get("too_verbose", 0) == 1
        assert issues.get("too_technical", 0) == 1

    def test_issue_patterns_detected_from_negative_entries(self):
        """With multiple negative entries, all issue patterns should be counted."""
        analyzer = FeedbackAnalyzer()
        feedback = [
            {"rating": 0, "too_verbose": True, "issues": ["not_specific"]},
            {"rating": 0, "inaccurate": True},
            {"rating": 0, "issues": ["too_verbose", "inaccurate"]},
        ]
        issues = analyzer.analyze_feedback_issues(feedback)
        assert issues["too_verbose"] >= 1
        assert issues["inaccurate"] >= 1
        assert issues["not_specific"] >= 1

    def test_positive_entries_not_counted_as_issues(self):
        """Entries with rating=1 should not contribute to issue counts."""
        analyzer = FeedbackAnalyzer()
        feedback = [
            {"rating": 1, "too_verbose": True},  # positive — skip
        ]
        issues = analyzer.analyze_feedback_issues(feedback)
        assert len(issues) == 0

    def test_entries_without_rating_skipped(self):
        """Entries without 'rating' field default to positive (skip)."""
        analyzer = FeedbackAnalyzer()
        feedback = [
            {"too_verbose": True},  # no rating field
        ]
        issues = analyzer.analyze_feedback_issues(feedback)
        assert len(issues) == 0
