from pathlib import Path

from app.core.config import Settings
from app.services.knowledge_updates.llm_wiki_coverage_reconciliation import (
    LLMWikiCoverageReconciliationService,
)
from app.services.training.unified_repository import (
    UnifiedFAQCandidate,
    UnifiedFAQCandidateRepository,
)


def _candidate(**overrides) -> UnifiedFAQCandidate:
    values = {
        "id": 1,
        "source": "matrix",
        "source_event_id": "$event",
        "source_timestamp": "2026-06-17T10:00:00+00:00",
        "question_text": "Do buyers need reputation in Bisq Easy?",
        "staff_answer": (
            "Buyers can buy BTC in Bisq Easy without reputation. "
            "Seller reputation is the main safety signal."
        ),
        "generated_answer": None,
        "staff_sender": "support",
        "embedding_similarity": None,
        "factual_alignment": None,
        "contradiction_score": 0.05,
        "completeness": None,
        "hallucination_risk": 0.05,
        "final_score": None,
        "llm_reasoning": None,
        "routing": "FULL_REVIEW",
        "review_status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "rejection_reason": None,
        "faq_id": None,
        "is_calibration_sample": True,
        "created_at": "2026-06-17T10:01:00+00:00",
        "updated_at": None,
        "protocol": "bisq_easy",
        "edited_staff_answer": None,
        "edited_question_text": None,
        "category": "reputation",
        "generated_answer_sources": (
            '[{"type":"wiki","title":"Reputation"},'
            '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
        "original_user_question": None,
        "original_staff_answer": None,
        "generation_confidence": 0.82,
        "has_correction": False,
    }
    values.update(overrides)
    return UnifiedFAQCandidate(**values)


def _write_page(
    data_dir: Path,
    *,
    page_id: str = "bisq2-reputation-basics",
    title: str = "Bisq Easy reputation basics",
    protocol: str = "bisq_easy",
    status: str = "reviewed",
    source_refs: str = "  - wiki:Reputation",
    body: str | None = None,
) -> Path:
    llm_wiki_dir = data_dir / "knowledge" / "llm_wiki" / "pages"
    llm_wiki_dir.mkdir(parents=True, exist_ok=True)
    page = llm_wiki_dir / f"{page_id}.md"
    page.write_text(
        f"""---
id: {page_id}
title: {title}
type: llm_wiki
page_type: support_playbook
status: {status}
protocol: {protocol}
reviewed_by: support-admin
reviewed_at: "2026-06-12"
risk_level: medium
source_refs:
{source_refs}
---
{body or '''## Canonical Support Answer

Buyers can buy BTC in Bisq Easy without reputation. Seller reputation is the main safety signal.

## Applies When

- The user asks whether buyers need reputation in Bisq Easy.
- The user asks why seller reputation matters.

## Do Not Say

- Do not say buyer reputation is required.

## Evidence / Sources

- `wiki:Reputation`

## Review Notes

## Last Change Summary

Reviewed support guidance.
'''}
""",
        encoding="utf-8",
    )
    return page


def test_dry_run_identifies_high_confidence_reviewed_wiki_coverage(
    tmp_path: Path,
) -> None:
    _write_page(tmp_path)
    service = LLMWikiCoverageReconciliationService(Settings(DATA_DIR=str(tmp_path)))

    report = service.reconcile([_candidate()], apply=False)

    assert report.applied_count == 0
    assert report.high_confidence_count == 1
    assert report.spot_check_count == 0
    assert report.remaining_count == 0
    assert report.items[0].candidate_id == 1
    assert report.items[0].action == "approve_covered"
    assert report.items[0].page_ref == "llm_wiki:bisq2-reputation-basics"
    assert report.items[0].confidence >= 0.9
    assert "llm_wiki_source_match" in report.items[0].reasons


def test_reconciliation_leaves_unsafe_or_unsupported_candidates_pending(
    tmp_path: Path,
) -> None:
    _write_page(tmp_path)
    service = LLMWikiCoverageReconciliationService(Settings(DATA_DIR=str(tmp_path)))

    report = service.reconcile(
        [
            _candidate(id=1, protocol="multisig_v1"),
            _candidate(id=2, contradiction_score=0.5),
            _candidate(
                id=3,
                generated_answer_sources='[{"type":"wiki","title":"Reputation"}]',
            ),
        ],
        apply=False,
    )

    assert report.high_confidence_count == 0
    assert report.spot_check_count == 0
    assert report.remaining_count == 3
    assert {item.action for item in report.items} == {"leave_pending"}


def test_strong_durable_source_overlap_can_cover_preexisting_candidates(
    tmp_path: Path,
) -> None:
    _write_page(
        tmp_path,
        source_refs="  - faq:buyer-reputation\n  - wiki:Reputation",
    )
    service = LLMWikiCoverageReconciliationService(Settings(DATA_DIR=str(tmp_path)))

    report = service.reconcile(
        [
            _candidate(
                generated_answer_sources=(
                    '[{"type":"faq","title":"buyer-reputation"},'
                    '{"type":"wiki","title":"Reputation"}]'
                ),
            )
        ],
        apply=False,
    )

    assert report.high_confidence_count == 1
    assert report.items[0].action == "approve_covered"
    assert "strong_source_overlap" in report.items[0].reasons
    assert "source_grounded_reviewed_coverage" in report.items[0].reasons


def test_apply_marks_only_pending_high_confidence_candidates_as_covered(
    tmp_path: Path,
) -> None:
    _write_page(tmp_path)
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    pending = repository.create(
        source="matrix",
        source_event_id="$covered",
        source_timestamp="2026-06-17T10:00:00+00:00",
        question_text="Do buyers need reputation in Bisq Easy?",
        staff_answer="Buyers can buy BTC in Bisq Easy without reputation. Seller reputation is the main safety signal.",
        protocol="bisq_easy",
        category="reputation",
        generated_answer_sources=(
            '[{"type":"wiki","title":"Reputation"},'
            '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
        contradiction_score=0.05,
        hallucination_risk=0.05,
    )
    stale = repository.create(
        source="matrix",
        source_event_id="$already-reviewed",
        source_timestamp="2026-06-17T10:05:00+00:00",
        question_text="Do buyers need reputation in Bisq Easy?",
        staff_answer="Buyers can buy BTC in Bisq Easy without reputation. Seller reputation is the main safety signal.",
        protocol="bisq_easy",
        category="reputation",
        generated_answer_sources=(
            '[{"type":"wiki","title":"Reputation"},'
            '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
        contradiction_score=0.05,
        hallucination_risk=0.05,
    )
    repository.reject(stale.id, reviewer="admin", reason="manual_reject")
    service = LLMWikiCoverageReconciliationService(Settings(DATA_DIR=str(tmp_path)))

    report = service.reconcile(
        [pending, repository.get_by_id(stale.id)],
        apply=True,
        repository=repository,
        reviewer="coverage-reconciliation",
    )

    updated_pending = repository.get_by_id(pending.id)
    updated_stale = repository.get_by_id(stale.id)
    assert report.applied_count == 1
    assert report.skipped_stale_count == 1
    assert updated_pending.review_status == "approved"
    assert updated_pending.reviewed_by == "coverage-reconciliation"
    assert updated_pending.faq_id == "llm_wiki:bisq2-reputation-basics"
    assert updated_stale.review_status == "rejected"


def test_apply_reports_stale_pending_write_once(tmp_path: Path) -> None:
    _write_page(tmp_path)

    class _StaleRepository:
        def approve_pending(self, candidate_id: int, reviewer: str, faq_id: str) -> bool:
            return False

    service = LLMWikiCoverageReconciliationService(Settings(DATA_DIR=str(tmp_path)))

    report = service.reconcile(
        [_candidate(id=91)],
        apply=True,
        repository=_StaleRepository(),
        reviewer="coverage-reconciliation",
    )

    assert report.applied_count == 0
    assert report.high_confidence_count == 0
    assert report.skipped_stale_count == 1
    assert report.items[0].action == "skipped_stale"
    assert report.items[0].reasons[-1] == "candidate_no_longer_pending"


def test_reconcile_pending_repository_gathers_before_applying(tmp_path: Path) -> None:
    _write_page(tmp_path)
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    candidates = [
        repository.create(
            source="matrix",
            source_event_id=f"$covered-{index}",
            source_timestamp=f"2026-06-17T10:0{index}:00+00:00",
            question_text="Do buyers need reputation in Bisq Easy?",
            staff_answer=(
                "Buyers can buy BTC in Bisq Easy without reputation. "
                "Seller reputation is the main safety signal."
            ),
            protocol="bisq_easy",
            category="reputation",
            generated_answer_sources=(
                '[{"type":"wiki","title":"Reputation"},'
                '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
            ),
            contradiction_score=0.05,
            hallucination_risk=0.05,
        )
        for index in range(3)
    ]
    service = LLMWikiCoverageReconciliationService(Settings(DATA_DIR=str(tmp_path)))

    report = service.reconcile_pending_repository(
        repository,
        apply=True,
        reviewer="auto-coverage-reconciliation",
        page_size=1,
    )

    assert report.applied_count == 3
    assert report.high_confidence_count == 3
    assert [
        repository.get_by_id(candidate.id).review_status for candidate in candidates
    ] == ["approved", "approved", "approved"]
