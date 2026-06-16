import sqlite3
from pathlib import Path

from app.core.config import Settings
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.training.unified_repository import UnifiedFAQCandidate


def _candidate(**overrides) -> UnifiedFAQCandidate:
    values = {
        "id": 7,
        "source": "matrix",
        "source_event_id": "$event",
        "source_timestamp": "2026-05-13T10:00:00+00:00",
        "question_text": "Do buyers need reputation in Bisq Easy?",
        "staff_answer": "Buyers can buy BTC in Bisq Easy without reputation. Seller reputation is the main safety signal.",
        "generated_answer": None,
        "staff_sender": "support",
        "embedding_similarity": None,
        "factual_alignment": None,
        "contradiction_score": 0.05,
        "completeness": None,
        "hallucination_risk": 0.1,
        "final_score": None,
        "llm_reasoning": None,
        "routing": "FULL_REVIEW",
        "review_status": "pending",
        "reviewed_by": None,
        "reviewed_at": None,
        "rejection_reason": None,
        "faq_id": None,
        "is_calibration_sample": True,
        "created_at": "2026-05-13T10:01:00+00:00",
        "updated_at": None,
        "protocol": "bisq_easy",
        "edited_staff_answer": None,
        "edited_question_text": None,
        "category": "reputation",
        "generated_answer_sources": '[{"type":"wiki","title":"Reputation"},{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]',
        "original_user_question": None,
        "original_staff_answer": None,
        "generation_confidence": 0.82,
        "has_correction": False,
    }
    values.update(overrides)
    return UnifiedFAQCandidate(**values)


def _write_page(data_dir: Path) -> Path:
    llm_wiki_dir = data_dir / "knowledge" / "llm_wiki" / "pages"
    llm_wiki_dir.mkdir(parents=True)
    page = llm_wiki_dir / "bisq2-reputation-basics.md"
    page.write_text(
        """---
id: bisq2-reputation-basics
title: Bisq Easy reputation basics
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: support-admin
reviewed_at: "2026-05-12"
risk_level: medium
source_refs:
  - wiki:Reputation
---
## Canonical Support Answer

Bisq Easy uses seller reputation as its main safety mechanism.

## Applies When

- The user asks about seller reputation.

## Do Not Say

- Do not say reputation can be transferred.

## Evidence / Sources

- `wiki:Reputation`

## Review Notes

## Last Change Summary

Initial page.
""",
        encoding="utf-8",
    )
    return page


def test_generates_existing_page_diff_with_checks(tmp_path: Path) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )

    proposal = service.get_or_create_proposal(candidate=_candidate())

    assert proposal.proposal_kind == "update_existing"
    assert proposal.target_page_id == "bisq2-reputation-basics"
    assert any(
        op["section"] == "Canonical Support Answer" for op in proposal.operations
    )
    assert "wiki:Reputation" in proposal.source_refs
    assert "llm_wiki:Bisq Easy reputation basics" in proposal.source_refs
    assert "support:matrix:$event" not in proposal.source_refs
    assert all(
        check["status"] != "fail" for check in proposal.checks if check["blocking"]
    )


def test_approve_writes_reviewed_llm_wiki_markdown(tmp_path: Path) -> None:
    page = _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate()
    proposal = service.get_or_create_proposal(candidate=candidate)
    operations = [
        (
            {
                **operation,
                "content": "Buyers can start in Bisq Easy without reputation.",
            }
            if operation["id"] == "canonical-answer"
            else operation
        )
        for operation in proposal.operations
    ]

    service.update_operations(candidate=candidate, operations=operations)
    approved = service.approve(candidate=candidate, reviewer="admin")

    written = page.read_text(encoding="utf-8")
    assert approved.status == "approved"
    assert "status: reviewed" in written
    assert "reviewed_by: admin" in written
    assert "Buyers can start in Bisq Easy without reputation." in written
    assert "support:matrix:$event" not in written


