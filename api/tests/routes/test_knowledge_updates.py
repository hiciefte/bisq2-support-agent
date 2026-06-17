from pathlib import Path

import app.routes.admin.knowledge_updates as knowledge_updates
import pytest
from app.core.config import Settings
from app.routes.admin.knowledge_updates import (
    get_current_knowledge_update,
    get_knowledge_update_counts,
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
            _candidate(id=3, routing="SPOT_CHECK"),
            _candidate(id=4, routing="AUTO_APPROVE"),
        ]
    )

    counts = await get_knowledge_update_counts(
        pipeline_service=pipeline,
        service=service,
    )

    assert counts == {"AUTO_APPROVE": 1, "SPOT_CHECK": 1, "FULL_REVIEW": 1}


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
