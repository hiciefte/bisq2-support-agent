"""
Admin Similar FAQ Review Queue routes for the Bisq Support API (Phase 7.1.5).

Endpoints for managing auto-extracted FAQs that are semantically similar
to existing FAQs, allowing admins to approve, merge, or dismiss.
"""

import logging
from typing import Optional

from app.core.config import get_settings
from app.core.exceptions import BaseAppException
from app.core.security import verify_admin_access
from app.models.faq import FAQItem
from app.models.similar_faq_candidate import (
    DismissRequest,
    MergeRequest,
    SimilarFaqCandidateListResponse,
)
from app.services.faq.similar_faq_repository import SimilarFaqRepository
from app.services.faq_service import FAQService
from fastapi import APIRouter, Depends, HTTPException, Request, status

# Setup logging
logger = logging.getLogger(__name__)

# Create admin router with authentication dependencies
router = APIRouter(
    prefix="/admin/similar-faqs",
    tags=["Admin Similar FAQs"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
        404: {"description": "Candidate not found"},
        409: {"description": "Conflict - Candidate already resolved"},
    },
)

# Initialize settings and services
settings = get_settings()
_repository: Optional[SimilarFaqRepository] = None
_faq_service: Optional[FAQService] = None


def get_faq_service(request: Request) -> FAQService:
    """Get the FAQ service instance.

    Checks app state first for test overrides, then uses singleton.
    """
    global _faq_service

    # Check for test override in app state
    if hasattr(request.app.state, "faq_service"):
        return request.app.state.faq_service

    # Initialize singleton if needed
    if _faq_service is None:
        _faq_service = FAQService(settings=settings)

    return _faq_service


def get_similar_faq_repository(request: Request) -> SimilarFaqRepository:
    """Get the similar FAQ repository instance.

    Checks app state first for test overrides, then uses singleton.
    """
    global _repository

    # Check for test override in app state
    if hasattr(request.app.state, "similar_faq_repository"):
        return request.app.state.similar_faq_repository

    # Initialize singleton if needed
    if _repository is None:
        db_path = settings.SIMILAR_FAQ_DB_PATH or "data/similar_faqs.db"
        _repository = SimilarFaqRepository(db_path)

    return _repository


@router.get("/pending", response_model=SimilarFaqCandidateListResponse)
async def get_pending_candidates(
    request: Request,
    repository: SimilarFaqRepository = Depends(get_similar_faq_repository),
):
    """Get all pending similar FAQ candidates for admin review.

    Returns a list of auto-extracted FAQs that are semantically similar
    to existing FAQs and await admin action.

    Returns:
        SimilarFaqCandidateListResponse: List of pending candidates with
        matched FAQ details for side-by-side comparison.
    """
    logger.info("Admin request to fetch pending similar FAQ candidates")

    try:
        result = repository.get_pending_candidates()
        logger.info(f"Returning {result.total} pending candidates")
        return result
    except Exception as e:
        logger.exception("Failed to fetch pending candidates")
        raise BaseAppException(
            detail="Failed to fetch pending candidates",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="SIMILAR_FAQ_FETCH_FAILED",
        ) from e


@router.post("/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str,
    request: Request,
    repository: SimilarFaqRepository = Depends(get_similar_faq_repository),
):
    """Approve a similar FAQ candidate as a new FAQ.

    Marks the candidate as approved. The approved FAQ will be
    added to the knowledge base as a new, verified entry.

    Args:
        candidate_id: UUID of the candidate to approve

    Returns:
        dict: Success confirmation

    Raises:
        HTTPException 404: If candidate not found
        HTTPException 409: If candidate already resolved
    """
    logger.info(f"Admin request to approve candidate: {candidate_id}")

    try:
        # Get admin identifier (could be enhanced to get from auth context)
        resolved_by = "admin"

        result = repository.approve_candidate(candidate_id, resolved_by)

        if result:
            logger.info(f"Candidate {candidate_id} approved successfully")
            return {"success": True, "candidate_id": candidate_id}
        else:
            # Check if candidate exists to differentiate 404 vs 409
            candidate = repository.get_candidate_by_id(candidate_id)
            if candidate is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Candidate {candidate_id} not found",
                )
            else:
                # Candidate exists but already resolved
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Candidate {candidate_id} is already resolved (status: {candidate.status})",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to approve candidate {candidate_id}")
        raise BaseAppException(
            detail="Failed to approve candidate",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="SIMILAR_FAQ_APPROVE_FAILED",
        ) from e


