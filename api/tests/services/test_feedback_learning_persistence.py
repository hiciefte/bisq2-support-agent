"""
Tests for durable feedback learning (weights + prompt guidance).

Covers the verified review findings:
- B1: prompt guidance computed by the cron script must survive process
  boundaries and be visible to the live server (TTL read-through cache).
- B2: learned source weights must persist across restarts.
- B3: store_feedback must debounce weight recomputation and must not
  reload the full feedback corpus per write.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from app.core.config import Settings
from app.db.database import get_database
from app.db.run_migrations import run_migrations
from app.services.feedback_service import FeedbackService

DEFAULT_FAQ_WEIGHT = 1.2


@pytest.fixture
def isolated_settings(tmp_path) -> Settings:
    """Settings backed by a fresh, fully-migrated per-test database.

    The session-scoped test data dir shares one feedback.db across tests;
    persistence assertions here need a clean learning_state per test.
    """
    settings = Settings(
        DEBUG=True,
        DATA_DIR=str(tmp_path),
        OPENAI_API_KEY="test-api-key",
        ADMIN_API_KEY="test-admin-key-with-sufficient-length-24chars",
        ENVIRONMENT="testing",
        COOKIE_SECURE=False,
        OPENAI_MODEL="openai:gpt-4o-mini",
        MAX_CHAT_HISTORY_LENGTH=5,
        MAX_CONTEXT_LENGTH=1000,
    )

    db_path = os.path.join(str(tmp_path), "feedback.db")
    db = get_database()
    db.reset()
    db.initialize(db_path)
    run_migrations(db_path)
    db.reset()
    db.initialize(db_path)

    return settings


def _reset_service_singleton():
    """Simulate a process restart: drop the FeedbackService singleton."""
    if FeedbackService._instance is not None and hasattr(
        FeedbackService._instance, "initialized"
    ):
        delattr(FeedbackService._instance, "initialized")
    FeedbackService._instance = None
    FeedbackService._feedback_cache = None
    FeedbackService._last_load_time = None
    FeedbackService._update_lock = None


def _store_raw_feedback(service, rating, source_type="faq", days_ago=0):
    """Insert feedback directly through the repository (no learning trigger)."""
    timestamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    service.repository.store_feedback(
        message_id=str(uuid.uuid4()),
        question="q",
        answer="a",
        rating=rating,
        timestamp=timestamp,
        sources_used=[{"type": source_type, "title": "t"}],
    )


class _StubAnalyzer:
    """Analyzer stub reporting enough issues to trigger prompt guidance."""

    def analyze_feedback_issues(self, _feedback):
        return {"too_verbose": 6, "wrong_version": 4}


class TestWeightPersistence:
    """B2: learned source weights survive restarts."""

    def test_weights_persist_across_service_instances(self, isolated_settings):
        service = FeedbackService(settings=isolated_settings)
        for _ in range(15):
            _store_raw_feedback(service, rating=1, source_type="faq")

        assert service.apply_feedback_weights() is True
        learned = service.get_source_weights()["faq"]
        assert learned != pytest.approx(DEFAULT_FAQ_WEIGHT)

        _reset_service_singleton()
        restarted = FeedbackService(settings=isolated_settings)

        assert restarted.get_source_weights()["faq"] == pytest.approx(learned)

    def test_weight_recompute_is_idempotent(self, isolated_settings):
        """N recomputes over the same window must equal one recompute."""
        service = FeedbackService(settings=isolated_settings)
        for _ in range(12):
            _store_raw_feedback(service, rating=1, source_type="faq")
        for _ in range(4):
            _store_raw_feedback(service, rating=0, source_type="faq")

        service.apply_feedback_weights()
        after_first = dict(service.get_source_weights())

        for _ in range(5):
            service.apply_feedback_weights()

        assert service.get_source_weights() == pytest.approx(after_first)

    def test_weight_recompute_does_not_load_full_corpus(self, isolated_settings):
        """Recompute must use the SQL aggregate, not get_all_feedback()."""
        service = FeedbackService(settings=isolated_settings)
        for _ in range(15):
            _store_raw_feedback(service, rating=1, source_type="faq")

        service.repository.get_all_feedback = Mock(
            side_effect=AssertionError("full corpus reload during weight recompute")
        )

        assert service.apply_feedback_weights() is True


class TestPromptGuidancePersistence:
    """B1: prompt guidance survives process boundaries."""

    def test_guidance_persists_across_service_instances(self, isolated_settings):
        service = FeedbackService(settings=isolated_settings)
        for _ in range(20):
            _store_raw_feedback(service, rating=0, source_type="faq")
        service.analyzer = _StubAnalyzer()

        assert service.update_prompt_based_on_feedback() is True
        guidance = service.get_prompt_guidance()
        assert guidance

        _reset_service_singleton()
        restarted = FeedbackService(settings=isolated_settings)

        assert restarted.get_prompt_guidance() == guidance

    def test_guidance_written_by_other_process_is_picked_up(self, isolated_settings):
        """Simulates the weekly cron writing guidance while the server runs."""
        service = FeedbackService(settings=isolated_settings)
        assert service.get_prompt_guidance() == []

        # Another process (the cron script) persists new guidance
        cron_guidance = ["Keep answers tight: answer first."]
        service.repository.set_learning_state("prompt_guidance", cron_guidance)

        # Within the TTL the cached (empty) value may be served; force expiry
        service._guidance_refreshed_at = None

        assert service.get_prompt_guidance() == cron_guidance

    def test_weights_written_by_other_process_are_picked_up(self, isolated_settings):
        """Server-side reload of weights persisted by the cron script."""
        service = FeedbackService(settings=isolated_settings)
        assert service.get_source_weights()["faq"] == pytest.approx(DEFAULT_FAQ_WEIGHT)

        service.repository.set_learning_state(
            "source_weights", {"faq": 0.9, "wiki": 1.1, "llm_wiki": 1.0}
        )
        service._weights_refreshed_at = None

        assert service.get_source_weights()["faq"] == pytest.approx(0.9)


class TestCronScriptPersistence:
    """The weekly cron script's output must reach a freshly started server."""

    async def test_cron_script_output_visible_to_fresh_server(
        self, isolated_settings, monkeypatch
    ):
        from app.scripts import process_feedback

        # Seed the shared database with a learnable 30-day window
        seed_service = FeedbackService(settings=isolated_settings)
        for _ in range(15):
            _store_raw_feedback(seed_service, rating=1, source_type="faq")
        for _ in range(20):
            _store_raw_feedback(seed_service, rating=0, source_type="wiki")
        seed_service.analyzer = _StubAnalyzer()

        # Run the cron entry point against the same database
        monkeypatch.setattr(process_feedback, "get_settings", lambda: isolated_settings)
        result = await process_feedback.main()
        assert result == {"entries_processed": 35}

        cron_weights = dict(seed_service.get_source_weights())
        cron_guidance = list(seed_service.get_prompt_guidance())
        assert cron_weights["faq"] != pytest.approx(DEFAULT_FAQ_WEIGHT)
        assert cron_guidance

        # Simulate the live server as a separate process
        _reset_service_singleton()
        server = FeedbackService(settings=isolated_settings)

        assert server.get_source_weights() == pytest.approx(cron_weights)
        assert server.get_prompt_guidance() == cron_guidance


