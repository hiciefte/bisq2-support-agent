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
from app.services.knowledge_updates.candidate_rework_triage import (
    CandidateReworkTriageService,
)
from app.services.knowledge_updates.code_evidence_promotion import (
    CodeEvidencePromotionService,
)
from app.services.knowledge_updates.llm_wiki_coverage_reconciliation import (
    LLMWikiCoverageReconciliationService,
)
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateProposal,
    KnowledgeUpdateService,
)
from app.services.knowledge_updates.topic_clusters import (
    KnowledgeReviewItem,
    KnowledgeTopicCluster,
    build_knowledge_review_items,
)
from app.services.rag.code_evidence import CODE_EVIDENCE_TYPE, CodeEvidenceRecord
from app.services.training.unified_pipeline_service import DuplicateFAQError
from app.services.training.unified_repository import UnifiedFAQCandidate
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
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
    feedback_tags: List[str] = Field(default_factory=list)
    future_generator_note: Optional[str] = None


class ApplyKnowledgeReworkActionRequest(BaseModel):
    action: str = Field(
        pattern=(
            "^(bulk_reject_non_durable|repair_metadata|"
            "repair_sources|review_cluster)$"
        )
    )
    candidate_ids: List[int] = Field(min_length=1, max_length=500)


class KnowledgeCoverageReconciliationRequest(BaseModel):
    apply: bool = Field(default=False)


class RejectKnowledgeUpdateRequest(BaseModel):
    reviewer: str = Field(default="admin")
    reason: str = Field(default="not_durable")


class CreateFAQFromKnowledgeUpdateRequest(BaseModel):
    reviewer: str = Field(default="admin")
    force: bool = Field(default=False)


class PromoteCodeEvidenceRequest(BaseModel):
    evidence: Dict[str, Any]
    question: Optional[str] = None
    public_guidance: Optional[str] = None


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


async def _get_knowledge_review_items(
    pipeline_service,
    service: KnowledgeUpdateService,
) -> List[KnowledgeReviewItem]:
    candidates = []
    async for candidate in _iter_pending_candidates(pipeline_service):
        candidates.append(candidate)
    return build_knowledge_review_items(
        candidates,
        service.is_candidate_reviewable,
        cluster_key=service.review_cluster_key,
    )


async def _get_candidate_cluster(
    *,
    candidate_id: int,
    pipeline_service,
    service: KnowledgeUpdateService,
) -> Optional[KnowledgeTopicCluster]:
    for item in await _get_knowledge_review_items(pipeline_service, service):
        if item.cluster is None:
            continue
        if candidate_id in item.cluster.candidate_ids:
            return item.cluster
    return None


def _cluster_member_ids(
    candidate_id: int,
    cluster: Optional[KnowledgeTopicCluster],
) -> List[int]:
    if cluster is None:
        return [candidate_id]
    return cluster.candidate_ids


def _approve_cluster_members(
    repository,
    *,
    member_ids: List[int],
    reviewer: str,
    page_ref: str,
) -> None:
    for member_id in member_ids:
        repository.approve(member_id, reviewer, page_ref)


def _reject_cluster_members(
    repository,
    *,
    member_ids: List[int],
    reviewer: str,
    reason: str,
) -> None:
    for member_id in member_ids:
        repository.reject(member_id, reviewer, reason)


def _skip_cluster_members(repository, *, member_ids: List[int]) -> None:
    for member_id in member_ids:
        repository.skip(member_id)


def _dedupe_candidate_ids(candidate_ids: List[int]) -> List[int]:
    seen = set()
    result = []
    for candidate_id in candidate_ids:
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        result.append(candidate_id)
    return result


def _find_rework_group(
    *,
    groups: List[Any],
    action: str,
    candidate_ids: List[int],
) -> Any:
    requested = set(candidate_ids)
    return next(
        (
            group
            for group in groups
            if group.action == action and set(group.candidate_ids) == requested
        ),
        None,
    )


