"""Tests for idempotent learning-review updates."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

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


def test_generated_answer_rating_actions_are_normalized() -> None:
    """Legacy answer_* actions should normalize to approved/rejected."""
    engine = LearningEngine()
    engine.min_samples_for_update = 99999

    engine.record_review(
        question_id="answer_rating:1:alice",
        confidence=0.7,
        admin_action="answer_approved",
        routing_action="SPOT_CHECK",
        metadata={"idempotent": True, "review_kind": "answer_quality"},
    )
    engine.record_review(
        question_id="answer_rating:2:alice",
        confidence=0.6,
        admin_action="answer_rejected",
        routing_action="FULL_REVIEW",
        metadata={"idempotent": True, "review_kind": "answer_quality"},
    )

    assert engine._review_history[0]["admin_action"] == "approved"
    assert engine._review_history[1]["admin_action"] == "rejected"


def test_record_review_stores_weight_for_threshold_learning() -> None:
    engine = LearningEngine()
    engine.min_samples_for_update = 99999

    engine.record_review(
        question_id="weighted-rating",
        confidence=0.42,
        admin_action="rejected",
        routing_action="queue_high",
        metadata={"source": "user_rating"},
        weight=5.0,
    )

    assert engine._review_history[0]["weight"] == 5.0


def test_weighted_percentile_uses_review_weights() -> None:
    engine = LearningEngine()

    assert engine._weighted_percentile([0.2, 0.9], 75, [10.0, 1.0]) == 0.2
    assert engine._weighted_percentile(
        [0.2, 0.4, 0.8], 75
    ) == engine._weighted_percentile([0.2, 0.4, 0.8], 75, [1.0, 1.0, 1.0])


def test_review_history_retention_is_per_entry_and_preserves_aggregates() -> None:
    engine = LearningEngine()
    repository = MagicMock()
    engine._repository = repository
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    engine._review_history = [
        {
            "question_id": "old",
            "timestamp": (cutoff - timedelta(seconds=1)).isoformat(),
        },
        {"question_id": "exact", "timestamp": cutoff.isoformat()},
        {
            "question_id": "new",
            "timestamp": (cutoff + timedelta(seconds=1)).isoformat(),
        },
        {"question_id": "unknown", "timestamp": "invalid"},
    ]
    threshold_history = engine._threshold_history.copy()

    assert engine.prune_review_history_before(cutoff, dry_run=True) == 1
    assert len(engine._review_history) == 4
    repository.save_learning_state.assert_not_called()

    assert engine.prune_review_history_before(cutoff) == 1
    assert [row["question_id"] for row in engine._review_history] == [
        "exact",
        "new",
        "unknown",
    ]
    assert engine._threshold_history == threshold_history
    repository.save_learning_state.assert_called_once()
