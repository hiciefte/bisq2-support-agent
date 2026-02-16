"""Tests for feedback orchestrator behavior."""

from unittest.mock import MagicMock

from app.services.escalation.feedback_orchestrator import (
    FeedbackOrchestrator,
    StaffRatingSignal,
)


def _make_signal(**overrides) -> StaffRatingSignal:
    data = {
        "message_id": "msg-1",
        "escalation_id": 1,
        "rater_id": "user-1",
        "confidence_score": 0.8,
        "edit_distance": 0.0,
        "user_rating": 1,
        "routing_action": "queue_high",
        "channel": "web",
        "trusted": True,
        "sources": [{"type": "faq"}],
    }
    data.update(overrides)
    return StaffRatingSignal(**data)


def test_untrusted_signal_does_not_update_learning() -> None:
    learning_engine = MagicMock()
    weight_manager = MagicMock()
    orchestrator = FeedbackOrchestrator(learning_engine, weight_manager)

    orchestrator.record_user_rating(_make_signal(trusted=False))

    learning_engine.record_review.assert_not_called()
    weight_manager.apply_quadrant_feedback.assert_not_called()


def test_trusted_helpful_edited_maps_to_admin_action_edited() -> None:
    learning_engine = MagicMock()
    weight_manager = MagicMock()
    orchestrator = FeedbackOrchestrator(learning_engine, weight_manager)

    orchestrator.record_user_rating(_make_signal(edit_distance=0.4, user_rating=1))

    kwargs = learning_engine.record_review.call_args.kwargs
    assert kwargs["admin_action"] == "edited"
    assert kwargs["metadata"]["idempotent"] is True
    assert kwargs["question_id"] == "user_rating_msg-1_user-1"


def test_trusted_unhelpful_maps_to_admin_action_rejected() -> None:
    learning_engine = MagicMock()
    weight_manager = MagicMock()
    orchestrator = FeedbackOrchestrator(learning_engine, weight_manager)

    orchestrator.record_user_rating(_make_signal(edit_distance=0.0, user_rating=0))

    kwargs = learning_engine.record_review.call_args.kwargs
    assert kwargs["admin_action"] == "rejected"
