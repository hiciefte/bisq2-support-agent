"""Admin routes for auto-training pipeline management."""

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.exceptions import BaseAppException
from app.core.security import verify_admin_access
from app.services.training.unified_pipeline_service import DuplicateFAQError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Request/Response
# =============================================================================


class UnifiedCalibrationStatusResponse(BaseModel):
    """Response model for unified calibration status."""

    samples_collected: int
    samples_required: int
    is_complete: bool
    auto_approve_threshold: float
    spot_check_threshold: float


class UnifiedCandidateResponse(BaseModel):
    """Response model for a unified FAQ candidate."""

    id: int
    source: str
    source_event_id: str
    source_timestamp: str
    question_text: str
    staff_answer: str
    generated_answer: Optional[str]
    staff_sender: Optional[str]
    embedding_similarity: Optional[float]
    factual_alignment: Optional[float]
    contradiction_score: Optional[float]
    completeness: Optional[float]
    hallucination_risk: Optional[float]
    final_score: Optional[float]
    generation_confidence: Optional[float]
    llm_reasoning: Optional[str]
    routing: str
    review_status: str
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    rejection_reason: Optional[str]
    faq_id: Optional[str]
    is_calibration_sample: bool
    created_at: str
    updated_at: Optional[str]
    protocol: Optional[str] = None
    edited_staff_answer: Optional[str] = None
    category: Optional[str] = None
    generated_answer_sources: Optional[List[Dict[str, Any]]] = None


class UnifiedApproveRequest(BaseModel):
    """Request model for approving a unified candidate."""

    reviewer: str = Field(description="Reviewer username")


# P4: Allowed rejection reasons for validation
ALLOWED_REJECT_REASONS = {
    "incorrect",
    "outdated",
    "too_vague",
    "off_topic",
    "duplicate",
    "other",
}
MAX_REJECTION_REASON_LENGTH = 500
MAX_PAGE_SIZE = 100
MAX_BATCH_SIZE = 50


class UnifiedRejectRequest(BaseModel):
    """Request model for rejecting a unified candidate."""

    reviewer: str = Field(description="Reviewer username")
    reason: str = Field(description="Rejection reason")


class UpdateCandidateRequest(BaseModel):
    """Request model for updating a candidate's editable fields."""

    edited_staff_answer: Optional[str] = Field(
        default=None, description="User-edited version of the staff answer"
    )
    category: Optional[str] = Field(
        default=None,
        description="FAQ category (e.g., Trading, Wallet, Installation, Security)",
    )


class RegenerateAnswerRequest(BaseModel):
    """Request model for regenerating the RAG answer with a specific protocol."""

    protocol: str = Field(
        description="Protocol to use for RAG generation (bisq_easy, multisig_v1, musig, all)"
    )


class RateGeneratedAnswerRequest(BaseModel):
    """Request model for rating the quality of a generated answer.

    This feedback is used to train the LearningEngine to determine
    what confidence threshold should result in auto-approval.
    """

    rating: str = Field(
        description="Rating of the generated answer quality: 'good' or 'needs_improvement'"
    )
    reviewer: str = Field(description="Reviewer username")


class UndoActionRequest(BaseModel):
    """Request model for undoing a recent action (approve/reject/skip).

    This allows reviewers to undo actions within a short time window.
    """

    action_type: str = Field(
        description="Type of action to undo: 'approve', 'reject', or 'skip'"
    )
    faq_id: Optional[str] = Field(
        default=None, description="FAQ ID to delete (required for undoing approve)"
    )


class ApproveResponse(BaseModel):
    """Response model for approve operation."""

    success: bool
    faq_id: Optional[str] = None


class SimilarFAQInfo(BaseModel):
    """Information about a similar FAQ found during duplicate check."""

    id: int = Field(description="FAQ ID")
    question: str = Field(description="FAQ question text")
    answer: str = Field(description="FAQ answer text (truncated)")
    similarity: float = Field(description="Similarity score (0-1)")
    category: Optional[str] = Field(default=None, description="FAQ category")


class DuplicateFAQErrorResponse(BaseModel):
    """Response model for duplicate FAQ error (409 Conflict)."""

    error: str = Field(default="duplicate_faq", description="Error type identifier")
    message: str = Field(description="Human-readable error message")
    candidate_id: int = Field(
        description="ID of the candidate that triggered the check"
    )
    similar_faqs: List[SimilarFAQInfo] = Field(description="List of similar FAQs found")


class ActionResponse(BaseModel):
    """Response model for action operations."""

    success: bool


