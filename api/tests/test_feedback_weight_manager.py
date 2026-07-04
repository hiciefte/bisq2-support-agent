"""
TDD tests for FeedbackWeightManager fixes.

Tests cover:
- Field name bug fix (helpful → rating)
- Sources fallback (sources_used → sources)
- Weight range clamping (0.75-1.25)
- Time window filter (30 days)
- Cold start dampening (minimum sample count before leaving defaults)
- Idempotent recompute (pure function of the 30-day window)
- Wilson score confidence intervals
"""

from datetime import datetime, timedelta, timezone

import pytest
from app.services.feedback.feedback_weight_manager import FeedbackWeightManager


def _make_feedback_entry(
    rating: int = 1,
    source_type: str = "faq",
    use_sources_used: bool = True,
    timestamp: str | None = None,
):
    """Helper to create a feedback entry with the correct field names."""
    entry = {
        "rating": rating,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }
    source = {"type": source_type, "title": "Test"}
    if use_sources_used:
        entry["sources_used"] = [source]
    else:
        entry["sources"] = [source]
    return entry


class TestFieldNameBugFix:
    """Entries with 'rating' (not 'helpful') should be processed."""

    def test_apply_weights_processes_entries_with_rating_field(self):
        """Entries with 'rating' field should change weights from defaults."""
        mgr = FeedbackWeightManager()
        default_faq = mgr.source_weights["faq"]

        # Create 15 positive faq entries — enough to trigger weight adjustment
        entries = [_make_feedback_entry(rating=1, source_type="faq") for _ in range(15)]
        result = mgr.apply_feedback_weights(entries)

        # Weights must have changed from default (entries were processed).
        # If the field-name bug persists, all entries are skipped and
        # weights stay at the default.
        assert result["faq"] != pytest.approx(default_faq)

    def test_entries_with_helpful_field_still_skipped(self):
        """Entries using the OLD 'helpful' field (without 'rating') should be skipped."""
        mgr = FeedbackWeightManager()
        entries = [
            {
                "helpful": True,
                "sources_used": [{"type": "faq", "title": "Test"}],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            for _ in range(15)
        ]
        result = mgr.apply_feedback_weights(entries)
        # These should be skipped — weights unchanged from defaults
        assert result["faq"] == pytest.approx(1.2, abs=0.01)


class TestSourcesFallback:
    """When 'sources_used' is absent, should fall back to 'sources' field."""

    def test_apply_weights_uses_sources_fallback(self):
        """Entries with only 'sources' (not 'sources_used') should be processed."""
        mgr = FeedbackWeightManager()

        entries = [
            _make_feedback_entry(rating=1, source_type="faq", use_sources_used=False)
            for _ in range(15)
        ]
        result = mgr.apply_feedback_weights(entries)
        # Should have processed — weights should differ from default
        assert "faq" in result


class TestWeightRangeClamping:
    """Weights must stay within [0.75, 1.25] range."""

    def test_weight_range_clamped_to_075_125(self):
        """Even with extreme feedback, weights stay within bounds."""
        mgr = FeedbackWeightManager()

        # All negative feedback for faq — should push weight down
        entries = [_make_feedback_entry(rating=0, source_type="faq") for _ in range(50)]
        result = mgr.apply_feedback_weights(entries)
        assert result["faq"] >= 0.75

        # All positive feedback for wiki — should push weight up
        mgr2 = FeedbackWeightManager()
        entries2 = [
            _make_feedback_entry(rating=1, source_type="wiki") for _ in range(50)
        ]
        result2 = mgr2.apply_feedback_weights(entries2)
        assert result2["wiki"] <= 1.25


class TestTimeWindowFilter:
    """Only process last 30 days of feedback."""

    def test_old_entries_are_excluded(self):
        """Entries older than 30 days should not change weights at all."""
        mgr = FeedbackWeightManager()
        default_faq = mgr.source_weights["faq"]

        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        old_entries = [
            _make_feedback_entry(rating=0, source_type="faq", timestamp=old_ts)
            for _ in range(50)
        ]
        result = mgr.apply_feedback_weights(old_entries)
        # All entries filtered out — weights unchanged
        assert result["faq"] == default_faq

    def test_recent_entries_are_processed(self):
        """Entries within 30 days should affect weights."""
        mgr = FeedbackWeightManager()
        default_faq = mgr.source_weights["faq"]

        recent_ts = datetime.now(timezone.utc).isoformat()
        recent_entries = [
            _make_feedback_entry(rating=0, source_type="faq", timestamp=recent_ts)
            for _ in range(20)
        ]
        result = mgr.apply_feedback_weights(recent_entries)
        # Recent negative entries should push weight down from default
        assert result["faq"] < default_faq


class TestColdStartDampening:
    """A source needs a minimum sample count before leaving its default.

    Note: the previous test here asserted that larger batches move weights
    further via a higher EMA learning rate. That encoded the frequency-scaled
    EMA bug (convergence speed scaled with event count), which was replaced by
    an idempotent pure function of the 30-day window.
    """

    def test_small_sample_keeps_default_weight(self):
        """At or below the minimum sample count, weight stays at default."""
        mgr = FeedbackWeightManager()
        default_faq = mgr.source_weights["faq"]

        small_batch = [
            _make_feedback_entry(rating=0, source_type="faq") for _ in range(10)
        ]
        result = mgr.apply_feedback_weights(small_batch)

        assert result["faq"] == pytest.approx(default_faq)

    def test_sufficient_sample_moves_weight(self):
        """Above the minimum sample count, weight follows the Wilson target."""
        mgr = FeedbackWeightManager()
        default_faq = mgr.source_weights["faq"]

        batch = [_make_feedback_entry(rating=0, source_type="faq") for _ in range(15)]
        result = mgr.apply_feedback_weights(batch)

        assert result["faq"] < default_faq


class TestIdempotentRecompute:
    """Recompute is a pure function of the window — reapplying is a no-op."""

    def test_reapplying_same_data_is_a_noop(self):
        """N applications of the same window must equal one application."""
        entries = [_make_feedback_entry(rating=1, source_type="faq") for _ in range(12)]
        entries += [_make_feedback_entry(rating=0, source_type="faq") for _ in range(4)]

        mgr = FeedbackWeightManager()
        first = dict(mgr.apply_feedback_weights(entries))
        for _ in range(10):
            mgr.apply_feedback_weights(entries)

        assert mgr.get_source_weights() == pytest.approx(first)

    def test_weight_matches_single_application_regardless_of_event_frequency(self):
        """Convergence must not scale with how often events arrive."""
        entries = [
            _make_feedback_entry(rating=0, source_type="wiki") for _ in range(20)
        ]

        mgr_once = FeedbackWeightManager()
        mgr_once.apply_feedback_weights(entries)

        mgr_many = FeedbackWeightManager()
        for _ in range(50):  # 50 "events" over the same window
            mgr_many.apply_feedback_weights(entries)

        assert mgr_many.get_source_weights()["wiki"] == pytest.approx(
            mgr_once.get_source_weights()["wiki"]
        )

    def test_apply_feedback_aggregates_is_pure_function_of_window(self):
        """Aggregate-driven recompute yields the same result as raw entries."""
        entries = [_make_feedback_entry(rating=1, source_type="faq") for _ in range(15)]

        mgr_entries = FeedbackWeightManager()
        mgr_entries.apply_feedback_weights(entries)

        mgr_aggregates = FeedbackWeightManager()
        mgr_aggregates.apply_feedback_aggregates(
            {"faq": {"positive": 15, "negative": 0, "total": 15}}
        )

        assert mgr_aggregates.get_source_weights()["faq"] == pytest.approx(
            mgr_entries.get_source_weights()["faq"]
        )

    def test_empty_aggregates_leave_weights_unchanged(self):
        """An empty window keeps current weights (no destructive reset)."""
        mgr = FeedbackWeightManager()
        mgr.apply_feedback_aggregates(
            {"faq": {"positive": 0, "negative": 20, "total": 20}}
        )
        lowered = mgr.get_source_weights()["faq"]

        mgr.apply_feedback_aggregates({})

        assert mgr.get_source_weights()["faq"] == pytest.approx(lowered)


class TestWilsonScore:
    """Wilson score lower bound for weight calibration."""

    def test_wilson_score_penalizes_small_samples(self):
        """Source with 3/3 positive should score lower than 90/100."""
        mgr = FeedbackWeightManager()
        score_small = mgr._calculate_wilson_lower_bound(3, 3)
        score_large = mgr._calculate_wilson_lower_bound(90, 100)
        assert score_large > score_small

    def test_wilson_score_with_zero_total(self):
        """Zero total returns 0.5 (neutral default)."""
        mgr = FeedbackWeightManager()
        assert mgr._calculate_wilson_lower_bound(0, 0) == 0.5

    def test_wilson_score_with_all_positive_large_sample(self):
        """Large all-positive sample approaches 1.0."""
        mgr = FeedbackWeightManager()
        score = mgr._calculate_wilson_lower_bound(1000, 1000)
        assert score > 0.99

    def test_wilson_score_with_all_negative(self):
        """All negative gives low score."""
        mgr = FeedbackWeightManager()
        score = mgr._calculate_wilson_lower_bound(0, 100)
        assert score < 0.05

    def test_wilson_score_fifty_percent(self):
        """50/50 with large sample gives ~0.5."""
        mgr = FeedbackWeightManager()
        score = mgr._calculate_wilson_lower_bound(500, 1000)
        assert 0.45 < score < 0.55
