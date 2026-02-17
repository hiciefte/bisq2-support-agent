"""
User-facing polling endpoint for escalation responses.
"""

import logging
import re

from app.channels.plugins.web.identity import derive_web_user_context
from app.core.config import get_settings
from app.models.escalation import (
    EscalationStatus,
    RateStaffAnswerRequest,
    UserPollResponse,
)
from app.routes.admin.escalations import get_escalation_service
from app.services.escalation.feedback_orchestrator import StaffRatingSignal
from app.services.escalation.rating_token import (
    generate_rating_token,
    verify_rating_token,
)
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

# Setup logging
logger = logging.getLogger(__name__)

# Create public router (no authentication required)
router = APIRouter()

# Message ID pattern: optional channel prefix + UUID v4
# Examples: "160541ae-..." (plain UUID) or "web_160541ae-..." (channel-prefixed)
MESSAGE_ID_PATTERN = re.compile(
    r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _derive_rater_id(request: Request) -> str:
    """Derive stable anonymous rater identity for token binding."""
    user_id, _ = derive_web_user_context(request)
    return user_id


def _get_rating_signing_key(settings) -> str:
    key = (getattr(settings, "ESCALATION_RATING_TOKEN_SECRET", "") or "").strip()
    if key:
        return key
    # Backward-compatible fallback in test/dev environments.
    return settings.ADMIN_API_KEY


def _build_rate_token_for_escalation(
    escalation,
    message_id: str,
    rater_id: str,
    signing_key: str,
    settings,
) -> str | None:
    if not escalation.staff_answer or not signing_key:
        return None
    return generate_rating_token(
        message_id=message_id,
        rater_id=rater_id,
        signing_key=signing_key,
        ttl_seconds=getattr(settings, "ESCALATION_RATING_TOKEN_TTL_SECONDS", 3600),
    )


@router.get("/escalations/{message_id}/response", response_model=UserPollResponse)
async def poll_escalation_response(
    request: Request,
    message_id: str = Path(
        ...,
        description="Message ID from the original question (UUID with optional channel prefix)",
        pattern=r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    service=Depends(get_escalation_service),
    settings=Depends(get_settings),
) -> UserPollResponse:
    """Poll for escalation response by message ID.

    Public endpoint - no authentication required.

    Args:
        message_id: UUID from the original question
        service: Escalation service dependency

    Returns:
        UserPollResponse with status and optional staff_answer

    Raises:
        HTTPException: 404 if message_id not found, 422 if invalid UUID
    """
    logger.debug(f"User polling for escalation response: {message_id}")

    try:
        signing_key = _get_rating_signing_key(settings)
        rater_id = _derive_rater_id(request)

        # Get escalation by message_id
        escalation = await service.repository.get_by_message_id(message_id)

        if not escalation:
            logger.debug(f"Message ID not found: {message_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"status": "not_found"},
            )

        # Check status and return appropriate response
        if escalation.status == EscalationStatus.PENDING:
            return UserPollResponse(
                status="pending",
                staff_answer=None,
                responded_at=None,
                resolution=None,
                closed_at=None,
            )
        elif escalation.status == EscalationStatus.IN_REVIEW:
            return UserPollResponse(
                status="pending",
                staff_answer=None,
                responded_at=None,
                resolution=None,
                closed_at=None,
            )
        elif escalation.status == EscalationStatus.RESPONDED:
            rate_token = _build_rate_token_for_escalation(
                escalation=escalation,
                message_id=message_id,
                rater_id=rater_id,
                signing_key=signing_key,
                settings=settings,
            )
            return UserPollResponse(
                status="resolved",
                staff_answer=escalation.staff_answer,
                responded_at=escalation.responded_at,
                resolution="responded",
                closed_at=None,
                staff_answer_rating=escalation.staff_answer_rating,
                rate_token=rate_token,
            )
        elif escalation.status == EscalationStatus.CLOSED:
            rate_token = _build_rate_token_for_escalation(
                escalation=escalation,
                message_id=message_id,
                rater_id=rater_id,
                signing_key=signing_key,
                settings=settings,
            )
            return UserPollResponse(
                status="resolved",
                staff_answer=escalation.staff_answer,
                responded_at=escalation.responded_at,
                resolution="closed",
                closed_at=escalation.closed_at,
                staff_answer_rating=escalation.staff_answer_rating,
                rate_token=rate_token,
            )
        else:
            # Unknown status, return pending to be safe
            return UserPollResponse(
                status="pending",
                staff_answer=None,
                responded_at=None,
                resolution=None,
                closed_at=None,
            )

    except HTTPException:
        # Re-raise HTTP exceptions without wrapping
        raise
    except Exception as e:
        logger.error(
            f"Failed to poll escalation response for {message_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve escalation status",
        ) from e


@router.post(
    "/escalations/{message_id}/rate",
    response_model=UserPollResponse,
)
async def rate_staff_answer(
    body: RateStaffAnswerRequest,
    request: Request,
    message_id: str = Path(
        ...,
        description="Message ID from the original question",
        pattern=r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    service=Depends(get_escalation_service),
    settings=Depends(get_settings),
) -> UserPollResponse:
    """Rate a staff answer as helpful or unhelpful.

    Public endpoint - no authentication required. Idempotent: re-rating overwrites.

    Returns:
        Updated UserPollResponse on success.

    Raises:
        HTTPException: 404 if message_id not found,
                       400 if escalation has no staff_answer yet.
    """
    try:
        escalation = await service.repository.get_by_message_id(message_id)

        if not escalation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escalation not found",
            )

        trusted = False
        rating_token_jti = None
        if body.rate_token:
            payload = verify_rating_token(
                token=body.rate_token,
                message_id=message_id,
                rater_id=_derive_rater_id(request),
                signing_key=_get_rating_signing_key(settings),
            )
            if payload is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired rating token",
                )
            trusted = True
            rating_token_jti = payload.jti

        updated = await service.repository.update_rating(message_id, body.rating)

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot rate: no staff answer yet",
            )

        if trusted and rating_token_jti:
            if not await service.repository.consume_rating_token_jti(
                message_id=message_id,
                token_jti=rating_token_jti,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Rating token already used",
                )

        if (
            trusted
            and getattr(service, "feedback_orchestrator", None) is not None
            and escalation is not None
        ):
            try:
                signal = StaffRatingSignal(
                    message_id=message_id,
                    escalation_id=escalation.id,
                    rater_id=_derive_rater_id(request),
                    confidence_score=escalation.confidence_score,
                    edit_distance=escalation.edit_distance or 0.0,
                    user_rating=body.rating,
                    routing_action=escalation.routing_action,
                    channel=escalation.channel,
                    trusted=True,
                    sources=escalation.sources,
                )
                service.feedback_orchestrator.record_user_rating(signal)
            except Exception:
                logger.exception(
                    "Feedback orchestrator failure for message %s", message_id
                )

        return UserPollResponse(
            status="resolved",
            staff_answer=escalation.staff_answer,
            responded_at=escalation.responded_at,
            resolution=escalation.status.value,
            closed_at=escalation.closed_at,
            staff_answer_rating=body.rating,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to rate staff answer for {message_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit rating",
        ) from e
