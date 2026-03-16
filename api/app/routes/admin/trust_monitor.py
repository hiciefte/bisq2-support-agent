from __future__ import annotations

from datetime import UTC, datetime

from app.core.security import verify_admin_access
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(
    prefix="/admin/security",
    tags=["Admin Trust Monitor"],
    dependencies=[Depends(verify_admin_access)],
)


class TrustMonitorPolicyResponse(BaseModel):
    enabled: bool
    name_collision_enabled: bool
    silent_observer_enabled: bool
    alert_surface: str
    matrix_public_room_ids: list[str]
    matrix_staff_room_id: str
    silent_observer_window_days: int
    early_read_window_seconds: int
    minimum_observations: int
    minimum_early_read_hits: int
    read_to_reply_ratio_threshold: float
    evidence_ttl_days: int
    aggregate_ttl_days: int
    finding_ttl_days: int
    updated_at: str


class TrustMonitorPolicyPatchRequest(BaseModel):
    enabled: bool | None = None
    name_collision_enabled: bool | None = None
    silent_observer_enabled: bool | None = None
    alert_surface: str | None = None
    matrix_public_room_ids: list[str] | None = None
    matrix_staff_room_id: str | None = None
    silent_observer_window_days: int | None = None
    early_read_window_seconds: int | None = None
    minimum_observations: int | None = None
    minimum_early_read_hits: int | None = None
    read_to_reply_ratio_threshold: float | None = None
    evidence_ttl_days: int | None = None
    aggregate_ttl_days: int | None = None
    finding_ttl_days: int | None = None


class TrustFindingResponse(BaseModel):
    id: int
    detector_key: str
    channel_id: str
    space_id: str
    suspect_actor_id: str
    suspect_display_name: str
    score: float
    status: str
    alert_surface: str
    evidence_summary: dict
    created_at: str
    updated_at: str
    last_notified_at: str | None
    notification_count: int


class TrustFindingListResponse(BaseModel):
    items: list[TrustFindingResponse]
    total: int


class TrustFindingCountsResponse(BaseModel):
    total: int
    open: int
    resolved: int
    false_positive: int
    suppressed: int
    benign: int


class TrustAccessAuditResponse(BaseModel):
    id: int
    actor_id: str
    action: str
    target_type: str
    target_id: str
    metadata: dict
    created_at: str


class TrustAccessAuditListResponse(BaseModel):
    items: list[TrustAccessAuditResponse]


class TrustRetentionRunResponse(BaseModel):
    id: int
    created_at: str
    deleted_evidence_events: int
    deleted_actor_aggregates: int
    deleted_findings: int
    deleted_feedback: int
    deleted_access_audit: int


class TrustMonitorOpsResponse(BaseModel):
    monitored_public_rooms: list[str]
    staff_room_id: str
    evidence_events_count: int
    actor_aggregates_count: int
    findings_count: int
    oldest_evidence_age_seconds: float | None
    oldest_aggregate_age_seconds: float | None
    oldest_finding_age_seconds: float | None
    last_retention_run: TrustRetentionRunResponse | None


class ChatOpsAuditResponse(BaseModel):
    id: int
    channel_id: str
    room_id: str
    actor_id: str
    command_name: str
    case_id: int | None
    source_message_id: str
    ok: bool
    idempotent: bool
    metadata: dict
    created_at: str


class ChatOpsAuditListResponse(BaseModel):
    items: list[ChatOpsAuditResponse]


class FindingActionRequest(BaseModel):
    actor_id: str | None = None


def _policy_service(request: Request):
    service = getattr(request.app.state, "trust_monitor_policy_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="Trust monitor policy service unavailable"
        )
    return service


def _monitor_service(request: Request):
    service = getattr(request.app.state, "trust_monitor_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Trust monitor service unavailable")
    return service