@router.post("/{candidate_id}/merge")
async def merge_candidate(
    candidate_id: str,
    merge_request: MergeRequest,
    request: Request,
    repository: SimilarFaqRepository = Depends(get_similar_faq_repository),
    faq_service: FAQService = Depends(get_faq_service),
):
    """Merge a similar FAQ candidate into an existing FAQ.

    Actually updates the matched FAQ content and marks the candidate as merged.
    The mode determines how the content is integrated:
    - replace: Overwrite existing FAQ answer with extracted answer
    - append: Add extracted answer to existing FAQ answer

    Args:
        candidate_id: UUID of the candidate to merge
        merge_request: Contains merge mode (replace/append)

    Returns:
        dict: Success confirmation with merge mode and updated FAQ ID

    Raises:
        HTTPException 404: If candidate not found or matched FAQ not found
        HTTPException 409: If candidate already resolved
    """
    logger.info(
        f"Admin request to merge candidate: {candidate_id} (mode: {merge_request.mode})"
    )

    try:
        # First get the candidate to access the extracted content and matched FAQ ID
        candidate = repository.get_candidate_by_id(candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate {candidate_id} not found",
            )

        # Check if already resolved
        if candidate.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Candidate {candidate_id} is already resolved (status: {candidate.status})",
            )

        # Get the matched FAQ to update
        matched_faq_id = str(candidate.matched_faq_id)
        all_faqs = faq_service.get_all_faqs()
        matched_faq = next((faq for faq in all_faqs if faq.id == matched_faq_id), None)

        if matched_faq is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Matched FAQ {matched_faq_id} not found",
            )

        # Prepare the merged content based on mode
        if merge_request.mode == "replace":
            # Replace: Use extracted answer entirely
            new_answer = candidate.extracted_answer
            new_question = candidate.extracted_question
        else:
            # Append: Add extracted answer to existing answer
            new_answer = f"{matched_faq.answer}\n\n---\n\n{candidate.extracted_answer}"
            new_question = matched_faq.question  # Keep original question

        # Create updated FAQ item
        updated_faq_item = FAQItem(
            question=new_question,
            answer=new_answer,
            category=matched_faq.category,
            source=matched_faq.source,
            verified=matched_faq.verified,
            protocol=matched_faq.protocol,
        )

        # Update the FAQ (this triggers vector store rebuild notification)
        updated_faq = faq_service.update_faq(matched_faq_id, updated_faq_item)
        if updated_faq is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update matched FAQ",
            )

        # Mark the candidate as merged
        resolved_by = "admin"
        result = repository.merge_candidate(
            candidate_id, resolved_by, merge_request.mode
        )

        if result:
            logger.info(
                f"Candidate {candidate_id} merged successfully into FAQ {matched_faq_id} "
                f"(mode: {merge_request.mode})"
            )
            return {
                "success": True,
                "candidate_id": candidate_id,
                "mode": merge_request.mode,
                "merged_faq_id": matched_faq_id,
            }
        else:
            # This shouldn't happen since we already checked status above
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Candidate {candidate_id} could not be marked as merged",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to merge candidate {candidate_id}")
        raise BaseAppException(
            detail="Failed to merge candidate",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="SIMILAR_FAQ_MERGE_FAILED",
        ) from e


@router.post("/{candidate_id}/dismiss")
async def dismiss_candidate(
    candidate_id: str,
    request: Request,
    dismiss_request: Optional[DismissRequest] = None,
    repository: SimilarFaqRepository = Depends(get_similar_faq_repository),
):
    """Dismiss a similar FAQ candidate.

    Marks the candidate as dismissed. An optional reason can be
    provided for auditing purposes.

    Args:
        candidate_id: UUID of the candidate to dismiss
        dismiss_request: Optional request body with dismissal reason

    Returns:
        dict: Success confirmation

    Raises:
        HTTPException 404: If candidate not found
        HTTPException 409: If candidate already resolved
    """
    reason = dismiss_request.reason if dismiss_request else None
    logger.info(
        f"Admin request to dismiss candidate: {candidate_id} (reason: {reason})"
    )

    try:
        resolved_by = "admin"

        result = repository.dismiss_candidate(candidate_id, resolved_by, reason)

        if result:
            logger.info(f"Candidate {candidate_id} dismissed successfully")
            return {"success": True, "candidate_id": candidate_id}
        else:
            candidate = repository.get_candidate_by_id(candidate_id)
            if candidate is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Candidate {candidate_id} not found",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Candidate {candidate_id} is already resolved (status: {candidate.status})",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to dismiss candidate {candidate_id}")
        raise BaseAppException(
            detail="Failed to dismiss candidate",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="SIMILAR_FAQ_DISMISS_FAILED",
        ) from e
