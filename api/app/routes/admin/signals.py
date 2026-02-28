"""Admin quality-signals routes.

This router consolidates feedback-driven quality signals and links them to
escalation cases for a single admin workflow across channels.
"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from app.core.security import verify_admin_access
from app.models.escalation import EscalationCreate, EscalationPriority, EscalationStatus
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

LINKED_ESCALATION_METADATA_KEY = "linked_escalation_id"

SignalFilter = Literal["all", "needs_action", "covered"]

router = APIRouter(
    prefix="/admin",
    tags=["Admin Signals"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


class SignalSummary(BaseModel):
    signal_id: str
    message_id: str
    channel: str
    rating: int
    timestamp: str
    question: str
    answer: str
    feedback_method: Optional[str] = None
    trust_level: Literal["asker", "non_asker", "staff", "untrusted"]
    coverage_state: Literal["not_linked", "linked_escalation", "auto_closed"]
    linked_escalation_id: Optional[int] = None
    linked_escalation_status: Optional[str] = None
    explanation: Optional[str] = None
    issues: List[str] = Field(default_factory=list)


class SignalListResponse(BaseModel):
    signals: List[SignalSummary]
    total: int
    actionable_count: int
    covered_count: int
    limit: int
    offset: int


class SignalCountsResponse(BaseModel):
    total: int
    actionable: int
    covered: int
    by_channel: Dict[str, int]


class ActionCountsResponse(BaseModel):
    pending_escalations: int
    open_escalations: int
    actionable_signals: int
    covered_signals: int
    total_signals: int
    unverified_faqs: int
    training_queue: int


class LinkCaseRequest(BaseModel):
    escalation_id: int = Field(..., ge=1)


class PromoteCaseRequest(BaseModel):
    reason: Optional[str] = Field(default="promoted_from_quality_signal")
    priority: Literal["normal", "high"] = "normal"


class ConversationOutcomeResponse(BaseModel):
    message_id: str
    signal: Optional[SignalSummary] = None
    escalation: Optional[Dict[str, Any]] = None
    recommended_action: Literal[
        "none",
        "review_case",
        "promote_case",
        "await_feedback",
    ] = "none"


def _parse_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _trust_level(
    metadata: Dict[str, Any],
) -> Literal["asker", "non_asker", "staff", "untrusted"]:
    if _parse_bool(metadata.get("is_staff")):
        return "staff"

    is_original_asker = _parse_bool(metadata.get("is_original_asker"))
    if is_original_asker is True:
        return "asker"
    if is_original_asker is False:
        return "non_asker"
    return "untrusted"


def _is_auto_closed_reaction_case(routing_reason: Optional[str]) -> bool:
    reason = (routing_reason or "").strip().lower()
    return reason.startswith("auto_reaction_negative") or reason == "reaction_reversed"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _feedback_matches_filters(
    feedback: Dict[str, Any],
    *,
    channel: Optional[str],
    rating: Optional[int],
    search: Optional[str],
) -> bool:
    if channel and _as_text(feedback.get("channel") or "web") != channel:
        return False
    if rating is not None and int(feedback.get("rating") or 0) != rating:
        return False
    if search:
        needle = search.strip().lower()
        if needle:
            question = _as_text(feedback.get("question")).lower()
            answer = _as_text(feedback.get("answer")).lower()
            if needle not in question and needle not in answer:
                return False
    return True


def _coverage_state_for_escalation(
    escalation: Any | None,
) -> Literal["not_linked", "linked_escalation", "auto_closed"]:
    if escalation is None:
        return "not_linked"
    if escalation.status == EscalationStatus.CLOSED and _is_auto_closed_reaction_case(
        escalation.routing_reason
    ):
        return "auto_closed"
    return "linked_escalation"


def _build_signal_summary(
    *,
    feedback: Dict[str, Any],
    metadata: Dict[str, Any],
    trust_level: Literal["asker", "non_asker", "staff", "untrusted"],
    coverage_state: Literal["not_linked", "linked_escalation", "auto_closed"],
    escalation: Any | None,
) -> SignalSummary:
    issues = metadata.get("issues")
    return SignalSummary(
        signal_id=_as_text(feedback.get("message_id")),
        message_id=_as_text(feedback.get("message_id")),
        channel=_as_text(feedback.get("channel") or "web"),
        rating=int(feedback.get("rating") or 0),
        timestamp=_as_text(feedback.get("timestamp")),
        question=_as_text(feedback.get("question")),
        answer=_as_text(feedback.get("answer")),
        feedback_method=feedback.get("feedback_method"),
        trust_level=trust_level,
        coverage_state=coverage_state,
        linked_escalation_id=escalation.id if escalation else None,
        linked_escalation_status=escalation.status.value if escalation else None,
        explanation=metadata.get("explanation"),
        issues=[str(issue) for issue in issues] if isinstance(issues, list) else [],
    )


async def _resolve_linked_escalation(
    feedback: Dict[str, Any],
    feedback_service,
    escalation_service,
):
    message_id = _as_text(feedback.get("message_id"))
    linked_id_raw = feedback_service.repository.get_feedback_metadata_value(
        message_id, LINKED_ESCALATION_METADATA_KEY
    )

    if linked_id_raw is not None:
        try:
            linked_id = int(linked_id_raw)
            linked = await escalation_service.repository.get_by_id(linked_id)
            if linked is not None:
                return linked
        except (TypeError, ValueError):
            logger.warning(
                "Invalid %s metadata for message_id=%s: %s",
                LINKED_ESCALATION_METADATA_KEY,
                message_id,
                linked_id_raw,
            )

    return await escalation_service.repository.get_by_message_id(message_id)


async def _to_signal_summary(
    feedback: Dict[str, Any],
    feedback_service,
    escalation_service,
) -> SignalSummary:
    metadata = feedback.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    escalation = await _resolve_linked_escalation(
        feedback=feedback,
        feedback_service=feedback_service,
        escalation_service=escalation_service,
    )
    return _build_signal_summary(
        feedback=feedback,
        metadata=metadata,
        trust_level=_trust_level(metadata),
        coverage_state=_coverage_state_for_escalation(escalation),
        escalation=escalation,
    )


async def get_feedback_service(request: Request):
    service = getattr(request.app.state, "feedback_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback service not available",
        )
    return service


async def get_escalation_service(request: Request):
    service = getattr(request.app.state, "escalation_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Escalation service not available",
        )
    return service


@router.get("/signals", response_model=SignalListResponse)
async def list_signals(
    status_filter: SignalFilter = Query("all", alias="status"),
    channel: Optional[str] = None,
    rating: Optional[int] = Query(default=None, ge=0, le=1),
    search: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    feedback_service=Depends(get_feedback_service),
    escalation_service=Depends(get_escalation_service),
) -> SignalListResponse:
    all_feedback = feedback_service.repository.get_all_feedback()
    filtered_feedback = [
        feedback
        for feedback in all_feedback
        if _feedback_matches_filters(
            feedback,
            channel=channel,
            rating=rating,
            search=search,
        )
    ]

    escalation_cache: Dict[str, Any | None] = {}
    selected: List[tuple[Dict[str, Any], Dict[str, Any], Any | None, Any, Any]] = []
    actionable_count = 0
    covered_count = 0

    for feedback in filtered_feedback:
        metadata = feedback.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        message_id = _as_text(feedback.get("message_id"))
        if message_id in escalation_cache:
            escalation = escalation_cache[message_id]
        else:
            escalation = await _resolve_linked_escalation(
                feedback=feedback,
                feedback_service=feedback_service,
                escalation_service=escalation_service,
            )
            escalation_cache[message_id] = escalation

        trust_level = _trust_level(metadata)
        coverage_state = _coverage_state_for_escalation(escalation)
        rating_value = int(feedback.get("rating") or 0)
        needs_action = (
            rating_value == 0
            and trust_level == "asker"
            and coverage_state == "not_linked"
        )
        if needs_action:
            actionable_count += 1
        if coverage_state != "not_linked":
            covered_count += 1

        include = status_filter == "all"
        if status_filter == "needs_action":
            include = needs_action
        elif status_filter == "covered":
            include = coverage_state != "not_linked"
        if include:
            selected.append(
                (feedback, metadata, escalation, trust_level, coverage_state)
            )

    total = len(selected)
    paginated_rows = selected[offset : offset + limit]
    paginated = [
        _build_signal_summary(
            feedback=feedback,
            metadata=metadata,
            trust_level=trust_level,
            coverage_state=coverage_state,
            escalation=escalation,
        )
        for feedback, metadata, escalation, trust_level, coverage_state in paginated_rows
    ]

    return SignalListResponse(
        signals=paginated,
        total=total,
        actionable_count=actionable_count,
        covered_count=covered_count,
        limit=limit,
        offset=offset,
    )


@router.get("/signals/counts", response_model=SignalCountsResponse)
async def get_signal_counts(
    feedback_service=Depends(get_feedback_service),
    escalation_service=Depends(get_escalation_service),
) -> SignalCountsResponse:
    all_feedback = feedback_service.repository.get_all_feedback()
    by_channel: Dict[str, int] = {}
    escalation_cache: Dict[str, Any | None] = {}
    actionable = 0
    covered = 0
    for feedback in all_feedback:
        channel_id = _as_text(feedback.get("channel") or "web")
        by_channel[channel_id] = by_channel.get(channel_id, 0) + 1

        metadata = feedback.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        message_id = _as_text(feedback.get("message_id"))
        if message_id in escalation_cache:
            escalation = escalation_cache[message_id]
        else:
            escalation = await _resolve_linked_escalation(
                feedback=feedback,
                feedback_service=feedback_service,
                escalation_service=escalation_service,
            )
            escalation_cache[message_id] = escalation

        trust_level = _trust_level(metadata)
        coverage_state = _coverage_state_for_escalation(escalation)
        rating_value = int(feedback.get("rating") or 0)
        if (
            rating_value == 0
            and trust_level == "asker"
            and coverage_state == "not_linked"
        ):
            actionable += 1
        if coverage_state != "not_linked":
            covered += 1

    return SignalCountsResponse(
        total=len(all_feedback),
        actionable=actionable,
        covered=covered,
        by_channel=by_channel,
    )


@router.get("/overview/action-counts", response_model=ActionCountsResponse)
async def get_overview_action_counts(
    request: Request,
    feedback_service=Depends(get_feedback_service),
    escalation_service=Depends(get_escalation_service),
) -> ActionCountsResponse:
    escalation_counts = await escalation_service.get_escalation_counts()
    signal_counts = await get_signal_counts(
        feedback_service=feedback_service,
        escalation_service=escalation_service,
    )

    unverified_faqs = 0
    faq_service = getattr(request.app.state, "faq_service", None)
    if faq_service is not None:
        try:
            faq_page = faq_service.get_faqs_paginated(
                page=1,
                page_size=1,
                verified=False,
            )
            unverified_faqs = int(getattr(faq_page, "total_count", 0))
        except Exception:
            logger.exception("Failed to fetch unverified FAQ count")

    training_queue = 0
    training_service = getattr(request.app.state, "unified_pipeline_service", None)
    if training_service is not None:
        try:
            queue_counts = training_service.get_queue_counts()
            training_queue = int(sum(int(v) for v in queue_counts.values()))
        except Exception:
            logger.exception("Failed to fetch training queue counts")

    return ActionCountsResponse(
        pending_escalations=escalation_counts.pending,
        open_escalations=escalation_counts.pending + escalation_counts.in_review,
        actionable_signals=signal_counts.actionable,
        covered_signals=signal_counts.covered,
        total_signals=signal_counts.total,
        unverified_faqs=unverified_faqs,
        training_queue=training_queue,
    )


@router.get(
    "/conversations/{message_id}/outcome",
    response_model=ConversationOutcomeResponse,
)
async def get_conversation_outcome(
    message_id: str,
    feedback_service=Depends(get_feedback_service),
    escalation_service=Depends(get_escalation_service),
) -> ConversationOutcomeResponse:
    feedback = feedback_service.repository.get_feedback_by_message_id(message_id)
    signal = (
        await _to_signal_summary(
            feedback=feedback,
            feedback_service=feedback_service,
            escalation_service=escalation_service,
        )
        if feedback
        else None
    )

    escalation = await escalation_service.repository.get_by_message_id(message_id)
    escalation_payload: Optional[Dict[str, Any]] = None
    if escalation is not None:
        escalation_payload = {
            "id": escalation.id,
            "status": escalation.status.value,
            "priority": escalation.priority.value,
            "routing_action": escalation.routing_action,
            "routing_reason": escalation.routing_reason,
            "staff_id": escalation.staff_id,
        }

    recommended_action: Literal[
        "none",
        "review_case",
        "promote_case",
        "await_feedback",
    ] = "none"
    if escalation is not None and escalation.status in {
        EscalationStatus.PENDING,
        EscalationStatus.IN_REVIEW,
    }:
        recommended_action = "review_case"
    elif escalation is not None and escalation.status == EscalationStatus.RESPONDED:
        recommended_action = "await_feedback"
    elif (
        signal is not None
        and signal.rating == 0
        and signal.trust_level == "asker"
        and signal.coverage_state == "not_linked"
    ):
        recommended_action = "promote_case"

    return ConversationOutcomeResponse(
        message_id=message_id,
        signal=signal,
        escalation=escalation_payload,
        recommended_action=recommended_action,
    )


@router.post("/signals/{signal_id}/link-case")
async def link_signal_to_case(
    signal_id: str,
    payload: LinkCaseRequest,
    feedback_service=Depends(get_feedback_service),
    escalation_service=Depends(get_escalation_service),
) -> Dict[str, Any]:
    feedback = feedback_service.repository.get_feedback_by_message_id(signal_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal {signal_id} not found",
        )

    escalation = await escalation_service.repository.get_by_id(payload.escalation_id)
    if escalation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Escalation {payload.escalation_id} not found",
        )

    ok = feedback_service.repository.set_feedback_metadata_value(
        signal_id,
        LINKED_ESCALATION_METADATA_KEY,
        payload.escalation_id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to link signal to escalation",
        )

    outcome = await get_conversation_outcome(
        message_id=signal_id,
        feedback_service=feedback_service,
        escalation_service=escalation_service,
    )
    return {"status": "linked", "outcome": outcome}


@router.post("/signals/{signal_id}/promote-case")
async def promote_signal_to_case(
    signal_id: str,
    payload: PromoteCaseRequest,
    feedback_service=Depends(get_feedback_service),
    escalation_service=Depends(get_escalation_service),
) -> Dict[str, Any]:
    feedback = feedback_service.repository.get_feedback_by_message_id(signal_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal {signal_id} not found",
        )

    existing = await escalation_service.repository.get_by_message_id(signal_id)
    if existing is None:
        metadata = feedback.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        confidence = metadata.get("confidence_score")
        try:
            confidence_score = float(confidence)
        except (TypeError, ValueError):
            confidence_score = 0.0

        priority = (
            EscalationPriority.HIGH
            if payload.priority == "high"
            else EscalationPriority.NORMAL
        )

        raw_channel_metadata = metadata.get("channel_metadata")
        parsed_channel_metadata = None
        if isinstance(raw_channel_metadata, str):
            try:
                parsed_channel_metadata = json.loads(raw_channel_metadata)
            except json.JSONDecodeError:
                parsed_channel_metadata = {"raw": raw_channel_metadata}
        elif isinstance(raw_channel_metadata, dict):
            parsed_channel_metadata = raw_channel_metadata

        if parsed_channel_metadata is None:
            parsed_channel_metadata = {
                "external_message_id": feedback.get("external_message_id"),
                "feedback_method": feedback.get("feedback_method"),
            }

        question_text = _as_text(feedback.get("question")).strip() or "Support request"
        ai_draft_answer = _as_text(feedback.get("answer")).strip()
        if not ai_draft_answer:
            ai_draft_answer = (
                "No AI draft answer was available for this signal. "
                "A support agent should provide a response."
            )

        try:
            create_payload = EscalationCreate(
                message_id=signal_id,
                channel=_as_text(feedback.get("channel") or "web"),
                user_id=_as_text(
                    metadata.get("user_id")
                    or metadata.get("actor_id")
                    or f"signal:{signal_id}"
                ),
                username=metadata.get("username"),
                channel_metadata=parsed_channel_metadata,
                question_original=question_text,
                question=question_text,
                ai_draft_answer_original=ai_draft_answer,
                ai_draft_answer=ai_draft_answer,
                user_language="en",
                translation_applied=False,
                confidence_score=max(0.0, min(1.0, confidence_score)),
                routing_action="needs_human",
                routing_reason=payload.reason or "promoted_from_quality_signal",
                sources=feedback.get("sources_used") or feedback.get("sources"),
                priority=priority,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot promote signal to escalation: {exc.errors()}",
            ) from exc
        existing = await escalation_service.create_escalation(create_payload)

    feedback_service.repository.set_feedback_metadata_value(
        signal_id,
        LINKED_ESCALATION_METADATA_KEY,
        existing.id,
    )

    outcome = await get_conversation_outcome(
        message_id=signal_id,
        feedback_service=feedback_service,
        escalation_service=escalation_service,
    )
    return {"status": "promoted", "escalation_id": existing.id, "outcome": outcome}
