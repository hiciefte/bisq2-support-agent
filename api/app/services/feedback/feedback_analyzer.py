"""
Feedback Analyzer for pattern detection and issue identification.

This module handles:
- Text analysis for common issues
- Feedback pattern recognition
- Issue counting and aggregation
- Enhanced statistics calculation
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from app.models.feedback import FeedbackItem

logger = logging.getLogger(__name__)


class FeedbackAnalyzer:
    """Analyzer for feedback patterns, issues, and statistics.

    This class handles:
    - Issue detection from feedback text
    - Pattern analysis across feedback entries
    - Statistical calculations
    """

    def __init__(self):
        """Initialize the feedback analyzer."""
        # Dictionary of issues and their associated keywords
        self.issue_keywords = {
            "too_verbose": [
                "too long",
                "verbose",
                "wordy",
                "rambling",
                "shorter",
                "concise",
            ],
            "too_technical": [
                "technical",
                "complex",
                "complicated",
                "jargon",
                "simpler",
                "simplify",
            ],
            "not_specific": [
                "vague",
                "unclear",
                "generic",
                "specific",
                "details",
                "elaborate",
                "more info",
            ],
            "inaccurate": [
                "wrong",
                "incorrect",
                "false",
                "error",
                "mistake",
                "accurate",
                "accuracy",
            ],
            "outdated": ["outdated", "old", "not current", "update"],
            "not_helpful": [
                "useless",
                "unhelpful",
                "doesn't help",
                "didn't help",
                "not useful",
            ],
            "missing_context": ["context", "missing", "incomplete", "partial"],
            "confusing": ["confusing", "confused", "unclear", "hard to understand"],
        }

        logger.info("Feedback analyzer initialized")

    def analyze_feedback_text(self, explanation_text: str) -> List[str]:
        """Analyze feedback explanation text to identify common issues.

        This uses simple keyword matching for now but could be enhanced with
        NLP or LLM-based analysis in the future.

        Args:
            explanation_text: The text to analyze

        Returns:
            List of detected issues
        """
        detected_issues: List[str] = []

        # Simple keyword-based issue detection
        if not explanation_text:
            return detected_issues

        explanation_lower = explanation_text.lower()

        # Check for each issue
        for issue, keywords in self.issue_keywords.items():
            for keyword in keywords:
                if keyword in explanation_lower:
                    detected_issues.append(issue)
                    break  # Found one match for this issue, no need to check other keywords

        return detected_issues

    def analyze_feedback_issues(self, feedback: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze feedback to identify common issues.

        Args:
            feedback: List of feedback entries

        Returns:
            Dictionary mapping issue types to their counts
        """
        issues: Dict[str, int] = defaultdict(int)

        for item in feedback:
            if item.get("rating", 1) == 0:
                # Check for specific issue fields
                for issue_key in [
                    "too_verbose",
                    "too_technical",
                    "not_specific",
                    "inaccurate",
                ]:
                    if item.get(issue_key):
                        issues[issue_key] += 1

                # Also check issue list if present
                for issue in item.get("issues", []):
                    issues[issue] += 1

        return dict(issues)

    def calculate_enhanced_stats(
        self,
        feedback_items: List[FeedbackItem],
        basic_stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate enhanced feedback statistics.

        Args:
            feedback_items: List of validated feedback items
            basic_stats: Basic statistics from repository

        Returns:
            Dictionary with comprehensive statistics
        """
        if not feedback_items:
            return {
                "total_feedback": basic_stats.get("total", 0),
                "positive_count": basic_stats.get("positive", 0),
                "negative_count": basic_stats.get("negative", 0),
                "helpful_rate": basic_stats.get("positive_rate", 0),
                "common_issues": {},
                "recent_negative_count": 0,
                "needs_faq_count": 0,
                "processed_count": basic_stats.get("processed", 0),
                "unprocessed_negative_count": basic_stats.get(
                    "unprocessed_negative", 0
                ),
                "source_effectiveness": {},
                "feedback_by_month": {},
            }

        # Recent negative feedback (last 30 days)
        thirty_days_ago = datetime.now().replace(day=1).strftime("%Y-%m-01")
        recent_negative = [
            item
            for item in feedback_items
            if item.is_negative and item.timestamp >= thirty_days_ago
        ]

        # Feedback that needs FAQ creation
        needs_faq_items = [
            item
            for item in feedback_items
            if item.is_negative and (item.explanation or item.has_no_source_response)
        ]

        # Feedback by month
        monthly_counts = self._calculate_monthly_counts(feedback_items)

        # Source effectiveness
        source_stats = self._calculate_source_effectiveness(feedback_items)

        # Convert common_issues from repository format to dict[str, int]
        common_issues = {
            item["issue"]: item["count"]
            for item in basic_stats.get("common_issues", [])
        }

        return {
            "total_feedback": basic_stats["total"],
            "positive_count": basic_stats["positive"],
            "negative_count": basic_stats["negative"],
            "helpful_rate": basic_stats["positive_rate"],
            "common_issues": common_issues,
            "recent_negative_count": len(recent_negative),
            "needs_faq_count": len(needs_faq_items),
            "processed_count": basic_stats.get("processed", 0),
            "unprocessed_negative_count": basic_stats.get("unprocessed_negative", 0),
            "source_effectiveness": source_stats,
            "feedback_by_month": monthly_counts,
        }

    def _calculate_monthly_counts(
        self, feedback_items: List[FeedbackItem]
    ) -> Dict[str, int]:
        """Calculate feedback counts grouped by month.

        Args:
            feedback_items: List of feedback items

        Returns:
            Dictionary mapping month (YYYY-MM) to count
        """
        monthly_counts: Dict[str, int] = defaultdict(int)
        for item in feedback_items:
            try:
                month_key = item.timestamp[:7]  # YYYY-MM
                monthly_counts[month_key] += 1
            except (IndexError, TypeError, AttributeError):
                # Handle cases where timestamp is None, empty, or malformed
                monthly_counts["unknown"] += 1

        return dict(monthly_counts)

    def _calculate_source_effectiveness(
        self, feedback_items: List[FeedbackItem]
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate effectiveness metrics for different source types.

        Args:
            feedback_items: List of feedback items

        Returns:
            Dictionary mapping source types to effectiveness metrics
        """
        source_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "positive": 0}
        )

        for item in feedback_items:
            sources = (
                item.sources_used
                if item.sources_used
                else (item.sources if item.sources else [])
            )
            for source in sources:
                source_type = source.get("type", "unknown")
                source_stats[source_type]["total"] += 1
                if item.is_positive:
                    source_stats[source_type]["positive"] += 1

        # Add helpfulness rate to source stats
        for source_type in source_stats:
            stats = source_stats[source_type]
            stats["helpful_rate"] = (
                stats["positive"] / stats["total"] if stats["total"] > 0 else 0
            )

        return dict(source_stats)
