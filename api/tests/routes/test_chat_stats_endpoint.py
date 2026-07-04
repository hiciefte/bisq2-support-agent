"""
Tests for GET /chat/stats (C2 review fix).

The endpoint must source statistics from SQLite-backed feedback via
FeedbackService.load_feedback() instead of reading legacy JSONL files,
run the aggregation off the event loop, and memoize results briefly.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.routes import chat
from app.services.feedback_service import FeedbackService


@pytest.fixture(autouse=True)
def reset_stats_cache():
    """Ensure each test starts with an empty chat-stats cache."""
    chat.reset_chat_stats_cache()
    yield
    chat.reset_chat_stats_cache()


def _row(response_time, timestamp=None, **extra):
    row = {"message_id": "m", "rating": 1, **extra}
    if response_time is not None:
        row["metadata"] = {"response_time": response_time}
    if timestamp is not None:
        row["timestamp"] = timestamp
    return row


def _sample_rows(now=None):
    now = now or datetime.now()
    recent = (now - timedelta(hours=1)).isoformat()
    old = (now - timedelta(days=3)).isoformat()
    return [
        _row(10.0, recent),
        _row(40.0, old),
        _row(30.0, recent),
        _row(None, recent),  # no metadata -> ignored
        {"message_id": "m5", "rating": 0, "metadata": {"other": 1}},  # ignored
    ]


class TestComputeChatStats:
    """Unit tests for the pure aggregation function."""

    def test_empty_feedback_returns_defaults(self):
        stats = chat.compute_chat_stats([])
        assert stats == {
            "total_queries": 0,
            "average_response_time": 300.0,
            "last_24h_average_response_time": 300.0,
        }

    def test_aggregates_overall_and_recent_averages(self):
        now = datetime.now()
        stats = chat.compute_chat_stats(_sample_rows(now), now=now)
        assert stats["total_queries"] == 3
        assert stats["average_response_time"] == pytest.approx(80.0 / 3)
        assert stats["last_24h_average_response_time"] == pytest.approx(20.0)

    def test_no_recent_queries_falls_back_to_overall_average(self):
        now = datetime.now()
        old = (now - timedelta(days=2)).isoformat()
        stats = chat.compute_chat_stats([_row(12.0, old)], now=now)
        assert stats["total_queries"] == 1
        assert stats["average_response_time"] == pytest.approx(12.0)
        assert stats["last_24h_average_response_time"] == pytest.approx(12.0)

    def test_invalid_timestamp_is_tolerated(self):
        stats = chat.compute_chat_stats(
            [_row(5.0, "not-a-timestamp"), _row(15.0, None)]
        )
        assert stats["total_queries"] == 2
        assert stats["average_response_time"] == pytest.approx(10.0)

    def test_timezone_aware_timestamps_counted_in_last_24h(self):
        """FeedbackService writes UTC ISO timestamps ("...+00:00"); they must
        be compared against an aware cutoff instead of silently dropping out
        of the 24h window via a swallowed naive/aware TypeError."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        old = (now - timedelta(days=3)).isoformat()
        assert recent.endswith("+00:00")

        stats = chat.compute_chat_stats([_row(10.0, recent), _row(50.0, old)])

        assert stats["total_queries"] == 2
        assert stats["average_response_time"] == pytest.approx(30.0)
        # Only the recent row is inside the 24h window.
        assert stats["last_24h_average_response_time"] == pytest.approx(10.0)

    def test_naive_timestamps_treated_as_utc(self):
        """Legacy naive timestamps keep working and are interpreted as UTC."""
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        old = (now - timedelta(days=3)).replace(tzinfo=None).isoformat()

        stats = chat.compute_chat_stats([_row(10.0, recent), _row(50.0, old)])

        assert stats["last_24h_average_response_time"] == pytest.approx(10.0)


class TestChatStatsEndpoint:
    """Integration tests for GET /chat/stats using SQLite-backed feedback."""

    def test_stats_computed_from_feedback_service(self, test_client, monkeypatch):
        now = datetime.now()
        monkeypatch.setattr(
            FeedbackService, "load_feedback", lambda self: _sample_rows(now)
        )

        response = test_client.get("/chat/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_queries"] == 3
        assert data["average_response_time"] == pytest.approx(80.0 / 3)
        assert data["last_24h_average_response_time"] == pytest.approx(20.0)

    def test_stats_defaults_when_no_feedback(self, test_client, monkeypatch):
        monkeypatch.setattr(FeedbackService, "load_feedback", lambda self: [])

        response = test_client.get("/chat/stats")

        assert response.status_code == 200
        assert response.json() == {
            "total_queries": 0,
            "average_response_time": 300.0,
            "last_24h_average_response_time": 300.0,
        }

    def test_stats_ignore_legacy_jsonl_files(
        self, test_client, test_settings, monkeypatch
    ):
        """Legacy feedback_*.jsonl files must no longer influence the stats."""
        feedback_dir = Path(test_settings.FEEDBACK_DIR_PATH)
        feedback_dir.mkdir(parents=True, exist_ok=True)
        legacy = {
            "metadata": {"response_time": 999.0},
            "timestamp": datetime.now().isoformat(),
        }
        (feedback_dir / "feedback_legacy.jsonl").write_text(json.dumps(legacy) + "\n")

        monkeypatch.setattr(FeedbackService, "load_feedback", lambda self: [])

        response = test_client.get("/chat/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["total_queries"] == 0
        assert data["average_response_time"] == 300.0

    def test_stats_cached_within_ttl(self, test_client, monkeypatch):
        calls = {"count": 0}

        def counting_load(self):
            calls["count"] += 1
            return _sample_rows()

        monkeypatch.setattr(FeedbackService, "load_feedback", counting_load)

        first = test_client.get("/chat/stats")
        second = test_client.get("/chat/stats")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert calls["count"] == 1

    def test_stats_recomputed_after_ttl_expiry(self, test_client, monkeypatch):
        calls = {"count": 0}

        def counting_load(self):
            calls["count"] += 1
            return _sample_rows()

        monkeypatch.setattr(FeedbackService, "load_feedback", counting_load)
        monkeypatch.setattr(chat, "_CHAT_STATS_TTL_SECONDS", 0.0)

        test_client.get("/chat/stats")
        test_client.get("/chat/stats")

        assert calls["count"] == 2
