from pathlib import Path

from app.core.config import Settings
from app.services.knowledge_updates.candidate_rework_triage import (
    CandidateReworkTriageService,
)
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.training.unified_repository import UnifiedFAQCandidate


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
        "created_at": "2026-06-17T10:01:00+00:00",
        "updated_at": None,
        "protocol": "bisq_easy",
        "edited_staff_answer": None,
        "edited_question_text": None,
        "category": "reputation",
        "generated_answer_sources": '[{"type":"wiki","title":"Reputation"}]',
        "original_user_question": None,
        "original_staff_answer": None,
        "generation_confidence": 0.82,
        "has_correction": False,
    }
    values.update(overrides)
    return UnifiedFAQCandidate(**values)


def _service(tmp_path: Path) -> KnowledgeUpdateService:
    return KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )


def test_triage_repairs_missing_protocol_with_inferred_protocol(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    candidate = _candidate(
        id=10,
        source="bisq2",
        protocol=None,
        category="Account",
        question_text="How do I restore my Bisq 2 profile on another computer?",
        staff_answer=(
            "Bisq 2 profile recovery depends on the local data directory. "
            "Restore from a backup of the profile data instead of creating a "
            "new profile."
        ),
        generated_answer_sources='[{"type":"wiki","title":"Data directory"}]',
    )

    triage = CandidateReworkTriageService(service).build([candidate])

    assert triage.total_blocked == 1
    assert triage.action_counts == {"repair_metadata": 1}
    group = triage.groups[0]
    assert group.action == "repair_metadata"
    assert group.inferred_protocol == "bisq_easy"
    assert group.inferred_protocol_confidence >= 0.6
    assert group.candidate_ids == [10]
    assert group.issue_codes == ["missing_protocol"]


def test_triage_reinfers_conflicting_protocol(tmp_path: Path) -> None:
    service = _service(tmp_path)
    candidate = _candidate(
        id=11,
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

    triage = CandidateReworkTriageService(service).build([candidate])

    assert triage.total_blocked == 1
    assert triage.action_counts == {"repair_metadata": 1}
    group = triage.groups[0]
    assert group.action == "repair_metadata"
    assert group.inferred_protocol == "bisq_easy"
    assert group.target_page_id
    assert "protocol_conflict" in group.issue_codes


def test_triage_groups_missing_source_refs_for_source_repair(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    candidates = [
        _candidate(
            id=index,
            protocol="multisig_v1",
            category="Troubleshooting",
            question_text=(
                "My Bisq 1 deposit transaction is confirmed but the trade "
                "still says wait for blockchain confirmation. What should I do?"
            ),
            staff_answer=(
                "Check the deposit txid on a block explorer and use SPV resync "
                "if Bisq has stale wallet-chain state."
            ),
            generated_answer_sources=None,
        )
        for index in (21, 22, 23)
    ]

    triage = CandidateReworkTriageService(service).build(candidates)

    assert triage.total_blocked == 3
    assert triage.action_counts == {"repair_sources": 1}
    group = triage.groups[0]
    assert group.action == "repair_sources"
    assert group.size == 3
    assert group.candidate_ids == [21, 22, 23]
    assert group.inferred_protocol == "multisig_v1"
    assert group.issue_codes == ["missing_source_refs"]
    assert group.topic == "wallet_sync_or_spv"


def test_triage_marks_low_reusability_as_bulk_reject(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    candidates = [
        _candidate(
            id=index,
            protocol=None,
            question_text="My account is temporarily locked. How can I notify my counterparty?",
            staff_answer="Notify the counterparty in the trade chat.",
            generated_answer_sources=None,
        )
        for index in (31, 32)
    ]

    triage = CandidateReworkTriageService(service).build(candidates)

    assert triage.total_blocked == 2
    assert triage.action_counts == {"bulk_reject_non_durable": 1}
    group = triage.groups[0]
    assert group.action == "bulk_reject_non_durable"
    assert group.size == 2
    assert group.requires_human_review is False
    assert "low_reusability" in group.issue_codes
