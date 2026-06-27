"""Promote code evidence into the normal LLM Wiki review workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import Settings
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateProposal,
    KnowledgeUpdateService,
)
from app.services.rag.code_evidence import CodeEvidenceRecord
from app.services.rag.source_refs import (
    CodeSourceRef,
    code_source_refs,
    imprecise_code_source_refs,
    parse_code_source_ref,
)
from app.services.training.unified_repository import (
    UnifiedFAQCandidate,
    UnifiedFAQCandidateRepository,
)


@dataclass(frozen=True)
class CodeEvidencePromotionResult:
    """Result of adding a code fact to the knowledge-update queue."""

    candidate: UnifiedFAQCandidate
    proposal: KnowledgeUpdateProposal


class CodeEvidencePromotionService:
    """Create reviewable LLM Wiki proposals from structured code evidence."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: UnifiedFAQCandidateRepository,
        knowledge_update_service: KnowledgeUpdateService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.knowledge_update_service = knowledge_update_service or KnowledgeUpdateService(
            settings=settings,
            db_path=repository.db_path,
        )

    def create_or_get_proposal(
        self,
        *,
        record: CodeEvidenceRecord,
        question: str | None = None,
        public_guidance: str | None = None,
    ) -> CodeEvidencePromotionResult:
        """Create or reuse a review candidate for a code evidence record."""
        guidance = _public_guidance(record=record, override=public_guidance)
        if not guidance:
            raise ValueError(
                "Code evidence promotion requires reviewed public guidance"
            )

        code_refs = code_source_refs(record.source_refs)
        if not code_refs:
            raise ValueError(
                "Code evidence promotion requires precise code source refs"
            )

        invalid_refs = imprecise_code_source_refs(record.source_refs)
        if invalid_refs:
            raise ValueError(
                "Code evidence promotion requires precise code source refs"
            )
        primary_ref = parse_code_source_ref(code_refs[0])
        if primary_ref is None or not _source_ref_matches_record(
            source_ref=primary_ref,
            record=record,
        ):
            raise ValueError(
                "Code evidence source refs must match the structured code evidence"
            )

        source_event_id = code_refs[0]
        candidate = self.repository.get_by_event_id(source_event_id)
        if candidate is None:
            candidate = self.repository.create(
                source="code_evidence",
                source_event_id=source_event_id,
                source_timestamp=datetime.now(timezone.utc).isoformat(),
                question_text=(
                    str(question or "").strip()
                    or _default_question(record)
                ),
                staff_answer=guidance,
                generated_answer=guidance,
                staff_sender="code-evidence-promotion",
                contradiction_score=0.0,
                hallucination_risk=_hallucination_risk(record),
                final_score=0.72,
                llm_reasoning=(
                    "Structured code evidence promoted into LLM Wiki review."
                ),
                routing="FULL_REVIEW",
                is_calibration_sample=False,
                category=_category(record),
                protocol=record.protocol,
                generated_answer_sources=json.dumps(
                    [_source_payload(record=record, guidance=guidance)]
                ),
                original_user_question=question,
                original_staff_answer=record.claim,
                generation_confidence=0.72,
            )

        proposal = self.knowledge_update_service.get_or_create_proposal(
            candidate=candidate
        )
        return CodeEvidencePromotionResult(candidate=candidate, proposal=proposal)


def _public_guidance(
    *,
    record: CodeEvidenceRecord,
    override: str | None,
) -> str:
    guidance = str(override or record.public_guidance or "").strip()
    return guidance


def _source_payload(
    *,
    record: CodeEvidenceRecord,
    guidance: str,
) -> dict[str, object]:
    source_ref = code_source_refs(record.source_refs)[0]
    return {
        "type": "code",
        "title": record.symbol,
        "source_ref": source_ref,
        "repo": record.repo,
        "commit": record.commit,
        "path": record.path,
        "line_start": record.line_start,
        "line_end": record.line_end,
        "protocol": record.protocol,
        "audience": record.audience,
        "freshness_class": record.freshness_class,
        "risk_level": record.risk_level,
        "applies_to_versions": list(record.applies_to_versions),
        "content": "\n".join(
            [
                record.claim,
                record.support_use,
                guidance,
            ]
        ),
    }


def _source_ref_matches_record(
    *,
    source_ref: CodeSourceRef,
    record: CodeEvidenceRecord,
) -> bool:
    return (
        source_ref.repo == record.repo
        and _same_commit(source_ref.commit, record.commit)
        and source_ref.path == record.path
        and source_ref.line_start == record.line_start
        and source_ref.line_end == record.line_end
    )


def _same_commit(left: str, right: str) -> bool:
    normalized_left = left.strip().lower()
    normalized_right = right.strip().lower()
    return (
        normalized_left == normalized_right
        or normalized_left.startswith(normalized_right)
        or normalized_right.startswith(normalized_left)
    )


def _category(record: CodeEvidenceRecord) -> str:
    text = f"{record.symbol} {record.claim} {record.support_use}".lower()
    if "exception" in text or "error" in text or "not found" in text:
        return "codebase error guidance"
    if "config" in text or "default" in text:
        return "codebase configuration guidance"
    return "codebase behavior guidance"


def _default_question(record: CodeEvidenceRecord) -> str:
    text = f"{record.claim} {record.support_use}".lower()
    if "not found" in text:
        return "What should a user do when an item can no longer be found?"
    if "exception" in text or "error" in text:
        return "What should a user do after seeing this error?"
    if "config" in text or "default" in text:
        return "How should support explain this configuration behavior?"
    return "How should support explain this product behavior?"


def _hallucination_risk(record: CodeEvidenceRecord) -> float:
    if record.risk_level == "high":
        return 0.35
    if record.risk_level == "medium":
        return 0.2
    return 0.1
