import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.channels.plugins.web.identity import derive_web_user_context
from app.channels.reactions import ReactionEvent, ReactionRating
from app.core.config import get_settings
from app.core.exceptions import BaseAppException
from app.models.feedback import ReactionSubmitRequest
from app.services.feedback_service import get_feedback_service
from fastapi import APIRouter, Request, status

router = APIRouter()
logger = logging.getLogger(__name__)

_FEEDBACK_EXPLANATION_RATE_LIMIT = 5
_FEEDBACK_EXPLANATION_RATE_WINDOW_SECONDS = 300.0
_feedback_explanation_attempts: dict[str, list[float]] = {}


def reset_feedback_explanation_rate_limiter() -> None:
    """Clear feedback explanation rate-limit state for tests."""
    _feedback_explanation_attempts.clear()


def _allow_feedback_explanation(user_id: str) -> bool:
    now = time.monotonic()
    cutoff = now - _FEEDBACK_EXPLANATION_RATE_WINDOW_SECONDS
    recent = [
        timestamp
        for timestamp in _feedback_explanation_attempts.get(user_id, [])
        if timestamp >= cutoff
    ]
    if len(recent) >= _FEEDBACK_EXPLANATION_RATE_LIMIT:
        _feedback_explanation_attempts[user_id] = recent
        return False
    recent.append(now)
    _feedback_explanation_attempts[user_id] = recent
    return True


@router.post("/feedback/react")
async def submit_reaction(request: Request, reaction: ReactionSubmitRequest):
    """Submit reaction feedback via unified ReactionProcessor pipeline."""
    processor = getattr(request.app.state, "reaction_processor", None)
    if not processor:
        raise BaseAppException(
            detail="Reaction processor not available",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="REACTION_PROCESSOR_UNAVAILABLE",
        )

    user_id, _ = derive_web_user_context(request)

    event = ReactionEvent(
        channel_id="web",  # SECURITY: forced
        external_message_id=reaction.message_id,
        reactor_id=user_id,
        rating=(
            ReactionRating.POSITIVE if reaction.rating == 1 else ReactionRating.NEGATIVE
        ),
        raw_reaction="thumbs_up" if reaction.rating == 1 else "thumbs_down",
        timestamp=datetime.now(timezone.utc),
    )

    result = await processor.process(event)
    if not result:
        raise BaseAppException(
            detail="Message not tracked or expired",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="MESSAGE_NOT_TRACKED",
        )

    return {
        "success": True,
        "needs_feedback_followup": reaction.rating == 0,
        "escalation_created": result.escalation_created,
        "escalation_message_id": result.escalation_message_id,
    }


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

    Channel-agnostic: works with any message_id format (web UUID,
    Matrix event_id, Bisq2 hex). New channels only need UI to collect
    explanations and POST here.

    This endpoint receives explanations about why an answer was unhelpful.
    It updates the existing feedback with the explanation and categorizes issues.
    """
    try:
        feedback_service = get_feedback_service(request)
        user_id, _ = derive_web_user_context(request)

        if not _allow_feedback_explanation(user_id):
            raise BaseAppException(
                detail="Too many feedback explanation attempts",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                error_code="FEEDBACK_EXPLANATION_RATE_LIMITED",
            )

        # Extract required fields
        message_id = str(explanation_data.get("message_id") or "").strip()
        explanation = str(explanation_data.get("explanation") or "").strip()

        if not message_id or not explanation:
            raise BaseAppException(
                detail="Missing required fields: message_id and explanation are required",
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="MISSING_REQUIRED_FIELDS",
            )

        processor = getattr(request.app.state, "reaction_processor", None)
        if processor is None or not hasattr(processor, "hash_reactor_identity"):
            raise BaseAppException(
                detail="Reaction processor not available",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="REACTION_PROCESSOR_UNAVAILABLE",
            )

        reactor_hash = processor.hash_reactor_identity("web", user_id)
        active_rating = feedback_service.repository.get_active_reaction_rating(
            "web", message_id, reactor_hash
        )
        if active_rating != int(ReactionRating.NEGATIVE):
            raise BaseAppException(
                detail="Feedback entry not found or update failed",
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="FEEDBACK_NOT_FOUND",
            )

        # Extract any specific issues mentioned by the user
        raw_issues = explanation_data.get("issues", [])
        user_provided_issues = [
            str(issue).strip()
            for issue in raw_issues
            if isinstance(issue, str) and str(issue).strip()
        ][:20]

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
