"""Tests for admin quality-signal routes."""

# flake8: noqa: E402

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("aisuite", MagicMock())

from app.core.config import Settings
from app.models.escalation import (
    Escalation,
    EscalationCountsResponse,
    EscalationPriority,
    EscalationStatus,
)
from app.routes.admin.signals import (
    get_escalation_service,
    get_feedback_service,
    router,
)
from app.services.training.unified_repository import UnifiedFAQCandidate
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _sample_feedback(message_id: str, rating: int, *, asker: bool = True):
    return {
        "id": 1,
        "message_id": message_id,
        "question": "What is Bisq Easy?",
        "answer": "Bisq Easy helps first-time buyers get BTC.",
        "rating": rating,
        "timestamp": "2026-02-25T10:00:00+00:00",
        "channel": "bisq2",
        "feedback_method": "reaction",
        "metadata": {
            "is_original_asker": asker,
            "explanation": "Needs more detail",
            "issues": ["not_specific"],
        },
    }


def _sample_escalation(message_id: str, escalation_id: int = 7) -> Escalation:
    now = datetime.now(timezone.utc)
    return Escalation(
        id=escalation_id,
        message_id=message_id,
        channel="bisq2",
        user_id="signal-user",
        username="user",
        channel_metadata={},
        question="What is Bisq Easy?",
        ai_draft_answer="Bisq Easy helps first-time buyers get BTC.",
        confidence_score=0.72,
        routing_action="needs_human",
        routing_reason="promoted_from_quality_signal",
        sources=[],
        staff_answer=None,
        staff_id=None,
        status=EscalationStatus.PENDING,
        priority=EscalationPriority.NORMAL,
        created_at=now,
        claimed_at=None,
        responded_at=None,
        closed_at=None,
    )


def _candidate(**overrides) -> UnifiedFAQCandidate:
    values = {
        "id": 1,
        "source": "matrix",
        "source_event_id": "$event",
        "source_timestamp": "2026-06-17T10:00:00+00:00",
        "question_text": "How do I open mediation when the trade timer expired?",
        "staff_answer": "Open mediation from the trade once the trade period has ended.",
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
        "protocol": "multisig_v1",
        "edited_staff_answer": None,
        "edited_question_text": None,
        "category": "Trading",
        "generated_answer_sources": '[{"type":"wiki","title":"Mediation"}]',
        "original_user_question": None,
        "original_staff_answer": None,
        "generation_confidence": 0.82,
        "has_correction": False,
    }
    values.update(overrides)
    return UnifiedFAQCandidate(**values)


class _KnowledgeRepository:
    def __init__(self, candidates, db_path: Path):
        self.candidates = candidates
        self.db_path = str(db_path)

    def get_pending(self, source=None, routing=None, limit=100, offset=0):
        rows = [
            candidate
            for candidate in self.candidates
            if (routing is None or candidate.routing == routing)
            and (source is None or candidate.source == source)
        ]
        return rows[offset : offset + limit]


def _build_app(
    feedback_service,
    escalation_service,
    *,
    settings=None,
    unified_pipeline_service=None,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if settings is not None:
        app.state.settings = settings
    if unified_pipeline_service is not None:
        app.state.unified_pipeline_service = unified_pipeline_service

    from app.core.security import verify_admin_access

    app.dependency_overrides[verify_admin_access] = lambda: None
    app.dependency_overrides[get_feedback_service] = lambda: feedback_service
    app.dependency_overrides[get_escalation_service] = lambda: escalation_service
    return TestClient(app)


def test_list_signals_includes_actionable_count():
    feedback_repo = MagicMock()
    feedback_repo.get_all_feedback.return_value = [
        _sample_feedback("msg-1", 0, asker=True),
        _sample_feedback("msg-2", 1, asker=True),
    ]
    feedback_repo.get_feedback_metadata_value.return_value = None
    feedback_service = SimpleNamespace(repository=feedback_repo)

    escalation_repo = MagicMock()
    escalation_repo.get_by_message_id = AsyncMock(return_value=None)
    escalation_repo.get_by_id = AsyncMock(return_value=None)
    escalation_service = SimpleNamespace(repository=escalation_repo)

    client = _build_app(
        feedback_service=feedback_service, escalation_service=escalation_service
    )
    response = client.get("/admin/signals")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] == 2
    assert payload["actionable_count"] == 1
    assert payload["covered_count"] == 0
    assert payload["signals"][0]["message_id"] in {"msg-1", "msg-2"}


