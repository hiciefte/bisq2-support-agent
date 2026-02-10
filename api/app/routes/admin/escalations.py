"""
Admin escalation management routes for the Bisq Support API.
"""

import logging
from typing import Any, Dict, Optional

from app.core.security import verify_admin_access
from app.models.escalation import (
    ClaimRequest,
    Escalation,
    EscalationAlreadyClaimedError,
    EscalationCountsResponse,
    EscalationListResponse,
    EscalationNotFoundError,
    EscalationNotRespondedError,
    EscalationPriority,
    EscalationStatus,
    GenerateFAQRequest,
    RespondRequest,
)
from fastapi import APIRouter, Depends, HTTPException, status

# Setup logging
logger = logging.getLogger(__name__)

# Create admin router with authentication dependencies
router = APIRouter(
    prefix="/admin/escalations",
    tags=["Admin Escalations"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)

# Module-level service holder (lazy initialization pattern)
_escalation_service = None


async def get_escalation_service():
    """Get or create the escalation service singleton.

    Returns:
        EscalationService instance
    """
    global _escalation_service
    if _escalation_service is None:
        from app.core.config import get_settings
        from app.services.escalation.escalation_repository import EscalationRepository
        from app.services.escalation.escalation_service import EscalationService

        settings = get_settings()
        repo = EscalationRepository(
            db_path=(
                settings.ESCALATION_DB_PATH
                if hasattr(settings, "ESCALATION_DB_PATH")
                else "data/escalations.db"
            )
        )
        await repo.initialize()
        _escalation_service = EscalationService(
            repository=repo,
            response_delivery=None,  # Will be wired in E08
            faq_service=None,  # Will be wired later
            learning_engine=None,  # Will be wired later
            settings=settings,
        )
    return _escalation_service


@router.get("", response_model=EscalationListResponse)
async def list_escalations(
    status: Optional[EscalationStatus] = None,
    channel: Optional[str] = None,
    priority: Optional[EscalationPriority] = None,
    limit: int = 20,
    offset: int = 0,
    service=Depends(get_escalation_service),
) -> EscalationListResponse:
    """List escalations with optional filters.

    Args:
        status: Filter by escalation status
        channel: Filter by channel identifier
        priority: Filter by priority level
        limit: Maximum number of results (1-100)
        offset: Number of results to skip
        service: Escalation service dependency

    Returns:
        EscalationListResponse with paginated results
    """
    logger.info(
        f"Admin request to list escalations: status={status}, channel={channel}, limit={limit}, offset={offset}"
    )

    try:
        result = await service.list_escalations(
            status=status,
            channel=channel,
            priority=priority,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to list escalations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to list escalations",
        ) from e


@router.get("/counts", response_model=EscalationCountsResponse)
async def get_escalation_counts(
    service=Depends(get_escalation_service),
) -> EscalationCountsResponse:
    """Get counts of escalations by status.

    Args:
        service: Escalation service dependency

    Returns:
        EscalationCountsResponse with counts by status
    """
    logger.info("Admin request to get escalation counts")

    try:
        counts = await service.get_escalation_counts()
        return counts
    except Exception as e:
        logger.error(f"Failed to get escalation counts: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get escalation counts",
        ) from e


@router.get("/{escalation_id}", response_model=Escalation)
async def get_escalation(
    escalation_id: int,
    service=Depends(get_escalation_service),
) -> Escalation:
    """Get a single escalation by ID.

    Args:
        escalation_id: Escalation ID
        service: Escalation service dependency

    Returns:
        Escalation record

    Raises:
        HTTPException: 404 if escalation not found
    """
    logger.info(f"Admin request to get escalation: {escalation_id}")

    try:
        escalation = await service.repository.get_by_id(escalation_id)
        if not escalation:
            raise EscalationNotFoundError(f"Escalation {escalation_id} not found")
        return escalation
    except EscalationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Escalation {escalation_id} not found",
        )
    except Exception as e:
        logger.error(f"Failed to get escalation {escalation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get escalation",
        ) from e