def _policy_response(policy) -> TrustMonitorPolicyResponse:
    return TrustMonitorPolicyResponse(
        enabled=policy.enabled,
        name_collision_enabled=policy.name_collision_enabled,
        silent_observer_enabled=policy.silent_observer_enabled,
        alert_surface=policy.alert_surface.value,
        matrix_public_room_ids=policy.matrix_public_room_ids,
        matrix_staff_room_id=policy.matrix_staff_room_id,
        silent_observer_window_days=policy.silent_observer_window_days,
        early_read_window_seconds=policy.early_read_window_seconds,
        minimum_observations=policy.minimum_observations,
        minimum_early_read_hits=policy.minimum_early_read_hits,
        read_to_reply_ratio_threshold=policy.read_to_reply_ratio_threshold,
        evidence_ttl_days=policy.evidence_ttl_days,
        aggregate_ttl_days=policy.aggregate_ttl_days,
        finding_ttl_days=policy.finding_ttl_days,
        updated_at=policy.updated_at.isoformat(),
    )


def _finding_response(finding) -> TrustFindingResponse:
    return TrustFindingResponse(
        id=finding.id,
        detector_key=finding.detector_key,
        channel_id=finding.channel_id,
        space_id=finding.space_id,
        suspect_actor_id=finding.suspect_actor_id,
        suspect_display_name=finding.suspect_display_name,
        score=finding.score,
        status=finding.status.value,
        alert_surface=finding.alert_surface.value,
        evidence_summary=finding.evidence_summary,
        created_at=finding.created_at.isoformat(),
        updated_at=finding.updated_at.isoformat(),
        last_notified_at=(
            finding.last_notified_at.isoformat() if finding.last_notified_at else None
        ),
        notification_count=finding.notification_count,
    )


def _access_audit_response(entry) -> TrustAccessAuditResponse:
    return TrustAccessAuditResponse(
        id=entry.id,
        actor_id=entry.actor_id,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        metadata=entry.metadata,
        created_at=entry.created_at.isoformat(),
    )


def _retention_response(entry) -> TrustRetentionRunResponse | None:
    if entry is None:
        return None
    return TrustRetentionRunResponse(
        id=entry.id,
        created_at=entry.created_at.isoformat(),
        deleted_evidence_events=entry.deleted_evidence_events,
        deleted_actor_aggregates=entry.deleted_actor_aggregates,
        deleted_findings=entry.deleted_findings,
        deleted_feedback=entry.deleted_feedback,
        deleted_access_audit=entry.deleted_access_audit,
    )


def _ops_response(snapshot) -> TrustMonitorOpsResponse:
    return TrustMonitorOpsResponse(
        monitored_public_rooms=snapshot.monitored_public_rooms,
        staff_room_id=snapshot.staff_room_id,
        evidence_events_count=snapshot.evidence_events_count,
        actor_aggregates_count=snapshot.actor_aggregates_count,
        findings_count=snapshot.findings_count,
        oldest_evidence_age_seconds=snapshot.oldest_evidence_age_seconds,
        oldest_aggregate_age_seconds=snapshot.oldest_aggregate_age_seconds,
        oldest_finding_age_seconds=snapshot.oldest_finding_age_seconds,
        last_retention_run=_retention_response(snapshot.last_retention_run),
    )


