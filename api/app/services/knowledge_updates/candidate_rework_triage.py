"""AI-assisted triage for LLM Wiki candidates blocked by review gates.

The normal Knowledge Updates queue intentionally excludes candidates with
missing protocol, missing sources, protocol conflicts, or low reusability. This
module keeps those safety gates intact while reducing the manual backlog into
actionable groups: repair metadata, repair sources, review a cluster, or bulk
reject non-durable handoff cases.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

from app.services.knowledge_updates.topic_clusters import topic_cluster_key
from app.services.rag.llm_wiki_loader import ALLOWED_PROTOCOLS
from app.services.rag.protocol_detector import ProtocolDetector
from app.services.training.unified_repository import UnifiedFAQCandidate

REWORK_ACTION_PRIORITY = {
    "bulk_reject_non_durable": 0,
    "repair_metadata": 1,
    "repair_sources": 2,
    "review_cluster": 3,
    "manual_decision": 4,
}
RECOVERABLE_PROTOCOL_CONFIDENCE = 0.60
GROUP_EXAMPLE_LIMIT = 5


@dataclass(frozen=True)
class CandidateReworkExample:
    candidate_id: int
    question: str
    answer: str

    def to_response(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "question": self.question,
            "answer": self.answer,
        }


@dataclass(frozen=True)
class CandidateReworkSignal:
    candidate: UnifiedFAQCandidate
    issue_codes: tuple[str, ...]
    inferred_protocol: str | None
    inferred_protocol_confidence: float
    target_page_id: str | None
    target_page_title: str | None
    topic: str
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class CandidateReworkGroup:
    action: str
    reason: str
    candidate_ids: list[int]
    issue_codes: list[str]
    inferred_protocol: str | None
    inferred_protocol_confidence: float
    target_page_id: str | None
    target_page_title: str | None
    topic: str
    source_ref_count: int
    source_ref_examples: list[str]
    examples: list[CandidateReworkExample]
    requires_human_review: bool

    @property
    def size(self) -> int:
        return len(self.candidate_ids)

    def to_response(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "size": self.size,
            "candidate_ids": self.candidate_ids,
            "issue_codes": self.issue_codes,
            "inferred_protocol": self.inferred_protocol,
            "inferred_protocol_confidence": self.inferred_protocol_confidence,
            "target_page_id": self.target_page_id,
            "target_page_title": self.target_page_title,
            "topic": self.topic,
            "source_ref_count": self.source_ref_count,
            "source_ref_examples": self.source_ref_examples,
            "examples": [example.to_response() for example in self.examples],
            "requires_human_review": self.requires_human_review,
        }


@dataclass(frozen=True)
class CandidateReworkTriage:
    total_candidates: int
    total_blocked: int
    group_count: int
    action_counts: dict[str, int]
    issue_counts: dict[str, int]
    groups: list[CandidateReworkGroup]

    def to_response(self) -> dict[str, Any]:
        return {
            "total_candidates": self.total_candidates,
            "total_blocked": self.total_blocked,
            "group_count": self.group_count,
            "action_counts": self.action_counts,
            "issue_counts": self.issue_counts,
            "groups": [group.to_response() for group in self.groups],
        }


class CandidateReworkTriageService:
    """Group blocked candidates into machine-triaged rework actions."""

    def __init__(self, knowledge_update_service):
        self.knowledge_update_service = knowledge_update_service
        self.protocol_detector = ProtocolDetector()

    def build(
        self,
        candidates: Sequence[UnifiedFAQCandidate],
        *,
        limit: int | None = None,
    ) -> CandidateReworkTriage:
        signals = [
            self._signal(candidate)
            for candidate in candidates
            if self.knowledge_update_service.candidate_reviewability_issues(candidate)
        ]
        grouped = self._groups(signals)
        sorted_groups = sorted(
            grouped,
            key=lambda group: (
                REWORK_ACTION_PRIORITY.get(group.action, 99),
                -group.size,
                group.target_page_id or "",
                min(group.candidate_ids),
            ),
        )
        visible_groups = sorted_groups[:limit] if limit is not None else sorted_groups
        return CandidateReworkTriage(
            total_candidates=len(candidates),
            total_blocked=len(signals),
            group_count=len(sorted_groups),
            action_counts=dict(Counter(group.action for group in sorted_groups)),
            issue_counts=dict(
                Counter(issue for signal in signals for issue in signal.issue_codes)
            ),
            groups=visible_groups,
        )

    def _signal(self, candidate: UnifiedFAQCandidate) -> CandidateReworkSignal:
        issues = tuple(
            self.knowledge_update_service.candidate_reviewability_issues(candidate)
        )
        inferred_protocol, confidence = self._inferred_protocol(candidate)
        enriched = (
            replace(candidate, protocol=inferred_protocol)
            if inferred_protocol in ALLOWED_PROTOCOLS
            else candidate
        )
        cluster_key = self.knowledge_update_service.review_cluster_key(enriched)
        target_page_id = _target_page_id_from_cluster_key(cluster_key)
        topic = topic_cluster_key(enriched).split("|", 1)[-1]
        return CandidateReworkSignal(
            candidate=candidate,
            issue_codes=issues,
            inferred_protocol=inferred_protocol,
            inferred_protocol_confidence=confidence,
            target_page_id=target_page_id,
            target_page_title=None,
            topic=topic,
            source_refs=tuple(_source_refs(candidate.generated_answer_sources)),
        )

    def _groups(
        self, signals: Iterable[CandidateReworkSignal]
    ) -> list[CandidateReworkGroup]:
        buckets: dict[str, list[CandidateReworkSignal]] = defaultdict(list)
        for signal in signals:
            buckets[_group_key(signal)].append(signal)
        return [self._group(group) for group in buckets.values()]

    def _group(self, signals: list[CandidateReworkSignal]) -> CandidateReworkGroup:
        first = signals[0]
        issue_codes = sorted(
            {issue for signal in signals for issue in signal.issue_codes}
        )
        source_refs = _dedupe(ref for signal in signals for ref in signal.source_refs)
        confidence = min(signal.inferred_protocol_confidence for signal in signals)
        action, reason, requires_human_review = _action_for_group(signals, source_refs)
        return CandidateReworkGroup(
            action=action,
            reason=reason,
            candidate_ids=[signal.candidate.id for signal in signals],
            issue_codes=issue_codes,
            inferred_protocol=first.inferred_protocol,
            inferred_protocol_confidence=round(confidence, 3),
            target_page_id=first.target_page_id,
            target_page_title=first.target_page_title,
            topic=first.topic,
            source_ref_count=len(source_refs),
            source_ref_examples=source_refs[:8],
            examples=[
                CandidateReworkExample(
                    candidate_id=signal.candidate.id,
                    question=_clean(
                        signal.candidate.edited_question_text
                        or signal.candidate.question_text
                    ),
                    answer=_clean(
                        signal.candidate.edited_staff_answer
                        or signal.candidate.staff_answer
                    ),
                )
                for signal in signals[:GROUP_EXAMPLE_LIMIT]
            ],
            requires_human_review=requires_human_review,
        )

    def _inferred_protocol(
        self, candidate: UnifiedFAQCandidate
    ) -> tuple[str | None, float]:
        if candidate.protocol in ALLOWED_PROTOCOLS:
            return candidate.protocol, 1.0
        text = " ".join(
            str(value or "")
            for value in (
                candidate.edited_question_text,
                candidate.original_user_question,
                candidate.question_text,
                candidate.edited_staff_answer,
                candidate.staff_answer,
                candidate.generated_answer,
                candidate.category,
            )
        )
        source = candidate.source if candidate.source in {"bisq2", "matrix"} else None
        protocol, confidence = (
            self.protocol_detector.detect_protocol_with_source_default(
                text,
                source,
                return_confidence=True,
            )
        )
        if protocol in ALLOWED_PROTOCOLS:
            return protocol, confidence
        return None, confidence


def _action_for_group(
    signals: Sequence[CandidateReworkSignal],
    source_refs: Sequence[str],
) -> tuple[str, str, bool]:
    issue_sets = [set(signal.issue_codes) for signal in signals]
    if all("low_reusability" in issues for issues in issue_sets):
        return (
            "bulk_reject_non_durable",
            "The reviewed answer is operational handoff or too case-specific for durable LLM Wiki guidance.",
            False,
        )
    if (
        all("missing_source_refs" in issues for issues in issue_sets)
        and not source_refs
    ):
        return (
            "repair_sources",
            "Retrieve durable wiki/FAQ/code evidence for the cluster before generating an LLM Wiki proposal.",
            False,
        )
    if all(_metadata_repairable(signal) for signal in signals):
        return (
            "repair_metadata",
            "Protocol metadata can be inferred with enough confidence; reclassify before normal review.",
            False,
        )
    if len(signals) >= 3:
        return (
            "review_cluster",
            "Review as one clustered synthesis task rather than individual candidate rows.",
            True,
        )
    return (
        "manual_decision",
        "The safety gates found conflicting or insufficient signals that need a human decision.",
        True,
    )


def _metadata_repairable(signal: CandidateReworkSignal) -> bool:
    issues = set(signal.issue_codes)
    metadata_issues = {
        "missing_protocol",
        "unsupported_protocol",
        "protocol_conflict",
    }
    return (
        bool(issues & metadata_issues)
        and not issues - metadata_issues
        and signal.inferred_protocol in ALLOWED_PROTOCOLS
        and signal.inferred_protocol_confidence >= RECOVERABLE_PROTOCOL_CONFIDENCE
    )


def _group_key(signal: CandidateReworkSignal) -> str:
    family = "manual"
    issues = set(signal.issue_codes)
    if "low_reusability" in issues:
        family = "non_durable"
    elif "missing_source_refs" in issues:
        family = "source_repair"
    elif issues & {"missing_protocol", "unsupported_protocol", "protocol_conflict"}:
        family = "metadata_repair"
    return "|".join(
        [
            family,
            signal.inferred_protocol or "none",
            signal.target_page_id or "unknown-target",
            signal.topic,
        ]
    )


def _target_page_id_from_cluster_key(cluster_key: str) -> str | None:
    parts = cluster_key.split("|")
    return parts[1] if len(parts) >= 2 and parts[1] else None


def _source_refs(raw_sources: str | None) -> list[str]:
    if not raw_sources:
        return []
    try:
        parsed = json.loads(raw_sources)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    refs = []
    for source in parsed:
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("type") or source.get("category") or "").lower()
        title = str(source.get("title") or "").strip()
        if source_type == "wiki" and title:
            refs.append(f"wiki:{title}")
        elif source_type == "faq":
            value = str(source.get("id") or source.get("faq_id") or title).strip()
            if value:
                refs.append(f"faq:{value}")
        elif source_type == "llm_wiki" and title:
            refs.append(f"llm_wiki:{title}")
        elif source_type in {"code", "code_fact"}:
            source_ref = str(source.get("source_ref") or "").strip()
            if source_ref:
                refs.append(source_ref)
    return _dedupe(refs)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())
