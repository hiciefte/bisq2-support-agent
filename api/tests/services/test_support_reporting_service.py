"""Tests for support-admin reporting aggregation."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from app.core.config import Settings
from app.services.admin_reporting_service import SupportReportingService
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.training.unified_repository import UnifiedFAQCandidateRepository


def _setup_reporting_db(tmp_path: Path) -> Path:
    settings = Settings(DATA_DIR=str(tmp_path))
    db_path = tmp_path / "unified_training.db"
    UnifiedFAQCandidateRepository(str(db_path))
    KnowledgeUpdateService(settings=settings, db_path=str(db_path))
    return db_path


def _create_candidate(
    db_path: Path,
    *,
    event_id: str,
    source: str = "matrix",
    routing: str = "FULL_REVIEW",
    protocol: str = "bisq_easy",
    category: str = "Trading",
) -> int:
    repo = UnifiedFAQCandidateRepository(str(db_path))
    candidate = repo.create(
        source=source,  # type: ignore[arg-type]
        source_event_id=event_id,
        source_timestamp="2026-06-01T09:00:00+00:00",
        question_text=f"Question for {event_id}",
        staff_answer="Staff answer",
        routing=routing,
        protocol=protocol,
        category=category,
    )
    return int(candidate.id)


def _insert_proposal(
    db_path: Path,
    *,
    candidate_id: int,
    target_page_id: str,
    target_page_title: str,
    proposal_kind: str,
    status: str,
    reviewed_by: str,
    reviewed_at: str,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO knowledge_update_proposals (
            candidate_id,
            target_page_id,
            target_page_path,
            target_page_title,
            proposal_kind,
            operations_json,
            preview_markdown,
            document_markdown_override,
            source_refs_json,
            checks_json,
            status,
            reviewed_by,
            reviewed_at,
            rejection_reason,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            candidate_id,
            target_page_id,
            f"api/data/knowledge/llm_wiki/pages/{target_page_id}.md",
            target_page_title,
            proposal_kind,
            json.dumps([]),
            "# Preview",
            json.dumps(["wiki:Bisq Easy"]),
            json.dumps([]),
            status,
            reviewed_by,
            reviewed_at,
            "2026-06-01T09:10:00+00:00",
            reviewed_at,
        ),
    )
    conn.commit()
    conn.close()


def test_support_work_report_aggregates_reviewed_llm_wiki_changes(
    tmp_path: Path,
) -> None:
    db_path = _setup_reporting_db(tmp_path)
    first = _create_candidate(
        db_path,
        event_id="$matrix-1",
        source="matrix",
        routing="FULL_REVIEW",
        protocol="bisq_easy",
        category="Onboarding",
    )
    second = _create_candidate(
        db_path,
        event_id="$matrix-2",
        source="matrix",
        routing="SPOT_CHECK",
        protocol="bisq_easy",
        category="Onboarding",
    )
    third = _create_candidate(
        db_path,
        event_id="bisq2-3",
        source="bisq2",
        routing="FULL_REVIEW",
        protocol="multisig_v1",
        category="Payment methods",
    )
    outside = _create_candidate(db_path, event_id="$outside")

    _insert_proposal(
        db_path,
        candidate_id=first,
        target_page_id="bisq-easy-basics",
        target_page_title="Bisq Easy basics",
        proposal_kind="update_existing",
        status="approved",
        reviewed_by="support-admin",
        reviewed_at="2026-06-01T10:00:00+00:00",
    )
    _insert_proposal(
        db_path,
        candidate_id=second,
        target_page_id="bisq-easy-basics",
        target_page_title="Bisq Easy basics",
        proposal_kind="update_existing",
        status="rejected",
        reviewed_by="support-admin",
        reviewed_at="2026-06-10T11:00:00+00:00",
    )
    _insert_proposal(
        db_path,
        candidate_id=third,
        target_page_id="fiat-payment-routing",
        target_page_title="Fiat payment routing",
        proposal_kind="create_new",
        status="approved",
        reviewed_by="second-reviewer",
        reviewed_at="2026-06-14T12:00:00+00:00",
    )
    _insert_proposal(
        db_path,
        candidate_id=outside,
        target_page_id="outside-window",
        target_page_title="Outside window",
        proposal_kind="create_new",
        status="approved",
        reviewed_by="support-admin",
        reviewed_at="2026-05-20T12:00:00+00:00",
    )

    report = SupportReportingService(db_path=str(db_path)).build_support_work_report(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 15),
        period_label="Cycle 62, blocks 840000-842000",
    )

    assert report["summary"] == {
        "total_reviews": 3,
        "approved": 2,
        "rejected": 1,
        "pages_touched": 2,
        "new_pages": 1,
        "existing_page_updates": 2,
    }
    assert report["reviewers"][0] == {
        "reviewer": "support-admin",
        "total_reviews": 2,
        "approved": 1,
        "rejected": 1,
    }
    assert report["pages"][0]["page_id"] == "bisq-easy-basics"
    assert report["pages"][0]["total_reviews"] == 2
    assert report["items"][0]["target_page_id"] == "fiat-payment-routing"
    assert "Cycle 62, blocks 840000-842000" in report["report_markdown"]
    assert "Total reviewed changes: 3" in report["report_markdown"]
    assert "Bisq Easy basics" in report["report_markdown"]


def test_support_work_report_filters_by_reviewer_and_includes_end_date(
    tmp_path: Path,
) -> None:
    db_path = _setup_reporting_db(tmp_path)
    alice_candidate = _create_candidate(db_path, event_id="$alice")
    bob_candidate = _create_candidate(db_path, event_id="$bob")
    _insert_proposal(
        db_path,
        candidate_id=alice_candidate,
        target_page_id="same-day",
        target_page_title="Same day",
        proposal_kind="update_existing",
        status="approved",
        reviewed_by="Alice",
        reviewed_at="2026-06-10T23:59:59+00:00",
    )
    _insert_proposal(
        db_path,
        candidate_id=bob_candidate,
        target_page_id="same-day",
        target_page_title="Same day",
        proposal_kind="update_existing",
        status="approved",
        reviewed_by="Bob",
        reviewed_at="2026-06-10T12:00:00+00:00",
    )

    report = SupportReportingService(db_path=str(db_path)).build_support_work_report(
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 10),
        reviewer="alice",
    )

    assert report["summary"]["total_reviews"] == 1
    assert report["reviewers"] == [
        {
            "reviewer": "Alice",
            "total_reviews": 1,
            "approved": 1,
            "rejected": 0,
        }
    ]
    assert report["items"][0]["reviewed_by"] == "Alice"


def test_support_work_report_rejects_inverted_period(tmp_path: Path) -> None:
    db_path = _setup_reporting_db(tmp_path)
    service = SupportReportingService(db_path=str(db_path))

    try:
        service.build_support_work_report(
            start_date=date(2026, 6, 16),
            end_date=date(2026, 6, 1),
        )
    except ValueError as exc:
        assert str(exc) == "start_date must be on or before end_date"
    else:
        raise AssertionError("Expected inverted reporting period to fail")
