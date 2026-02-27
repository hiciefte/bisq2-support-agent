"""Tests for admin quality-signal routes."""

# flake8: noqa: E402

import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("aisuite", MagicMock())

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


def _build_app(feedback_service, escalation_service) -> TestClient:
    app = FastAPI()
    app.include_router(router)

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
