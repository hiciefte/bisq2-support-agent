"""
Dashboard service for admin overview metrics and analytics.

This service combines real-time data from the database with historical metrics
from Prometheus to provide comprehensive dashboard statistics.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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

    async def close(self) -> None:
        """Close resources and cleanup.

        Properly closes the PrometheusClient's HTTP connection pool to
        prevent resource leaks when the service is disposed.
        """
        await self.prometheus_client.close()

    async def get_dashboard_overview(
        self,
        period: str = "7d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get comprehensive dashboard overview combining real-time and historical data.

        Args:
            period: Time period for trends ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)

        Returns:
            Dict containing dashboard metrics including:
            - helpful_rate: Current helpful rate percentage
            - helpful_rate_trend: Trend indicator for selected period
            - average_response_time: Current average response time
            - response_time_trend: Performance trend for selected period
            - negative_feedback_count: Recent negative feedback count
            - negative_feedback_trend: Growth rate for selected period
            - feedback_items_for_faq: Items that could benefit from FAQ creation
            - system_uptime: Current system uptime
            - total_queries: Total queries processed
            - total_faqs_created: Total FAQs created from feedback
            - period: Selected period
            - period_label: Human-readable period description
        """
        logger.info(f"Generating dashboard overview data for period: {period}")

        try:
            # Get feedback items that would benefit from FAQ creation
            feedback_for_faq = await self._get_feedback_items_for_faq()

            # Calculate system uptime
            uptime_seconds = time.time() - self.system_start_time

            # Get FAQ creation statistics
            faq_stats = await self._get_faq_creation_stats()

            # Convert period to hours for Prometheus queries
            window_hours = self._period_to_hours(period, start_date, end_date)

            # Get period timestamps for feedback stats
            current_start, current_end, _, _ = self._get_period_timestamps(
                period, start_date, end_date
            )

            # Get period-filtered feedback statistics for current values
            period_feedback_stats = await asyncio.to_thread(
                self.feedback_service.repository.get_feedback_stats_for_period,
                current_start.isoformat(),
                current_end.isoformat(),
            )

            # Calculate trends for the selected period
            helpful_rate_trend = await self._calculate_helpful_rate_trend(
                period, start_date, end_date
            )
            response_time_trend = await self._calculate_response_time_trend(
                period, start_date, end_date
            )
            negative_feedback_trend = await self._calculate_negative_feedback_trend(
                period, start_date, end_date
            )

            # Get response time metrics for the selected period
            avg_response_time = await self._get_average_response_time(
                window_hours=window_hours
            )
            p95_response_time = await self._get_average_response_time(
                window_hours=window_hours, percentile=0.95
            )

            # Get period metadata
            period_label = self._get_period_label(period, start_date, end_date)

            dashboard_data = {
                # Core metrics (all period-filtered now)
                "helpful_rate": period_feedback_stats["helpful_rate"]
                * 100,  # Convert to percentage
                "helpful_rate_trend": helpful_rate_trend,
                "average_response_time": avg_response_time or 2.3,  # Fallback if None
                "p95_response_time": p95_response_time,  # May be None if no data
                "response_time_trend": response_time_trend,
                "negative_feedback_count": period_feedback_stats["negative"],
                "negative_feedback_trend": negative_feedback_trend,
                # Dashboard-specific data
                "feedback_items_for_faq": feedback_for_faq,
                "feedback_items_for_faq_count": len(feedback_for_faq),
                "system_uptime": uptime_seconds,
                "total_queries": await self._get_total_query_count(),
                "total_faqs_created": faq_stats["total_created_from_feedback"],
                # Additional context
                "total_feedback": period_feedback_stats["total"],
                "total_faqs": faq_stats["total_faqs"],
                "last_updated": datetime.now(timezone.utc).isoformat(),
                # Period metadata
                "period": period,
                "period_label": period_label,
            }

            # Add custom date range to response if applicable
            if period == "custom" and start_date and end_date:
                dashboard_data["period_start"] = start_date
                dashboard_data["period_end"] = end_date

            logger.info("Successfully generated dashboard overview")
            return dashboard_data

        except Exception as e:
            logger.error(f"Failed to generate dashboard overview: {e}", exc_info=True)
            # Return fallback data with period context
            return await self._get_fallback_dashboard_data(period)

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

    async def _get_average_response_time(
        self, window_hours: int = 1, percentile: Optional[float] = None
    ) -> Optional[float]:
        """
        Get response time from Prometheus metrics for the specified period.

        Args:
            window_hours: Time window in hours (matches period selection)
            percentile: If specified, return this percentile (e.g., 0.95 for P95)

        Returns:
            Response time in seconds, or None if unavailable
        """
        try:
            # Try to get real data from Prometheus
            prom_value = await self.prometheus_client.get_average_response_time(
                window_hours=window_hours, percentile=percentile
            )
            if prom_value is not None:
                return prom_value

            # No data available from Prometheus
            metric_type = f"P{int(percentile * 100)}" if percentile else "average"
            logger.warning(
                f"No Prometheus data available for {metric_type} response time ({window_hours}h window)"
            )
            return None
        except Exception as e:
            logger.error(
                f"Failed to get response time from Prometheus: {e}", exc_info=True
            )
            return None

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

    async def _calculate_helpful_rate_trend(
        self,
        period: str = "7d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> float:
        """Calculate helpful rate trend (delta in percentage points).

        Compares helpful rate from current period vs previous equivalent period.
        Returns absolute change in percentage points (not relative change).
        Positive value = improvement, negative value = degradation.

        Args:
            period: Time period ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)
        """
        try:
            # Get period timestamps
            current_start, current_end, previous_start, previous_end = (
                self._get_period_timestamps(period, start_date, end_date)
            )

            # Get stats for both periods (offload to thread to avoid blocking event loop)
            current_stats, previous_stats = await asyncio.gather(
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    current_start.isoformat(),
                    current_end.isoformat(),
                ),
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    previous_start.isoformat(),
                    previous_end.isoformat(),
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
                f"Helpful rate trend ({period}): {trend:+.1f}% (current: {current_rate:.1f}%, previous: {previous_rate:.1f}%)"
            )
            return trend

        except Exception as e:
            logger.error(f"Failed to calculate helpful rate trend: {e}", exc_info=True)
            return 0.0

    async def _calculate_response_time_trend(
        self,
        period: str = "7d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> float:
        """Calculate response time trend from Prometheus metrics.

        Positive value = slower (degradation), negative value = faster (improvement).
        Falls back to zero if insufficient data.

        Args:
            period: Time period ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)
        """
        try:
            # Convert period to hours for Prometheus query
            window_hours = self._period_to_hours(period, start_date, end_date)

            # Try to get real trend from Prometheus
            prom_trend = await self.prometheus_client.get_response_time_trend(
                window_hours=window_hours
            )
            if prom_trend is not None:
                logger.info(
                    f"Response time trend ({period}, {window_hours}h): {prom_trend:+.3f}s"
                )
                return prom_trend

            # Fallback to zero if no data available (no change)
            logger.debug(
                "No Prometheus data available for response time trend, returning zero"
            )
            return 0.0
        except Exception as e:
            logger.error(f"Failed to calculate response time trend: {e}", exc_info=True)
            return 0.0

    async def _calculate_negative_feedback_trend(
        self,
        period: str = "7d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> float:
        """Calculate negative feedback trend (relative percentage change).

        Compares negative feedback count from current period vs previous equivalent period.
        Returns relative percentage change: ((current - previous) / previous) * 100.
        Positive value = more negative feedback (degradation).
        Negative value = less negative feedback (improvement).

        Args:
            period: Time period ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)
        """
        try:
            # Get period timestamps
            current_start, current_end, previous_start, previous_end = (
                self._get_period_timestamps(period, start_date, end_date)
            )

            # Get stats for both periods (offload to thread to avoid blocking event loop)
            current_stats, previous_stats = await asyncio.gather(
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    current_start.isoformat(),
                    current_end.isoformat(),
                ),
                asyncio.to_thread(
                    self.feedback_service.repository.get_feedback_stats_for_period,
                    previous_start.isoformat(),
                    previous_end.isoformat(),
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
                f"Negative feedback trend ({period}): {trend:+.1f}% (current: {current_negative}, previous: {previous_negative})"
            )
            return trend

        except Exception as e:
            logger.error(
                f"Failed to calculate negative feedback trend: {e}", exc_info=True
            )
            return 0.0

    def _get_period_timestamps(
        self,
        period: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> tuple[datetime, datetime, datetime, datetime]:
        """Calculate current and previous period timestamps.

        Args:
            period: Time period ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)
            now: Current datetime (defaults to now, mainly for testing)

        Returns:
            Tuple of (current_start, current_end, previous_start, previous_end)

        Raises:
            ValueError: If period is invalid or custom dates are missing
        """
        if now is None:
            now = datetime.now(timezone.utc)

        if period == "24h":
            # Current: last 24 hours
            current_start = now - timedelta(hours=24)
            current_end = now
            # Previous: 24-48 hours ago
            previous_start = now - timedelta(hours=48)
            previous_end = now - timedelta(hours=24)

        elif period == "7d":
            # Current: last 7 days
            current_start = now - timedelta(days=7)
            current_end = now
            # Previous: 7-14 days ago
            previous_start = now - timedelta(days=14)
            previous_end = now - timedelta(days=7)

        elif period == "30d":
            # Current: last 30 days
            current_start = now - timedelta(days=30)
            current_end = now
            # Previous: 30-60 days ago
            previous_start = now - timedelta(days=60)
            previous_end = now - timedelta(days=30)

        elif period == "custom":
            if not start_date or not end_date:
                raise ValueError("start_date and end_date required for custom period")

            # Parse custom dates
            current_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            current_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

            # Calculate duration for previous period
            duration = current_end - current_start
            previous_end = current_start
            previous_start = previous_end - duration

        else:
            raise ValueError(f"Invalid period: {period}")

        return current_start, current_end, previous_start, previous_end

    def _period_to_hours(
        self,
        period: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """Convert period to hours for Prometheus queries.

        Args:
            period: Time period ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)

        Returns:
            Number of hours in the period

        Raises:
            ValueError: If period is invalid
        """
        if period == "24h":
            return 24
        elif period == "7d":
            return 168  # 7 * 24
        elif period == "30d":
            return 720  # 30 * 24
        elif period == "custom":
            if not start_date or not end_date:
                raise ValueError("start_date and end_date required for custom period")
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            duration = end - start
            return int(duration.total_seconds() / 3600)  # Convert to hours
        else:
            raise ValueError(f"Invalid period: {period}")

    def _get_period_label(
        self,
        period: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Get human-readable period label.

        Args:
            period: Time period ("24h", "7d", "30d", "custom")
            start_date: Start date for custom period (ISO format)
            end_date: End date for custom period (ISO format)

        Returns:
            Human-readable period description
        """
        if period == "24h":
            return "vs previous 24 hours"
        elif period == "7d":
            return "vs previous 7 days"
        elif period == "30d":
            return "vs previous 30 days"
        elif period == "custom" and start_date and end_date:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            days = (end - start).days
            return f"vs previous {days} days"
        else:
            return "vs previous period"

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

    async def _get_fallback_dashboard_data(self, period: str = "7d") -> Dict[str, Any]:
        """Return fallback dashboard data when main data retrieval fails.

        Args:
            period: Time period for context (used in period_label)
        """
        return {
            "helpful_rate": 75.0,
            "helpful_rate_trend": 0.0,
            "average_response_time": 3.0,
            "p95_response_time": None,
            "response_time_trend": 0.0,
            "negative_feedback_count": 0,
            "negative_feedback_trend": 0.0,
            "feedback_items_for_faq": [],
            "feedback_items_for_faq_count": 0,
            "system_uptime": time.time() - self.system_start_time,
            "total_queries": 0,
            "total_faqs_created": 0,
            "total_feedback": 0,
            "total_faqs": 0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "period": period,
            "period_label": self._get_period_label(period),
            "fallback": True,
        }
