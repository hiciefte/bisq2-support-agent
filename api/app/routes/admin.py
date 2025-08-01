"""
Admin routes for the Bisq Support API.
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

from app.core.config import get_settings
from app.core.security import verify_admin_access
from app.models.faq import FAQItem, FAQIdentifiedItem, FAQListResponse
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService

# Setup logging
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Create router with better documentation of admin security requirements
router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)

# Create a singleton instance of FeedbackService
feedback_service = FeedbackService(settings=settings)

# Create a singleton instance of FAQService
faq_service = FAQService(settings=settings)

# Controlled vocabulary for issue types to prevent high-cardinality
KNOWN_ISSUE_TYPES = {
    "too_verbose": "too_verbose",
    "too_technical": "too_technical",
    "not_specific": "not_specific",
    "inaccurate": "inaccurate",
    "outdated": "outdated",
    "not_helpful": "not_helpful",
    "missing_context": "missing_context",
    "confusing": "confusing",
    # Add mappings for commonly seen free-form issues
    "wrong": "inaccurate",
    "error": "inaccurate",
    "missing": "missing_context",
    "unclear": "confusing",
    "complex": "too_technical",
    "long": "too_verbose",
    "wordy": "too_verbose",
    "vague": "not_specific",
    "unhelpful": "not_helpful",
}

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


def map_to_controlled_issue_type(issue: str) -> str:
    """Map arbitrary issue strings to controlled vocabulary to prevent high-cardinality.

    Args:
        issue: The original issue string

    Returns:
        A standardized issue type from the controlled vocabulary
    """
    # Convert to lowercase for consistent matching
    issue_lower = issue.lower()

    # Check if the issue is in our known issues mapping
    for key, value in KNOWN_ISSUE_TYPES.items():
        if key in issue_lower:
            return value

    # If no match, return "other"
    return "other"


@router.get("/feedback", response_model=Dict[str, Any])
async def get_feedback_analytics():
    """Get analytics about user feedback.

    This endpoint requires admin authentication via the API key.
    Authentication can be provided through:
    - Authorization header with Bearer token
    - api_key query parameter
    """
    feedback = feedback_service.load_feedback()

    # Basic analytics
    total = len(feedback)

    if total == 0:
        return {
            "total_feedback": 0,
            "helpful_rate": 0,
            "source_effectiveness": {},
            "common_issues": {},
            "recent_negative": [],
        }

    # Consider rating 1 as helpful, rating 0 as unhelpful
    helpful_count = sum(1 for item in feedback if item.get("rating", 0) == 1)
    unhelpful_count = total - helpful_count

    # Source effectiveness
    source_stats = {}
    for item in feedback:
        # Try sources_used first, then fall back to sources if sources_used doesn't exist
        sources_list = item.get("sources_used", item.get("sources", []))
        for source in sources_list:
            source_type = source.get("type", "unknown")
            if source_type not in source_stats:
                source_stats[source_type] = {"total": 0, "helpful": 0}

            source_stats[source_type]["total"] += 1
            if item.get("rating", 0) == 1:  # Consider rating 1 as helpful
                source_stats[source_type]["helpful"] += 1

    # Common issues in negative feedback
    raw_issues = {}
    for item in feedback:
        if item.get("rating", 0) == 0:  # Consider rating 0 as unhelpful
            # Check specific issue fields
            for issue_key in [
                "too_verbose",
                "too_technical",
                "not_specific",
                "inaccurate",
            ]:
                if item.get(issue_key):
                    raw_issues[issue_key] = raw_issues.get(issue_key, 0) + 1

            # Also check metadata.issues list if present
            if item.get("metadata") and item["metadata"].get("issues"):
                for issue in item["metadata"]["issues"]:
                    raw_issues[issue] = raw_issues.get(issue, 0) + 1

    # Map to controlled vocabulary to prevent high-cardinality
    common_issues = {}
    for issue, count in raw_issues.items():
        mapped_issue = map_to_controlled_issue_type(issue)
        common_issues[mapped_issue] = common_issues.get(mapped_issue, 0) + count

    # Sort issues by count, descending
    sorted_issues = sorted(common_issues.items(), key=lambda x: x[1], reverse=True)

    # Limit to maximum number of unique issues
    if len(common_issues) > settings.MAX_UNIQUE_ISSUES:
        logger.info(
            f"Found {len(common_issues)} issues, limiting to {settings.MAX_UNIQUE_ISSUES}"
        )

        # Keep the top issues based on MAX_UNIQUE_ISSUES
        top_issues = dict(
            sorted_issues[: settings.MAX_UNIQUE_ISSUES - 1]
        )  # Leave room for "other"

        # Combine remaining issues as "other"
        other_count = sum(
            count for _, count in sorted_issues[settings.MAX_UNIQUE_ISSUES - 1 :]
        )
        if other_count > 0:
            top_issues["other"] = other_count

        common_issues = top_issues

    return {
        "total_feedback": total,
        "helpful_rate": helpful_count / total if total > 0 else 0,
        "helpful_count": helpful_count,
        "unhelpful_count": unhelpful_count,
        "source_effectiveness": source_stats,
        "common_issues": common_issues,
        "recent_negative": [
            {
                **f,
                "explanation": (
                    f.get("metadata", {}).get("explanation", "")[:100] + "..."
                    if f.get("metadata", {}).get("explanation", "")
                    and len(f.get("metadata", {}).get("explanation", "")) > 100
                    else f.get("metadata", {}).get("explanation", "")
                ),
            }
            for f in feedback
            if f.get("rating", 0) == 0
        ][-5:],
        # Include recent negative feedback with truncated explanation from metadata
    }


@router.get("/metrics", response_class=Response)
async def get_metrics():
    """Get feedback metrics in Prometheus format.

    This endpoint requires admin authentication via the API key.
    Authentication can be provided through:
    - Authorization header with Bearer token
    - api_key query parameter
    """
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
    for issue_type in list(KNOWN_ISSUE_TYPES.values()) + ["other"]:
        ISSUE_COUNT.labels(issue_type=issue_type)._value.set(0)

    # Now set the new values
    for issue_type, count in analytics["common_issues"].items():
        ISSUE_COUNT.labels(issue_type=issue_type)._value.set(count)

    # Return metrics in Prometheus format
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/faqs", response_model=FAQListResponse)
async def get_all_faqs_for_admin_route():
    """Get all FAQs for the admin interface."""
    logger.info("Admin request to fetch all FAQs")
    faqs = faq_service.get_all_faqs()
    return FAQListResponse(faqs=faqs)


@router.post("/faqs", response_model=FAQIdentifiedItem, status_code=201)
async def add_new_faq_route(faq_item: FAQItem):
    """Add a new FAQ."""
    logger.info(f"Admin request to add new FAQ: {faq_item.question[:30]}...")
    try:
        new_faq = faq_service.add_faq(faq_item)
        return new_faq
    except Exception as e:
        logger.error(f"Failed to add FAQ: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add FAQ.") from e


@router.put("/faqs/{faq_id}", response_model=FAQIdentifiedItem)
async def update_existing_faq_route(faq_id: str, faq_item_update: FAQItem):
    """Update an existing FAQ by its ID."""
    logger.info(f"Admin request to update FAQ with id: {faq_id}")
    updated_faq = faq_service.update_faq(faq_id, faq_item_update)
    if not updated_faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return updated_faq


@router.delete("/faqs/{faq_id}", status_code=204)
async def delete_existing_faq_route(faq_id: str):
    """Delete an existing FAQ by its ID."""
    logger.info(f"Admin request to delete FAQ with id: {faq_id}")
    success = faq_service.delete_faq(faq_id)
    if not success:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return Response(status_code=204)
