import sqlite3
from pathlib import Path

from app.core.config import Settings
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.knowledge_updates.topic_clusters import KnowledgeTopicCluster
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
    reloaded = service._load_page_by_id("bisq2-reputation-basics")
    assert reloaded is not None
    assert "Buyers can start in Bisq Easy without reputation." in reloaded.body


def test_topic_cluster_proposal_requires_document_synthesis(
    tmp_path: Path,
) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidates = [
        _candidate(
            id=1,
            question_text="Do buyers need reputation in Bisq Easy?",
            staff_answer="Buyers do not need reputation to buy BTC in Bisq Easy.",
        ),
        _candidate(
            id=2,
            question_text="Why does seller reputation matter in Bisq Easy?",
            staff_answer="Seller reputation is the main safety signal in Bisq Easy.",
        ),
        _candidate(
            id=3,
            question_text="Can a buyer start without their own reputation?",
            staff_answer="Buyers can start without reputation, but should prefer reputable sellers.",
        ),
    ]
    cluster = KnowledgeTopicCluster(
        key="bisq_easy|bisq_easy_reputation_or_risk",
        topic="bisq_easy_reputation_or_risk",
        candidates=candidates,
    )

    proposal = service.get_or_create_proposal(
        candidate=candidates[0],
        cluster=cluster,
    )

    assert any(
        operation["id"] == "cluster-synthesis" for operation in proposal.operations
    )
    assert "3 related support discussions" in proposal.preview_markdown
    assert any(
        check["code"] == "cluster_synthesis_review" and check["status"] == "fail"
        for check in proposal.checks
    )
    try:
        service.approve(candidate=candidates[0], reviewer="admin")
    except ValueError as exc:
        assert "Cluster synthesis review" in str(exc)
    else:
        raise AssertionError("cluster proposal should require an edited document")

    updated = service.update_document_markdown(
        candidate=candidates[0],
        markdown=proposal.preview_markdown.replace(
            "Buyers do not need reputation to buy BTC in Bisq Easy.",
            "Buyers do not need their own reputation to buy BTC in Bisq Easy, but should prefer sellers with strong reputation.",
        ),
    )

    assert any(
        check["code"] == "cluster_synthesis_review" and check["status"] == "pass"
        for check in updated.checks
    )


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


