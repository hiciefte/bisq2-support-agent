from pathlib import Path

from app.core.config import Settings
from app.scripts.reconcile_llm_wiki_coverage import run_reconciliation
from app.services.training.unified_repository import UnifiedFAQCandidateRepository


def _write_page(data_dir: Path) -> None:
    llm_wiki_dir = data_dir / "knowledge" / "llm_wiki" / "pages"
    llm_wiki_dir.mkdir(parents=True, exist_ok=True)
    (llm_wiki_dir / "bisq2-reputation-basics.md").write_text(
        """---
id: bisq2-reputation-basics
title: Bisq Easy reputation basics
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: support-admin
reviewed_at: "2026-06-12"
risk_level: medium
source_refs:
  - wiki:Reputation
---
## Canonical Support Answer

Buyers can buy BTC in Bisq Easy without reputation. Seller reputation is the main safety signal.

## Applies When

- The user asks whether buyers need reputation in Bisq Easy.

## Do Not Say

- Do not say buyer reputation is required.

## Evidence / Sources

- `wiki:Reputation`
""",
        encoding="utf-8",
    )


def test_run_reconciliation_applies_pending_covered_candidates(tmp_path: Path) -> None:
    _write_page(tmp_path)
    db_path = tmp_path / "unified_training.db"
    repository = UnifiedFAQCandidateRepository(str(db_path))
    candidate = repository.create(
        source="matrix",
        source_event_id="$covered",
        source_timestamp="2026-06-17T10:00:00+00:00",
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

    result = run_reconciliation(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(db_path),
        apply=True,
    )

    assert result["applied_count"] == 1
    assert repository.get_by_id(candidate.id).review_status == "approved"
    assert repository.get_by_id(candidate.id).reviewed_by == "scheduled-coverage-reconciliation"


def test_run_reconciliation_supports_dry_run(tmp_path: Path) -> None:
    _write_page(tmp_path)
    db_path = tmp_path / "unified_training.db"
    repository = UnifiedFAQCandidateRepository(str(db_path))
    candidate = repository.create(
        source="matrix",
        source_event_id="$covered",
        source_timestamp="2026-06-17T10:00:00+00:00",
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

    result = run_reconciliation(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(db_path),
        apply=False,
    )

    assert result["high_confidence_count"] == 1
    assert result["applied_count"] == 0
    assert repository.get_by_id(candidate.id).review_status == "pending"
