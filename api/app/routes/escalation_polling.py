"""
User-facing polling endpoint for escalation responses.
"""

import logging
import re

from app.models.escalation import (
    EscalationStatus,
    RateStaffAnswerRequest,
    UserPollResponse,
)
from app.routes.admin.escalations import get_escalation_service
from fastapi import APIRouter, Depends, HTTPException, Path, status

# Setup logging
logger = logging.getLogger(__name__)

# Create public router (no authentication required)
router = APIRouter()

# Message ID pattern: optional channel prefix + UUID v4
# Examples: "160541ae-..." (plain UUID) or "web_160541ae-..." (channel-prefixed)
MESSAGE_ID_PATTERN = re.compile(
    r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@router.get("/escalations/{message_id}/response", response_model=UserPollResponse)
async def poll_escalation_response(
    message_id: str = Path(
        ...,
        description="Message ID from the original question (UUID with optional channel prefix)",
        pattern=r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    service=Depends(get_escalation_service),
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
            return UserPollResponse(
                status="resolved",
                staff_answer=escalation.staff_answer,
                responded_at=escalation.responded_at,
                resolution="responded",
                closed_at=None,
                staff_answer_rating=escalation.staff_answer_rating,
            )
        elif escalation.status == EscalationStatus.CLOSED:
            return UserPollResponse(
                status="resolved",
                staff_answer=escalation.staff_answer,
                responded_at=escalation.responded_at,
                resolution="closed",
                closed_at=escalation.closed_at,
                staff_answer_rating=escalation.staff_answer_rating,
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
    message_id: str = Path(
        ...,
        description="Message ID from the original question",
        pattern=r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
    service=Depends(get_escalation_service),
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

        updated = await service.repository.update_rating(message_id, body.rating)

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot rate: no staff answer yet",
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
