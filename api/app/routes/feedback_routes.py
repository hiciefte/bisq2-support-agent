import json
import logging
from pathlib import Path
from typing import Any, Dict

from app.core.config import get_settings
from app.core.exceptions import BaseAppException
from app.models.feedback import FeedbackRequest
from app.services.feedback_service import get_feedback_service
from fastapi import APIRouter, Request, status

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/feedback/submit")
async def submit_feedback(request: Request, feedback: FeedbackRequest):
    """
    Submit feedback for a chat response.
    """
    try:
        # Get the Feedback service directly
        feedback_service = get_feedback_service(request)

        # Convert Pydantic model to dict
        feedback_data = feedback.model_dump()

        # Store feedback using the feedback service
        await feedback_service.store_feedback(feedback_data)

        # Add needs_feedback_followup flag for negative feedback
        needs_followup = feedback.rating == 0

        return {
            "status": "success",
            "message": "Feedback recorded successfully",
            "success": True,
            "needs_feedback_followup": needs_followup,
        }

    except BaseAppException:
        # Let service-level exceptions bubble up to centralized error handler
        raise
    except Exception as e:
        logger.error(f"Error recording feedback: {e!s}", exc_info=True)
        raise BaseAppException(
            detail="An error occurred while recording your feedback",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_SUBMISSION_FAILED",
        ) from e


@router.get("/feedback/stats")
async def get_feedback_stats():
    """
    Get aggregated feedback statistics.
    """
    try:
        settings = get_settings()
        feedback_dir = Path(settings.FEEDBACK_DIR_PATH)
        if not feedback_dir.exists():
            return {"total_feedback": 0, "average_rating": 0, "positive_ratio": 0}

        total_feedback = 0
        total_rating = 0
        positive_ratings = 0

        # Process all feedback files
        for feedback_file in feedback_dir.glob("feedback_*.jsonl"):
            with open(feedback_file) as f:
                for line in f:
                    feedback = json.loads(line)
                    total_feedback += 1
                    total_rating += feedback["rating"]
                    if feedback["rating"] > 0:
                        positive_ratings += 1

        average_rating = total_rating / total_feedback if total_feedback > 0 else 0
        positive_ratio = positive_ratings / total_feedback if total_feedback > 0 else 0

        return {
            "total_feedback": total_feedback,
            "average_rating": average_rating,
            "positive_ratio": positive_ratio,
        }

    except BaseAppException:
        # Let service-level exceptions bubble up to centralized error handler
        raise
    except Exception as e:
        logger.error(f"Error getting feedback stats: {e!s}", exc_info=True)
        raise BaseAppException(
            detail="An error occurred while retrieving feedback statistics",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_STATS_FAILED",
        ) from e


@router.post("/feedback/explanation", response_model=Dict[str, Any])
async def submit_feedback_explanation(
    request: Request,
    explanation_data: Dict[str, Any],
):
    """Submit explanation for negative feedback.

    This endpoint receives explanations about why an answer was unhelpful.
    It updates the existing feedback with the explanation and categorizes issues.
    """
    try:
        feedback_service = get_feedback_service(request)

        # Extract required fields
        message_id = explanation_data.get("message_id")
        explanation = explanation_data.get("explanation")

        if message_id is None or not explanation:
            raise BaseAppException(
                detail="Missing required fields: message_id and explanation are required",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="MISSING_REQUIRED_FIELDS",
            )

        # Extract any specific issues mentioned by the user
        user_provided_issues = explanation_data.get("issues", [])

        # Analyze explanation text for common issues ONLY if no specific issues provided by user
        detected_issues_from_text = []
        if explanation and not user_provided_issues:
            detected_issues_from_text = await feedback_service.analyze_feedback_text(
                explanation
            )

        # Combine user-provided issues and detected issues. Prioritize user-provided ones.
        all_issues_to_pass = list(user_provided_issues)
        for detected_issue in detected_issues_from_text:
            if detected_issue not in all_issues_to_pass:
                all_issues_to_pass.append(detected_issue)

        success = await feedback_service.update_feedback_entry(
            message_id=message_id, explanation=explanation, issues=all_issues_to_pass
        )

        if not success:
            raise BaseAppException(
                detail="Feedback entry not found or update failed",
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="FEEDBACK_NOT_FOUND",
            )

        return {
            "success": True,
            "message": "Feedback explanation received",
            "issues": all_issues_to_pass,
        }

    except BaseAppException:
        # Let service-level exceptions bubble up to centralized error handler
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback explanation: {e!s}", exc_info=True)
        raise BaseAppException(
            detail="An error occurred while submitting feedback explanation",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FEEDBACK_EXPLANATION_FAILED",
        ) from e
