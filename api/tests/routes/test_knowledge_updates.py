from pathlib import Path

import app.routes.admin.knowledge_updates as knowledge_updates
import pytest
from app.core.config import Settings
from app.routes.admin.knowledge_updates import (
    KnowledgeReviewRequest,
    PromoteCodeEvidenceRequest,
    approve_knowledge_update,
    get_current_knowledge_update,
    get_generator_feedback_records,
    get_knowledge_update_counts,
    promote_code_evidence_to_knowledge_update,
)
from app.services.knowledge_updates.llm_wiki_update_service import (
    KnowledgeUpdateService,
)
from app.services.training.unified_repository import UnifiedFAQCandidateRepository
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


class _Repository:
    def __init__(self, candidates):
        self.candidates = candidates

    def get_pending(self, source=None, routing=None, limit=100, offset=0):
        rows = [
            candidate
            for candidate in self.candidates
            if (routing is None or candidate.routing == routing)
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


class _PipelineService:
    def __init__(self, candidates):
        self.repository = _Repository(candidates)


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
    source_ref = (
        "code:bisq2@abc123:api/src/main/java/bisq/api/OfferResource.java:42-44"
    )

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