def _rework_cluster_from_group(
    *,
    group: Any,
    candidates: List[Any],
) -> KnowledgeTopicCluster:
    return KnowledgeTopicCluster(
        key=(
            f"rework:{group.action}:{group.topic}:"
            f"{'-'.join(str(candidate_id) for candidate_id in group.candidate_ids)}"
        ),
        topic=group.topic,
        candidates=candidates,
    )


def _rework_action_response(
    *,
    action: str,
    candidate_ids: List[int],
    updated_count: int = 0,
    rejected_count: int = 0,
    proposal_count: int = 0,
    failed_candidate_ids: Optional[List[int]] = None,
    remaining_issues_by_candidate: Optional[Dict[str, List[str]]] = None,
    message: str,
) -> Dict[str, Any]:
    remaining = remaining_issues_by_candidate or {}
    failed = failed_candidate_ids or []
    return {
        "success": not failed and not remaining,
        "action": action,
        "candidate_ids": candidate_ids,
        "updated_count": updated_count,
        "rejected_count": rejected_count,
        "proposal_count": proposal_count,
        "failed_candidate_ids": failed,
        "remaining_blocked_count": len(remaining),
        "remaining_issues_by_candidate": remaining,
        "message": message,
    }


def _create_forced_knowledge_update_proposal(
    service: KnowledgeUpdateService,
    candidate: UnifiedFAQCandidate,
) -> KnowledgeUpdateProposal:
    return service.get_or_create_proposal(candidate=candidate, force=True)


def _authenticated_admin_reviewer(request: Request) -> str:
    reviewer = getattr(getattr(request, "state", None), "admin_actor", None)
    if reviewer:
        return str(reviewer)
    return "admin"


@router.get("/counts")
async def get_knowledge_update_counts(
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, int]:
    """Return counts for candidates suitable for LLM Wiki review."""
    try:
        counts = {"AUTO_APPROVE": 0, "SPOT_CHECK": 0, "FULL_REVIEW": 0}
        for item in await _get_knowledge_review_items(pipeline_service, service):
            counts[item.routing] = counts.get(item.routing, 0) + 1
        return counts
    except Exception as exc:
        logger.exception("Failed to get knowledge update counts")
        raise BaseAppException(
            detail="Failed to get knowledge update counts",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_UPDATE_COUNTS_FAILED",
        ) from exc