class BatchApproveRequest(BaseModel):
    """Request model for batch approving multiple candidates."""

    candidate_ids: List[int] = Field(description="List of candidate IDs to approve")
    reviewer: str = Field(default="admin", description="Reviewer username")


class BatchApproveResponse(BaseModel):
    """Response model for batch approve operation."""

    success: bool
    approved_count: int
    failed_ids: List[int] = Field(default_factory=list)
    created_faq_ids: List[str] = Field(default_factory=list)


class SyncResponse(BaseModel):
    """Response model for sync operations.

    Attributes:
        status: Operation status ("started", "completed", "error")
        processed: Number of items processed (for completed operations)
        message: Human-readable status message
        task_id: Background task ID (for async operations)
    """

    status: str
    processed: Optional[int] = None
    message: Optional[str] = None
    task_id: Optional[str] = None


class LearningMetricsResponse(BaseModel):
    """Response model for learning metrics."""

    current_thresholds: Dict[str, float]
    total_reviews: int
    approval_rate: float
    edit_rate: float
    rejection_rate: float
    threshold_updates: int
    avg_confidence: Optional[float] = None
    std_confidence: Optional[float] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None


class LaunchReadinessResponse(BaseModel):
    """Response model for launch readiness check."""

    is_ready: bool
    readiness_score: float
    passed_criteria: int
    total_criteria: int
    criteria: Dict[str, Any]
    recommendations: List[str]
    current_thresholds: Dict[str, float]
    metrics_summary: Dict[str, Any]
    checked_at: str


class FlaggedFAQItem(BaseModel):
    """Response model for a flagged FAQ item."""

    thread_id: int
    faq_id: str
    correction_reason: Optional[str]
    original_answer: Optional[str]
    correction_content: Optional[str]
    state: str
    flagged_at: Optional[str]


class FlaggedFAQsResponse(BaseModel):
    """Response model for GET /flagged-faqs."""

    flagged: List[FlaggedFAQItem]


class ResolveFlaggedFAQRequest(BaseModel):
    """Request model for resolving a flagged FAQ."""

    action: str = Field(
        description="Resolution action: 'update', 'confirm', or 'delete'"
    )
    reviewer: str = Field(description="Reviewer username")
    new_answer: Optional[str] = Field(
        default=None,
        description="New answer text (required for 'update' action)",
    )


class ResolveFlaggedFAQResponse(BaseModel):
    """Response model for POST /flagged-faqs/{id}/resolve."""

    status: str = Field(default="resolved")
    action: str


# =============================================================================
# Router Definition
# =============================================================================