def test_low_source_support_adds_non_blocking_warning(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        staff_answer=(
            "Use the BSQ wallet receive tab in the DAO section when you need "
            "to receive BSQ from another Bisq user."
        ),
        generated_answer_sources=(
            '[{"type":"wiki","title":"System time",'
            '"content":"Users should synchronize their operating system clock with internet time."}]'
        ),
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    support_check = next(
        check for check in proposal.checks if check["code"] == "source_support"
    )
    assert support_check["status"] == "warn"
    assert support_check["blocking"] is False


def test_generated_markdown_uses_readable_durable_review_artifacts(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )

    proposal = service.get_or_create_proposal(candidate=_candidate())

    assert "Derived from reviewed" not in proposal.preview_markdown
    assert "$event" not in proposal.preview_markdown
    assert "Updated through the Knowledge Updates admin workflow." in (
        proposal.preview_markdown
    )
    assert "- `wiki:Reputation`" in proposal.preview_markdown
    assert "- `llm_wiki:Bisq Easy reputation basics`" in proposal.preview_markdown


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


def test_missing_protocol_does_not_match_protocol_specific_page(tmp_path: Path) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=31,
        protocol=None,
        category="Trading",
        question_text=(
            "I am temporarily locked out of my account but had an open trade. "
            "How can I notify my counterparty?"
        ),
        staff_answer="Notify the counterparty in the trade chat.",
        generated_answer_sources='[{"type":"wiki","title":"Bisq Easy"}]',
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert proposal.proposal_kind == "create_new"
    assert proposal.target_page_id != "bisq2-reputation-basics"
    assert any(
        check["code"] == "candidate_protocol" and check["status"] == "fail"
        for check in proposal.checks
    )
    assert any(
        check["code"] == "candidate_reusability" and check["status"] == "fail"
        for check in proposal.checks
    )


def test_thin_situational_answer_blocks_approval(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=32,
        protocol="multisig_v1",
        category="Trading",
        question_text=(
            "I am temporarily locked out of my account but had an open trade. "
            "How can I notify my counterparty?"
        ),
        staff_answer="Notify the counterparty in the trade chat.",
        generated_answer_sources='[{"type":"wiki","title":"Mediation"}]',
    )
    service.get_or_create_proposal(candidate=candidate)

    try:
        service.approve(candidate=candidate, reviewer="admin")
    except ValueError as exc:
        assert "Candidate reusability" in str(exc)
    else:
        raise AssertionError("thin situational candidate should block approval")


def test_exact_llm_wiki_source_can_match_reviewed_page(tmp_path: Path) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        generated_answer_sources=(
            '[{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert proposal.proposal_kind == "update_existing"
    assert proposal.target_page_id == "bisq2-reputation-basics"


def test_deprecated_llm_wiki_source_does_not_match_target(tmp_path: Path) -> None:
    page = _write_page(tmp_path)
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "status: reviewed", "status: deprecated"
        ),
        encoding="utf-8",
    )
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        generated_answer_sources=(
            '[{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert proposal.proposal_kind == "create_new"
    assert proposal.target_page_id != "bisq2-reputation-basics"


def test_candidate_reviewability_requires_protocol_sources_and_reusability(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        protocol=None,
        staff_answer="Notify the counterparty in the trade chat.",
        generated_answer_sources=None,
    )

    assert service.candidate_reviewability_issues(candidate) == [
        "missing_protocol",
        "missing_source_refs",
        "low_reusability",
    ]
    assert not service.is_candidate_reviewable(candidate)


def test_candidate_reviewability_rejects_protocols_not_supported_by_loader(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(protocol="musig")

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert service.candidate_reviewability_issues(candidate) == ["unsupported_protocol"]
    assert not service.is_candidate_reviewable(candidate)
    assert any(
        check["code"] == "candidate_protocol" and check["status"] == "fail"
        for check in proposal.checks
    )


def test_candidate_reviewability_rejects_conflicting_protocol_signal(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        protocol="multisig_v1",
        category="Troubleshooting",
        question_text=(
            "My Bisq2 says 0 connections to Tor and does not list any offers. "
            "Bisq1 connects just fine. Using MacOS version. Any ideas?"
        ),
        staff_answer=(
            "Ensure your system clock is synchronized with the internet clock. "
            "Also verify that you have downloaded the latest version of Bisq."
        ),
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert service.candidate_reviewability_issues(candidate) == ["protocol_conflict"]
    assert not service.is_candidate_reviewable(candidate)
    assert any(
        check["code"] == "candidate_protocol_consistency"
        and check["status"] == "fail"
        and check["blocking"] is True
        for check in proposal.checks
    )


def test_candidate_reviewability_allows_secondary_cross_version_reference(
    tmp_path: Path,
) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        protocol="multisig_v1",
        category="Payment Methods",
        question_text=(
            "Do accounts for buying using Cash by Mail (CBM) and US Postal Money "
            "Order (USPMO) need to include the name/address combination used on "
            "the mailed package? What about changing this information later? "
            "Are accounts signed after valid buys?"
        ),
        original_user_question=(
            "Trying to understand creating accounts for/using cash by mail and "
            "USPMO. Are the accounts signed after making a valid buy from a "
            "signed account, despite not being limited by signing, for use in "
            "Bisq2 signed age?"
        ),
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert "protocol_conflict" not in service.candidate_reviewability_issues(candidate)
    assert any(
        check["code"] == "candidate_protocol_consistency" and check["status"] == "pass"
        for check in proposal.checks
    )


def test_unsupported_protocol_does_not_use_exact_llm_wiki_source_match(
    tmp_path: Path,
) -> None:
    _write_page(tmp_path)
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        protocol="musig",
        generated_answer_sources='[{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]',
    )

    proposal = service.get_or_create_proposal(candidate=candidate)

    assert proposal.proposal_kind == "create_new"
    assert proposal.target_page_id != "bisq2-reputation-basics"


def test_candidate_reviewability_accepts_durable_candidate(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path))
    service = KnowledgeUpdateService(
        settings=settings,
        db_path=str(tmp_path / "unified_training.db"),
    )

    assert service.candidate_reviewability_issues(_candidate()) == []
    assert service.is_candidate_reviewable(_candidate())
