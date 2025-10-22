"""
Dashboard service for admin overview metrics and analytics.

This service combines real-time data from the database with historical metrics
from Prometheus to provide comprehensive dashboard statistics.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.config import Settings
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService
from app.services.prometheus_client import PrometheusClient

logger = logging.getLogger(__name__)


class DashboardService:
    """Service for dashboard data aggregation and analytics."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.feedback_service = FeedbackService(settings)
        self.faq_service = FAQService(settings)
        self.prometheus_client = PrometheusClient(settings)
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
                "last_updated": datetime.now(timezone.utc).isoformat(),
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
                # AND exclude already-processed feedback (feedback that has been turned into FAQs)
                if (
                    feedback.is_negative
                    and (feedback.explanation or feedback.has_no_source_response)
                    and not feedback.is_processed
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
            logger.error(f"Failed to get feedback items for FAQ: {e}", exc_info=True)
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
            logger.error(f"Failed to get FAQ creation stats: {e}", exc_info=True)
            return {
                "total_faqs": 0,
                "total_created_from_feedback": 0,
                "total_manual": 0,
            }

    async def _get_average_response_time(self) -> float:
        """
        Get average response time from Prometheus metrics.
        Falls back to simulated value if Prometheus is unavailable.
        """
        try:
            # Try to get real data from Prometheus
            prom_value = await self.prometheus_client.get_average_response_time()
            if prom_value is not None:
                return prom_value

            # Fallback to simulated value if no data available
            logger.warning(
                "No Prometheus data available for average response time, using fallback"
            )
            return 2.3  # seconds
        except Exception as e:
            logger.error(f"Failed to get average response time: {e}", exc_info=True)
            return 5.0  # fallback

    async def _get_total_query_count(self) -> int:
        """
        Get total query count from Prometheus metrics.
        Falls back to zero if Prometheus is unavailable.
        """
        try:
            # Try to get real data from Prometheus
            prom_value = await self.prometheus_client.get_total_query_count()
            if prom_value is not None:
                return prom_value

            # Fallback to zero if no data available
            logger.warning(
                "No Prometheus data available for query count, using fallback"
            )
            return 0
        except Exception as e:
            logger.error(f"Failed to get total query count: {e}", exc_info=True)
            return 0

    async def _calculate_helpful_rate_trend(self) -> float:
        """Calculate helpful rate trend (delta in percentage points).

        Compares helpful rate from last 24 hours vs previous 24 hours.
        Returns absolute change in percentage points (not relative change).
        Positive value = improvement, negative value = degradation.
        """
        try:
            import asyncio
            from datetime import timedelta

            now = datetime.now(timezone.utc)

            # Current period: last 24 hours
            current_start = (now - timedelta(hours=24)).isoformat()
            current_end = now.isoformat()

            # Previous period: 24-48 hours ago
            previous_start = (now - timedelta(hours=48)).isoformat()
            previous_end = (now - timedelta(hours=24)).isoformat()

            # Get stats for both periods (offload to thread to avoid blocking event loop)
            current_stats, previous_stats = await asyncio.gather(
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    current_start,
                    current_end,
                ),
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    previous_start,
                    previous_end,
                ),
            )

            # Calculate helpful rates (as percentages)
            current_rate = current_stats["helpful_rate"] * 100
            previous_rate = previous_stats["helpful_rate"] * 100

            # Calculate absolute change
            if previous_stats["total"] == 0:
                # No previous data, can't calculate trend
                logger.debug("No previous period data for helpful rate trend")
                return 0.0

            trend = current_rate - previous_rate
            logger.info(
                f"Helpful rate trend: {trend:+.1f}% (current: {current_rate:.1f}%, previous: {previous_rate:.1f}%)"
            )
            return trend

        except Exception as e:
            logger.error(f"Failed to calculate helpful rate trend: {e}", exc_info=True)
            return 0.0

    async def _calculate_response_time_trend(self) -> float:
        """Calculate response time trend from Prometheus metrics.

        Positive value = slower (degradation), negative value = faster (improvement).
        Falls back to zero if insufficient data.
        """
        try:
            # Try to get real trend from Prometheus
            prom_trend = await self.prometheus_client.get_response_time_trend()
            if prom_trend is not None:
                return prom_trend

            # Fallback to zero if no data available (no change)
            logger.debug(
                "No Prometheus data available for response time trend, returning zero"
            )
            return 0.0
        except Exception as e:
            logger.error(f"Failed to calculate response time trend: {e}", exc_info=True)
            return 0.0

    async def _calculate_negative_feedback_trend(self) -> float:
        """Calculate negative feedback trend (relative percentage change).

        Compares negative feedback count from last 24 hours vs previous 24 hours.
        Returns relative percentage change: ((current - previous) / previous) * 100.
        Positive value = more negative feedback (degradation).
        Negative value = less negative feedback (improvement).
        """
        try:
            import asyncio
            from datetime import timedelta

            now = datetime.now(timezone.utc)

            # Current period: last 24 hours
            current_start = (now - timedelta(hours=24)).isoformat()
            current_end = now.isoformat()

            # Previous period: 24-48 hours ago
            previous_start = (now - timedelta(hours=48)).isoformat()
            previous_end = (now - timedelta(hours=24)).isoformat()

            # Get stats for both periods (offload to thread to avoid blocking event loop)
            current_stats, previous_stats = await asyncio.gather(
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    current_start,
                    current_end,
                ),
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    previous_start,
                    previous_end,
                ),
            )

            current_negative = current_stats["negative"]
            previous_negative = previous_stats["negative"]

            # Calculate percentage change
            if previous_negative == 0:
                # No previous data
                if current_negative == 0:
                    # No change
                    return 0.0
                else:
                    # No baseline to compare against - treat as zero trend per policy
                    logger.debug(
                        "No previous negative feedback; treating as 0.0% trend per zero-data policy"
                    )
                    return 0.0

            # Calculate percentage change: ((current - previous) / previous) * 100
            trend = ((current_negative - previous_negative) / previous_negative) * 100
            logger.info(
                f"Negative feedback trend: {trend:+.1f}% (current: {current_negative}, previous: {previous_negative})"
            )
            return trend

        except Exception as e:
            logger.error(
                f"Failed to calculate negative feedback trend: {e}", exc_info=True
            )
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
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "fallback": True,
        }
