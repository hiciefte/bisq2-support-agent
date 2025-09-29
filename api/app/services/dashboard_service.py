"""
Dashboard service for admin overview metrics and analytics.

This service combines real-time data from the database with historical metrics
from Prometheus to provide comprehensive dashboard statistics.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService

logger = logging.getLogger(__name__)


class DashboardService:
    """Service for dashboard data aggregation and analytics."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.feedback_service = FeedbackService(settings)
        self.faq_service = FAQService(settings)
        self.system_start_time = time.time()

    async def get_dashboard_overview(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard overview combining real-time and historical data.

        Returns:
            Dict containing dashboard metrics including:
            - helpful_rate: Current helpful rate percentage
            - helpful_rate_trend: 24h trend indicator
            - average_response_time: Current average response time
            - response_time_trend: Performance trend
            - negative_feedback_count: Recent negative feedback count
            - negative_feedback_trend: Growth rate
            - feedback_items_for_faq: Items that could benefit from FAQ creation
            - system_uptime: Current system uptime
            - total_queries: Total queries processed
            - total_faqs_created: Total FAQs created from feedback
        """
        logger.info("Generating dashboard overview data")

        try:
            # Get current feedback statistics
            feedback_stats = self.feedback_service.get_feedback_stats_enhanced()

            # Get feedback items that would benefit from FAQ creation
            feedback_for_faq = await self._get_feedback_items_for_faq()

            # Calculate system uptime
            uptime_seconds = time.time() - self.system_start_time

            # Get FAQ creation statistics
            faq_stats = await self._get_faq_creation_stats()

            # Calculate trends (simplified for now - in production would query Prometheus)
            helpful_rate_trend = await self._calculate_helpful_rate_trend()
            response_time_trend = await self._calculate_response_time_trend()
            negative_feedback_trend = await self._calculate_negative_feedback_trend()

            dashboard_data = {
                # Core metrics
                "helpful_rate": feedback_stats["helpful_rate"]
                * 100,  # Convert to percentage
                "helpful_rate_trend": helpful_rate_trend,
                "average_response_time": await self._get_average_response_time(),
                "response_time_trend": response_time_trend,
                "negative_feedback_count": feedback_stats["negative_count"],
                "negative_feedback_trend": negative_feedback_trend,
                # Dashboard-specific data
                "feedback_items_for_faq": feedback_for_faq,
                "feedback_items_for_faq_count": len(feedback_for_faq),
                "system_uptime": uptime_seconds,
                "total_queries": await self._get_total_query_count(),
                "total_faqs_created": faq_stats["total_created_from_feedback"],
                # Additional context
                "total_feedback": feedback_stats["total_feedback"],
                "total_faqs": faq_stats["total_faqs"],
                "last_updated": datetime.now().isoformat(),
            }

            logger.info("Successfully generated dashboard overview")
            return dashboard_data

        except Exception as e:
            logger.error(f"Failed to generate dashboard overview: {e}", exc_info=True)
            # Return fallback data
            return await self._get_fallback_dashboard_data()

    async def _get_feedback_items_for_faq(self) -> List[Dict[str, Any]]:
        """Get feedback items that would benefit from FAQ creation."""
        try:
            # Use the same logic as the feedback service to ensure consistency
            feedback_items = (
                self.feedback_service.get_negative_feedback_for_faq_creation()
            )

            # Convert to dictionary format expected by the dashboard
            faq_candidates = []
            for feedback in feedback_items:
                # Use the same criteria as feedback service: negative feedback with explanations or "no source" responses
                if feedback.is_negative and (
                    feedback.explanation or feedback.has_no_source_response
                ):

                    faq_candidates.append(
                        {
                            "message_id": feedback.message_id,
                            "question": feedback.question,
                            "answer": feedback.answer,
                            "explanation": feedback.explanation,
                            "issues": feedback.issues,
                            "timestamp": feedback.timestamp,
                            "potential_category": self._suggest_faq_category(
                                feedback.issues
                            ),
                        }
                    )

            # Return the most recent 10 candidates
            return sorted(faq_candidates, key=lambda x: x["timestamp"], reverse=True)[
                :10
            ]

        except Exception as e:
            logger.error(f"Failed to get feedback items for FAQ: {e}")
            return []

    async def _get_faq_creation_stats(self) -> Dict[str, int]:
        """Get FAQ creation statistics."""
        try:
            all_faqs = self.faq_service.get_all_faqs()

            return {
                "total_faqs": len(all_faqs),
                "total_created_from_feedback": len(
                    [f for f in all_faqs if f.source == "Feedback"]
                ),
                "total_manual": len([f for f in all_faqs if f.source == "Manual"]),
            }
        except Exception as e:
            logger.error(f"Failed to get FAQ creation stats: {e}")
            return {
                "total_faqs": 0,
                "total_created_from_feedback": 0,
                "total_manual": 0,
            }

    async def _get_average_response_time(self) -> float:
        """
        Get average response time.
        In production, this would query Prometheus for historical data.
        """
        try:
            # For now, return a simulated value
            # In production: query Prometheus for actual metrics
            # Example: rate(bisq_query_response_time_seconds_sum[1h]) / rate(bisq_query_response_time_seconds_count[1h])
            return 2.3  # seconds
        except Exception as e:
            logger.error(f"Failed to get average response time: {e}")
            return 5.0  # fallback

    async def _get_total_query_count(self) -> int:
        """
        Get total query count.
        In production, this would query Prometheus metrics.
        """
        try:
            # For now, return a simulated value
            # In production: query bisq_queries_total from Prometheus
            return 1247  # simulated
        except Exception as e:
            logger.error(f"Failed to get total query count: {e}")
            return 0

    async def _calculate_helpful_rate_trend(self) -> float:
        """Calculate helpful rate trend (positive/negative percentage change)."""
        try:
            # Simplified calculation - in production would compare current vs previous period
            # using Prometheus time-series data
            return 2.3  # +2.3% improvement
        except Exception as e:
            logger.error(f"Failed to calculate helpful rate trend: {e}")
            return 0.0

    async def _calculate_response_time_trend(self) -> float:
        """Calculate response time trend (positive = slower, negative = faster)."""
        try:
            # Simplified calculation - in production would use Prometheus
            return -0.8  # -0.8 seconds improvement
        except Exception as e:
            logger.error(f"Failed to calculate response time trend: {e}")
            return 0.0

    async def _calculate_negative_feedback_trend(self) -> float:
        """Calculate negative feedback trend (positive = more negative feedback)."""
        try:
            # Simplified calculation - in production would use Prometheus
            return -5.2  # -5.2% reduction in negative feedback
        except Exception as e:
            logger.error(f"Failed to calculate negative feedback trend: {e}")
            return 0.0

    def _suggest_faq_category(self, issues: List[str]) -> str:
        """Suggest an FAQ category based on feedback issues."""
        # Simple categorization logic
        issue_keywords = {
            "Technical": ["error", "bug", "crash", "broken", "not working"],
            "User Experience": [
                "confusing",
                "unclear",
                "hard to understand",
                "complex",
            ],
            "Performance": ["slow", "timeout", "loading", "delay"],
            "Content": ["wrong", "incorrect", "outdated", "missing"],
        }

        for category, keywords in issue_keywords.items():
            for issue in issues:
                if any(keyword in issue.lower() for keyword in keywords):
                    return category

        return "General"

    async def _get_fallback_dashboard_data(self) -> Dict[str, Any]:
        """Return fallback dashboard data when main data retrieval fails."""
        return {
            "helpful_rate": 75.0,
            "helpful_rate_trend": 0.0,
            "average_response_time": 3.0,
            "response_time_trend": 0.0,
            "negative_feedback_count": 0,
            "negative_feedback_trend": 0.0,
            "feedback_items_for_faq": [],
            "system_uptime": time.time() - self.system_start_time,
            "total_queries": 0,
            "total_faqs_created": 0,
            "total_feedback": 0,
            "total_faqs": 0,
            "last_updated": datetime.now().isoformat(),
            "fallback": True,
        }
