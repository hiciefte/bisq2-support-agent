"""Admin routes for LLM Wiki knowledge update review."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.exceptions import BaseAppException
from app.core.security import verify_admin_access
from app.routes.admin.training import (
    _build_learning_review_metadata,
    _candidate_to_dict,
    _normalize_review_admin_action,
    get_pipeline_service,
)
from app.services.faq.duplicate_guard import build_duplicate_faq_detail
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.training.unified_pipeline_service import DuplicateFAQError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
KNOWLEDGE_UPDATE_PAGE_SIZE = 500

router = APIRouter(
    prefix="/admin/knowledge-updates",
    tags=["Admin Knowledge Updates"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


class KnowledgeUpdateOperation(BaseModel):
    id: str
    section: str
    action: str
    content: str


class UpdateKnowledgeProposalRequest(BaseModel):
    operations: List[KnowledgeUpdateOperation]


class UpdateKnowledgeDocumentRequest(BaseModel):
    markdown: str = Field(min_length=1)


class KnowledgeReviewRequest(BaseModel):
    reviewer: str = Field(default="admin")


class RejectKnowledgeUpdateRequest(BaseModel):
    reviewer: str = Field(default="admin")
    reason: str = Field(default="not_durable")


class CreateFAQFromKnowledgeUpdateRequest(BaseModel):
    reviewer: str = Field(default="admin")
    force: bool = Field(default=False)


class ActionResponse(BaseModel):
    success: bool


class KnowledgeUpdateApproveResponse(BaseModel):
    success: bool
    page_id: Optional[str] = None


class CreateFAQFromKnowledgeUpdateResponse(BaseModel):
    success: bool
    faq_id: Optional[str] = None


def get_knowledge_update_service(request: Request) -> KnowledgeUpdateService:
    settings = getattr(request.app.state, "settings", None)
    pipeline_service = getattr(request.app.state, "unified_pipeline_service", None)
    if settings is None or pipeline_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge update service dependencies are not initialized",
        )
    return KnowledgeUpdateService(
        settings=settings,
        db_path=pipeline_service.repository.db_path,
    )


async def _iter_pending_candidates(
    pipeline_service,
    *,
    routing: Optional[str] = None,
):
    offset = 0
    while True:
        candidates = await run_in_threadpool(
            lambda: pipeline_service.repository.get_pending(
                routing=routing,
                limit=KNOWLEDGE_UPDATE_PAGE_SIZE,
                offset=offset,
            )
        )
        if not candidates:
            return

        for candidate in candidates:
            yield candidate

        if len(candidates) < KNOWLEDGE_UPDATE_PAGE_SIZE:
            return
        offset += len(candidates)


@router.get("/counts")
async def get_knowledge_update_counts(
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, int]:
    """Return counts for candidates suitable for LLM Wiki review."""
    try:
        counts = {"AUTO_APPROVE": 0, "SPOT_CHECK": 0, "FULL_REVIEW": 0}
        async for candidate in _iter_pending_candidates(pipeline_service):
            if service.is_candidate_reviewable(candidate):
                counts[candidate.routing] = counts.get(candidate.routing, 0) + 1
        return counts
    except Exception as exc:
        logger.exception("Failed to get knowledge update counts")
        raise BaseAppException(
            detail="Failed to get knowledge update counts",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_UPDATE_COUNTS_FAILED",
        ) from exc


@router.get("/current")
async def get_current_knowledge_update(
    queue: str = "FULL_REVIEW",
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Optional[Dict[str, Any]]:
    """Return the next candidate with a lazily generated LLM Wiki proposal."""
    try:
        candidate = None
        async for pending in _iter_pending_candidates(
            pipeline_service,
            routing=queue,
        ):
            if service.is_candidate_reviewable(pending):
                candidate = pending
                break
        if candidate is None:
            return None
        proposal = await run_in_threadpool(
            lambda: service.get_or_create_proposal(candidate=candidate)
        )
        return {
            "candidate": _candidate_to_dict(candidate),
            "proposal": service.to_response(proposal, candidate),
        }
    except Exception as exc:
        logger.exception("Failed to get current knowledge update")
        raise BaseAppException(
            detail="Failed to get current knowledge update",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_UPDATE_CURRENT_FAILED",
        ) from exc


@router.post("/{candidate_id}/generate")
async def regenerate_knowledge_update_proposal(
    candidate_id: int,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Regenerate a candidate's proposed LLM Wiki diff."""
    candidate = await run_in_threadpool(
        lambda: pipeline_service.repository.get_by_id(candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )
    proposal = await run_in_threadpool(
        lambda: service.get_or_create_proposal(candidate=candidate, force=True)
    )
    return service.to_response(proposal, candidate)


@router.patch("/{candidate_id}/proposal")
async def update_knowledge_update_proposal(
    candidate_id: int,
    request_body: UpdateKnowledgeProposalRequest,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Update the editable structured operations for a proposal."""
    candidate = await run_in_threadpool(
        lambda: pipeline_service.repository.get_by_id(candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )
    operations = [operation.model_dump() for operation in request_body.operations]
    proposal = await run_in_threadpool(
        lambda: service.update_operations(candidate=candidate, operations=operations)
    )
    return service.to_response(proposal, candidate)


@router.patch("/{candidate_id}/document")
async def update_knowledge_update_document(
    candidate_id: int,
    request_body: UpdateKnowledgeDocumentRequest,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Update the full proposed LLM Wiki markdown document."""
    candidate = await run_in_threadpool(
        lambda: pipeline_service.repository.get_by_id(candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )
    try:
        proposal = await run_in_threadpool(
            lambda: service.update_document_markdown(
                candidate=candidate,
                markdown=request_body.markdown,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return service.to_response(proposal, candidate)


@router.post("/{candidate_id}/approve", response_model=KnowledgeUpdateApproveResponse)
async def approve_knowledge_update(
    candidate_id: int,
    request_body: KnowledgeReviewRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
):
    """Approve a proposed LLM Wiki change and mark the vector index stale."""
    candidate = await run_in_threadpool(
        lambda: pipeline_service.repository.get_by_id(candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )

    try:
        proposal = await run_in_threadpool(
            lambda: service.approve(candidate=candidate, reviewer=request_body.reviewer)
        )
        page_id = proposal.target_page_id or f"candidate-{candidate_id}"
        pipeline_service.repository.approve(
            candidate_id,
            request_body.reviewer,
            f"llm_wiki:{page_id}",
        )
        _record_learning_review(
            request=request,
            candidate=candidate,
            reviewer=request_body.reviewer,
            review_kind="llm_wiki_decision",
            admin_action="approved",
        )

        rag_service = getattr(request.app.state, "rag_service", None)
        state_manager = getattr(rag_service, "state_manager", None)
        if state_manager is not None:
            state_manager.mark_change(
                operation="llm_wiki_update",
                item_id=str(page_id),
                metadata={"candidate_id": candidate_id},
            )
        return KnowledgeUpdateApproveResponse(success=True, page_id=page_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to approve knowledge update %s", candidate_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve knowledge update {candidate_id}",
        ) from exc


@router.post("/{candidate_id}/reject", response_model=ActionResponse)
async def reject_knowledge_update(
    candidate_id: int,
    request_body: RejectKnowledgeUpdateRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
):
    """Reject a knowledge update as non-durable or unsuitable."""
    candidate = await run_in_threadpool(
        lambda: pipeline_service.repository.get_by_id(candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )
    reason = request_body.reason.strip() or "not_durable"
    await run_in_threadpool(
        lambda: service.mark_rejected(
            candidate_id=candidate_id,
            reviewer=request_body.reviewer,
            reason=reason,
        )
    )
    await pipeline_service.reject_candidate(
        candidate_id=candidate_id,
        reviewer=request_body.reviewer,
        reason=reason,
    )
    _record_learning_review(
        request=request,
        candidate=candidate,
        reviewer=request_body.reviewer,
        review_kind="llm_wiki_decision",
        admin_action="rejected",
    )
    return ActionResponse(success=True)


@router.post("/{candidate_id}/skip", response_model=ActionResponse)
async def skip_knowledge_update(
    candidate_id: int,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Move a knowledge update candidate to the end of its queue."""
    await pipeline_service.skip_candidate(candidate_id=candidate_id)
    return ActionResponse(success=True)


@router.post(
    "/{candidate_id}/create-faq",
    response_model=CreateFAQFromKnowledgeUpdateResponse,
)
async def create_faq_from_knowledge_update(
    candidate_id: int,
    request_body: CreateFAQFromKnowledgeUpdateRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
):
    """Escape hatch: create a public FAQ instead of an LLM Wiki update."""
    candidate = await run_in_threadpool(
        lambda: pipeline_service.repository.get_by_id(candidate_id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )
    try:
        faq_id = await pipeline_service.approve_candidate(
            candidate_id=candidate_id,
            reviewer=request_body.reviewer,
            force=request_body.force,
        )
        _record_learning_review(
            request=request,
            candidate=candidate,
            reviewer=request_body.reviewer,
            review_kind="faq_escape_hatch",
            admin_action="approved",
        )
        return CreateFAQFromKnowledgeUpdateResponse(success=True, faq_id=faq_id)
    except DuplicateFAQError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=build_duplicate_faq_detail(
                message=str(exc),
                similar_faqs=exc.similar_faqs,
                context={"candidate_id": candidate_id},
            ),
        ) from exc


def _record_learning_review(
    *,
    request: Request,
    candidate: Any,
    reviewer: str,
    review_kind: str,
    admin_action: str,
) -> None:
    learning_engine = getattr(request.app.state, "learning_engine", None)
    if learning_engine is None or candidate.generation_confidence is None:
        return
    learning_engine.record_review(
        question_id=str(candidate.id),
        confidence=candidate.generation_confidence,
        admin_action=_normalize_review_admin_action(admin_action),
        routing_action=candidate.routing,
        metadata=_build_learning_review_metadata(
            source=candidate.source,
            comparison_score=candidate.final_score,
            reviewer=reviewer,
            review_kind=review_kind,
        ),
    )
