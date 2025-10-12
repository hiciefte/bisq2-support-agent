"""
Admin analytics and metrics routes for the Bisq Support API.
"""

import logging

from app.core.config import get_settings
from app.core.exceptions import BaseAppException
from app.core.security import verify_admin_access
from app.models.feedback import DashboardOverviewResponse
from app.services.dashboard_service import DashboardService
from app.services.feedback_service import FeedbackService
from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

# Setup logging
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

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

# Create singleton instances
feedback_service = FeedbackService(settings=settings)
dashboard_service = DashboardService(settings=settings)

# Create Prometheus metrics
# Use Gauge for metrics that can go up and down
FEEDBACK_HELPFUL_RATE = Gauge(
    "bisq_feedback_helpful_rate", "Percentage of helpful feedback"
)
SOURCE_HELPFUL_RATE = Gauge(
    "bisq_source_helpful_rate", "Helpful rate by source type", ["source_type"]
)

# Use Counter for metrics that only increase
FEEDBACK_TOTAL = Counter("bisq_feedback_total", "Total number of feedback entries")
FEEDBACK_HELPFUL = Counter(
    "bisq_feedback_helpful", "Number of helpful feedback entries"
)
FEEDBACK_UNHELPFUL = Counter(
    "bisq_feedback_unhelpful", "Number of unhelpful feedback entries"
)
SOURCE_TOTAL = Counter(
    "bisq_source_total", "Total usage count by source type", ["source_type"]
)
SOURCE_HELPFUL = Counter(
    "bisq_source_helpful", "Helpful count by source type", ["source_type"]
)
ISSUE_COUNT = Counter(
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

    # Reset Counters if needed (in case of server restart)
    # We only do this for Counter types since they're cumulative
    # Note: This is a workaround - in production you should use proper persistence
    FEEDBACK_TOTAL._value.set(0)
    FEEDBACK_HELPFUL._value.set(0)
    FEEDBACK_UNHELPFUL._value.set(0)

    # Update Counter metrics with current values
    FEEDBACK_TOTAL._value.set(analytics["total_feedback"])
    FEEDBACK_HELPFUL._value.set(analytics["helpful_count"])
    FEEDBACK_UNHELPFUL._value.set(analytics["unhelpful_count"])

    # Update Gauge metrics (these can go up or down)
    FEEDBACK_HELPFUL_RATE.set(analytics["helpful_rate"] * 100)  # Convert to percentage

    # Update source metrics
    for source_type, stats in analytics["source_effectiveness"].items():
        # Reset before setting new values
        SOURCE_TOTAL.labels(source_type=source_type)._value.set(0)
        SOURCE_HELPFUL.labels(source_type=source_type)._value.set(0)

        # Set new values
        SOURCE_TOTAL.labels(source_type=source_type)._value.set(stats["total"])
        SOURCE_HELPFUL.labels(source_type=source_type)._value.set(stats["helpful"])

        helpful_rate = stats["helpful"] / stats["total"] if stats["total"] > 0 else 0
        SOURCE_HELPFUL_RATE.labels(source_type=source_type).set(
            helpful_rate * 100
        )  # Convert to percentage

    # Update issue metrics with controlled vocabulary to prevent high-cardinality
    # First clear any existing metrics to ensure removed issues don't persist
    for issue_type in [*KNOWN_ISSUE_TYPES.values(), "other"]:
        ISSUE_COUNT.labels(issue_type=issue_type)._value.set(0)

    # Now set the new values
    for issue_type, count in analytics["common_issues"].items():
        ISSUE_COUNT.labels(issue_type=issue_type)._value.set(count)

    # Return metrics in Prometheus format
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview():
    """Get comprehensive dashboard overview with metrics and analytics.

    This endpoint provides a complete dashboard overview combining:
    - Real-time feedback statistics and trends
    - Average response time metrics
    - Feedback items that would benefit from FAQ creation
    - System uptime and query statistics
    - Historical trend data for performance monitoring

    Authentication required via API key.
    """
    logger.info("Admin request to fetch dashboard overview")

    # Track dashboard requests
    DASHBOARD_REQUESTS.inc()

    try:
        overview_data = await dashboard_service.get_dashboard_overview()
        return DashboardOverviewResponse(**overview_data)
    except Exception as e:
        logger.error(f"Failed to fetch dashboard overview: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch dashboard overview",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="DASHBOARD_FETCH_FAILED",
        ) from e