def _chatops_audit_store(request: Request):
    store = getattr(request.app.state, "chatops_audit_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="ChatOps audit store unavailable")
    return store


@router.get("/trust-monitor/policy", response_model=TrustMonitorPolicyResponse)
def get_policy(request: Request) -> TrustMonitorPolicyResponse:
    return _policy_response(_policy_service(request).get_policy())


@router.patch("/trust-monitor/policy", response_model=TrustMonitorPolicyResponse)
def patch_policy(
    payload: TrustMonitorPolicyPatchRequest, request: Request
) -> TrustMonitorPolicyResponse:
    updated = _policy_service(request).set_policy(
        **payload.model_dump(exclude_none=True)
    )
    monitor_service = getattr(request.app.state, "trust_monitor_service", None)
    if monitor_service is not None:
        monitor_service.store.add_access_audit(
            actor_id="admin",
            action="policy_update",
            target_type="trust_monitor_policy",
            target_id="default",
            metadata=payload.model_dump(exclude_none=True),
            created_at=datetime.now(UTC),
        )
    return _policy_response(updated)


@router.get("/findings", response_model=TrustFindingListResponse)
def list_findings(
    request: Request, status_filter: str | None = None, detector_key: str | None = None
) -> TrustFindingListResponse:
    listing = _monitor_service(request).list_findings(
        status=status_filter, detector_key=detector_key
    )
    return TrustFindingListResponse(
        items=[_finding_response(item) for item in listing.items],
        total=listing.total,
    )


@router.get("/findings/counts", response_model=TrustFindingCountsResponse)
def count_findings(request: Request) -> TrustFindingCountsResponse:
    counts = _monitor_service(request).count_findings()
    return TrustFindingCountsResponse(
        total=counts.total,
        open=counts.open,
        resolved=counts.resolved,
        false_positive=counts.false_positive,
        suppressed=counts.suppressed,
        benign=counts.benign,
    )


@router.get("/trust-monitor/access-audit", response_model=TrustAccessAuditListResponse)
def list_access_audit(
    request: Request, limit: int = 20
) -> TrustAccessAuditListResponse:
    entries = _monitor_service(request).list_access_audit(limit=max(1, min(limit, 100)))
    return TrustAccessAuditListResponse(
        items=[_access_audit_response(entry) for entry in entries]
    )


@router.get("/trust-monitor/ops", response_model=TrustMonitorOpsResponse)
def get_ops_snapshot(request: Request) -> TrustMonitorOpsResponse:
    return _ops_response(_monitor_service(request).ops_snapshot())


@router.get("/chatops/audit", response_model=ChatOpsAuditListResponse)
def list_chatops_audit(
    request: Request, limit: int = 20, channel_id: str | None = None
) -> ChatOpsAuditListResponse:
    entries = _chatops_audit_store(request).list_entries(
        limit=max(1, min(limit, 100)),
        channel_id=channel_id,
    )
    return ChatOpsAuditListResponse(
        items=[
            ChatOpsAuditResponse(
                id=entry.id,
                channel_id=entry.channel_id,
                room_id=entry.room_id,
                actor_id=entry.actor_id,
                command_name=entry.command_name,
                case_id=entry.case_id,
                source_message_id=entry.source_message_id,
                ok=entry.ok,
                idempotent=entry.idempotent,
                metadata=entry.metadata,
                created_at=entry.created_at.isoformat(),
            )
            for entry in entries
        ]
    )


@router.post("/findings/{finding_id}/resolve", response_model=TrustFindingResponse)
def resolve_finding(
    finding_id: int, request: Request, payload: FindingActionRequest | None = None
) -> TrustFindingResponse:
    updated = _monitor_service(request).apply_feedback(
        finding_id,
        action="resolve",
        actor_id=(payload.actor_id if payload and payload.actor_id else "admin"),
    )
    return _finding_response(updated)


@router.post(
    "/findings/{finding_id}/false-positive", response_model=TrustFindingResponse
)
def false_positive(
    finding_id: int, request: Request, payload: FindingActionRequest | None = None
) -> TrustFindingResponse:
    updated = _monitor_service(request).apply_feedback(
        finding_id,
        action="false_positive",
        actor_id=(payload.actor_id if payload and payload.actor_id else "admin"),
    )
    return _finding_response(updated)


@router.post("/findings/{finding_id}/suppress", response_model=TrustFindingResponse)
def suppress_finding(
    finding_id: int, request: Request, payload: FindingActionRequest | None = None
) -> TrustFindingResponse:
    updated = _monitor_service(request).apply_feedback(
        finding_id,
        action="suppress",
        actor_id=(payload.actor_id if payload and payload.actor_id else "admin"),
    )
    return _finding_response(updated)


@router.post("/findings/{finding_id}/mark-benign", response_model=TrustFindingResponse)
def mark_benign(
    finding_id: int, request: Request, payload: FindingActionRequest | None = None
) -> TrustFindingResponse:
    updated = _monitor_service(request).apply_feedback(
        finding_id,
        action="mark_benign",
        actor_id=(payload.actor_id if payload and payload.actor_id else "admin"),
    )
    return _finding_response(updated)


# Resolve Pydantic forward references for FastAPI response models in isolated test imports.
TrustMonitorPolicyResponse.model_rebuild()
TrustFindingResponse.model_rebuild()
TrustFindingListResponse.model_rebuild()
TrustFindingCountsResponse.model_rebuild()
TrustAccessAuditResponse.model_rebuild()
TrustAccessAuditListResponse.model_rebuild()
TrustRetentionRunResponse.model_rebuild()
TrustMonitorOpsResponse.model_rebuild()
ChatOpsAuditResponse.model_rebuild()
ChatOpsAuditListResponse.model_rebuild()