def test_promote_signal_creates_case_and_links_signal():
    message_id = "msg-promote-1"
    escalation = _sample_escalation(message_id=message_id, escalation_id=9)

    feedback_repo = MagicMock()
    feedback_repo.get_feedback_by_message_id.return_value = _sample_feedback(
        message_id, 0, asker=True
    )
    feedback_repo.get_feedback_metadata_value.side_effect = [None, 9, 9]
    feedback_repo.set_feedback_metadata_value.return_value = True
    feedback_service = SimpleNamespace(repository=feedback_repo)

    escalation_repo = MagicMock()
    get_by_message_counter = {"count": 0}

    async def _get_by_message_id(_message_id: str):
        get_by_message_counter["count"] += 1
        if get_by_message_counter["count"] == 1:
            return None
        return escalation

    escalation_repo.get_by_message_id = AsyncMock(side_effect=_get_by_message_id)
    escalation_repo.get_by_id = AsyncMock(return_value=escalation)

    escalation_service = SimpleNamespace(
        repository=escalation_repo,
        create_escalation=AsyncMock(return_value=escalation),
    )

    client = _build_app(
        feedback_service=feedback_service, escalation_service=escalation_service
    )
    response = client.post(
        f"/admin/signals/{message_id}/promote-case",
        json={"priority": "normal", "reason": "promoted_from_quality_signal"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "promoted"
    assert payload["escalation_id"] == 9
    escalation_service.create_escalation.assert_awaited_once()
    feedback_repo.set_feedback_metadata_value.assert_called_with(
        message_id, "linked_escalation_id", 9
    )


def test_action_counts_aggregates_escalations_and_signals():
    feedback_repo = MagicMock()
    feedback_repo.get_all_feedback.return_value = [
        _sample_feedback("msg-1", 0, asker=True)
    ]
    feedback_repo.get_feedback_metadata_value.return_value = None
    feedback_service = SimpleNamespace(repository=feedback_repo)

    escalation_repo = MagicMock()
    escalation_repo.get_by_message_id = AsyncMock(return_value=None)
    escalation_repo.get_by_id = AsyncMock(return_value=None)
    escalation_service = SimpleNamespace(
        repository=escalation_repo,
        get_escalation_counts=AsyncMock(
            return_value=EscalationCountsResponse(
                pending=2,
                in_review=1,
                responded=0,
                closed=0,
                total=3,
            )
        ),
    )

    client = _build_app(
        feedback_service=feedback_service, escalation_service=escalation_service
    )
    response = client.get("/admin/overview/action-counts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["pending_escalations"] == 2
    assert payload["open_escalations"] == 3
    assert payload["actionable_signals"] == 1


def test_action_counts_use_clustered_knowledge_update_review_items(tmp_path: Path):
    feedback_repo = MagicMock()
    feedback_repo.get_all_feedback.return_value = []
    feedback_service = SimpleNamespace(repository=feedback_repo)

    escalation_repo = MagicMock()
    escalation_repo.get_by_message_id = AsyncMock(return_value=None)
    escalation_repo.get_by_id = AsyncMock(return_value=None)
    escalation_service = SimpleNamespace(
        repository=escalation_repo,
        get_escalation_counts=AsyncMock(
            return_value=EscalationCountsResponse(
                pending=0,
                in_review=0,
                responded=0,
                closed=0,
                total=0,
            )
        ),
    )
    knowledge_repo = _KnowledgeRepository(
        [
            _candidate(id=1),
            _candidate(
                id=2,
                question_text="How can I request a support ticket for a stuck trade?",
                staff_answer=(
                    "Use the support ticket flow in Bisq for the affected trade "
                    "before escalating to external support channels."
                ),
                generated_answer_sources=(
                    '[{"type":"wiki","title":"Dispute Resolution in Bisq 1"}]'
                ),
            ),
            _candidate(
                id=3,
                question_text="Can I start mediation with Ctrl+O?",
                staff_answer=(
                    "Ctrl+O can open the mediation flow for a Bisq 1 trade, "
                    "but support should still explain when mediation is appropriate."
                ),
                generated_answer_sources=(
                    '[{"type":"wiki","title":"Dispute Resolution in Bisq 1"}]'
                ),
            ),
        ],
        tmp_path / "unified_training.db",
    )
    unified_pipeline_service = SimpleNamespace(repository=knowledge_repo)

    client = _build_app(
        feedback_service=feedback_service,
        escalation_service=escalation_service,
        settings=Settings(DATA_DIR=str(tmp_path)),
        unified_pipeline_service=unified_pipeline_service,
    )

    response = client.get("/admin/overview/action-counts")

    assert response.status_code == 200
    assert response.json()["training_queue"] == 1


def test_promote_signal_with_empty_answer_uses_safe_fallback():
    message_id = "msg-empty-answer"
    escalation = _sample_escalation(message_id=message_id, escalation_id=11)

    feedback = _sample_feedback(message_id, 0, asker=True)
    feedback["answer"] = ""

    feedback_repo = MagicMock()
    feedback_repo.get_feedback_by_message_id.return_value = feedback
    feedback_repo.get_feedback_metadata_value.side_effect = [None, 11, 11]
    feedback_repo.set_feedback_metadata_value.return_value = True
    feedback_service = SimpleNamespace(repository=feedback_repo)

    escalation_repo = MagicMock()
    escalation_repo.get_by_message_id = AsyncMock(
        side_effect=[None, escalation, escalation]
    )
    escalation_repo.get_by_id = AsyncMock(return_value=escalation)
    escalation_service = SimpleNamespace(
        repository=escalation_repo,
        create_escalation=AsyncMock(return_value=escalation),
    )

    client = _build_app(
        feedback_service=feedback_service, escalation_service=escalation_service
    )
    response = client.post(
        f"/admin/signals/{message_id}/promote-case",
        json={"priority": "normal", "reason": "manual_test"},
    )
    assert response.status_code == 200
    create_payload = escalation_service.create_escalation.await_args.args[0]
    assert create_payload.ai_draft_answer.startswith("No AI draft answer was available")
