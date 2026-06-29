from pathlib import Path

import app.routes.admin.knowledge_updates as knowledge_updates
import pytest
from app.core.config import Settings
from app.routes.admin.knowledge_updates import (
    ApplyKnowledgeReworkActionRequest,
    KnowledgeCoverageReconciliationRequest,
    KnowledgeReviewRequest,
    PromoteCodeEvidenceRequest,
    apply_knowledge_update_rework_action,
    approve_knowledge_update,
    get_current_knowledge_update,
    get_generator_feedback_records,
    get_knowledge_update_counts,
    get_knowledge_update_rework_triage,
    promote_code_evidence_to_knowledge_update,
    reconcile_reviewed_knowledge_coverage,
)
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.training.unified_repository import (
    UnifiedFAQCandidate,
    UnifiedFAQCandidateRepository,
)
from fastapi import HTTPException


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
        "contradiction_score": 0.0,
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


def _write_reviewed_llm_wiki_page(data_dir: Path) -> None:
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

## Review Notes

## Last Change Summary

Reviewed support guidance.
""",
        encoding="utf-8",
    )


class _Repository:
    def __init__(self, candidates):
        self.candidates = candidates
        self.stale_pending_write_ids = set()

    def get_pending(self, source=None, routing=None, limit=100, offset=0):
        rows = [
            candidate
            for candidate in self.candidates
            if candidate.review_status == "pending"
            and (routing is None or candidate.routing == routing)
            and (source is None or candidate.source == source)
        ]
        return rows[offset : offset + limit]

    def get_by_id(self, candidate_id):
        return next(
            (
                candidate
                for candidate in self.candidates
                if candidate.id == candidate_id
            ),
            None,
        )

    def approve(self, candidate_id, reviewer, faq_id):
        candidate = self.get_by_id(candidate_id)
        if candidate is not None:
            candidate.review_status = "approved"
            candidate.reviewed_by = reviewer
            candidate.faq_id = faq_id

    def approve_pending(self, candidate_id, reviewer, faq_id):
        candidate = self.get_by_id(candidate_id)
        if (
            candidate is None
            or candidate.review_status != "pending"
            or candidate.id in self.stale_pending_write_ids
        ):
            return False
        candidate.review_status = "approved"
        candidate.reviewed_by = reviewer
        candidate.faq_id = faq_id
        return True

    def reject(self, candidate_id, reviewer, reason, reason_note=None):
        candidate = self.get_by_id(candidate_id)
        if candidate is not None:
            candidate.review_status = "rejected"
            candidate.reviewed_by = reviewer
            candidate.rejection_reason = reason
            candidate.rejection_note = reason_note

    def reject_pending_many(self, candidate_ids, reviewer, reason, reason_note=None):
        candidates = [self.get_by_id(candidate_id) for candidate_id in candidate_ids]
        if any(
            candidate is None
            or candidate.review_status != "pending"
            or candidate.id in self.stale_pending_write_ids
            for candidate in candidates
        ):
            return 0
        for candidate in candidates:
            candidate.review_status = "rejected"
            candidate.reviewed_by = reviewer
            candidate.rejection_reason = reason
            candidate.rejection_note = reason_note
        return len(candidates)

    def reject_pending(self, candidate_id, reviewer, reason, reason_note=None):
        return (
            self.reject_pending_many([candidate_id], reviewer, reason, reason_note) == 1
        )

    def update_candidate(self, candidate_id, **updates):
        candidate = self.get_by_id(candidate_id)
        if candidate is None:
            return None
        updates.pop("require_pending", None)
        for key, value in updates.items():
            if value is not None and hasattr(candidate, key):
                setattr(candidate, key, value)
        return candidate

    def update_pending_candidate(self, candidate_id, **updates):
        candidate = self.get_by_id(candidate_id)
        if (
            candidate is None
            or candidate.review_status != "pending"
            or candidate.id in self.stale_pending_write_ids
        ):
            return None
        return self.update_candidate(candidate_id, **updates)


class _PipelineService:
    def __init__(self, candidates):
        self.repository = _Repository(candidates)
        self.regenerate_calls = []

    async def regenerate_candidate_answer(self, candidate_id, protocol):
        self.regenerate_calls.append((candidate_id, protocol))
        return self.repository.update_candidate(
            candidate_id,
            protocol=protocol,
            generated_answer="Regenerated answer with durable source support.",
            generated_answer_sources='[{"type":"wiki","title":"Wallet sync"}]',
            generation_confidence=0.81,
        )

    async def regenerate_pending_candidate_answer(self, candidate_id, protocol):
        candidate = self.repository.get_by_id(candidate_id)
        if (
            candidate is None
            or candidate.review_status != "pending"
            or candidate.id in self.repository.stale_pending_write_ids
        ):
            return None
        return await self.regenerate_candidate_answer(candidate_id, protocol)


@pytest.mark.asyncio
async def test_knowledge_update_counts_only_include_reviewable_candidates(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(id=1, routing="FULL_REVIEW"),
            _candidate(
                id=2,
                routing="FULL_REVIEW",
                protocol=None,
                generated_answer_sources=None,
            ),
            _candidate(id=3, routing="SPOT_CHECK"),
        ]
    )

    counts = await get_knowledge_update_counts(
        pipeline_service=pipeline,
        service=service,
    )

    assert counts == {"AUTO_APPROVE": 0, "SPOT_CHECK": 1, "FULL_REVIEW": 1}


@pytest.mark.asyncio
async def test_reviewed_knowledge_coverage_dry_run_does_not_mutate_candidates(
    tmp_path: Path,
) -> None:
    _write_reviewed_llm_wiki_page(tmp_path)
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    covered = _candidate(
        id=41,
        generated_answer_sources=(
            '[{"type":"wiki","title":"Reputation"},'
            '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
    )
    pipeline = _PipelineService([covered])
    request = _Request()

    response = await reconcile_reviewed_knowledge_coverage(
        request_body=KnowledgeCoverageReconciliationRequest(apply=False),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response["high_confidence_count"] == 1
    assert response["applied_count"] == 0
    assert response["items"][0]["action"] == "approve_covered"
    assert response["items"][0]["page_ref"] == "llm_wiki:bisq2-reputation-basics"
    assert pipeline.repository.get_by_id(41).review_status == "pending"


@pytest.mark.asyncio
async def test_reviewed_knowledge_coverage_apply_marks_safe_matches_approved(
    tmp_path: Path,
) -> None:
    _write_reviewed_llm_wiki_page(tmp_path)
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    covered = _candidate(
        id=51,
        generated_answer_sources=(
            '[{"type":"wiki","title":"Reputation"},'
            '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
    )
    unsafe = _candidate(
        id=52,
        contradiction_score=0.6,
        generated_answer_sources=(
            '[{"type":"wiki","title":"Reputation"},'
            '{"type":"llm_wiki","title":"Bisq Easy reputation basics"}]'
        ),
    )
    pipeline = _PipelineService([covered, unsafe])
    request = _Request()

    response = await reconcile_reviewed_knowledge_coverage(
        request_body=KnowledgeCoverageReconciliationRequest(apply=True),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response["high_confidence_count"] == 1
    assert response["applied_count"] == 1
    assert response["remaining_count"] == 1
    assert pipeline.repository.get_by_id(51).review_status == "approved"
    assert pipeline.repository.get_by_id(51).reviewed_by == "support-admin"
    assert pipeline.repository.get_by_id(51).faq_id == "llm_wiki:bisq2-reputation-basics"
    assert pipeline.repository.get_by_id(52).review_status == "pending"


@pytest.mark.asyncio
async def test_rework_triage_endpoint_groups_blocked_candidates(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(id=1, routing="FULL_REVIEW"),
            _candidate(
                id=2,
                routing="FULL_REVIEW",
                protocol=None,
                source="bisq2",
                category="Account",
                question_text="How do I restore my Bisq 2 profile on another computer?",
                generated_answer_sources='[{"type":"wiki","title":"Data directory"}]',
            ),
            _candidate(
                id=3,
                routing="FULL_REVIEW",
                protocol=None,
                question_text="My account is temporarily locked. How do I notify my counterparty?",
                staff_answer="Notify the counterparty in the trade chat.",
                generated_answer_sources=None,
            ),
        ]
    )

    response = await get_knowledge_update_rework_triage(
        pipeline_service=pipeline,
        service=service,
    )

    assert response["total_blocked"] == 2
    assert response["action_counts"] == {
        "bulk_reject_non_durable": 1,
        "repair_metadata": 1,
    }
    assert response["group_count"] == 2
    assert response["groups"][0]["action"] == "bulk_reject_non_durable"
    assert response["groups"][1]["action"] == "repair_metadata"


@pytest.mark.asyncio
async def test_rework_triage_endpoint_limits_visible_groups(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(
                id=1,
                routing="FULL_REVIEW",
                protocol=None,
                source="bisq2",
                category="Account",
                question_text="How do I restore my Bisq 2 profile on another computer?",
                generated_answer_sources='[{"type":"wiki","title":"Data directory"}]',
            ),
            _candidate(
                id=2,
                routing="FULL_REVIEW",
                protocol=None,
                question_text="My account is temporarily locked. How do I notify my counterparty?",
                staff_answer="Notify the counterparty in the trade chat.",
                generated_answer_sources=None,
            ),
        ]
    )

    response = await get_knowledge_update_rework_triage(
        limit=1,
        pipeline_service=pipeline,
        service=service,
    )

    assert response["total_blocked"] == 2
    assert response["group_count"] == 2
    assert len(response["groups"]) == 1
    assert response["groups"][0]["action"] == "bulk_reject_non_durable"


def test_rework_action_request_does_not_accept_spoofable_reviewer() -> None:
    assert "reviewer" not in ApplyKnowledgeReworkActionRequest.model_fields


@pytest.mark.asyncio
async def test_rework_action_bulk_rejects_non_durable_group(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
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
    pipeline = _PipelineService([*candidates, _candidate(id=33)])
    request = _Request()
    request.app.state.learning_engine = None

    response = await apply_knowledge_update_rework_action(
        request_body=ApplyKnowledgeReworkActionRequest(
            action="bulk_reject_non_durable",
            candidate_ids=[31, 32],
        ),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response["success"] is True
    assert response["rejected_count"] == 2
    assert response["updated_count"] == 0
    assert response["proposal_count"] == 0
    assert pipeline.repository.get_by_id(31).review_status == "rejected"
    assert pipeline.repository.get_by_id(31).reviewed_by == "support-admin"
    assert pipeline.repository.get_by_id(32).rejection_reason == "not_durable"
    assert (
        "AI-assisted rework triage" in pipeline.repository.get_by_id(32).rejection_note
    )
    assert pipeline.repository.get_by_id(33).review_status == "pending"


@pytest.mark.asyncio
async def test_rework_action_bulk_reject_detects_stale_pending_write(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidates = [
        _candidate(
            id=index,
            protocol=None,
            question_text="My account is temporarily locked. How can I notify my counterparty?",
            staff_answer="Notify the counterparty in the trade chat.",
            generated_answer_sources=None,
        )
        for index in (34, 35)
    ]
    pipeline = _PipelineService(candidates)
    pipeline.repository.stale_pending_write_ids.add(34)
    request = _Request()
    request.app.state.learning_engine = None

    with pytest.raises(HTTPException) as exc_info:
        await apply_knowledge_update_rework_action(
            request_body=ApplyKnowledgeReworkActionRequest(
                action="bulk_reject_non_durable",
                candidate_ids=[34, 35],
            ),
            request=request,
            pipeline_service=pipeline,
            service=service,
        )

    assert exc_info.value.status_code == 409
    assert [candidate.review_status for candidate in candidates] == [
        "pending",
        "pending",
    ]


@pytest.mark.asyncio
async def test_rework_action_repairs_metadata_and_prepares_normal_proposal(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=41,
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
    pipeline = _PipelineService([candidate])
    request = _Request()
    request.app.state.learning_engine = None

    response = await apply_knowledge_update_rework_action(
        request_body=ApplyKnowledgeReworkActionRequest(
            action="repair_metadata",
            candidate_ids=[41],
        ),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    updated = pipeline.repository.get_by_id(41)
    proposal = service.get_by_candidate_id(41)
    assert response["success"] is True
    assert response["updated_count"] == 1
    assert response["proposal_count"] == 1
    assert response["remaining_blocked_count"] == 0
    assert updated.protocol == "bisq_easy"
    assert proposal is not None
    assert proposal.status == "pending"


@pytest.mark.asyncio
async def test_rework_action_metadata_repair_detects_stale_pending_write(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=42,
        source="bisq2",
        protocol=None,
        category="Account",
        question_text="How do I restore my Bisq 2 profile on another computer?",
        generated_answer_sources='[{"type":"wiki","title":"Data directory"}]',
    )
    pipeline = _PipelineService([candidate])
    pipeline.repository.stale_pending_write_ids.add(42)
    request = _Request()
    request.app.state.learning_engine = None

    with pytest.raises(HTTPException) as exc_info:
        await apply_knowledge_update_rework_action(
            request_body=ApplyKnowledgeReworkActionRequest(
                action="repair_metadata",
                candidate_ids=[42],
            ),
            request=request,
            pipeline_service=pipeline,
            service=service,
        )

    assert exc_info.value.status_code == 409
    assert pipeline.repository.get_by_id(42).protocol is None
    assert service.get_by_candidate_id(42) is None


@pytest.mark.asyncio
async def test_rework_action_repairs_sources_through_rag_regeneration(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=51,
        protocol="multisig_v1",
        category="Troubleshooting",
        question_text=(
            "My Bisq 1 deposit transaction is confirmed but the trade still "
            "says wait for blockchain confirmation. What should I do?"
        ),
        staff_answer=(
            "Check the deposit txid on a block explorer and use SPV resync "
            "if Bisq has stale wallet-chain state."
        ),
        generated_answer_sources=None,
    )
    pipeline = _PipelineService([candidate])
    request = _Request()
    request.app.state.learning_engine = None

    response = await apply_knowledge_update_rework_action(
        request_body=ApplyKnowledgeReworkActionRequest(
            action="repair_sources",
            candidate_ids=[51],
        ),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    updated = pipeline.repository.get_by_id(51)
    proposal = service.get_by_candidate_id(51)
    assert response["success"] is True
    assert response["updated_count"] == 1
    assert response["proposal_count"] == 1
    assert response["remaining_blocked_count"] == 0
    assert pipeline.regenerate_calls == [(51, "multisig_v1")]
    assert updated.generated_answer_sources == '[{"type":"wiki","title":"Wallet sync"}]'
    assert proposal is not None
    assert "wiki:Wallet sync" in proposal.source_refs


@pytest.mark.asyncio
async def test_rework_action_reports_remaining_source_repair_blocks(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=52,
        protocol="multisig_v1",
        category="Troubleshooting",
        question_text=(
            "My Bisq 1 deposit transaction is confirmed but the trade still "
            "says wait for blockchain confirmation. What should I do?"
        ),
        staff_answer=(
            "Check the deposit txid on a block explorer and use SPV resync "
            "if Bisq has stale wallet-chain state."
        ),
        generated_answer_sources=None,
    )
    pipeline = _PipelineService([candidate])

    async def regenerate_without_sources(candidate_id, protocol):
        pipeline.regenerate_calls.append((candidate_id, protocol))
        return pipeline.repository.update_candidate(
            candidate_id,
            protocol=protocol,
            generated_answer="Regenerated answer without durable source support.",
            generated_answer_sources=None,
        )

    pipeline.regenerate_candidate_answer = regenerate_without_sources
    request = _Request()
    request.app.state.learning_engine = None

    response = await apply_knowledge_update_rework_action(
        request_body=ApplyKnowledgeReworkActionRequest(
            action="repair_sources",
            candidate_ids=[52],
        ),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response["success"] is False
    assert response["updated_count"] == 1
    assert response["proposal_count"] == 0
    assert response["remaining_blocked_count"] == 1
    assert response["remaining_issues_by_candidate"] == {"52": ["missing_source_refs"]}


@pytest.mark.asyncio
async def test_rework_action_source_repair_detects_stale_pending_write(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidate = _candidate(
        id=53,
        protocol="multisig_v1",
        category="Troubleshooting",
        question_text="My Bisq 1 wallet is out of sync. What should I do?",
        staff_answer="Use SPV resync when the wallet chain state is stale.",
        generated_answer_sources=None,
    )
    pipeline = _PipelineService([candidate])
    pipeline.repository.stale_pending_write_ids.add(53)
    request = _Request()
    request.app.state.learning_engine = None

    with pytest.raises(HTTPException) as exc_info:
        await apply_knowledge_update_rework_action(
            request_body=ApplyKnowledgeReworkActionRequest(
                action="repair_sources",
                candidate_ids=[53],
            ),
            request=request,
            pipeline_service=pipeline,
            service=service,
        )

    assert exc_info.value.status_code == 409
    assert pipeline.regenerate_calls == []
    assert service.get_by_candidate_id(53) is None


@pytest.mark.asyncio
async def test_rework_action_opens_cluster_review_without_marking_reviewed(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    candidates = [
        _candidate(
            id=index,
            protocol="musig",
            category="Policy",
            question_text=f"How should support handle recurring policy topic {index}?",
            staff_answer=(
                "Support should explain the durable policy and avoid making "
                "case-specific promises."
            ),
            generated_answer_sources='[{"type":"wiki","title":"Support policy"}]',
        )
        for index in (61, 62, 63)
    ]
    pipeline = _PipelineService(candidates)
    request = _Request()
    request.app.state.learning_engine = None

    response = await apply_knowledge_update_rework_action(
        request_body=ApplyKnowledgeReworkActionRequest(
            action="review_cluster",
            candidate_ids=[61, 62, 63],
        ),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response["success"] is True
    assert response["proposal_count"] == 1
    assert response["cluster"]["size"] == 3
    assert response["cluster"]["candidate_ids"] == [61, 62, 63]
    assert response["candidate"]["id"] == 61
    assert response["proposal"]["status"] == "pending"
    assert any(
        check["code"] == "cluster_synthesis_review"
        for check in response["proposal"]["checks"]
    )
    assert [candidate.review_status for candidate in candidates] == [
        "pending",
        "pending",
        "pending",
    ]


@pytest.mark.asyncio
async def test_knowledge_update_counts_page_through_all_pending_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge_updates, "KNOWLEDGE_UPDATE_PAGE_SIZE", 2)
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(id=1, routing="FULL_REVIEW"),
            _candidate(id=2, routing="FULL_REVIEW", protocol=None),
            _candidate(
                id=3,
                routing="SPOT_CHECK",
                question_text="How do I verify the Bisq 1 deposit transaction?",
                staff_answer="Check the deposit transaction ID in the trade details and verify it with a Bitcoin block explorer before deciding whether the trade is funded.",
                protocol="multisig_v1",
                category="Wallet",
                generated_answer_sources='[{"type":"wiki","title":"Deposit transaction"}]',
            ),
            _candidate(
                id=4,
                routing="AUTO_APPROVE",
                question_text="How do I check payment method limits?",
                staff_answer="Use the payment method details and the trade period shown in Bisq before deciding whether a fiat transfer is late or still within the expected window.",
                protocol="multisig_v1",
                category="Payment Methods",
                generated_answer_sources='[{"type":"wiki","title":"Payment methods"}]',
            ),
        ]
    )

    counts = await get_knowledge_update_counts(
        pipeline_service=pipeline,
        service=service,
    )

    assert counts == {"AUTO_APPROVE": 1, "SPOT_CHECK": 1, "FULL_REVIEW": 1}


@pytest.mark.asyncio
async def test_knowledge_update_counts_collapse_topic_cluster(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(
                id=1,
                question_text="How do I open mediation when the trade timer expired?",
                staff_answer="Open mediation from the trade once the trade period has ended.",
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Mediation"}]',
            ),
            _candidate(
                id=2,
                question_text="How can I request a support ticket for a stuck trade?",
                staff_answer="Use the support ticket flow in the Bisq app for the affected trade and keep the trade context there before escalating to external support channels.",
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Dispute Resolution in Bisq 1"}]',
            ),
            _candidate(
                id=3,
                question_text="Can I start mediation with Ctrl+O?",
                staff_answer="Ctrl+O can open the mediation flow for a Bisq 1 trade, but the support answer should still explain when mediation is appropriate.",
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Dispute Resolution in Bisq 1"}]',
            ),
        ]
    )

    counts = await get_knowledge_update_counts(
        pipeline_service=pipeline,
        service=service,
    )

    assert counts == {"AUTO_APPROVE": 0, "SPOT_CHECK": 0, "FULL_REVIEW": 1}


@pytest.mark.asyncio
async def test_knowledge_update_counts_do_not_collapse_oversized_topic_cluster(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(
                id=index,
                question_text=f"How do I open mediation for stuck trade {index}?",
                staff_answer=(
                    "Open mediation from the Bisq trade and keep the trade context "
                    "inside the app before escalating to external support."
                ),
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Mediation"}]',
            )
            for index in range(1, 7)
        ]
    )

    counts = await get_knowledge_update_counts(
        pipeline_service=pipeline,
        service=service,
    )

    assert counts == {"AUTO_APPROVE": 0, "SPOT_CHECK": 0, "FULL_REVIEW": 6}


@pytest.mark.asyncio
async def test_knowledge_update_counts_do_not_collapse_mixed_target_topics(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(
                id=1,
                question_text="How do I open mediation for a stuck trade?",
                staff_answer=(
                    "Open mediation from the affected trade so the mediator has "
                    "the trade context and messages."
                ),
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Mediation"}]',
            ),
            _candidate(
                id=2,
                question_text="How do I open mediation after a failed bank transfer?",
                staff_answer=(
                    "Open mediation and explain the payment-method issue before "
                    "trying to use a different account."
                ),
                protocol="multisig_v1",
                category="Payment Methods",
                generated_answer_sources='[{"type":"wiki","title":"Payment methods"}]',
            ),
            _candidate(
                id=3,
                question_text="How do I open support if my wallet state is wrong?",
                staff_answer=(
                    "Check the wallet state and use the in-app support flow when "
                    "the trade cannot be resolved safely."
                ),
                protocol="multisig_v1",
                category="Wallet",
                generated_answer_sources='[{"type":"wiki","title":"Wallet"}]',
            ),
        ]
    )

    counts = await get_knowledge_update_counts(
        pipeline_service=pipeline,
        service=service,
    )

    assert counts == {"AUTO_APPROVE": 0, "SPOT_CHECK": 0, "FULL_REVIEW": 3}


@pytest.mark.asyncio
async def test_current_knowledge_update_skips_unreviewable_candidate(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(
                id=1,
                protocol=None,
                generated_answer_sources=None,
            ),
            _candidate(id=2),
        ]
    )

    response = await get_current_knowledge_update(
        queue="FULL_REVIEW",
        pipeline_service=pipeline,
        service=service,
    )

    assert response is not None
    assert response["candidate"]["id"] == 2


@pytest.mark.asyncio
async def test_current_knowledge_update_pages_until_reviewable_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge_updates, "KNOWLEDGE_UPDATE_PAGE_SIZE", 2)
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(id=1, protocol=None, generated_answer_sources=None),
            _candidate(id=2, protocol="musig"),
            _candidate(id=3),
        ]
    )

    response = await get_current_knowledge_update(
        queue="FULL_REVIEW",
        pipeline_service=pipeline,
        service=service,
    )

    assert response is not None
    assert response["candidate"]["id"] == 3


@pytest.mark.asyncio
async def test_current_knowledge_update_returns_topic_cluster_context(
    tmp_path: Path,
) -> None:
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService(
        [
            _candidate(
                id=10,
                question_text="How do I open mediation when the seller is not responding?",
                staff_answer="Use the mediation flow after the trade period when the peer does not respond.",
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Mediation"}]',
            ),
            _candidate(
                id=11,
                question_text="How do I request a support ticket for a trade dispute?",
                staff_answer="Open a support ticket from the Bisq trade before using external channels, so the mediator has the trade context and messages in the app.",
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Dispute Resolution in Bisq 1"}]',
            ),
            _candidate(
                id=12,
                question_text="Can I start mediation manually with Ctrl+O?",
                staff_answer="Ctrl+O can open mediation for a Bisq 1 trade, but the guidance should explain the trade-period and dispute context before telling users to escalate.",
                protocol="multisig_v1",
                category="Trading",
                generated_answer_sources='[{"type":"wiki","title":"Dispute Resolution in Bisq 1"}]',
            ),
        ]
    )

    response = await get_current_knowledge_update(
        queue="FULL_REVIEW",
        pipeline_service=pipeline,
        service=service,
    )

    assert response is not None
    assert response["candidate"]["id"] == 10
    assert response["cluster"]["size"] == 3
    assert response["cluster"]["candidate_ids"] == [10, 11, 12]
    assert response["cluster"]["topic"] == "open_mediation_or_support_ticket"
    assert any(
        check["code"] == "cluster_synthesis_review"
        for check in response["proposal"]["checks"]
    )


class _State:
    pass


class _Request:
    def __init__(self):
        self.app = _State()
        self.app.state = _State()
        self.state = _State()
        self.state.admin_actor = "support-admin"


@pytest.mark.asyncio
async def test_approve_knowledge_update_passes_review_outcome_feedback(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService([candidate])
    request = _Request()
    request.app.state.learning_engine = None
    request.app.state.rag_service = None
    service.get_or_create_proposal(candidate=candidate)

    response = await approve_knowledge_update(
        candidate_id=candidate.id,
        request_body=KnowledgeReviewRequest(
            reviewer="admin",
            feedback_tags=["source_support", "scope_narrowing"],
            future_generator_note="Future drafts should avoid unsupported UI labels.",
        ),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    approved = service.get_by_candidate_id(candidate.id)
    assert response.success is True
    assert approved is not None
    assert approved.feedback_tags == ["source_support", "scope_narrowing"]
    assert (
        approved.future_generator_note
        == "Future drafts should avoid unsupported UI labels."
    )


@pytest.mark.asyncio
async def test_approve_knowledge_update_runs_automatic_coverage_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService([candidate])
    request = _Request()
    request.app.state.learning_engine = None
    request.app.state.rag_service = None
    service.get_or_create_proposal(candidate=candidate)
    calls = []

    async def _record_reconciliation(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(
        knowledge_updates,
        "_run_automatic_coverage_reconciliation",
        _record_reconciliation,
    )

    response = await approve_knowledge_update(
        candidate_id=candidate.id,
        request_body=KnowledgeReviewRequest(reviewer="admin"),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response.success is True
    assert len(calls) == 1
    assert calls[0]["pipeline_service"] is pipeline
    assert calls[0]["service"] is service
    assert calls[0]["trigger_page_id"] == "bisq-easy-reputation"


@pytest.mark.asyncio
async def test_approve_knowledge_update_ignores_coverage_reconciliation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    pipeline = _PipelineService([candidate])
    request = _Request()
    request.app.state.learning_engine = None
    request.app.state.rag_service = None
    service.get_or_create_proposal(candidate=candidate)

    async def _fail_reconciliation(**kwargs):
        raise RuntimeError("coverage reconciliation failed")

    monkeypatch.setattr(
        knowledge_updates,
        "_run_automatic_coverage_reconciliation",
        _fail_reconciliation,
    )

    response = await approve_knowledge_update(
        candidate_id=candidate.id,
        request_body=KnowledgeReviewRequest(reviewer="admin"),
        request=request,
        pipeline_service=pipeline,
        service=service,
    )

    assert response.success is True
    assert service.get_by_candidate_id(candidate.id).status == "approved"


@pytest.mark.asyncio
async def test_generator_feedback_records_endpoint_returns_export(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=str(tmp_path / "unified_training.db"),
    )
    service.get_or_create_proposal(candidate=candidate)
    service.approve(
        candidate=candidate,
        reviewer="admin",
        feedback_tags=["missing_caveat"],
        future_generator_note="Future drafts should include caveats earlier.",
    )

    response = await get_generator_feedback_records(
        limit=10,
        service=service,
    )

    assert response["count"] == 1
    assert response["items"][0]["candidate_id"] == candidate.id
    assert response["items"][0]["feedback_tags"] == ["missing_caveat"]

    reviewer_filtered = await get_generator_feedback_records(
        limit=10,
        reviewer="admin",
        service=service,
    )
    assert reviewer_filtered["count"] == 1
    assert reviewer_filtered["items"][0]["candidate_id"] == candidate.id

    target_filtered = await get_generator_feedback_records(
        limit=10,
        target_page_id=response["items"][0]["target_page_id"],
        service=service,
    )
    assert target_filtered["count"] == 1
    assert target_filtered["items"][0]["candidate_id"] == candidate.id

    missing_target = await get_generator_feedback_records(
        limit=10,
        target_page_id="missing-page",
        service=service,
    )
    assert missing_target["count"] == 0


@pytest.mark.asyncio
async def test_promote_code_evidence_endpoint_creates_reviewable_proposal(
    tmp_path: Path,
) -> None:
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    pipeline = type("Pipeline", (), {"repository": repository})()
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=repository.db_path,
    )
    source_ref = "code:bisq2@abc123:api/src/main/java/bisq/api/OfferResource.java:42-44"

    response = await promote_code_evidence_to_knowledge_update(
        request_body=PromoteCodeEvidenceRequest(
            question="The app says Offer not found. What should I do?",
            public_guidance=(
                "If a user sees Offer not found, explain that the offer may "
                "already have been taken or removed. Ask them to refresh the "
                "offer list and retry."
            ),
            evidence={
                "id": "bisq2:abc123:HTTPException.404:42",
                "kind": "code_fact",
                "repo": "bisq2",
                "commit": "abc123",
                "path": "api/src/main/java/bisq/api/OfferResource.java",
                "line_start": 42,
                "line_end": 44,
                "symbol": "OfferResource.HTTPException.404",
                "protocol": "bisq_easy",
                "audience": "staff_only",
                "freshness_class": "release_bound",
                "risk_level": "medium",
                "claim": "OfferResource can return user-visible error detail: Offer not found.",
                "support_use": "Use when users report that an offer disappeared.",
                "source_refs": [source_ref],
            },
        ),
        pipeline_service=pipeline,
        service=service,
    )

    assert response["candidate"]["source"] == "code_evidence"
    assert response["candidate"]["routing"] == "FULL_REVIEW"
    assert response["proposal"]["status"] == "pending"
    assert source_ref in response["proposal"]["source_refs"]


@pytest.mark.asyncio
async def test_promote_code_evidence_endpoint_accepts_symbol_less_evidence(
    tmp_path: Path,
) -> None:
    repository = UnifiedFAQCandidateRepository(str(tmp_path / "unified_training.db"))
    pipeline = type("Pipeline", (), {"repository": repository})()
    service = KnowledgeUpdateService(
        settings=Settings(DATA_DIR=str(tmp_path)),
        db_path=repository.db_path,
    )
    source_ref = "code:bisq2@abc123:api/src/main/java/bisq/api/OfferResource.java:42-44"

    response = await promote_code_evidence_to_knowledge_update(
        request_body=PromoteCodeEvidenceRequest(
            question="The app says Offer not found. What should I do?",
            public_guidance=(
                "If a user sees Offer not found, ask them to refresh the offer "
                "list and retry."
            ),
            evidence={
                "id": "bisq2:abc123:HTTPException.404:42",
                "kind": "code_fact",
                "repo": "bisq2",
                "commit": "abc123",
                "path": "api/src/main/java/bisq/api/OfferResource.java",
                "line_start": 42,
                "line_end": 44,
                "protocol": "bisq_easy",
                "audience": "staff_only",
                "freshness_class": "release_bound",
                "risk_level": "medium",
                "claim": "OfferResource can return user-visible error detail: Offer not found.",
                "support_use": "Use when users report that an offer disappeared.",
                "source_refs": [source_ref],
            },
        ),
        pipeline_service=pipeline,
        service=service,
    )

    assert response["candidate"]["source"] == "code_evidence"
    assert source_ref in response["proposal"]["source_refs"]
