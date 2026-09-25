"""Delivery calibration must use answer judgments, not knowledge governance."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.learning_engine import LaunchReadinessChecker, LearningEngine


def review(engine, question_id, confidence=0.85, action="approved", **metadata):
    engine.record_review(
        question_id=question_id,
        confidence=confidence,
        admin_action=action,
        routing_action="SPOT_CHECK",
        metadata={"review_kind": "answer_quality", **metadata},
    )


@pytest.mark.parametrize(
    "kind",
    [
        "faq_decision",
        "llm_wiki_decision",
        "llm_wiki_rework_triage",
        "faq_escape_hatch",
        "unclassified",
    ],
)
def test_knowledge_history_never_unlocks_calibration_or_delivery(kind):
    engine = LearningEngine()
    engine.auto_send_threshold = 0.82  # Preserve a previously stored value.
    original = engine.get_current_thresholds()
    history = engine.get_threshold_history()
    for i in range(100):
        review(engine, str(i), confidence=0.99, review_kind=kind)

    assert len(engine._review_history) == 100
    assert engine.get_calibration_metrics()["total_reviews"] == 0
    assert engine.get_current_thresholds() == original
    assert engine.get_threshold_history() == history
    assert not engine.has_sufficient_calibration_samples()
    assert AutoSendRouter(engine)._get_thresholds() == (0.95, 0.70)
    readiness = LaunchReadinessChecker(engine).check_readiness()
    assert readiness["criteria"]["sufficient_data"]["value"] == 0
    assert not readiness["is_ready"]


def test_unknown_legacy_approval_without_quality_evidence_is_audit_only():
    engine = LearningEngine()
    for i in range(60):
        engine.record_review(str(i), 0.99, "approved", "AUTO_APPROVE")
    assert len(engine.get_threshold_history()) == 1
    assert engine.get_calibration_metrics()["total_reviews"] == 0


def test_minimum_and_update_cadence_only_count_changed_distinct_answers():
    engine = LearningEngine()
    for i in range(49):
        review(engine, f"answer-{i}")
    review(engine, "knowledge", review_kind="faq_decision")
    assert not engine.has_sufficient_calibration_samples()
    assert len(engine.get_threshold_history()) == 1

    review(engine, "answer-49")
    assert engine.has_sufficient_calibration_samples()
    thresholds = engine.get_current_thresholds()
    history = engine.get_threshold_history()
    for i in range(40):
        review(engine, f"knowledge-{i}", review_kind="llm_wiki_decision")
    review(engine, "answer-49", idempotent=True)  # Identical repeated judgment.
    assert engine.get_current_thresholds() == thresholds
    assert engine.get_threshold_history() == history


def test_mixed_history_has_exactly_the_same_percentiles_as_quality_only():
    quality, mixed = LearningEngine(), LearningEngine()
    for engine in (quality, mixed):
        engine.learning_rate = 1.0
    for i in range(99):
        review(
            mixed,
            f"faq-{i}",
            confidence=0.01,
            action="rejected",
            review_kind="faq_decision",
        )
    for i in range(60):
        action = "approved" if i < 45 else "edited" if i < 50 else "rejected"
        confidence = 0.88 if i < 45 else 0.72 if i < 50 else 0.4
        for engine in (quality, mixed):
            review(engine, f"answer-{i}", confidence=confidence, action=action)
    assert mixed.get_current_thresholds() == quality.get_current_thresholds()
    assert mixed.get_current_thresholds() == {
        "auto_send_threshold": 0.88,
        "queue_high_threshold": 0.88,
        "reject_threshold": 0.4,
    }
    assert mixed.get_calibration_metrics() == quality.get_calibration_metrics()


def test_multiple_raters_do_not_turn_one_candidate_into_many_questions():
    engine = LearningEngine()
    for i in range(60):
        review(engine, f"answer_rating:7:reviewer-{i}", idempotent=True)
    assert len(engine._review_history) == 60
    assert engine.get_calibration_metrics()["total_reviews"] == 1
    assert len(engine.get_threshold_history()) == 1
    assert not engine.has_sufficient_calibration_samples()


def test_latest_answer_judgment_wins_and_does_not_replace_knowledge_audit():
    engine = LearningEngine()
    review(engine, "answer_rating:7:alice", action="approved", idempotent=True)
    review(engine, "answer_rating:7:bob", action="rejected", idempotent=True)
    review(engine, "answer_rating:7:alice", action="edited", idempotent=True)
    review(engine, "answer_rating:7:alice", review_kind="faq_decision", idempotent=True)
    assert len(engine._review_history) == 3
    assert engine.get_calibration_metrics()["total_reviews"] == 1
    assert engine.get_calibration_metrics()["edit_rate"] == 1.0
    assert engine._review_history[-1]["metadata"]["review_kind"] == "faq_decision"


def test_staff_response_and_user_ratings_share_the_underlying_question():
    engine = LearningEngine()
    review(engine, "escalation_7", calibration_question_id="escalation:7")
    review(
        engine,
        "user_rating_msg_user-a",
        action="rejected",
        source="user_rating",
        calibration_question_id="escalation:7",
    )
    review(
        engine,
        "user_rating_msg_user-b",
        action="edited",
        source="user_rating",
        calibration_question_id="escalation:7",
    )
    assert engine.get_calibration_metrics()["total_reviews"] == 1
    assert engine.get_calibration_metrics()["edit_rate"] == 1.0


def test_legacy_load_preserves_every_row_and_threshold_without_recalibration():
    base = {
        "confidence": 0.88,
        "admin_action": "approved",
        "routing_action": "SPOT_CHECK",
    }
    rows = [
        {**base, "question_id": "42", "metadata": {"source": "matrix"}},
        {**base, "question_id": "43", "metadata": {"review_kind": "faq_decision"}},
        {
            **base,
            "question_id": "escalation_9",
            "metadata": {"channel": "web", "staff_id": "staff", "edit_distance": 0.0},
        },
        {
            **base,
            "question_id": "answer_rating:8:alice",
            "admin_action": "answer_approved",
            "metadata": {"review_kind": "answer_quality"},
        },
        {
            **base,
            "question_id": "user_rating_msg_person",
            "metadata": {
                "source": "user_rating",
                "idempotent": True,
                "channel": "web",
                "user_rating": 1,
                "original_confidence": 0.88,
                "edit_distance": 0.0,
            },
        },
        {
            **base,
            "question_id": "escalation_10",
            "metadata": {
                "review_kind": "faq_decision",
                "channel": "web",
                "staff_id": "staff",
                "edit_distance": 0.0,
            },
        },
    ]
    state = {
        "auto_send_threshold": 0.84,
        "queue_high_threshold": 0.68,
        "reject_threshold": 0.44,
        "review_history": deepcopy(rows),
        "threshold_history": [{"reason": "legacy", "auto_send": 0.84}],
    }
    repository = MagicMock()
    repository.get_learning_state.return_value = deepcopy(state)
    engine = LearningEngine(repository)
    assert engine._review_history == rows
    assert engine.get_threshold_history() == state["threshold_history"]
    assert engine.get_current_thresholds() == {
        k: state[k]
        for k in ("auto_send_threshold", "queue_high_threshold", "reject_threshold")
    }
    assert engine.get_calibration_metrics()["total_reviews"] == 2
    assert engine.get_learning_metrics()["answer_quality_reviews_total"] == 3
    repository.save_learning_state.assert_not_called()
    engine.save_state(repository)
    assert repository.save_learning_state.call_args.kwargs["review_history"] == rows


def test_legacy_duplicate_question_uses_latest_timestamp_not_list_position():
    engine = LearningEngine()
    engine._review_history = [
        {
            "question_id": "answer_rating:7:alice",
            "confidence": 0.91,
            "admin_action": "approved",
            "metadata": {"review_kind": "answer_quality"},
            "timestamp": "2026-09-25T12:00:00+00:00",
        },
        {
            "question_id": "answer_rating:7:bob",
            "confidence": 0.2,
            "admin_action": "rejected",
            "metadata": {"review_kind": "answer_quality"},
            "timestamp": "2026-09-25T11:00:00+00:00",
        },
    ]
    assert engine.get_calibration_metrics()["total_reviews"] == 1
    assert engine.get_calibration_metrics()["approval_rate"] == 1.0


def test_invalid_quality_values_do_not_count_toward_sample_minimum():
    engine = LearningEngine()
    for i, confidence in enumerate([float("nan"), float("inf"), -0.1, 1.1]):
        review(engine, f"bad-{i}", confidence=confidence)
    assert len(engine._review_history) == 4
    assert engine.get_calibration_metrics()["total_reviews"] == 0


def test_persistence_caps_separate_cohorts_without_changing_history_or_thresholds(
    tmp_path,
):
    from app.services.knowledge.candidate_repository import KnowledgeCandidateRepository

    quality = [
        {
            "question_id": f"answer-{i}",
            "confidence": 0.88,
            "admin_action": "approved",
            "metadata": {"review_kind": "answer_quality"},
        }
        for i in range(60)
    ]
    knowledge = [
        {
            "question_id": f"knowledge-{i}",
            "confidence": 0.99,
            "admin_action": "approved",
            "metadata": {"review_kind": "llm_wiki_decision"},
        }
        for i in range(1100)
    ]
    reviews = quality + knowledge
    preserved = deepcopy(reviews)
    engine = LearningEngine()
    engine._review_history = reviews
    engine.auto_send_threshold = 0.843
    fake_repository = MagicMock()
    engine.save_state(fake_repository)
    expected = quality + knowledge[-1000:]
    assert (
        fake_repository.save_learning_state.call_args.kwargs["review_history"]
        == expected
    )
    assert engine._review_history == preserved
    engine._repository = fake_repository
    engine._auto_persist()
    assert (
        fake_repository.save_learning_state.call_args.kwargs["review_history"]
        == expected
    )

    repository = KnowledgeCandidateRepository(str(tmp_path / "learning.db"))
    # Direct repository callers are bounded by the same rule.
    repository.save_learning_state(
        0.843, 0.7, 0.4, reviews, [{"auto_send": 0.843, "reason": "legacy"}]
    )
    loaded = LearningEngine(repository)
    assert loaded._review_history == expected
    assert loaded.auto_send_threshold == 0.843
    assert loaded.get_calibration_metrics()["total_reviews"] == 60
    assert loaded.has_sufficient_calibration_samples()
    assert reviews == preserved


def test_persistence_cap_bounds_both_cohorts_and_preserves_interleaved_order():
    rows = [
        row
        for i in range(5)
        for row in (
            {
                "question_id": f"quality-{i}",
                "metadata": {"review_kind": "answer_quality"},
            },
            {
                "question_id": f"knowledge-{i}",
                "metadata": {"review_kind": "faq_decision"},
            },
        )
    ]
    assert LearningEngine.bounded_review_history(rows, per_kind_limit=2) == rows[-4:]
    assert LearningEngine.bounded_review_history(rows, per_kind_limit=0) == []