def test_approve_writes_full_document_override(tmp_path: Path) -> None:
    page = _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate()
    proposal = service.get_or_create_proposal(candidate=candidate)
    edited_markdown = proposal.preview_markdown.replace(
        "Seller reputation is the main safety signal.",
        "Seller reputation is the main safety signal, but buyers do not need their own reputation to start.",
    )

    updated = service.update_document_markdown(
        candidate=candidate,
        markdown=edited_markdown,
    )
    approved = service.approve(candidate=candidate, reviewer="admin")

    written = page.read_text(encoding="utf-8")
    assert updated.document_markdown_override is not None
    assert approved.status == "approved"
    assert "reviewed_by: admin" in written
    assert "buyers do not need their own reputation to start" in written
    assert "wiki:Reputation" in written
    assert "support:matrix:$event" not in written


def test_document_override_source_refs_drive_approval_checks(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=17,
        protocol="multisig_v1",
        category="fiat stablecoin routing",
        question_text="Can I send fiat to Bisq to buy stablecoins?",
        staff_answer="Users do not send fiat to Bisq itself.",
        generated_answer_sources="[]",
    )
    proposal = service.get_or_create_proposal(candidate=candidate)
    assert any(
        check["code"] == "source_refs" and check["status"] == "fail"
        for check in proposal.checks
    )
    assert "source_refs: []" in proposal.preview_markdown

    edited_markdown = proposal.preview_markdown.replace(
        "source_refs: []",
        "\n".join(
            [
                "source_refs:",
                "  - wiki:Payment methods",
                "  - wiki:Trading Monero",
                "  - wiki:Trade Protocols",
                "  - faq:1041",
            ]
        ),
    )
    updated = service.update_document_markdown(
        candidate=candidate,
        markdown=edited_markdown,
    )
    approved = service.approve(candidate=candidate, reviewer="admin")

    assert updated.source_refs == [
        "wiki:Payment methods",
        "wiki:Trading Monero",
        "wiki:Trade Protocols",
        "faq:1041",
    ]
    assert all(
        check["status"] != "fail" for check in updated.checks if check["blocking"]
    )
    written = (
        Path(settings.LLM_WIKI_DIR_PATH) / f"{proposal.target_page_id}.md"
    ).read_text(encoding="utf-8")
    assert approved.status == "approved"
    assert "source_refs:" in written
    assert "wiki:Payment methods" in written
    assert "status: reviewed" in written


def test_operation_update_clears_full_document_override(tmp_path: Path) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate()
    proposal = service.get_or_create_proposal(candidate=candidate)
    service.update_document_markdown(
        candidate=candidate,
        markdown=proposal.preview_markdown,
    )

    updated = service.update_operations(
        candidate=candidate,
        operations=proposal.operations,
    )

    assert updated.document_markdown_override is None


def test_faq_source_refs_prefer_durable_faq_id(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        generated_answer_sources=(
            '[{"type":"faq","title":"Why is the trade wizard not working?",'
            '"id":"1071","faq_id":"1071",'
            '"url":"/faq/why-is-the-trade-wizard-not-working-for-me-34be1021"}]'
        )
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert "faq:1071" in proposal.source_refs
    assert (
        "faq:why-is-the-trade-wizard-not-working-for-me-34be1021"
        not in proposal.source_refs
    )
    assert "support:matrix:$event" not in proposal.source_refs


def test_approval_blocks_invalid_operation(tmp_path: Path) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate()
    service.get_or_create_proposal(candidate=candidate)
    service.update_operations(
        candidate=candidate,
        operations=[
            {
                "id": "bad",
                "section": "Unsupported",
                "action": "append_paragraph",
                "content": "Invalid",
            }
        ],
    )

    try:
        service.approve(candidate=candidate, reviewer="admin")
    except ValueError as exc:
        assert "Structured diff schema" in str(exc)
    else:
        raise AssertionError("invalid structured diff should block approval")


def test_service_initializes_proposal_table(tmp_path: Path) -> None:
    db_path = tmp_path / "unified_training.db"
    KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)), db_path=str(db_path)
    )

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_update_proposals'"
    )
    assert cursor.fetchone() is not None
    conn.close()
