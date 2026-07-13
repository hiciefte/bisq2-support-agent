"""Regression tests for the public SQLite-backed feedback statistics endpoint."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_feedback_stats_use_sqlite_and_ignore_legacy_jsonl(
    test_client, test_settings, monkeypatch
):
    """Current SQLite statistics must win over abandoned JSONL data."""
    feedback_dir = Path(test_settings.FEEDBACK_DIR_PATH)
    feedback_dir.mkdir(parents=True, exist_ok=True)
    legacy_feedback = {
        "rating": 0,
        "message_id": "legacy-only",
    }
    (feedback_dir / "feedback_legacy.jsonl").write_text(
        json.dumps(legacy_feedback) + "\n",
        encoding="utf-8",
    )

    repository = SimpleNamespace(
        get_feedback_stats=MagicMock(
            return_value={
                "total": 4,
                "positive": 3,
                "negative": 1,
                "positive_rate": 0.75,
            }
        )
    )
    feedback_service = SimpleNamespace(repository=repository)
    monkeypatch.setattr(
        test_client.app.state,
        "feedback_service",
        feedback_service,
        raising=False,
    )

    response = test_client.get("/feedback/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_feedback": 4,
        "average_rating": pytest.approx(0.75),
        "positive_ratio": pytest.approx(0.75),
    }
    repository.get_feedback_stats.assert_called_once_with()
