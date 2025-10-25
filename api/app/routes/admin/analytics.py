"""
Admin analytics and metrics routes for the Bisq Support API.
"""

import logging
from typing import Literal

from app.core.config import get_settings
from app.core.exceptions import BaseAppException
from app.core.security import verify_admin_access
from app.models.feedback import DashboardOverviewResponse
from app.services.dashboard_service import DashboardService
from app.services.feedback_service import FeedbackService
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from prometheus_client import (  # type: ignore[attr-defined]
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    generate_latest,
)

# Setup logging
logger = logging.getLogger(__name__)  # type: ignore[attr-defined]

# Create main admin router with authentication dependencies for protected routes
router = APIRouter(
    prefix="/admin",
    tags=["Admin Analytics"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)

# Initialize settings and services
settings = get_settings()
feedback_service = FeedbackService(settings=settings)
dashboard_service = DashboardService(settings=settings)

# Create Prometheus metrics
# Use Gauge for metrics that can go up and down (absolute values that change)
FEEDBACK_TOTAL = Gauge("bisq_feedback_total", "Total number of feedback entries")
FEEDBACK_HELPFUL = Gauge("bisq_feedback_helpful", "Number of helpful feedback entries")
FEEDBACK_UNHELPFUL = Gauge(
    "bisq_feedback_unhelpful", "Number of unhelpful feedback entries"
)
FEEDBACK_HELPFUL_RATE = Gauge(
    "bisq_feedback_helpful_rate", "Percentage of helpful feedback"
)
SOURCE_TOTAL = Gauge(
    "bisq_source_total", "Total usage count by source type", ["source_type"]
)
SOURCE_HELPFUL = Gauge(
    "bisq_source_helpful", "Helpful count by source type", ["source_type"]
)
SOURCE_HELPFUL_RATE = Gauge(
    "bisq_source_helpful_rate", "Helpful rate by source type", ["source_type"]
)
ISSUE_COUNT = Gauge(
    "bisq_issue_count", "Count of specific issues in feedback", ["issue_type"]
)

# Dashboard-specific metrics
FAQ_CREATION_TOTAL = Counter(
    "bisq_faq_creation_total", "Total number of FAQs created from feedback"
)
SYSTEM_UPTIME = Gauge("bisq_system_uptime_seconds", "System uptime in seconds")
DASHBOARD_REQUESTS = Counter(
    "bisq_dashboard_requests_total", "Total requests to dashboard endpoints"
)


@router.get("/metrics", response_class=Response)
async def get_metrics() -> Response:
    """Get feedback metrics in Prometheus format.

    This endpoint requires admin authentication via the API key.
    Authentication can be provided through:
    - Authorization header with Bearer token
    - api_key query parameter
    """
    # Import here to avoid circular dependency
    from app.routes.admin.feedback import KNOWN_ISSUE_TYPES, get_feedback_analytics

    # Get feedback analytics
    analytics = await get_feedback_analytics()

    # Update Gauge metrics with current values (Gauges are absolute values, not cumulative)
    FEEDBACK_TOTAL.set(analytics["total_feedback"])
    FEEDBACK_HELPFUL.set(analytics["helpful_count"])
    FEEDBACK_UNHELPFUL.set(analytics["unhelpful_count"])
    FEEDBACK_HELPFUL_RATE.set(analytics["helpful_rate"] * 100)  # Convert to percentage

    # Update source metrics
    for source_type, stats in analytics["source_effectiveness"].items():
        # Set Gauge values (no need to reset first, Gauges are absolute)
        SOURCE_TOTAL.labels(source_type=source_type).set(stats["total"])
        SOURCE_HELPFUL.labels(source_type=source_type).set(stats["helpful"])

        helpful_rate = stats["helpful"] / stats["total"] if stats["total"] > 0 else 0
        SOURCE_HELPFUL_RATE.labels(source_type=source_type).set(
            helpful_rate * 100
        )  # Convert to percentage

    # Update issue metrics with controlled vocabulary to prevent high-cardinality
    # First clear any existing metrics to ensure removed issues don't persist
    for issue_type in [*KNOWN_ISSUE_TYPES.values(), "other"]:
        ISSUE_COUNT.labels(issue_type=issue_type).set(0)

    # Now set the new values
    for issue_type, count in analytics["common_issues"].items():
        ISSUE_COUNT.labels(issue_type=issue_type).set(count)

    # Return metrics in Prometheus format
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    period: Literal["24h", "7d", "30d", "custom"] = "7d",
    start_date: str | None = None,
    end_date: str | None = None,
):
    """Get comprehensive dashboard overview with metrics and analytics.

    This endpoint provides a complete dashboard overview combining:
    - Real-time feedback statistics and trends
    - Average response time metrics
    - Feedback items that would benefit from FAQ creation
    - System uptime and query statistics
    - Historical trend data for performance monitoring

    Query Parameters:
        period: Time period for trends ("24h", "7d", "30d", "custom"). Default: "7d"
        start_date: Start date for custom period (ISO format, required if period="custom")
        end_date: End date for custom period (ISO format, required if period="custom")

    Authentication required via API key.
    """
    logger.info(f"Admin request to fetch dashboard overview (period={period})")

    # Validate custom period requires dates
    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date and end_date are required for custom period",
            )

    # Track dashboard requests
    DASHBOARD_REQUESTS.inc()

    try:
        overview_data = await dashboard_service.get_dashboard_overview(
            period=period,
            start_date=start_date,
            end_date=end_date,
        )
        return DashboardOverviewResponse(**overview_data)
    except Exception as e:
        logger.error(f"Failed to fetch dashboard overview: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch dashboard overview",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="DASHBOARD_FETCH_FAILED",
        ) from e
