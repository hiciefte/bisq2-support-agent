"""Reconcile pending candidates already covered by reviewed LLM Wiki pages."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol, Sequence

from app.core.config import Settings
from app.services.rag.llm_wiki_loader import LLMWikiLoader
from app.services.training.unified_repository import UnifiedFAQCandidate

HIGH_CONFIDENCE_THRESHOLD = 0.82
SPOT_CHECK_THRESHOLD = 0.65
MAX_SAFE_CONTRADICTION = 0.35
MAX_SAFE_HALLUCINATION = 0.35
MIN_HIGH_LEXICAL_SUPPORT = 0.38
MIN_SPOT_LEXICAL_SUPPORT = 0.25

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.IGNORECASE)
TOKEN_STOPWORDS = {
    "about",
    "after",
    "also",
    "answer",
    "because",
    "before",
    "bisq",
    "bitcoin",
    "could",
    "from",
    "have",
    "into",
    "need",
    "should",
    "that",
    "their",
    "there",
    "this",
    "trade",
    "user",
    "what",
    "when",
    "where",
    "which",
    "with",
    "without",
    "would",
    "your",
}


class CandidateApprovalRepository(Protocol):
    def approve_pending(
        self, candidate_id: int, reviewer: str, faq_id: str
    ) -> bool: ...

    def get_pending(
        self,
        source: Optional[str] = None,
        routing: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UnifiedFAQCandidate]: ...


@dataclass(frozen=True)
class LLMWikiCoverageItem:
    candidate_id: int
    action: str
    page_id: Optional[str]
    page_title: Optional[str]
    page_ref: Optional[str]
    confidence: float
    lexical_support: float
    source_overlap_count: int
    reasons: list[str]

    def to_response(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LLMWikiCoverageReconciliationReport:
    total_candidates: int
    high_confidence_count: int
    spot_check_count: int
    remaining_count: int
    applied_count: int
    skipped_stale_count: int
    items: list[LLMWikiCoverageItem]

    def to_response(self) -> dict[str, Any]:
        return {
            "total_candidates": self.total_candidates,
            "high_confidence_count": self.high_confidence_count,
            "spot_check_count": self.spot_check_count,
            "remaining_count": self.remaining_count,
            "applied_count": self.applied_count,
            "skipped_stale_count": self.skipped_stale_count,
            "items": [item.to_response() for item in self.items],
        }


@dataclass(frozen=True)
class _ReviewedPage:
    page_id: str
    title: str
    protocol: str
    source_refs: set[str]
    content: str

    @property
    def page_ref(self) -> str:
        return f"llm_wiki:{self.page_id}"


@dataclass(frozen=True)
class _CoverageScore:
    page: _ReviewedPage
    confidence: float
    lexical_support: float
    source_overlap_count: int
    reasons: list[str]


class LLMWikiCoverageReconciliationService:
    """Find pending candidates already answered by reviewed LLM Wiki knowledge."""

    def __init__(self, settings: Settings, loader: Optional[LLMWikiLoader] = None):
        self.settings = settings
        self.loader = loader or LLMWikiLoader()

    def reconcile(
        self,
        candidates: Sequence[UnifiedFAQCandidate | None],
        *,
        apply: bool,
        repository: Optional[CandidateApprovalRepository] = None,
        reviewer: str = "coverage-reconciliation",
    ) -> LLMWikiCoverageReconciliationReport:
        pages = self._reviewed_pages()
        items = [self._classify_candidate(candidate, pages) for candidate in candidates]
        applied_count = 0

        if apply:
            if repository is None:
                raise ValueError("repository is required when apply=True")
            applied_items: list[LLMWikiCoverageItem] = []
            for item in items:
                if item.action != "approve_covered" or item.page_ref is None:
                    applied_items.append(item)
                    continue
                applied = repository.approve_pending(
                    item.candidate_id,
                    reviewer,
                    item.page_ref,
                )
                if applied:
                    applied_count += 1
                    applied_items.append(item)
                else:
                    applied_items.append(
                        LLMWikiCoverageItem(
                            candidate_id=item.candidate_id,
                            action="skipped_stale",
                            page_id=item.page_id,
                            page_title=item.page_title,
                            page_ref=item.page_ref,
                            confidence=item.confidence,
                            lexical_support=item.lexical_support,
                            source_overlap_count=item.source_overlap_count,
                            reasons=[*item.reasons, "candidate_no_longer_pending"],
                        )
                    )
            items = applied_items

        return LLMWikiCoverageReconciliationReport(
            total_candidates=len([candidate for candidate in candidates if candidate]),
            high_confidence_count=sum(
                1 for item in items if item.action == "approve_covered"
            ),
            spot_check_count=sum(1 for item in items if item.action == "spot_check"),
            remaining_count=sum(1 for item in items if item.action == "leave_pending"),
            applied_count=applied_count,
            skipped_stale_count=sum(
                1 for item in items if item.action == "skipped_stale"
            ),
            items=items,
        )

    def reconcile_pending_repository(
        self,
        repository: CandidateApprovalRepository,
        *,
        apply: bool,
        reviewer: str = "coverage-reconciliation",
        page_size: int = 500,
    ) -> LLMWikiCoverageReconciliationReport:
        """Reconcile all currently pending candidates from a repository.

        The pending rows are gathered before any apply mutation so offset-based
        pagination cannot skip rows as candidates leave the pending queue.
        """
        candidates: list[UnifiedFAQCandidate] = []
        offset = 0
        while True:
            page = repository.get_pending(limit=page_size, offset=offset)
            if not page:
                break
            candidates.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)

        return self.reconcile(
            candidates,
            apply=apply,
            repository=repository if apply else None,
            reviewer=reviewer,
        )

    def _reviewed_pages(self) -> list[_ReviewedPage]:
        root = Path(self.settings.LLM_WIKI_DIR_PATH)
        pages: list[_ReviewedPage] = []
        if not root.exists():
            return pages

        for document in self.loader.load_documents(root):
            metadata = document.metadata
            page_id = str(metadata.get("id") or "").strip()
            title = str(metadata.get("title") or page_id).strip()
            protocol = str(metadata.get("protocol") or "").strip()
            source_refs = _string_set(metadata.get("source_refs"))
            if not page_id or not title or not protocol or not source_refs:
                continue
            pages.append(
                _ReviewedPage(
                    page_id=page_id,
                    title=title,
                    protocol=protocol,
                    source_refs=source_refs,
                    content=document.page_content,
                )
            )
        return pages

    def _classify_candidate(
        self,
        candidate: UnifiedFAQCandidate | None,
        pages: Sequence[_ReviewedPage],
    ) -> LLMWikiCoverageItem:
        if candidate is None:
            return _empty_item(candidate_id=-1, reason="missing_candidate")
        if candidate.review_status != "pending":
            return _empty_item(
                candidate_id=candidate.id,
                action="skipped_stale",
                reason="candidate_no_longer_pending",
            )
        if _unsafe_candidate(candidate):
            return _empty_item(
                candidate_id=candidate.id,
                reason="candidate_has_high_risk_scores",
            )

        best = self._best_score(candidate, pages)
        if best is None:
            return _empty_item(
                candidate_id=candidate.id, reason="no_reviewed_page_match"
            )

        action = "leave_pending"
        if _is_high_confidence(best):
            action = "approve_covered"
        elif best.confidence >= SPOT_CHECK_THRESHOLD:
            action = "spot_check"

        return LLMWikiCoverageItem(
            candidate_id=candidate.id,
            action=action,
            page_id=best.page.page_id,
            page_title=best.page.title,
            page_ref=best.page.page_ref,
            confidence=round(best.confidence, 3),
            lexical_support=round(best.lexical_support, 3),
            source_overlap_count=best.source_overlap_count,
            reasons=best.reasons,
        )

    def _best_score(
        self,
        candidate: UnifiedFAQCandidate,
        pages: Sequence[_ReviewedPage],
    ) -> Optional[_CoverageScore]:
        scores = [
            score
            for page in pages
            if _protocol_compatible(candidate.protocol, page.protocol)
            for score in [_score_page(candidate, page)]
            if score.confidence > 0
        ]
        if not scores:
            return None
        return max(scores, key=lambda score: score.confidence)


def _score_page(candidate: UnifiedFAQCandidate, page: _ReviewedPage) -> _CoverageScore:
    candidate_sources = _candidate_source_refs(candidate)
    llm_wiki_titles = _candidate_source_titles(candidate, "llm_wiki")
    exact_llm_wiki_match = _page_title_matches(page, llm_wiki_titles)
    source_overlap = candidate_sources.intersection(page.source_refs)
    lexical_support = _lexical_support(
        " ".join(
            value
            for value in [
                candidate.edited_question_text or candidate.question_text,
                candidate.edited_staff_answer or candidate.staff_answer,
            ]
            if value
        ),
        page.content,
    )

    reasons: list[str] = []
    confidence = 0.0
    if exact_llm_wiki_match:
        confidence += 0.58
        reasons.append("llm_wiki_source_match")
    if source_overlap:
        confidence += min(0.24, len(source_overlap) * 0.08)
        reasons.append("durable_source_overlap")
    if _has_strong_source_overlap(source_overlap):
        confidence += 0.12
        reasons.append("strong_source_overlap")
    if _category_signal(candidate.category, page):
        confidence += 0.06
        reasons.append("category_signal")
    confidence += min(0.28, lexical_support * 0.46)
    if lexical_support >= MIN_HIGH_LEXICAL_SUPPORT:
        reasons.append("lexically_supported")

    if (
        _has_strong_source_overlap(source_overlap)
        and lexical_support >= 0.55
        and not exact_llm_wiki_match
    ):
        confidence = max(confidence, 0.86)
        reasons.append("source_grounded_reviewed_coverage")

    if not exact_llm_wiki_match and not _has_strong_source_overlap(source_overlap):
        confidence = min(confidence, SPOT_CHECK_THRESHOLD - 0.01)
        reasons.append("needs_stronger_source_match")

    return _CoverageScore(
        page=page,
        confidence=min(confidence, 0.99),
        lexical_support=lexical_support,
        source_overlap_count=len(source_overlap),
        reasons=reasons or ["weak_match"],
    )


def _is_high_confidence(score: _CoverageScore) -> bool:
    has_source_gate = (
        "llm_wiki_source_match" in score.reasons
        or "strong_source_overlap" in score.reasons
    )
    return (
        has_source_gate
        and score.confidence >= HIGH_CONFIDENCE_THRESHOLD
        and score.lexical_support >= MIN_HIGH_LEXICAL_SUPPORT
    )


def _unsafe_candidate(candidate: UnifiedFAQCandidate) -> bool:
    contradiction = candidate.contradiction_score or 0.0
    hallucination = candidate.hallucination_risk or 0.0
    return (
        contradiction >= MAX_SAFE_CONTRADICTION
        or hallucination >= MAX_SAFE_HALLUCINATION
    )


def _protocol_compatible(candidate_protocol: Optional[str], page_protocol: str) -> bool:
    if not candidate_protocol:
        return False
    return page_protocol == "all" or candidate_protocol == page_protocol


def _candidate_source_refs(candidate: UnifiedFAQCandidate) -> set[str]:
    refs: set[str] = set()
    for source in _candidate_sources(candidate):
        source_type = str(source.get("type") or "").strip()
        title = str(source.get("title") or "").strip()
        source_ref = str(source.get("source_ref") or "").strip()
        if source_ref:
            refs.add(source_ref)
        elif source_type and title:
            refs.add(f"{source_type}:{title}")
    return refs


def _candidate_source_titles(
    candidate: UnifiedFAQCandidate,
    source_type: str,
) -> set[str]:
    return {
        str(source.get("title") or "").strip()
        for source in _candidate_sources(candidate)
        if str(source.get("type") or "").strip() == source_type
        and str(source.get("title") or "").strip()
    }


def _candidate_sources(candidate: UnifiedFAQCandidate) -> list[dict[str, Any]]:
    raw = candidate.generated_answer_sources
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _page_title_matches(page: _ReviewedPage, titles: set[str]) -> bool:
    normalized = {_slug(title) for title in titles}
    return _slug(page.title) in normalized or _slug(page.page_id) in normalized


def _has_strong_source_overlap(source_overlap: set[str]) -> bool:
    return len(source_overlap) >= 2 or any(
        ref.startswith("faq:") or ref.startswith("code:") for ref in source_overlap
    )


def _category_signal(category: Optional[str], page: _ReviewedPage) -> bool:
    if not category:
        return False
    category_tokens = _tokens(category)
    if not category_tokens:
        return False
    page_tokens = _tokens(f"{page.title} {page.content}")
    return bool(category_tokens.intersection(page_tokens))


def _lexical_support(candidate_text: str, page_text: str) -> float:
    candidate_counts = Counter(_tokens(candidate_text))
    if not candidate_counts:
        return 0.0
    page_tokens = _tokens(page_text)
    if not page_tokens:
        return 0.0
    matched = sum(
        count for token, count in candidate_counts.items() if token in page_tokens
    )
    total = sum(candidate_counts.values())
    return matched / total if total else 0.0


def _tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text or "")
        if len(token) > 2 and token.casefold() not in TOKEN_STOPWORDS
    }


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, Iterable):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _empty_item(
    *,
    candidate_id: int,
    reason: str,
    action: str = "leave_pending",
) -> LLMWikiCoverageItem:
    return LLMWikiCoverageItem(
        candidate_id=candidate_id,
        action=action,
        page_id=None,
        page_title=None,
        page_ref=None,
        confidence=0.0,
        lexical_support=0.0,
        source_overlap_count=0,
        reasons=[reason],
    )
