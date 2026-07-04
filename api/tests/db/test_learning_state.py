"""
Tests for the learning_state persistence layer.

Covers:
- Migration 004 creates the learning_state table (up) and removes it (down)
- FeedbackRepository.set_learning_state / get_learning_state JSON roundtrip
- FeedbackRepository.get_source_feedback_aggregates 30-day SQL aggregate
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from app.db.database import FeedbackDatabase, get_database
from app.db.repository import FeedbackRepository
from app.db.run_migrations import rollback_migration, run_migrations

MIGRATION_NAME = "004_add_learning_state.sql"


@pytest.fixture
def migrated_db_path(tmp_path):
    """Create a temporary database with base schema and all migrations applied."""
    db_path = tmp_path / "test_feedback.db"

    # Reset singleton state to allow fresh initialization for each test
    FeedbackDatabase._instance = None

    db = FeedbackDatabase()
    db.initialize(str(db_path))
    run_migrations(str(db_path))

    yield str(db_path)

    if db_path.exists():
        db_path.unlink()
    FeedbackDatabase._instance = None


@pytest.fixture
def repository(tmp_path):
    """Repository backed by a fresh, fully-migrated per-test database.

    Points the shared database singleton at an isolated tmp_path database so
    aggregate assertions are not polluted by the session-scoped test data dir.
    """
    db_path = str(tmp_path / "feedback.db")

    db = get_database()
    db.reset()
    db.initialize(db_path)
    run_migrations(db_path)
    db.reset()
    db.initialize(db_path)

    return FeedbackRepository()


def _table_exists(db_path: str, table: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


class TestLearningStateMigration:
    """Migration 004 creates and rolls back the learning_state table."""

    def test_learning_state_table_created(self, migrated_db_path):
        assert _table_exists(migrated_db_path, "learning_state")

        conn = sqlite3.connect(migrated_db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(learning_state)")
            columns = {row[1]: row for row in cursor.fetchall()}
        finally:
            conn.close()

        assert set(columns) >= {"key", "value", "updated_at"}
        # key must be the primary key for upsert semantics
        assert columns["key"][5] == 1  # pk flag

    def test_migration_is_idempotent(self, migrated_db_path):
        # Second run must be a no-op, not an error
        run_migrations(migrated_db_path)
        assert _table_exists(migrated_db_path, "learning_state")

    def test_down_migration_removes_table(self, migrated_db_path):
        rollback_migration(migrated_db_path, MIGRATION_NAME)
        assert not _table_exists(migrated_db_path, "learning_state")


class TestLearningStateRepository:
    """JSON-serialized key/value persistence in the feedback database."""

    def test_get_missing_key_returns_none(self, repository):
        assert repository.get_learning_state("does_not_exist") is None

    def test_set_and_get_dict_roundtrip(self, repository):
        weights = {"faq": 1.15, "wiki": 0.9, "llm_wiki": 1.25}
        repository.set_learning_state("source_weights", weights)
        assert repository.get_learning_state("source_weights") == weights

    def test_set_and_get_list_roundtrip(self, repository):
        guidance = ["Keep answers tight.", "Use plain language first."]
        repository.set_learning_state("prompt_guidance", guidance)
        assert repository.get_learning_state("prompt_guidance") == guidance

    def test_set_overwrites_existing_value(self, repository):
        repository.set_learning_state("source_weights", {"faq": 1.0})
        repository.set_learning_state("source_weights", {"faq": 1.2})
        assert repository.get_learning_state("source_weights") == {"faq": 1.2}


class TestSourceFeedbackAggregates:
    """SQL aggregate over the 30-day window replaces full-corpus reloads."""

    @staticmethod
    def _store(repository, rating, sources_used=None, sources=None, days_ago=0):
        timestamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        repository.store_feedback(
            message_id=str(uuid.uuid4()),
            question="q",
            answer="a",
            rating=rating,
            timestamp=timestamp,
            sources=sources,
            sources_used=sources_used,
        )

    def test_counts_positive_and_negative_per_source_type(self, repository):
        faq = [{"type": "faq", "title": "t"}]
        wiki = [{"type": "wiki", "title": "t"}]
        for _ in range(3):
            self._store(repository, rating=1, sources_used=faq)
        for _ in range(2):
            self._store(repository, rating=0, sources_used=faq)
        self._store(repository, rating=1, sources_used=wiki)

        aggregates = repository.get_source_feedback_aggregates(days=30)

        assert aggregates["faq"] == {"positive": 3, "negative": 2, "total": 5}
        assert aggregates["wiki"] == {"positive": 1, "negative": 0, "total": 1}

    def test_excludes_entries_outside_time_window(self, repository):
        faq = [{"type": "faq", "title": "t"}]
        self._store(repository, rating=1, sources_used=faq, days_ago=60)
        self._store(repository, rating=1, sources_used=faq, days_ago=1)

        aggregates = repository.get_source_feedback_aggregates(days=30)

        assert aggregates["faq"]["total"] == 1

    def test_falls_back_to_sources_when_sources_used_absent(self, repository):
        wiki = [{"type": "wiki", "title": "t"}]
        self._store(repository, rating=1, sources=wiki)

        aggregates = repository.get_source_feedback_aggregates(days=30)

        assert aggregates["wiki"]["total"] == 1

    def test_source_without_type_counts_as_unknown(self, repository):
        self._store(repository, rating=0, sources_used=[{"title": "no type"}])

        aggregates = repository.get_source_feedback_aggregates(days=30)

        assert aggregates["unknown"] == {"positive": 0, "negative": 1, "total": 1}

    def test_entries_without_sources_are_ignored(self, repository):
        self._store(repository, rating=1)

        aggregates = repository.get_source_feedback_aggregates(days=30)

        assert aggregates == {}