@router.post("/coverage-reconciliation")
async def reconcile_reviewed_knowledge_coverage(
    request_body: KnowledgeCoverageReconciliationRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Resolve pending candidates already covered by reviewed LLM Wiki pages.

    The endpoint is dry-run by default. Applying uses pending-only approvals so
    human actions made after the dry-run cannot be overwritten.
    """
    try:
        candidates = []
        async for candidate in _iter_pending_candidates(pipeline_service):
            candidates.append(candidate)
        reconciler = LLMWikiCoverageReconciliationService(service.settings)
        report = await run_in_threadpool(
            lambda: reconciler.reconcile(
                candidates,
                apply=request_body.apply,
                repository=(
                    pipeline_service.repository if request_body.apply else None
                ),
                reviewer=_authenticated_admin_reviewer(request),
            )
        )
        return report.to_response()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to reconcile reviewed LLM Wiki coverage")
        raise BaseAppException(
            detail="Failed to reconcile reviewed knowledge coverage",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_COVERAGE_RECONCILIATION_FAILED",
        ) from exc


async def _run_automatic_coverage_reconciliation(
    *,
    pipeline_service,
    service: KnowledgeUpdateService,
    trigger_page_id: str,
    reviewer: str = "auto-coverage-reconciliation",
) -> Dict[str, Any]:
    reconciler = LLMWikiCoverageReconciliationService(service.settings)
    report = await run_in_threadpool(
        lambda: reconciler.reconcile_pending_repository(
            pipeline_service.repository,
            apply=True,
            reviewer=reviewer,
            page_size=KNOWLEDGE_UPDATE_PAGE_SIZE,
        )
    )
    logger.info(
        "Automatic reviewed coverage reconciliation after %s: applied=%s, "
        "spot_check=%s, remaining=%s, stale=%s",
        trigger_page_id,
        report.applied_count,
        report.spot_check_count,
        report.remaining_count,
        report.skipped_stale_count,
    )
    return report.to_response()


async def _run_automatic_coverage_reconciliation_safely(
    *,
    pipeline_service,
    service: KnowledgeUpdateService,
    trigger_page_id: str,
) -> None:
    try:
        await _run_automatic_coverage_reconciliation(
            pipeline_service=pipeline_service,
            service=service,
            trigger_page_id=trigger_page_id,
        )
    except Exception:
        logger.exception(
            "Automatic reviewed coverage reconciliation failed after approving %s",
            trigger_page_id,
        )


@router.get("/rework-triage")
async def get_knowledge_update_rework_triage(
    limit: int = Query(default=25, ge=1, le=100),
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Return AI-assisted triage for candidates blocked by safety gates."""
    try:
        limit_value = int(getattr(limit, "default", limit))
        candidates = []
        async for candidate in _iter_pending_candidates(pipeline_service):
            candidates.append(candidate)
        triage = await run_in_threadpool(
            lambda: CandidateReworkTriageService(service).build(
                candidates,
                limit=limit_value,
            )
        )
        return triage.to_response()
    except Exception as exc:
        logger.exception("Failed to get knowledge update rework triage")
        raise BaseAppException(
            detail="Failed to get knowledge update rework triage",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_UPDATE_REWORK_TRIAGE_FAILED",
        ) from exc


@router.post("/rework-triage/actions")
async def apply_knowledge_update_rework_action(
    request_body: ApplyKnowledgeReworkActionRequest,
    request: Request,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Apply one validated AI-assisted rework action to a blocked candidate group."""
    candidate_ids = _dedupe_candidate_ids(request_body.candidate_ids)
    candidates = []
    async for candidate in _iter_pending_candidates(pipeline_service):
        candidates.append(candidate)
    candidates_by_id = {candidate.id: candidate for candidate in candidates}

    triage_service = CandidateReworkTriageService(service)
    triage = await run_in_threadpool(lambda: triage_service.build(candidates))
    group = _find_rework_group(
        groups=triage.groups,
        action=request_body.action,
        candidate_ids=candidate_ids,
    )
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Requested rework group is no longer current. Refresh triage "
                "before applying this action."
            ),
        )

    group_candidates = [
        candidates_by_id[candidate_id]
        for candidate_id in group.candidate_ids
        if candidate_id in candidates_by_id
    ]
    if len(group_candidates) != len(group.candidate_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more candidates are no longer pending.",
        )

    reviewer = _authenticated_admin_reviewer(request)

    if group.action == "bulk_reject_non_durable":
        return await _apply_rework_bulk_reject(
            group=group,
            candidates=group_candidates,
            reviewer=reviewer,
            request=request,
            pipeline_service=pipeline_service,
            service=service,
        )
    if group.action == "repair_metadata":
        return await _apply_rework_metadata_repair(
            group=group,
            candidates=group_candidates,
            pipeline_service=pipeline_service,
            service=service,
        )
    if group.action == "repair_sources":
        return await _apply_rework_source_repair(
            group=group,
            candidates=group_candidates,
            pipeline_service=pipeline_service,
            service=service,
        )
    if group.action == "review_cluster":
        return await _apply_rework_cluster_review(
            group=group,
            candidates=group_candidates,
            service=service,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported rework action: {group.action}",
    )


async def _apply_rework_bulk_reject(
    *,
    group: Any,
    candidates: List[Any],
    reviewer: str,
    request: Request,
    pipeline_service,
    service: KnowledgeUpdateService,
) -> Dict[str, Any]:
    reason = "not_durable"
    note = (
        "AI-assisted rework triage: bulk rejected as non-durable. "
        f"Reason: {group.reason}"
    )

    def reject_candidates() -> int:
        reject_pending_many = getattr(
            pipeline_service.repository, "reject_pending_many", None
        )
        if reject_pending_many is not None:
            return int(
                reject_pending_many(
                    [candidate.id for candidate in candidates],
                    reviewer,
                    reason,
                    reason_note=note,
                )
            )

        rejected_count = 0
        for candidate in candidates:
            reject_pending = getattr(
                pipeline_service.repository, "reject_pending", None
            )
            if reject_pending is None:
                if getattr(candidate, "review_status", None) != "pending":
                    continue
                pipeline_service.repository.reject(
                    candidate.id,
                    reviewer,
                    reason,
                    reason_note=note,
                )
                rejected_count += 1
                continue

            if reject_pending(
                candidate.id,
                reviewer,
                reason,
                reason_note=note,
            ):
                rejected_count += 1
        return rejected_count

    rejected_count = await run_in_threadpool(reject_candidates)
    if rejected_count != len(candidates):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more candidates changed before rejection could be applied. "
                "Refresh triage before retrying."
            ),
        )

    def mark_rejected_proposals() -> None:
        for candidate in candidates:
            service.mark_rejected(
                candidate_id=candidate.id,
                reviewer=reviewer,
                reason=reason,
            )

    await run_in_threadpool(mark_rejected_proposals)
    for candidate in candidates:
        _record_learning_review(
            request=request,
            candidate=candidate,
            reviewer=reviewer,
            review_kind="llm_wiki_rework_triage",
            admin_action="rejected",
        )
    return _rework_action_response(
        action=group.action,
        candidate_ids=group.candidate_ids,
        rejected_count=rejected_count,
        message=f"Rejected {rejected_count} non-durable candidate(s).",
    )


async def _apply_rework_metadata_repair(
    *,
    group: Any,
    candidates: List[Any],
    pipeline_service,
    service: KnowledgeUpdateService,
) -> Dict[str, Any]:
    if not group.inferred_protocol:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This group no longer has a repairable inferred protocol.",
        )

    def repair_candidates() -> tuple[int, int, Dict[str, List[str]], List[int]]:
        updated_count = 0
        proposal_count = 0
        remaining: Dict[str, List[str]] = {}
        stale_candidate_ids: List[int] = []
        for candidate in candidates:
            updated = pipeline_service.repository.update_pending_candidate(
                candidate.id,
                protocol=group.inferred_protocol,
            )
            if updated is None:
                stale_candidate_ids.append(candidate.id)
                continue
            updated_count += 1
            issues = service.candidate_reviewability_issues(updated)
            if issues:
                remaining[str(candidate.id)] = issues
                continue
            service.get_or_create_proposal(candidate=updated, force=True)
            proposal_count += 1
        return updated_count, proposal_count, remaining, stale_candidate_ids

    updated_count, proposal_count, remaining, stale_candidate_ids = (
        await run_in_threadpool(repair_candidates)
    )
    if stale_candidate_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more candidates changed before metadata repair could be "
                "applied. Refresh triage before retrying."
            ),
        )
    return _rework_action_response(
        action=group.action,
        candidate_ids=group.candidate_ids,
        updated_count=updated_count,
        proposal_count=proposal_count,
        remaining_issues_by_candidate=remaining,
        message=(
            f"Applied `{group.inferred_protocol}` to {updated_count} " "candidate(s)."
        ),
    )


async def _apply_rework_source_repair(
    *,
    group: Any,
    candidates: List[Any],
    pipeline_service,
    service: KnowledgeUpdateService,
) -> Dict[str, Any]:
    regenerate = getattr(pipeline_service, "regenerate_pending_candidate_answer", None)
    if regenerate is None:
        regenerate = getattr(pipeline_service, "regenerate_candidate_answer", None)
    if regenerate is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Source repair requires the RAG regeneration service.",
        )

    updated_count = 0
    proposal_count = 0
    failed: List[int] = []
    stale_candidate_ids: List[int] = []
    remaining: Dict[str, List[str]] = {}
    for candidate in candidates:
        protocol = candidate.protocol or group.inferred_protocol
        if not protocol:
            failed.append(candidate.id)
            remaining[str(candidate.id)] = ["missing_protocol"]
            continue
        updated = await regenerate(candidate.id, protocol)
        if updated is None:
            stale_candidate_ids.append(candidate.id)
            continue
        updated_count += 1
        issues = service.candidate_reviewability_issues(updated)
        if issues:
            remaining[str(candidate.id)] = issues
            continue
        await run_in_threadpool(
            _create_forced_knowledge_update_proposal, service, updated
        )
        proposal_count += 1

    if stale_candidate_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more candidates changed before source repair could be "
                "applied. Refresh triage before retrying."
            ),
        )

    return _rework_action_response(
        action=group.action,
        candidate_ids=group.candidate_ids,
        updated_count=updated_count,
        proposal_count=proposal_count,
        failed_candidate_ids=failed,
        remaining_issues_by_candidate=remaining,
        message=(
            f"Regenerated source-grounded answers for {updated_count} " "candidate(s)."
        ),
    )


async def _apply_rework_cluster_review(
    *,
    group: Any,
    candidates: List[Any],
    service: KnowledgeUpdateService,
) -> Dict[str, Any]:
    cluster = _rework_cluster_from_group(group=group, candidates=candidates)
    representative = candidates[0]
    proposal = await run_in_threadpool(
        lambda: service.get_or_create_proposal(
            candidate=representative,
            cluster=cluster,
            force=True,
        )
    )
    response = _rework_action_response(
        action=group.action,
        candidate_ids=group.candidate_ids,
        proposal_count=1,
        message="Opened a clustered synthesis proposal for human review.",
    )
    response.update(
        {
            "candidate": _candidate_to_dict(representative),
            "proposal": service.to_response(proposal, representative),
            "cluster": cluster.to_response(),
        }
    )
    return response


@router.get("/current")
async def get_current_knowledge_update(
    queue: str = "FULL_REVIEW",
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Optional[Dict[str, Any]]:
    """Return the next candidate with a lazily generated LLM Wiki proposal."""
    try:
        item = None
        for review_item in await _get_knowledge_review_items(
            pipeline_service,
            service,
        ):
            if review_item.routing == queue:
                item = review_item
                break
        if item is None:
            return None
        candidate = item.candidate
        proposal = await run_in_threadpool(
            lambda: service.get_or_create_proposal(
                candidate=candidate,
                cluster=item.cluster,
            )
        )
        return {
            "candidate": _candidate_to_dict(candidate),
            "proposal": service.to_response(proposal, candidate),
            "cluster": item.cluster.to_response() if item.cluster else None,
        }
    except Exception as exc:
        logger.exception("Failed to get current knowledge update")
        raise BaseAppException(
            detail="Failed to get current knowledge update",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_UPDATE_CURRENT_FAILED",
        ) from exc


@router.get("/generator-feedback")
async def get_generator_feedback_records(
    limit: int = Query(default=100, ge=1, le=500),
    target_page_id: Optional[str] = None,
    reviewer: Optional[str] = None,
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Return approved LLM Wiki review examples for generator improvement."""
    try:
        items = await run_in_threadpool(
            lambda: service.list_generator_feedback_records(
                limit=limit,
                target_page_id=target_page_id,
                reviewer=reviewer,
            )
        )
        return {"count": len(items), "items": items}
    except Exception as exc:
        logger.exception("Failed to get generator feedback records")
        raise BaseAppException(
            detail="Failed to get generator feedback records",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="KNOWLEDGE_UPDATE_GENERATOR_FEEDBACK_FAILED",
        ) from exc


@router.post("/code-evidence/proposals")
async def promote_code_evidence_to_knowledge_update(
    request_body: PromoteCodeEvidenceRequest,
    pipeline_service=Depends(get_pipeline_service()),
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
) -> Dict[str, Any]:
    """Promote selected code evidence into the normal LLM Wiki review queue."""
    try:
        record = _code_evidence_record_from_payload(
            request_body.evidence,
            public_guidance=request_body.public_guidance,
        )
        promotion = CodeEvidencePromotionService(
            settings=service.settings,
            repository=pipeline_service.repository,
            knowledge_update_service=service,
        )
        result = await run_in_threadpool(
            lambda: promotion.create_or_get_proposal(
                record=record,
                question=request_body.question,
                public_guidance=request_body.public_guidance,
            )
        )
        return {
            "candidate": _candidate_to_dict(result.candidate),
            "proposal": service.to_response(result.proposal, result.candidate),
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to promote code evidence into knowledge update")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to promote code evidence",
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
    cluster = await _get_candidate_cluster(
        candidate_id=candidate_id,
        pipeline_service=pipeline_service,
        service=service,
    )
    proposal = await run_in_threadpool(
        lambda: service.get_or_create_proposal(
            candidate=candidate,
            cluster=cluster,
            force=True,
        )
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


def _code_evidence_record_from_payload(
    evidence: Dict[str, Any],
    *,
    public_guidance: Optional[str],
) -> CodeEvidenceRecord:
    data = dict(evidence or {})
    if "type" not in data:
        data["type"] = data.get("kind") or CODE_EVIDENCE_TYPE
    if "source_refs" not in data and data.get("source_ref"):
        data["source_refs"] = [data["source_ref"]]
    if not str(data.get("symbol") or "").strip():
        data["symbol"] = (
            f"{data.get('path')}:{data.get('line_start')}-{data.get('line_end')}"
        )
    if public_guidance:
        data["public_guidance"] = public_guidance
    return CodeEvidenceRecord.from_dict(data)


@router.post("/{candidate_id}/approve", response_model=KnowledgeUpdateApproveResponse)
async def approve_knowledge_update(
    candidate_id: int,
    request_body: KnowledgeReviewRequest,
    request: Request,
    background_tasks: BackgroundTasks,
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
        cluster = await _get_candidate_cluster(
            candidate_id=candidate_id,
            pipeline_service=pipeline_service,
            service=service,
        )
        proposal = await run_in_threadpool(
            lambda: service.approve(
                candidate=candidate,
                reviewer=request_body.reviewer,
                cluster=cluster,
                feedback_tags=request_body.feedback_tags,
                future_generator_note=request_body.future_generator_note,
            )
        )
        page_id = proposal.target_page_id or f"candidate-{candidate_id}"
        await run_in_threadpool(
            lambda: _approve_cluster_members(
                pipeline_service.repository,
                member_ids=_cluster_member_ids(candidate_id, cluster),
                reviewer=request_body.reviewer,
                page_ref=f"llm_wiki:{page_id}",
            )
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
        background_tasks.add_task(
            _run_automatic_coverage_reconciliation_safely,
            pipeline_service=pipeline_service,
            service=service,
            trigger_page_id=str(page_id),
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
    cluster = await _get_candidate_cluster(
        candidate_id=candidate_id,
        pipeline_service=pipeline_service,
        service=service,
    )
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
    await run_in_threadpool(
        lambda: _reject_cluster_members(
            pipeline_service.repository,
            member_ids=[
                member_id
                for member_id in _cluster_member_ids(candidate_id, cluster)
                if member_id != candidate_id
            ],
            reviewer=request_body.reviewer,
            reason=reason,
        )
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
    service: KnowledgeUpdateService = Depends(get_knowledge_update_service),
):
    """Move a knowledge update candidate to the end of its queue."""
    cluster = await _get_candidate_cluster(
        candidate_id=candidate_id,
        pipeline_service=pipeline_service,
        service=service,
    )
    await pipeline_service.skip_candidate(candidate_id=candidate_id)
    await run_in_threadpool(
        lambda: _skip_cluster_members(
            pipeline_service.repository,
            member_ids=[
                member_id
                for member_id in _cluster_member_ids(candidate_id, cluster)
                if member_id != candidate_id
            ],
        )
    )
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
