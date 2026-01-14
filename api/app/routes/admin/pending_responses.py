"""API routes for pending moderator review responses.

These endpoints provide a simplified interface for the frontend moderator
review queue, matching the expected API contract.
"""

import logging
from typing import Any, Dict, Optional

from app.core.config import Settings, get_settings
from app.core.security import verify_admin_access
from app.services.pending_response_service import PendingResponseService
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette import status as http_status

router = APIRouter(
    prefix="/admin/pending",
    tags=["Admin Pending Responses"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)

# Separate router for test endpoints (no auth required)
test_router = APIRouter(
    prefix="/admin/pending",
    tags=["Admin Pending Responses - Testing"],
)

logger = logging.getLogger(__name__)


class EditAnswerRequest(BaseModel):
    """Request model for editing an answer."""

    answer: str


def _transform_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """Transform backend response format to frontend expected format.

    Args:
        response: Backend response dict

    Returns:
        Frontend-compatible response dict
    """
    # Extract detected_version from metadata to top level
    detected_version = (
        response.get("metadata", {}).get("detected_version", "General")
        if response.get("metadata")
        else "General"
    )

    return {
        "id": response.get("id"),
        "question": response.get("question"),
        "answer": response.get("answer"),
        "confidence": response.get("confidence", 0.0),
        "detected_version": detected_version,
        "sources": response.get("sources", []),
        "created_at": response.get("created_at"),
    }


@router.get("")
async def get_pending_responses(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Get all pending responses awaiting moderator review.

    Frontend expects:
    - List of responses with id, question, answer, confidence, detected_version, sources, created_at
    - Only responses with status="pending"

    Returns:
        JSON with responses array and metadata
    """
    try:
        pending_service = PendingResponseService(settings)
        result = await pending_service.get_pending_responses(
            status="pending",
            limit=100,  # Frontend doesn't paginate, get reasonable limit
            offset=0,
        )

        # Transform responses to frontend expected format
        transformed_responses = [
            _transform_response(r) for r in result.get("responses", [])
        ]

        return {
            "responses": transformed_responses,
            "total": result.get("total", 0),
        }

    except Exception as e:
        logger.error(f"Error getting pending responses: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get pending responses",
        )


@router.post("/{response_id}/approve")
async def approve_response(
    response_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Approve a pending response and mark it for sending.

    Args:
        response_id: The response ID to approve

    Returns:
        Success status
    """
    try:
        pending_service = PendingResponseService(settings)
        success = await pending_service.update_response(
            response_id=response_id,
            status="approved",
            reviewed_by=None,  # TODO: Extract from auth token
            modified_answer=None,
            review_notes=None,
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        return {
            "success": True,
            "message": "Response approved successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving response {response_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve response",
        )


@router.post("/{response_id}/reject")
async def reject_response(
    response_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Reject a pending response.

    Args:
        response_id: The response ID to reject

    Returns:
        Success status
    """
    try:
        pending_service = PendingResponseService(settings)
        success = await pending_service.update_response(
            response_id=response_id,
            status="rejected",
            reviewed_by=None,  # TODO: Extract from auth token
            modified_answer=None,
            review_notes=None,
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        return {
            "success": True,
            "message": "Response rejected successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting response {response_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject response",
        )


@router.post("/{response_id}/edit")
async def edit_and_approve_response(
    response_id: str,
    edit_request: EditAnswerRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    """Edit an answer and approve it for sending.

    Args:
        response_id: The response ID to edit
        edit_request: Request with edited answer

    Returns:
        Success status
    """
    # Validate answer is not empty
    if not edit_request.answer or not edit_request.answer.strip():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Answer cannot be empty",
        )

    try:
        pending_service = PendingResponseService(settings)
        success = await pending_service.update_response(
            response_id=response_id,
            status="modified",
            reviewed_by=None,  # TODO: Extract from auth token
            modified_answer=edit_request.answer.strip(),
            review_notes=None,
        )

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        return {
            "success": True,
            "message": "Answer saved and approved successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing response {response_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to edit response",
        )


@test_router.post("/test/create-response")
async def create_test_response(
    question: str = Query(default="How do I make my first trade on Bisq?"),
    answer: str = Query(default="To make your first trade, open the app and..."),
    confidence: float = Query(default=0.75, ge=0.0, le=1.0),
    detected_version: Optional[str] = Query(default="Bisq 2"),
    settings: Settings = Depends(get_settings),
) -> Dict[str, str]:
    """Create a test pending response (for E2E testing only).

    This endpoint creates a pending response entry for testing the
    moderator review queue. Only available in non-production environments.

    Args:
        question: Test question text
        answer: Test answer text
        confidence: Confidence score (0-1)
        detected_version: Version string (Bisq 1, Bisq 2, General)

    Returns:
        Success message with response ID
    """
    # Only allow in non-production environments
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Test endpoint not available in production",
        )

    try:
        pending_service = PendingResponseService(settings)

        # Determine routing action based on confidence
        if confidence >= 0.7:
            routing_action = "queue_medium"
        else:
            routing_action = "queue_low"

        # Queue the test response
        response_id = await pending_service.queue_response(
            question=question,
            answer=answer,
            confidence=confidence,
            routing_action=routing_action,
            sources=[
                {
                    "title": "Test Source",
                    "type": "wiki",
                    "content": "Test source content for E2E testing",
                    "relevance": 0.85,
                }
            ],
            metadata={
                "detected_version": detected_version,
                "source": "e2e_test",
            },
            channel="web",
        )

        logger.info(f"Created test pending response {response_id}")
        return {
            "message": "Test response created",
            "response_id": response_id,
        }

    except Exception as e:
        logger.error(f"Error creating test response: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create test response: {e!s}",
        ) from e


@test_router.delete("/test/{response_id}")
async def delete_test_response(
    response_id: str,
    settings: Settings = Depends(get_settings),
) -> Dict[str, str]:
    """Delete a test pending response (for E2E testing cleanup).

    Only available in non-production environments.

    Args:
        response_id: The response ID to delete

    Returns:
        Success message
    """
    # Only allow in non-production environments
    if settings.ENVIRONMENT.lower() == "production":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Test endpoint not available in production",
        )

    try:
        pending_service = PendingResponseService(settings)
        success = await pending_service.delete_response(response_id)

        if not success:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Response {response_id} not found",
            )

        logger.info(f"Deleted test pending response {response_id}")
        return {"message": f"Response {response_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting test response: {e}", exc_info=True)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete test response: {e!s}",
        ) from e
