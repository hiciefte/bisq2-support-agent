"""Tests for comparison-score-based routing in the pipeline service.

1D: Route candidates based on comparison_score (how well the AI answer
matches the staff answer), not just generation_confidence (which is
not predictive of quality per production data analysis).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.training.unified_pipeline_service import UnifiedPipelineService


def _make_service(*, calibration_mode: bool = False) -> UnifiedPipelineService:
    repo = SimpleNamespace(
        is_calibration_mode=lambda: calibration_mode,
    )
    service = object.__new__(UnifiedPipelineService)
    service.repository = repo
    service.learning_engine = None
    return service


class TestComparisonScoreRouting:
    def test_very_low_score_routes_to_full_review(self) -> None:
        svc = _make_service()
        routing, _ = svc._determine_routing(final_score=0.3, comparison_score=0.3)
        assert routing == "FULL_REVIEW"

    def test_auto_reject_threshold(self) -> None:
        svc = _make_service()
        routing, _ = svc._determine_routing(final_score=0.2, comparison_score=0.2)
        assert routing == "FULL_REVIEW"

    def test_low_comparison_overrides_high_final_score(self) -> None:
        svc = _make_service()
        routing, _ = svc._determine_routing(final_score=0.95, comparison_score=0.3)
        assert routing == "FULL_REVIEW"

    def test_good_scores_allow_spot_check(self) -> None:
        svc = _make_service()
        routing, _ = svc._determine_routing(final_score=0.80, comparison_score=0.60)
        assert routing == "SPOT_CHECK"

    def test_calibration_mode_always_full_review(self) -> None:
        svc = _make_service(calibration_mode=True)
        routing, is_cal = svc._determine_routing(
            final_score=0.99, comparison_score=0.99
        )
        assert routing == "FULL_REVIEW"
        assert is_cal is True

    def test_none_comparison_score_uses_final_score_only(self) -> None:
        svc = _make_service()
        routing, _ = svc._determine_routing(final_score=0.95, comparison_score=None)
        assert routing != "FULL_REVIEW"