class TestStoreFeedbackDebounce:
    """B3: weight recomputation is debounced on the write path."""

    @staticmethod
    def _feedback_payload():
        return {
            "message_id": str(uuid.uuid4()),
            "question": "q",
            "answer": "a",
            "rating": 1,
            "sources_used": [{"type": "faq", "title": "t"}],
        }

    async def test_rapid_writes_trigger_single_recompute(self, isolated_settings):
        service = FeedbackService(settings=isolated_settings)
        recompute = AsyncMock(return_value=True)
        service.apply_feedback_weights_async = recompute

        for _ in range(5):
            assert await service.store_feedback(self._feedback_payload()) is True

        assert recompute.call_count == 1

    async def test_recompute_runs_again_after_cooldown(self, isolated_settings):
        service = FeedbackService(settings=isolated_settings)
        recompute = AsyncMock(return_value=True)
        service.apply_feedback_weights_async = recompute

        await service.store_feedback(self._feedback_payload())
        assert recompute.call_count == 1

        # Age the last trigger past the cooldown window
        service._last_learning_trigger -= 3600

        await service.store_feedback(self._feedback_payload())
        assert recompute.call_count == 2

    async def test_learning_failure_does_not_fail_storage(self, isolated_settings):
        service = FeedbackService(settings=isolated_settings)
        service.apply_feedback_weights_async = AsyncMock(
            side_effect=Exception("weight crash")
        )

        assert await service.store_feedback(self._feedback_payload()) is True

    async def test_trailing_feedback_is_learned_after_cooldown(
        self, isolated_settings, monkeypatch
    ):
        """A write inside the cooldown must schedule ONE trailing recompute so
        trailing feedback is learned even when no later write arrives."""
        from app.services import feedback_service as feedback_service_module

        monkeypatch.setattr(feedback_service_module, "_LEARNING_COOLDOWN_SECONDS", 0.05)
        service = FeedbackService(settings=isolated_settings)
        recompute = AsyncMock(return_value=True)
        service.apply_feedback_weights_async = recompute

        await service.store_feedback(self._feedback_payload())
        await service.store_feedback(self._feedback_payload())  # inside cooldown
        assert recompute.call_count == 1

        trailing_task = service._pending_learning_task
        assert trailing_task is not None

        # A further write inside the cooldown must not stack a second task.
        await service.store_feedback(self._feedback_payload())
        assert service._pending_learning_task is trailing_task

        await asyncio.wait_for(trailing_task, timeout=2.0)
        assert recompute.call_count == 2
