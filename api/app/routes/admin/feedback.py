"""
Admin feedback management routes for the Bisq Support API.
"""

import logging
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.exceptions import (
    BaseAppException,
    FeedbackAlreadyProcessedError,
    FeedbackNotFoundError,
)
from app.core.security import verify_admin_access
from app.models.faq import FAQIdentifiedItem, FAQItem
from app.models.feedback import (
    CreateFAQFromFeedbackRequest,
    FeedbackFilterRequest,
    FeedbackListResponse,
    FeedbackStatsResponse,
)
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService
from fastapi import APIRouter, Depends, status

# Setup logging
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Create main admin router with authentication dependencies for protected routes
router = APIRouter(
    prefix="/admin",
    tags=["Admin Feedback"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)

# Create singleton instances
feedback_service = FeedbackService(settings=settings)
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
async def get_feedback_analytics() -> Dict[str, Any]:
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
    raw_issues: dict[str, int] = {}
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
    common_issues: dict[str, int] = {}
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


@router.get("/feedback/list", response_model=FeedbackListResponse)
async def get_feedback_list(
    rating: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    issues: Optional[str] = None,  # Comma-separated list
    source_types: Optional[str] = None,  # Comma-separated list
    search_text: Optional[str] = None,
    needs_faq: Optional[bool] = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "newest",
):
    """Get filtered and paginated feedback list for admin interface.

    This endpoint provides comprehensive feedback management capabilities:
    - Filter by rating (positive/negative/all)
    - Filter by date range
    - Filter by issue types
    - Filter by source types
    - Text search across questions/answers/explanations
    - Filter for feedback needing FAQ creation
    - Pagination and sorting support

    Authentication required via API key.
    """
    logger.info(
        f"Admin request to fetch feedback list with filters: rating={rating}, page={page}"
    )

    # Parse comma-separated lists
    issues_list = [issue.strip() for issue in issues.split(",")] if issues else None
    source_types_list = (
        [st.strip() for st in source_types.split(",")] if source_types else None
    )

    # Create filter request
    filters = FeedbackFilterRequest(
        rating=rating,
        date_from=date_from,
        date_to=date_to,
        issues=issues_list,
        source_types=source_types_list,
        search_text=search_text,
        needs_faq=needs_faq,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
    )

    try:
        result = feedback_service.get_feedback_with_filters(filters)
        return result
    except Exception as e:
        logger.error(f"Failed to fetch feedback list: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch feedback list",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_LIST_FETCH_FAILED",
        ) from e


@router.get("/feedback/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats_enhanced():
    """Get enhanced feedback statistics for admin dashboard.

    Provides comprehensive analytics including:
    - Basic counts and rates
    - Common issues breakdown
    - Source effectiveness metrics
    - Recent activity trends
    - Items needing FAQ creation

    Authentication required via API key.
    """
    logger.info("Admin request to fetch enhanced feedback statistics")

    try:
        stats = feedback_service.get_feedback_stats_enhanced()
        return FeedbackStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to fetch feedback stats: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch feedback statistics",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_STATS_FETCH_FAILED",
        ) from e


@router.get("/feedback/needs-faq")
async def get_feedback_needing_faq() -> Dict[str, Any]:
    """Get negative feedback that would benefit from FAQ creation.

    Returns feedback items that:
    - Have negative ratings
    - Include explanations from users about why the answer was unhelpful
    - Have responses indicating the LLM had no source information

    This endpoint is specifically designed to help support agents identify
    knowledge gaps that should be addressed with new FAQs.

    Authentication required via API key.
    """
    logger.info("Admin request to fetch feedback needing FAQ creation")

    try:
        feedback_items = feedback_service.get_negative_feedback_for_faq_creation()
        return {"feedback_items": feedback_items, "count": len(feedback_items)}
    except Exception as e:
        logger.error(
            f"Failed to fetch feedback needing FAQ creation: {e}", exc_info=True
        )
        raise BaseAppException(
            detail="Failed to fetch feedback data",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_FAQ_FETCH_FAILED",
        ) from e


@router.post("/feedback/create-faq", response_model=FAQIdentifiedItem, status_code=201)
async def create_faq_from_feedback(request: CreateFAQFromFeedbackRequest):
    """Create a new FAQ based on feedback.

    This endpoint allows support agents to convert negative feedback into
    new FAQ entries, helping to address knowledge gaps and improve future
    responses for similar questions.

    The original feedback entry is automatically marked as processed with
    a reference to the created FAQ for tracking purposes.

    Authentication required via API key.
    """
    logger.info(f"Admin request to create FAQ from feedback: {request.message_id}")

    try:
        # Check if feedback exists (simple existence check only)
        existing_feedback = feedback_service.repository.get_feedback_by_message_id(
            request.message_id
        )

        if not existing_feedback:
            raise FeedbackNotFoundError(request.message_id)

        # Create the FAQ item
        # Note: We don't check if feedback is already processed here to avoid race conditions
        # The atomic update in mark_feedback_as_processed handles concurrency safely
        faq_item = FAQItem(
            question=request.suggested_question or "Generated from feedback",
            answer=request.suggested_answer,
            category=request.category,
            source="Feedback",  # Mark as created from feedback
        )

        # Add the FAQ using the FAQ service
        new_faq = faq_service.add_faq(faq_item)

        # Try to atomically mark the feedback as processed
        # The repository uses an atomic UPDATE with WHERE processed = 0
        # This ensures only one concurrent request can successfully mark it
        try:
            marked = feedback_service.mark_feedback_as_processed(
                message_id=request.message_id, faq_id=new_faq.id
            )

            if not marked:
                # Atomic update failed - feedback was already processed by another request
                # Rollback the FAQ creation to maintain consistency
                logger.warning(
                    f"Feedback {request.message_id} was already processed by another request, "
                    f"rolling back FAQ {new_faq.id}"
                )

                # Attempt to delete the orphaned FAQ
                try:
                    faq_service.delete_faq(new_faq.id)
                    logger.info(
                        f"Successfully rolled back FAQ {new_faq.id} after concurrent processing detected"
                    )
                except Exception as delete_error:
                    # Log delete error but preserve original error context
                    logger.error(
                        f"Failed to rollback FAQ {new_faq.id} during race condition recovery: {delete_error}",
                        exc_info=True,
                    )

                # Return 409 Conflict - feedback was already processed by concurrent request
                raise FeedbackAlreadyProcessedError(request.message_id)
        except BaseAppException:
            # Re-raise application exceptions without wrapping
            raise
        except Exception as mark_error:
            # Marking raised an exception - rollback the FAQ creation
            logger.error(
                f"Exception while marking feedback {request.message_id} as processed: {mark_error}",
                exc_info=True,
            )

            # Attempt to delete the orphaned FAQ
            try:
                faq_service.delete_faq(new_faq.id)
                logger.info(f"Rolled back FAQ {new_faq.id} after marking exception")
            except Exception as delete_error:
                # Log delete error but preserve original error context
                logger.error(
                    f"Failed to rollback FAQ {new_faq.id} during error recovery: {delete_error}",
                    exc_info=True,
                )

            raise BaseAppException(
                detail=f"Failed to mark feedback as processed: {mark_error}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code="FEEDBACK_MARK_FAILED",
            ) from mark_error

        # Record FAQ creation metric
        from app.routes.admin.analytics import FAQ_CREATION_TOTAL

        FAQ_CREATION_TOTAL.inc()

        logger.info(
            f"Successfully created FAQ from feedback {request.message_id}: {new_faq.id} "
            f"(Feedback marked as processed)"
        )
        return new_faq

    except BaseAppException:
        # Re-raise application exceptions (404, 409) without wrapping
        raise
    except Exception as e:
        logger.error(
            f"Failed to create FAQ from feedback {request.message_id}: {e}",
            exc_info=True,
        )
        raise BaseAppException(
            detail="Failed to create FAQ from feedback",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FAQ_FROM_FEEDBACK_FAILED",
        ) from e


@router.get("/feedback/{message_id}")
async def get_feedback_details(message_id: str) -> Dict[str, Any]:
    """Get complete feedback details including full conversation history.

    This endpoint retrieves a single feedback entry with all associated data:
    - Question, answer, rating, and explanation
    - Complete conversation history with all messages
    - Metadata and issue types
    - Timestamps

    Authentication required via API key.
    """
    logger.info(f"Admin request to fetch feedback details for message: {message_id}")

    try:
        feedback = feedback_service.repository.get_feedback_by_message_id(message_id)

        if not feedback:
            raise FeedbackNotFoundError(message_id)

        return feedback
    except BaseAppException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to fetch feedback details for {message_id}: {e}", exc_info=True
        )
        raise BaseAppException(
            detail="Failed to fetch feedback details",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_DETAILS_FETCH_FAILED",
        ) from e


@router.get("/feedback/by-issues")
async def get_feedback_by_issues() -> Dict[str, Any]:
    """Get feedback grouped by issue types for pattern analysis.

    This endpoint helps support agents understand common problems
    by grouping negative feedback by issue categories such as:
    - too_verbose, too_technical, inaccurate, etc.

    Authentication required via API key.
    """
    logger.info("Admin request to fetch feedback grouped by issues")

    try:
        issues_dict = feedback_service.get_feedback_by_issues()

        # Convert to a more API-friendly format
        result = []
        for issue, items in issues_dict.items():
            result.append(
                {
                    "issue_type": issue,
                    "count": len(items),
                    "feedback_items": items[:5],  # Include first 5 examples
                }
            )

        # Sort by count descending
        result.sort(key=lambda x: x["count"], reverse=True)

        return {"issues": result, "total_issues": len(result)}
    except Exception as e:
        logger.error(f"Failed to fetch feedback by issues: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch feedback by issues",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_BY_ISSUES_FETCH_FAILED",
        ) from e
