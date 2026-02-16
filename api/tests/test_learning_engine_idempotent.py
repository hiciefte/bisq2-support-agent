"""Tests for idempotent learning-review updates."""

from app.services.rag.learning_engine import LearningEngine


def test_idempotent_user_rating_overwrites_prior_review() -> None:
    """Same idempotent question_id should overwrite instead of append."""
    engine = LearningEngine()
    engine.min_samples_for_update = 99999  # keep threshold updates out of scope

    engine.record_review(
        question_id="user_rating_msg_1_user_a",
        confidence=0.81,
        admin_action="approved",
        routing_action="queue_high",
        metadata={"source": "user_rating", "idempotent": True},
    )
    engine.record_review(
        question_id="user_rating_msg_1_user_a",
        confidence=0.81,
        admin_action="rejected",
        routing_action="queue_high",
        metadata={"source": "user_rating", "idempotent": True},
    )

    assert len(engine._review_history) == 1
    assert engine._review_history[0]["admin_action"] == "rejected"


def test_non_idempotent_reviews_continue_to_append() -> None:
    """Legacy behavior remains unchanged for normal reviews."""
    engine = LearningEngine()
    engine.min_samples_for_update = 99999

    engine.record_review(
        question_id="escalation_1",
        confidence=0.5,
        admin_action="approved",
        routing_action="queue_high",
        metadata={"source": "escalation"},
    )
    engine.record_review(
        question_id="escalation_1",
        confidence=0.5,
        admin_action="rejected",
        routing_action="queue_high",
        metadata={"source": "escalation"},
    )

    assert len(engine._review_history) == 2
