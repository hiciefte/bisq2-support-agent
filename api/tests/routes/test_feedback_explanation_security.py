"""Security tests for POST /feedback/explanation."""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.reactions import ReactionProcessor, SentMessageTracker
from app.routes import feedback_routes
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_explanation_rate_limiter():
    feedback_routes.reset_feedback_explanation_rate_limiter()
    yield
    feedback_routes.reset_feedback_explanation_rate_limiter()


def _install_feedback_dependencies(test_client: TestClient, test_settings):
    feedback_service = MagicMock()
    feedback_service.repository = MagicMock()
    feedback_service.analyze_feedback_text = AsyncMock(return_value=[])
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)

    processor = ReactionProcessor(
        tracker=SentMessageTracker(),
        feedback_service=feedback_service,
        reactor_identity_salt=test_settings.REACTOR_IDENTITY_SALT,
    )
    app_state = cast(Any, test_client.app).state
    app_state.feedback_service = feedback_service
    app_state.reaction_processor = processor
    return feedback_service, processor


def test_feedback_explanation_requires_matching_web_reaction(
    test_client: TestClient, test_settings
) -> None:
    feedback_service, _ = _install_feedback_dependencies(test_client, test_settings)
    feedback_service.repository.get_active_reaction_rating.return_value = None
    test_client.cookies.set("session_id", "feedback-session")

    response = test_client.post(
        "/feedback/explanation",
        json={"message_id": "web_abc123", "explanation": "Not specific enough"},
    )

    assert response.status_code == 404
    feedback_service.update_feedback_entry.assert_not_awaited()


def test_feedback_explanation_updates_matching_web_reactor(
    test_client: TestClient, test_settings
) -> None:
    feedback_service, processor = _install_feedback_dependencies(
        test_client, test_settings
    )
    feedback_service.repository.get_active_reaction_rating.return_value = 0
    test_client.cookies.set("session_id", "feedback-session")

    response = test_client.post(
        "/feedback/explanation",
        json={
            "message_id": "web_abc123",
            "explanation": "Not specific enough",
            "issues": ["not_specific", "", 123],
        },
    )

    assert response.status_code == 200
    # Recompute the expected hash from the same session cookie without depending
    # on FastAPI internals.
    import hashlib

    digest = hashlib.sha256("feedback-session".encode("utf-8")).hexdigest()
    expected_user_id = f"user_{digest[:24]}"
    expected_hash = processor.hash_reactor_identity("web", expected_user_id)
    feedback_service.repository.get_active_reaction_rating.assert_called_once_with(
        "web", "web_abc123", expected_hash
    )
    feedback_service.update_feedback_entry.assert_awaited_once_with(
        message_id="web_abc123",
        explanation="Not specific enough",
        issues=["not_specific"],
    )


def test_feedback_explanation_is_rate_limited(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    feedback_service, _ = _install_feedback_dependencies(test_client, test_settings)
    feedback_service.repository.get_active_reaction_rating.return_value = 0
    monkeypatch.setattr(feedback_routes, "_FEEDBACK_EXPLANATION_RATE_LIMIT", 1)
    test_client.cookies.set("session_id", "feedback-session")

    first = test_client.post(
        "/feedback/explanation",
        json={"message_id": "web_abc123", "explanation": "Not specific enough"},
    )
    second = test_client.post(
        "/feedback/explanation",
        json={"message_id": "web_abc123", "explanation": "Still not enough"},
    )

    assert first.status_code == 200
    assert second.status_code == 429


def test_feedback_explanation_rate_limiter_sweeps_stale_users(monkeypatch) -> None:
    times = iter([1000.0, 1401.0])
    monkeypatch.setattr(feedback_routes.time, "monotonic", lambda: next(times))

    assert feedback_routes._allow_feedback_explanation("old-user") is True
    assert "old-user" in feedback_routes._feedback_explanation_attempts

    assert feedback_routes._allow_feedback_explanation("new-user") is True

    assert "old-user" not in feedback_routes._feedback_explanation_attempts
    assert "new-user" in feedback_routes._feedback_explanation_attempts
