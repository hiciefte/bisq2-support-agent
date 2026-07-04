"""
Tests for admin feedback analytics aggregation and caching (C1 review fix).

get_feedback_analytics() feeds both /admin/feedback and the /metrics
Prometheus endpoint (scraped every 15s), so it must:
- run the feedback load + aggregation off the event loop,
- memoize the computed analytics dict with a short TTL,
- keep the response shape unchanged.
"""

import asyncio
import threading
from unittest.mock import MagicMock

import pytest
from app.routes.admin import feedback as admin_feedback


@pytest.fixture(autouse=True)
def reset_analytics_cache():
    """Ensure each test starts with an empty analytics cache."""
    admin_feedback.reset_feedback_analytics_cache()
    yield
    admin_feedback.reset_feedback_analytics_cache()


def _sample_rows():
    return [
        {
            "message_id": "m1",
            "rating": 1,
            "sources_used": [{"type": "wiki", "title": "A"}],
        },
        {
            "message_id": "m2",
            "rating": 0,
            "sources": [{"type": "faq", "title": "B"}],
            "metadata": {"issues": ["too_verbose"], "explanation": "x" * 150},
        },
        {
            "message_id": "m3",
            "rating": 0,
            "too_technical": True,
        },
    ]


class TestComputeFeedbackAnalytics:
    """Unit tests for the pure aggregation function."""

    def test_empty_feedback_returns_zeroed_shape(self):
        result = admin_feedback.compute_feedback_analytics([], max_unique_issues=10)
        assert result == {
            "total_feedback": 0,
            "helpful_rate": 0,
            "source_effectiveness": {},
            "common_issues": {},
            "recent_negative": [],
        }

    def test_aggregates_counts_sources_and_issues(self):
        result = admin_feedback.compute_feedback_analytics(
            _sample_rows(), max_unique_issues=10
        )
        assert result["total_feedback"] == 3
        assert result["helpful_count"] == 1
        assert result["unhelpful_count"] == 2
        assert result["helpful_rate"] == pytest.approx(1 / 3)
        assert result["source_effectiveness"]["wiki"] == {"total": 1, "helpful": 1}
        assert result["source_effectiveness"]["faq"] == {"total": 1, "helpful": 0}
        assert result["common_issues"] == {"too_verbose": 1, "too_technical": 1}
        assert len(result["recent_negative"]) == 2

    def test_long_explanations_are_truncated(self):
        result = admin_feedback.compute_feedback_analytics(
            _sample_rows(), max_unique_issues=10
        )
        explanations = [item["explanation"] for item in result["recent_negative"]]
        assert "x" * 100 + "..." in explanations

    def test_issue_cardinality_is_capped(self):
        rows = [
            {"message_id": f"m{i}", "rating": 0, "metadata": {"issues": [f"issue{i}"]}}
            for i in range(10)
        ]
        result = admin_feedback.compute_feedback_analytics(rows, max_unique_issues=10)
        # Unknown free-form issues collapse into the controlled "other" bucket
        assert result["common_issues"] == {"other": 10}

    def test_response_shape_keys_are_stable(self):
        """Both /metrics and the admin endpoint rely on these exact keys."""
        result = admin_feedback.compute_feedback_analytics(
            _sample_rows(), max_unique_issues=10
        )
        assert set(result.keys()) == {
            "total_feedback",
            "helpful_rate",
            "helpful_count",
            "unhelpful_count",
            "source_effectiveness",
            "common_issues",
            "recent_negative",
        }


class TestGetFeedbackAnalyticsCaching:
    """TTL memoization so 15s Prometheus scrapes stay O(1)."""

    def test_load_feedback_called_once_within_ttl(self, monkeypatch):
        load_mock = MagicMock(return_value=_sample_rows())
        monkeypatch.setattr(admin_feedback.feedback_service, "load_feedback", load_mock)

        async def scenario():
            first = await admin_feedback.get_feedback_analytics()
            second = await admin_feedback.get_feedback_analytics()
            return first, second

        first, second = asyncio.run(scenario())

        assert load_mock.call_count == 1
        assert first == second
        assert first["total_feedback"] == 3

    def test_cache_recomputes_after_ttl_expiry(self, monkeypatch):
        load_mock = MagicMock(return_value=_sample_rows())
        monkeypatch.setattr(admin_feedback.feedback_service, "load_feedback", load_mock)
        monkeypatch.setattr(admin_feedback, "_ANALYTICS_CACHE_TTL_SECONDS", 0.0)

        async def scenario():
            await admin_feedback.get_feedback_analytics()
            await admin_feedback.get_feedback_analytics()

        asyncio.run(scenario())

        assert load_mock.call_count == 2


class TestGetFeedbackAnalyticsOffLoop:
    """The load + aggregation must not run on the event loop thread."""

    def test_load_and_aggregation_run_in_worker_thread(self, monkeypatch):
        seen = {}

        def recording_load():
            seen["thread"] = threading.get_ident()
            return _sample_rows()

        monkeypatch.setattr(
            admin_feedback.feedback_service, "load_feedback", recording_load
        )

        async def scenario():
            await admin_feedback.get_feedback_analytics()
            return threading.get_ident()

        loop_thread = asyncio.run(scenario())

        assert seen["thread"] != loop_thread