@router.post("/{escalation_id}/claim", response_model=Escalation)
async def claim_escalation(
    escalation_id: int,
    request: ClaimRequest,
    service=Depends(get_escalation_service),
) -> Escalation:
    """Claim an escalation for review.

    Args:
        escalation_id: Escalation ID
        request: Claim request with staff_id
        service: Escalation service dependency

    Returns:
        Updated escalation record

    Raises:
        HTTPException: 404 if not found, 409 if already claimed
    """
    logger.info(
        f"Admin request to claim escalation {escalation_id} by {request.staff_id}"
    )

    try:
        escalation = await service.claim_escalation(escalation_id, request.staff_id)
        logger.info(f"Escalation {escalation_id} claimed by {request.staff_id}")
        return escalation
    except EscalationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Escalation {escalation_id} not found",
        )
    except EscalationAlreadyClaimedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Escalation {escalation_id} is already claimed",
        )
    except Exception as e:
        logger.error(f"Failed to claim escalation {escalation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to claim escalation",
        ) from e


@router.post("/{escalation_id}/respond", response_model=Escalation)
async def respond_to_escalation(
    escalation_id: int,
    request: RespondRequest,
    service=Depends(get_escalation_service),
) -> Escalation:
    """Provide a staff answer to an escalation.

    Args:
        escalation_id: Escalation ID
        request: Response request with staff_answer and staff_id
        service: Escalation service dependency

    Returns:
        Updated escalation record

    Raises:
        HTTPException: 404 if not found
    """
    logger.info(
        f"Admin request to respond to escalation {escalation_id} by {request.staff_id}"
    )

    try:
        escalation = await service.respond_to_escalation(
            escalation_id, request.staff_answer, request.staff_id
        )
        logger.info(f"Escalation {escalation_id} responded by {request.staff_id}")
        return escalation
    except EscalationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Escalation {escalation_id} not found",
        )
    except Exception as e:
        logger.error(
            f"Failed to respond to escalation {escalation_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to respond to escalation",
        ) from e


@router.post("/{escalation_id}/generate-faq", response_model=Dict[str, Any])
async def generate_faq(
    escalation_id: int,
    request: GenerateFAQRequest,
    service=Depends(get_escalation_service),
) -> Dict[str, Any]:
    """Generate an FAQ from an escalation.

    Args:
        escalation_id: Escalation ID
        request: FAQ generation request
        service: Escalation service dependency

    Returns:
        Dictionary with faq_id and status

    Raises:
        HTTPException: 400 if escalation not responded, 404 if not found
    """
    logger.info(f"Admin request to generate FAQ from escalation {escalation_id}")

    try:
        result = await service.generate_faq_from_escalation(
            escalation_id,
            request.question,
            request.answer,
            request.category,
            request.protocol,
        )
        logger.info(f"FAQ generated from escalation {escalation_id}: {result}")
        return result
    except EscalationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Escalation {escalation_id} not found",
        )
    except EscalationNotRespondedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Escalation {escalation_id} has not been responded to yet",
        )
    except Exception as e:
        logger.error(
            f"Failed to generate FAQ from escalation {escalation_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate FAQ",
        ) from e


@router.post("/{escalation_id}/close", response_model=Escalation)
async def close_escalation(
    escalation_id: int,
    service=Depends(get_escalation_service),
) -> Escalation:
    """Close an escalation.

    Args:
        escalation_id: Escalation ID
        service: Escalation service dependency

    Returns:
        Updated escalation record

    Raises:
        HTTPException: 404 if not found
    """
    logger.info(f"Admin request to close escalation {escalation_id}")

    try:
        escalation = await service.close_escalation(escalation_id)
        logger.info(f"Escalation {escalation_id} closed")
        return escalation
    except EscalationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Escalation {escalation_id} not found",
        )
    except Exception as e:
        logger.error(f"Failed to close escalation {escalation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to close escalation",
        ) from e