router = APIRouter(
    prefix="/admin/training",
    tags=["Admin Training"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


# =============================================================================
# Dependency for UnifiedPipelineService
# =============================================================================


def get_pipeline_service():
    """Get UnifiedPipelineService from application state.

    Returns the unified FAQ training pipeline service that handles
    both Bisq 2 and Matrix sources.
    """
    from fastapi import Request

    def _get_service(request: Request):
        if not hasattr(request.app.state, "unified_pipeline_service"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unified pipeline service not initialized",
            )
        return request.app.state.unified_pipeline_service

    return _get_service


# =============================================================================
# Unified Pipeline Endpoints
# =============================================================================


@router.get(
    "/unified/calibration/status", response_model=UnifiedCalibrationStatusResponse
)
async def get_unified_calibration_status(
    pipeline_service=Depends(get_pipeline_service()),
):
    """Get unified calibration status.

    Returns current calibration status from the unified pipeline.
    """
    logger.info("Admin request for unified calibration status")
    try:
        status_obj = pipeline_service.get_calibration_status()
        return UnifiedCalibrationStatusResponse(
            samples_collected=status_obj.samples_collected,
            samples_required=status_obj.samples_required,
            is_complete=status_obj.is_complete,
            auto_approve_threshold=status_obj.auto_approve_threshold,
            spot_check_threshold=status_obj.spot_check_threshold,
        )
    except Exception as e:
        logger.exception("Failed to get unified calibration status")
        raise BaseAppException(
            detail="Failed to get unified calibration status",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="UNIFIED_CALIBRATION_STATUS_FAILED",
        ) from e


@router.get("/unified/queue/counts")
async def get_unified_queue_counts(
    pipeline_service=Depends(get_pipeline_service()),
):
    """Get counts for each queue in the unified pipeline."""
    logger.info("Admin request for unified queue counts")
    try:
        counts = pipeline_service.get_queue_counts()
        return counts
    except Exception as e:
        logger.exception("Failed to get unified queue counts")
        raise BaseAppException(
            detail="Failed to get unified queue counts",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="UNIFIED_QUEUE_COUNTS_FAILED",
        ) from e


@router.get("/unified/queue/current")
async def get_unified_current_item(
    routing: str = "FULL_REVIEW",
    pipeline_service=Depends(get_pipeline_service()),
):
    """Get the next item to review from unified pipeline."""
    logger.info(f"Admin request for unified current item (routing={routing})")
    try:
        candidate = pipeline_service.get_current_item(routing=routing)
        if candidate is None:
            return None
        return _candidate_to_dict(candidate)
    except Exception as e:
        logger.exception("Failed to get unified current item")
        raise BaseAppException(
            detail="Failed to get unified current item",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="UNIFIED_CURRENT_ITEM_FAILED",
        ) from e


@router.get("/unified/queue/pending")
async def get_unified_pending_reviews(
    page: int = 1,
    page_size: int = 10,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Get paginated list of unified pending reviews."""
    logger.info(f"Admin request for unified pending reviews (page={page})")

    # Validate and clamp pagination parameters
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    try:
        # Convert page/page_size to limit/offset for the service API
        offset = (page - 1) * page_size
        candidates = pipeline_service.get_pending_reviews(
            limit=page_size, offset=offset
        )

        # Get total count for pagination using efficient COUNT(*) query
        total = pipeline_service.count_pending_reviews()

        return {
            "items": [_candidate_to_dict(c) for c in candidates],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.exception("Failed to get unified pending reviews")
        raise BaseAppException(
            detail="Failed to get unified pending reviews",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="UNIFIED_PENDING_REVIEWS_FAILED",
        ) from e


@router.get("/unified/queue/batch")
async def get_batch_items(
    routing: str = "AUTO_APPROVE",
    limit: int = 10,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Get multiple items for batch review mode.

    This endpoint is designed for the batch approve feature in the AUTO_APPROVE
    queue, returning multiple candidates that can be reviewed and approved in bulk.

    Args:
        routing: Queue routing filter (default: AUTO_APPROVE)
        limit: Maximum number of items to return (default: 10, max: 50)
    """
    logger.info(f"Admin request for batch items (routing={routing}, limit={limit})")

    # Enforce limits: clamp to valid range 1..MAX_BATCH_SIZE
    limit = max(1, min(limit, MAX_BATCH_SIZE))

    try:
        candidates = pipeline_service.repository.get_pending(
            routing=routing,
            limit=limit,
        )
        return {
            "items": [_candidate_to_dict(c) for c in candidates],
            "total": len(candidates),
            "routing": routing,
        }
    except Exception as e:
        logger.exception("Failed to get batch items")
        raise BaseAppException(
            detail="Failed to get batch items",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="BATCH_ITEMS_FAILED",
        ) from e


@router.post("/candidates/{candidate_id}/approve", response_model=ApproveResponse)
async def approve_candidate(
    candidate_id: int,
    request_body: UnifiedApproveRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Approve a unified FAQ candidate and create FAQ entry."""
    logger.info(f"Admin request to approve candidate {candidate_id}")
    try:
        # Get candidate first to record generation_confidence for learning
        candidate = pipeline_service.repository.get_by_id(candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate {candidate_id} not found",
            )

        faq_id = await pipeline_service.approve_candidate(
            candidate_id=candidate_id,
            reviewer=request_body.reviewer,
        )

        # Record feedback to LearningEngine using generation_confidence (not final_score)
        learning_engine = getattr(request.app.state, "learning_engine", None)
        if learning_engine and candidate.generation_confidence is not None:
            learning_engine.record_review(
                question_id=str(candidate_id),
                confidence=candidate.generation_confidence,  # Use RAG confidence, NOT comparison score
                admin_action="approved",
                routing_action=candidate.routing,
                metadata={
                    "source": candidate.source,
                    "comparison_score": candidate.final_score,  # Keep for analysis
                    "reviewer": request_body.reviewer,
                },
            )
            logger.debug(
                f"Recorded approval to LearningEngine: candidate={candidate_id}, "
                f"generation_confidence={candidate.generation_confidence}"
            )

        return ApproveResponse(success=True, faq_id=faq_id)
    except DuplicateFAQError as e:
        # Return 409 Conflict with detailed duplicate information
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_faq",
                "message": str(e),
                "candidate_id": candidate_id,
                "similar_faqs": [
                    {
                        "id": faq.id,
                        "question": faq.question,
                        "answer": (
                            faq.answer[:200] + "..."
                            if len(faq.answer) > 200
                            else faq.answer
                        ),
                        "similarity": faq.similarity,
                        "category": getattr(faq, "category", None),
                    }
                    for faq in e.similar_faqs
                ],
            },
        ) from e
    except Exception as e:
        logger.exception(f"Failed to approve candidate {candidate_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve candidate {candidate_id}",
        ) from e


@router.post("/candidates/batch-approve", response_model=BatchApproveResponse)
async def batch_approve_candidates(
    request_body: BatchApproveRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Batch approve multiple FAQ candidates at once.

    This endpoint is optimized for the AUTO_APPROVE queue where high-confidence
    candidates can be approved in bulk for efficiency.
    """
    logger.info(
        f"Admin request to batch approve {len(request_body.candidate_ids)} candidates"
    )

    approved_count = 0
    failed_ids: List[int] = []
    created_faq_ids: List[str] = []

    learning_engine = getattr(request.app.state, "learning_engine", None)

    for candidate_id in request_body.candidate_ids:
        try:
            # Get candidate first to record generation_confidence for learning
            candidate = pipeline_service.repository.get_by_id(candidate_id)
            if candidate is None:
                logger.warning(f"Batch approve: Candidate {candidate_id} not found")
                failed_ids.append(candidate_id)
                continue

            # Skip already processed candidates
            if candidate.review_status != "pending":
                logger.warning(
                    f"Batch approve: Candidate {candidate_id} already processed "
                    f"(status: {candidate.review_status})"
                )
                failed_ids.append(candidate_id)
                continue

            faq_id = await pipeline_service.approve_candidate(
                candidate_id=candidate_id,
                reviewer=request_body.reviewer,
            )

            # Record feedback to LearningEngine
            if learning_engine and candidate.generation_confidence is not None:
                learning_engine.record_review(
                    question_id=str(candidate_id),
                    confidence=candidate.generation_confidence,
                    admin_action="approved",
                    routing_action=candidate.routing,
                    metadata={
                        "source": candidate.source,
                        "comparison_score": candidate.final_score,
                        "reviewer": request_body.reviewer,
                        "batch_approve": True,
                    },
                )

            approved_count += 1
            if faq_id:
                created_faq_ids.append(faq_id)

        except DuplicateFAQError:
            logger.warning(f"Batch approve: Candidate {candidate_id} is duplicate")
            failed_ids.append(candidate_id)
        except Exception:
            logger.exception(
                f"Batch approve: Failed to approve candidate {candidate_id}"
            )
            failed_ids.append(candidate_id)

    logger.info(
        f"Batch approve completed: {approved_count} approved, "
        f"{len(failed_ids)} failed"
    )

    return BatchApproveResponse(
        success=len(failed_ids) == 0,
        approved_count=approved_count,
        failed_ids=failed_ids,
        created_faq_ids=created_faq_ids,
    )


@router.post("/candidates/{candidate_id}/reject", response_model=ActionResponse)
async def reject_candidate(
    candidate_id: int,
    request_body: UnifiedRejectRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Reject a unified FAQ candidate."""
    logger.info(f"Admin request to reject candidate {candidate_id}")

    # P4: Validate rejection reason
    reason = request_body.reason.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rejection reason cannot be empty",
        )
    if len(reason) > MAX_REJECTION_REASON_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rejection reason too long (max {MAX_REJECTION_REASON_LENGTH} characters)",
        )
    # Custom reasons (not in allowed list) must be at least 3 characters
    if reason not in ALLOWED_REJECT_REASONS and len(reason) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Custom rejection reason must be at least 3 characters",
        )

    try:
        # Get candidate first to record generation_confidence for learning
        candidate = pipeline_service.repository.get_by_id(candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate {candidate_id} not found",
            )

        await pipeline_service.reject_candidate(
            candidate_id=candidate_id,
            reviewer=request_body.reviewer,
            reason=reason,
        )

        # Record feedback to LearningEngine using generation_confidence (not final_score)
        learning_engine = getattr(request.app.state, "learning_engine", None)
        if learning_engine and candidate.generation_confidence is not None:
            learning_engine.record_review(
                question_id=str(candidate_id),
                confidence=candidate.generation_confidence,  # Use RAG confidence, NOT comparison score
                admin_action="rejected",
                routing_action=candidate.routing,
                metadata={
                    "source": candidate.source,
                    "comparison_score": candidate.final_score,  # Keep for analysis
                    "reviewer": request_body.reviewer,
                    "rejection_reason": reason,
                },
            )
            logger.debug(
                f"Recorded rejection to LearningEngine: candidate={candidate_id}, "
                f"generation_confidence={candidate.generation_confidence}"
            )

        return ActionResponse(success=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to reject candidate {candidate_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject candidate {candidate_id}",
        ) from e


@router.post("/candidates/{candidate_id}/skip", response_model=ActionResponse)
async def skip_candidate(
    candidate_id: int,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Skip a unified FAQ candidate for later review."""
    logger.info(f"Admin request to skip candidate {candidate_id}")
    try:
        await pipeline_service.skip_candidate(candidate_id=candidate_id)
        return ActionResponse(success=True)
    except Exception as e:
        logger.exception(f"Failed to skip candidate {candidate_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to skip candidate {candidate_id}",
        ) from e


@router.post("/candidates/{candidate_id}/undo", response_model=ActionResponse)
async def undo_candidate_action(
    candidate_id: int,
    request_body: UndoActionRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Undo a recent action (approve/reject/skip) on a candidate.

    This endpoint allows reviewers to undo their most recent action within
    a short time window (typically 5 seconds on the frontend).

    For approve actions, the FAQ is deleted if faq_id is provided.
    For reject/skip actions, the candidate is simply reverted to pending.
    """
    logger.info(
        f"Admin request to undo {request_body.action_type} for candidate {candidate_id}"
    )

    # Validate action_type
    valid_actions = {"approve", "reject", "skip"}
    if request_body.action_type not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action_type. Must be one of: {', '.join(valid_actions)}",
        )

    try:
        # Get FAQ service for approve undo
        faq_service = getattr(request.app.state, "faq_service", None)

        await pipeline_service.undo_action(
            candidate_id=candidate_id,
            action_type=request_body.action_type,
            faq_id=request_body.faq_id,
            faq_service=faq_service,
        )
        return ActionResponse(success=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception(f"Failed to undo action for candidate {candidate_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to undo action for candidate {candidate_id}",
        ) from e


@router.post("/candidates/{candidate_id}/rate-answer", response_model=ActionResponse)
async def rate_generated_answer(
    candidate_id: int,
    request_body: RateGeneratedAnswerRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Rate the quality of the RAG-generated answer for LearningEngine training.

    This endpoint records whether the generated answer would be good enough to
    auto-send to users. The feedback is used to train the LearningEngine to
    determine appropriate confidence thresholds for auto-approval.

    This is SEPARATE from approving/rejecting the FAQ candidate:
    - Rate Generated Answer: Would this RAG answer be acceptable to send?
    - Approve/Reject Candidate: Should this Q&A become a training FAQ?
    """
    logger.info(
        f"Admin request to rate generated answer for candidate {candidate_id}: "
        f"rating={request_body.rating}"
    )
    try:
        # Get candidate to access generation_confidence
        candidate = pipeline_service.repository.get_by_id(candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate {candidate_id} not found",
            )

        if candidate.generated_answer is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No generated answer to rate - generate one first",
            )

        # Validate rating value
        if request_body.rating not in ("good", "needs_improvement"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rating must be 'good' or 'needs_improvement'",
            )

        # Record feedback to LearningEngine for auto-send threshold training
        learning_engine = getattr(request.app.state, "learning_engine", None)
        if learning_engine and candidate.generation_confidence is not None:
            # Map rating to admin_action for the LearningEngine
            # "good" means the answer would be acceptable to auto-send
            # "needs_improvement" means it requires human review
            admin_action = (
                "answer_approved"
                if request_body.rating == "good"
                else "answer_rejected"
            )

            learning_engine.record_review(
                question_id=str(candidate_id),
                confidence=candidate.generation_confidence,
                admin_action=admin_action,
                routing_action=candidate.routing,
                metadata={
                    "source": candidate.source,
                    "comparison_score": candidate.final_score,
                    "reviewer": request_body.reviewer,
                    "rating_type": "generated_answer_quality",
                },
            )
            logger.info(
                f"Recorded answer rating to LearningEngine: candidate={candidate_id}, "
                f"rating={request_body.rating}, generation_confidence={candidate.generation_confidence}"
            )
        else:
            logger.warning(
                f"Could not record answer rating: learning_engine={learning_engine is not None}, "
                f"generation_confidence={candidate.generation_confidence}"
            )

        return ActionResponse(success=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            f"Failed to rate generated answer for candidate {candidate_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rate generated answer for candidate {candidate_id}",
        ) from e


@router.patch("/candidates/{candidate_id}")
async def update_candidate(
    candidate_id: int,
    request_body: UpdateCandidateRequest,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Update a candidate's editable fields (e.g., edited_staff_answer).

    This endpoint allows reviewers to edit the staff answer before approval.
    The edited answer will be used when creating the FAQ entry.
    """
    logger.info(f"Admin request to update candidate {candidate_id}")
    try:
        candidate = await pipeline_service.update_candidate(
            candidate_id=candidate_id,
            edited_staff_answer=request_body.edited_staff_answer,
            category=request_body.category,
        )
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate {candidate_id} not found",
            )
        return _candidate_to_dict(candidate)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to update candidate {candidate_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update candidate {candidate_id}",
        ) from e


@router.post("/candidates/{candidate_id}/regenerate")
async def regenerate_candidate_answer(
    candidate_id: int,
    request_body: RegenerateAnswerRequest,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Regenerate the RAG answer for a candidate with a specific protocol.

    This endpoint allows reviewers to select a protocol (bisq_easy, multisig_v1,
    musig, or all) and regenerate the comparison answer using that protocol's
    context in the RAG system.

    The scores will be recalculated based on the new generated answer.
    """
    logger.info(
        f"Admin request to regenerate answer for candidate {candidate_id} "
        f"with protocol {request_body.protocol}"
    )

    # Validate protocol
    valid_protocols = {"bisq_easy", "multisig_v1", "musig", "all"}
    if request_body.protocol not in valid_protocols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid protocol. Must be one of: {', '.join(valid_protocols)}",
        )

    try:
        candidate = await pipeline_service.regenerate_candidate_answer(
            candidate_id=candidate_id,
            protocol=request_body.protocol,
        )
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Candidate {candidate_id} not found",
            )
        return _candidate_to_dict(candidate)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to regenerate answer for candidate {candidate_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate answer for candidate {candidate_id}",
        ) from e


# Sync endpoints for unified pipeline
@router.post("/sync/bisq", response_model=SyncResponse)
async def trigger_bisq_sync(
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Trigger sync of Bisq 2 conversations.

    Fetches conversations from Bisq 2 API and processes them through
    the unified training pipeline.

    Returns:
        Status with processed count and message.
    """
    logger.info("Admin request to trigger Bisq sync")

    try:
        # Get or create Bisq API client
        bisq_api = getattr(request.app.state, "bisq_api", None)
        if not bisq_api:
            from app.core.config import get_settings
            from app.integrations.bisq_api import Bisq2API

            settings = get_settings()
            bisq_api = Bisq2API(settings)
            request.app.state.bisq_api = bisq_api

        # Get or create state manager
        state_manager = getattr(request.app.state, "bisq_sync_state", None)
        if not state_manager:
            from app.services.training.bisq_sync_state import BisqSyncStateManager

            state_manager = BisqSyncStateManager()
            request.app.state.bisq_sync_state = state_manager

        # Run sync
        processed = await pipeline_service.sync_bisq_conversations(
            bisq_api=bisq_api,
            state_manager=state_manager,
        )

        return SyncResponse(
            status="completed",
            processed=processed,
            message=f"Processed {processed} Bisq conversations",
        )

    except Exception as e:
        logger.exception("Bisq sync failed")
        return SyncResponse(
            status="error",
            message=str(e),
        )


@router.post("/sync/matrix", response_model=SyncResponse)
async def trigger_matrix_sync(
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Trigger sync of Matrix conversations.

    Polls configured Matrix rooms for staff replies to user questions
    and processes them through the unified training pipeline.

    Returns:
        Status with processed count and message.
        Returns "skipped" status if Matrix is not configured or matrix-nio
        is not installed.
    """
    logger.info("Admin request to trigger Matrix sync")

    try:
        from app.core.config import get_settings

        settings = get_settings()

        # Check if Matrix is configured
        homeserver = getattr(settings, "MATRIX_HOMESERVER_URL", "") or ""
        rooms = getattr(settings, "MATRIX_ROOMS", []) or []

        if not homeserver.strip() or not rooms:
            logger.info("Matrix not configured, skipping sync")
            return SyncResponse(
                status="skipped",
                processed=0,
                message="Matrix not configured (MATRIX_HOMESERVER_URL or MATRIX_ROOMS not set)",
            )

        # Check if matrix-nio is available
        import importlib.util

        if importlib.util.find_spec("nio") is None:
            logger.warning("matrix-nio not installed, skipping Matrix sync")
            return SyncResponse(
                status="skipped",
                processed=0,
                message="matrix-nio not installed",
            )

        # Get or create Matrix sync service
        matrix_sync = getattr(request.app.state, "matrix_sync_service", None)
        if not matrix_sync:
            from app.integrations.matrix.polling_state import PollingStateManager
            from app.services.training.matrix_sync_service import MatrixSyncService

            # Create polling state manager for Matrix
            polling_state = PollingStateManager(
                state_file=settings.get_data_path("matrix_polling_state.json")
            )

            matrix_sync = MatrixSyncService(
                settings=settings,
                pipeline_service=pipeline_service,
                polling_state=polling_state,
            )
            request.app.state.matrix_sync_service = matrix_sync

        # Run sync
        processed = await matrix_sync.sync_rooms()

        return SyncResponse(
            status="completed",
            processed=processed,
            message=f"Processed {processed} Matrix Q&A pairs",
        )

    except Exception as e:
        logger.exception("Matrix sync failed")
        return SyncResponse(
            status="error",
            message=str(e),
        )


# =============================================================================
# Learning Engine Endpoints
# =============================================================================


@router.get("/learning/metrics", response_model=LearningMetricsResponse)
async def get_learning_metrics(request: Request):
    """Get current learning engine metrics and thresholds.

    Returns the current adaptive thresholds and statistics about admin reviews
    that have been used to train the thresholds.
    """
    logger.info("Admin request for learning metrics")

    learning_engine = getattr(request.app.state, "learning_engine", None)
    if learning_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learning engine not initialized",
        )

    current_thresholds = learning_engine.get_current_thresholds()
    metrics = learning_engine.get_learning_metrics()

    return LearningMetricsResponse(
        current_thresholds=current_thresholds,
        total_reviews=metrics["total_reviews"],
        approval_rate=metrics["approval_rate"],
        edit_rate=metrics["edit_rate"],
        rejection_rate=metrics["rejection_rate"],
        threshold_updates=metrics["threshold_updates"],
        avg_confidence=metrics.get("avg_confidence"),
        std_confidence=metrics.get("std_confidence"),
        min_confidence=metrics.get("min_confidence"),
        max_confidence=metrics.get("max_confidence"),
    )


@router.get("/learning/readiness", response_model=LaunchReadinessResponse)
async def get_launch_readiness(request: Request):
    """Check if the system is ready for production launch.

    Evaluates multiple criteria based on learning engine performance:
    - Sufficient review data collected
    - High approval rate
    - Low edit/rejection rates
    - Stable thresholds
    - Good average confidence
    """
    logger.info("Admin request for launch readiness check")

    learning_engine = getattr(request.app.state, "learning_engine", None)
    if learning_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learning engine not initialized",
        )

    from app.services.rag.learning_engine import LaunchReadinessChecker

    checker = LaunchReadinessChecker(learning_engine)
    result = checker.check_readiness()

    return LaunchReadinessResponse(
        is_ready=result["is_ready"],
        readiness_score=result["readiness_score"],
        passed_criteria=result["passed_criteria"],
        total_criteria=result["total_criteria"],
        criteria=result["criteria"],
        recommendations=result["recommendations"],
        current_thresholds=result["current_thresholds"],
        metrics_summary=result["metrics_summary"],
        checked_at=result["checked_at"],
    )


# =============================================================================
# Flagged FAQs Endpoints (Cycle 18)
# =============================================================================


@router.get("/flagged-faqs", response_model=FlaggedFAQsResponse)
async def get_flagged_faqs(
    pipeline_service=Depends(get_pipeline_service()),
):
    """Get all FAQs flagged for review due to post-approval corrections.

    Cycle 18: Returns threads in 'reopened_for_correction' state with their
    correction details.

    Returns:
        List of flagged FAQs with correction information.
    """
    logger.info("Admin request for flagged FAQs")
    try:
        flagged = pipeline_service.get_flagged_faqs()
        return FlaggedFAQsResponse(flagged=flagged)
    except Exception as e:
        logger.exception("Failed to get flagged FAQs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get flagged FAQs",
        ) from e


@router.post(
    "/flagged-faqs/{thread_id}/resolve",
    response_model=ResolveFlaggedFAQResponse,
)
async def resolve_flagged_faq(
    thread_id: int,
    request_body: ResolveFlaggedFAQRequest,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Resolve a flagged FAQ by updating, confirming, or deleting it.

    Cycle 18: Handles post-approval correction resolution.

    Args:
        thread_id: ID of the thread to resolve
        request_body: Resolution action and details

    Returns:
        Resolution status and action taken.

    Raises:
        400: Invalid action
        404: Thread not found
    """
    logger.info(
        f"Admin request to resolve flagged FAQ thread {thread_id} "
        f"with action '{request_body.action}'"
    )

    # Validate action
    valid_actions = {"update", "confirm", "delete"}
    if request_body.action not in valid_actions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{request_body.action}'. "
            f"Must be one of: {', '.join(valid_actions)}",
        )

    try:
        await pipeline_service.resolve_flagged_faq(
            thread_id=thread_id,
            action=request_body.action,
            reviewer=request_body.reviewer,
            new_answer=request_body.new_answer,
        )
        return ResolveFlaggedFAQResponse(
            status="resolved",
            action=request_body.action,
        )
    except ValueError as e:
        # Thread not found or invalid state
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.exception(f"Failed to resolve flagged FAQ thread {thread_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve flagged FAQ thread {thread_id}",
        ) from e


# =============================================================================
# Helper Functions
# =============================================================================


def _candidate_to_dict(candidate: Any) -> Dict[str, Any]:
    """Convert UnifiedFAQCandidate to dictionary for JSON response.

    Transforms a UnifiedFAQCandidate dataclass into a JSON-serializable dictionary
    suitable for API responses. Handles special fields like JSON-encoded sources
    and optional fields that may not be present on older candidates.

    Args:
        candidate: UnifiedFAQCandidate instance from the repository

    Returns:
        Dictionary containing all candidate fields with the following structure:
        - id: Unique candidate identifier
        - source: Origin ("bisq2" or "matrix")
        - source_event_id: Unique event ID from source system
        - source_timestamp: ISO timestamp of original message
        - question_text: User's question (may be LLM-transformed for clarity)
        - staff_answer: Staff's answer (may be LLM-transformed)
        - generated_answer: RAG-generated answer for comparison
        - staff_sender: Identifier of the staff member
        - embedding_similarity: Cosine similarity between embeddings (0-1)
        - factual_alignment: LLM-judged factual alignment score (0-1)
        - contradiction_score: Score indicating contradictions (0-1, lower better)
        - completeness: Score for answer completeness (0-1)
        - hallucination_risk: Risk of hallucination in RAG answer (0-1, lower better)
        - final_score: Weighted combination of all scores (0-1)
        - generation_confidence: RAG's own confidence (distinct from final_score)
        - llm_reasoning: LLM's explanation for comparison scores
        - routing: Routing decision (AUTO_APPROVE, SPOT_CHECK, FULL_REVIEW)
        - review_status: Current status (pending, approved, rejected)
        - reviewed_by: Admin who reviewed (if reviewed)
        - reviewed_at: ISO timestamp of review (if reviewed)
        - rejection_reason: Reason for rejection (if rejected)
        - faq_id: Created FAQ ID (if approved)
        - is_calibration_sample: Whether this is a calibration sample
        - created_at: ISO timestamp of candidate creation
        - updated_at: ISO timestamp of last update
        - protocol: Detected Bisq protocol (bisq_easy, multisig_v1, etc.)
        - edited_staff_answer: Admin-edited version of staff answer
        - category: FAQ category (Trading, Wallet, etc.)
        - generated_answer_sources: List of source documents used by RAG
        - original_user_question: Pre-transformation user question
        - original_staff_answer: Pre-transformation staff answer
    """
    # Parse sources JSON string to list if present
    sources_raw = getattr(candidate, "generated_answer_sources", None)
    sources = None
    if sources_raw:
        try:
            sources = json.loads(sources_raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse sources JSON for candidate {candidate.id}")
            sources = None

    return {
        "id": candidate.id,
        "source": candidate.source,
        "source_event_id": candidate.source_event_id,
        "source_timestamp": candidate.source_timestamp,
        "question_text": candidate.question_text,
        "staff_answer": candidate.staff_answer,
        "generated_answer": candidate.generated_answer,
        "staff_sender": candidate.staff_sender,
        "embedding_similarity": candidate.embedding_similarity,
        "factual_alignment": candidate.factual_alignment,
        "contradiction_score": candidate.contradiction_score,
        "completeness": candidate.completeness,
        "hallucination_risk": candidate.hallucination_risk,
        "final_score": candidate.final_score,
        "generation_confidence": getattr(candidate, "generation_confidence", None),
        "llm_reasoning": candidate.llm_reasoning,
        "routing": candidate.routing,
        "review_status": candidate.review_status,
        "reviewed_by": candidate.reviewed_by,
        "reviewed_at": candidate.reviewed_at,
        "rejection_reason": candidate.rejection_reason,
        "faq_id": candidate.faq_id,
        "is_calibration_sample": candidate.is_calibration_sample,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
        "protocol": getattr(candidate, "protocol", None),
        "edited_staff_answer": getattr(candidate, "edited_staff_answer", None),
        "category": getattr(candidate, "category", None),
        "generated_answer_sources": sources,
        "original_user_question": getattr(candidate, "original_user_question", None),
        "original_staff_answer": getattr(candidate, "original_staff_answer", None),
    }
