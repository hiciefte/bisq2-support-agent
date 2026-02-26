"""
Tests for the staff answer rating endpoint (POST /escalations/{message_id}/rate).

Covers:
- Rating a responded escalation (200)
- Rating a closed escalation with staff_answer (200)
- Rating a pending escalation with no staff_answer (400)
- Rating a non-existent message_id (404)
- Invalid rating values (422 via Pydantic)
- Re-rating / idempotency (200 + overwritten)
- Rating appears in poll response
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, call

import pytest
from app.core.config import Settings, get_settings
from app.models.escalation import (
    Escalation,
    EscalationDeliveryStatus,
    EscalationPriority,
    EscalationStatus,
)
from app.routes.escalation_polling import router as polling_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_escalation(
    status: EscalationStatus = EscalationStatus.RESPONDED,
    staff_answer: str | None = "Here is the answer",
    responded_at: datetime | None = datetime(2025, 1, 15, 12, 0, 0),
    staff_answer_rating: int | None = None,
    **overrides,
) -> Escalation:
    data = dict(
        id=1,
        message_id="12345678-1234-1234-1234-123456789abc",
        channel="matrix",
        user_id="@user:matrix.org",
        username="testuser",
        question="How do I set up Bisq?",
        ai_draft_answer="Here's how to set up Bisq...",
        confidence_score=0.65,
        routing_action="needs_human",
        status=status,
        priority=EscalationPriority.NORMAL,
        created_at=datetime(2025, 1, 15, 10, 0, 0),
        staff_answer=staff_answer,
        responded_at=responded_at,
        delivery_status=EscalationDeliveryStatus.NOT_REQUIRED,
        delivery_attempts=0,
        staff_answer_rating=staff_answer_rating,
    )
    data.update(overrides)
    return Escalation(**data)


@pytest.fixture
def mock_service():
    service = MagicMock()
    service.repository = MagicMock()
    service.repository.get_by_message_id = AsyncMock()
    service.repository.consume_rating_token_jti = AsyncMock(return_value=True)
    service.record_staff_answer_rating = AsyncMock(return_value=True)
    service.feedback_orchestrator = MagicMock()
    service.feedback_orchestrator.record_user_rating = MagicMock()
    return service


@pytest.fixture
def client(mock_service):
    app = FastAPI()
    app.include_router(polling_router)

    from app.routes.admin.escalations import get_escalation_service

    app.dependency_overrides[get_escalation_service] = lambda: mock_service
    app.dependency_overrides[get_settings] = lambda: Settings(
        DEBUG=True,
        DATA_DIR="/tmp",
        ADMIN_API_KEY="test-admin-key-with-sufficient-length-24chars",
        ENVIRONMENT="testing",
        COOKIE_SECURE=False,
    )

    return TestClient(app)


MESSAGE_ID = "12345678-1234-1234-1234-123456789abc"


class TestRateStaffAnswer:
    """Tests for POST /escalations/{message_id}/rate"""

    def test_rate_responded_escalation(self, client, mock_service):
        """Rating a responded escalation should succeed."""
        escalation = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True

        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["staff_answer_rating"] == 1
        mock_service.record_staff_answer_rating.assert_awaited_once_with(
            escalation=escalation,
            rating=1,
            rater_id=ANY,
            trusted=False,
        )

    def test_rate_closed_escalation_with_staff_answer(self, client, mock_service):
        """Rating a closed escalation with a staff_answer should also succeed."""
        escalation = _make_escalation(
            status=EscalationStatus.CLOSED,
            staff_answer="Closed with answer",
        )
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True

        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 0})

        assert resp.status_code == 200
        data = resp.json()
        assert data["staff_answer_rating"] == 0

    def test_rate_pending_escalation_no_staff_answer(self, client, mock_service):
        """Rating a pending escalation (no staff_answer) returns 400."""
        escalation = _make_escalation(
            status=EscalationStatus.PENDING,
            staff_answer=None,
            responded_at=None,
        )
        mock_service.repository.get_by_message_id.return_value = escalation
        # Atomic update returns False because staff_answer IS NOT NULL check fails
        mock_service.record_staff_answer_rating.return_value = False

        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 1})

        assert resp.status_code == 400
        assert "no staff answer" in resp.json()["detail"].lower()

    def test_rate_nonexistent_message(self, client, mock_service):
        """Rating a non-existent message_id returns 404."""
        mock_service.repository.get_by_message_id.return_value = None

        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 1})

        assert resp.status_code == 404

    def test_rate_invalid_value_too_high(self, client, mock_service):
        """Rating value > 1 returns 422 (Pydantic validation)."""
        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 2})

        assert resp.status_code == 422

    def test_rate_invalid_value_negative(self, client, mock_service):
        """Rating value < 0 returns 422 (Pydantic validation)."""
        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": -1})

        assert resp.status_code == 422

    def test_rerate_is_idempotent(self, client, mock_service):
        """Re-rating should overwrite previous rating."""
        escalation = _make_escalation(staff_answer_rating=0)
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True

        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 1})

        assert resp.status_code == 200
        assert resp.json()["staff_answer_rating"] == 1

    def test_rating_in_poll_response(self, client, mock_service):
        """Staff answer rating should appear in the poll GET response."""
        escalation = _make_escalation(staff_answer_rating=1)
        mock_service.repository.get_by_message_id.return_value = escalation

        resp = client.get(f"/escalations/{MESSAGE_ID}/response")

        assert resp.status_code == 200
        assert resp.json()["staff_answer_rating"] == 1

    def test_poll_resolved_includes_rate_token(self, client, mock_service, monkeypatch):
        """Resolved poll responses should include a signed rating token."""
        escalation = _make_escalation(staff_answer_rating=1)
        mock_service.repository.get_by_message_id.return_value = escalation
        monkeypatch.setattr(
            "app.routes.escalation_polling.generate_rating_token",
            lambda *args, **kwargs: "rate_token_123",
        )

        resp = client.get(f"/escalations/{MESSAGE_ID}/response")

        assert resp.status_code == 200
        assert resp.json()["rate_token"] == "rate_token_123"

    def test_rate_without_token_is_accepted_but_not_trusted(self, client, mock_service):
        """Untrusted submissions still update DB rating but do not trigger learning."""
        escalation = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True

        resp = client.post(f"/escalations/{MESSAGE_ID}/rate", json={"rating": 1})

        assert resp.status_code == 200
        mock_service.record_staff_answer_rating.assert_awaited_once_with(
            escalation=escalation,
            rating=1,
            rater_id=ANY,
            trusted=False,
        )

    def test_rate_with_invalid_token_returns_400(
        self, client, mock_service, monkeypatch
    ):
        """Invalid tokens are rejected."""
        escalation = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True
        monkeypatch.setattr(
            "app.routes.escalation_polling.verify_rating_token",
            lambda *args, **kwargs: None,
        )

        resp = client.post(
            f"/escalations/{MESSAGE_ID}/rate",
            json={"rating": 1, "rate_token": "invalid_token"},
        )

        assert resp.status_code == 400
        mock_service.record_staff_answer_rating.assert_not_awaited()

    def test_rate_with_valid_token_triggers_learning(
        self, client, mock_service, monkeypatch
    ):
        """Trusted submissions should be forwarded to the orchestrator."""
        escalation = _make_escalation(
            status=EscalationStatus.RESPONDED,
            staff_answer="answer",
            ai_draft_answer="draft",
            confidence_score=0.84,
            routing_action="queue_high",
        )
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True
        mock_service.repository.consume_rating_token_jti.return_value = True

        monkeypatch.setattr(
            "app.routes.escalation_polling.verify_rating_token",
            lambda *args, **kwargs: SimpleNamespace(
                message_id=MESSAGE_ID,
                rater_id="user_abc",
                jti="jti_1",
            ),
        )

        resp = client.post(
            f"/escalations/{MESSAGE_ID}/rate",
            json={"rating": 0, "rate_token": "valid_token"},
        )

        assert resp.status_code == 200
        mock_service.record_staff_answer_rating.assert_awaited_once_with(
            escalation=escalation,
            rating=0,
            rater_id=ANY,
            trusted=True,
        )

        consume_idx = mock_service.repository.mock_calls.index(
            call.consume_rating_token_jti(message_id=MESSAGE_ID, token_jti="jti_1")
        )
        rate_idx = mock_service.mock_calls.index(
            call.record_staff_answer_rating(
                escalation=escalation,
                rating=0,
                rater_id=ANY,
                trusted=True,
            )
        )
        assert consume_idx < rate_idx

    def test_replayed_token_returns_409(self, client, mock_service, monkeypatch):
        """Reusing a consumed token jti should be rejected."""
        escalation = _make_escalation(status=EscalationStatus.RESPONDED)
        mock_service.repository.get_by_message_id.return_value = escalation
        mock_service.record_staff_answer_rating.return_value = True
        mock_service.repository.consume_rating_token_jti.return_value = False
        monkeypatch.setattr(
            "app.routes.escalation_polling.verify_rating_token",
            lambda *args, **kwargs: SimpleNamespace(
                message_id=MESSAGE_ID,
                rater_id="user_abc",
                jti="jti_1",
            ),
        )

        resp = client.post(
            f"/escalations/{MESSAGE_ID}/rate",
            json={"rating": 1, "rate_token": "valid_token"},
        )

        assert resp.status_code == 409
        mock_service.repository.consume_rating_token_jti.assert_awaited_once_with(
            message_id=MESSAGE_ID,
            token_jti="jti_1",
        )
        mock_service.record_staff_answer_rating.assert_not_awaited()
