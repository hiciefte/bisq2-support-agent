"""API routes for moderator review queue.

These endpoints allow moderators to review, approve, reject, or modify
pending responses before they are sent to users.
"""

import logging
from typing import Optional

from app.core.config import Settings, get_settings
from app.core.security import verify_admin_access
from app.services.pending_response_service import PendingResponseService
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette import status as http_status

router = APIRouter(
    prefix="/admin",
    tags=["Admin Queue"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)
logger = logging.getLogger(__name__)


class ReviewAction(BaseModel):
    """Model for review action request."""

    status: str  # approved, rejected, modified
    reviewed_by: Optional[str] = None
    modified_answer: Optional[str] = None
    review_notes: Optional[str] = None


@router.get("/queue")
async def get_pending_queue(
    request: Request,
    status: str = "pending",
    priority: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    settings: Settings = Depends(get_settings),
):
    """Get pending responses in the review queue.

    Args:
        status: Filter by status (pending, approved, rejected, modified)
        priority: Filter by priority (high, normal)
        limit: Maximum number of responses
        offset: Pagination offset

    Returns:
        List of pending responses with pagination info
    """
    try:
        pending_service = PendingResponseService(settings)
        result = await pending_service.get_pending_responses(
            status=status,
            priority=priority,
            limit=limit,
            offset=offset,
        )
        return result

    except Exception as e:
        logger.error(f"Error getting pending queue: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get pending queue",
        )


@router.get("/queue/stats")
async def get_queue_stats(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Get statistics about the pending response queue.

    Returns:
        Queue statistics including counts by status and priority
    """
    try:
        pending_service = PendingResponseService(settings)
        stats = await pending_service.get_queue_stats()
        return stats

    except Exception as e:
        logger.error(f"Error getting queue stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get queue statistics",
        )


@router.get("/queue/{response_id}")
async def get_pending_response(
    response_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Get a specific pending response by ID.

    Args:
        response_id: The response ID

    Returns:
        The pending response details
    """
    try:
        pending_service = PendingResponseService(settings)
        response = await pending_service.get_response_by_id(response_id)

        if not response:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting response {response_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get pending response",
        )


@router.post("/queue/{response_id}/review")
async def review_response(
    response_id: str,
    action: ReviewAction,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Review and update a pending response.

    Args:
        response_id: The response ID
        action: The review action (approve, reject, modify)

    Returns:
        Success status
    """
    # Validate status
    valid_statuses = ["approved", "rejected", "modified"]
    if action.status not in valid_statuses:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {valid_statuses}",
        )

    # Modified status requires modified_answer
    if action.status == "modified" and not action.modified_answer:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Modified answer is required when status is 'modified'",
        )

    try:
        pending_service = PendingResponseService(settings)
        success = await pending_service.update_response(
            response_id=response_id,
            status=action.status,
            reviewed_by=action.reviewed_by,
            modified_answer=action.modified_answer,
            review_notes=action.review_notes,
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        return {"success": True, "message": f"Response {action.status} successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reviewing response {response_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to review response",
        )


@router.delete("/queue/{response_id}")
async def delete_pending_response(
    response_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Delete a pending response from the queue.

    Args:
        response_id: The response ID to delete

    Returns:
        Success status
    """
    try:
        pending_service = PendingResponseService(settings)
        success = await pending_service.delete_response(response_id)

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        return {"success": True, "message": "Response deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting response {response_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete response",
        )
