"""Tests for FeedbackService and FeedbackRepository reaction-feedback extensions.

Covers:
- Repository: store_feedback with channel metadata, reaction tracking CRUD
- Service: store_reaction_feedback, revoke_reaction_feedback
- Stats: feedback_by_channel and feedback_by_method breakdowns
"""

import sqlite3
from unittest.mock import MagicMock

import pytest
from app.db.repository import FeedbackRepository
from app.services.feedback_service import FeedbackService


@pytest.fixture()
def db_conn(tmp_path):
    """Create a fresh SQLite DB with full schema + migration 003."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Base schema
    conn.execute("""
        CREATE TABLE feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            rating INTEGER NOT NULL,
            explanation TEXT,
            sources TEXT,
            sources_used TEXT,
            timestamp TEXT NOT NULL,
            processed INTEGER DEFAULT 0,
            processed_at TEXT,
            faq_id TEXT,
            channel TEXT DEFAULT 'web' NOT NULL,
            feedback_method TEXT DEFAULT 'web_dialog' NOT NULL,
            external_message_id TEXT,
            reactor_identity_hash TEXT,
            reaction_emoji TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            position INTEGER NOT NULL,
            FOREIGN KEY (feedback_id) REFERENCES feedback(id)
        )
    """)
    conn.execute("""
        CREATE TABLE feedback_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            FOREIGN KEY (feedback_id) REFERENCES feedback(id)
        )
    """)
    conn.execute("""
        CREATE TABLE feedback_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER NOT NULL,
            issue_type TEXT NOT NULL,
            FOREIGN KEY (feedback_id) REFERENCES feedback(id)
        )
    """)
    conn.execute("""
        CREATE TABLE feedback_reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            external_message_id TEXT NOT NULL,
            reactor_identity_hash TEXT NOT NULL,
            reaction_emoji TEXT NOT NULL,
            feedback_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE,
            UNIQUE(channel, external_message_id, reactor_identity_hash)
        )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_channel ON feedback(channel, timestamp)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_method ON feedback(feedback_method)"
    )

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture()
def repo(db_conn):
    """FeedbackRepository with mocked database connection."""
    repository = FeedbackRepository.__new__(FeedbackRepository)
    mock_db = MagicMock()
    mock_db.get_connection.return_value.__enter__ = lambda _: db_conn
    mock_db.get_connection.return_value.__exit__ = MagicMock(return_value=False)
    repository.db = mock_db
    return repository


# =============================================================================
# Repository: store_feedback with channel metadata
# =============================================================================


class TestRepositoryStoreWithChannelMetadata:
    """Test store_feedback with new channel fields."""

    def test_store_with_defaults(self, repo, db_conn):
        """Storing without channel fields uses defaults."""
        feedback_id = repo.store_feedback(
            message_id="m1",
            question="Q",
            answer="A",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
        )
        row = db_conn.execute(
            "SELECT channel, feedback_method FROM feedback WHERE id=?",
            (feedback_id,),
        ).fetchone()
        assert row["channel"] == "web"
        assert row["feedback_method"] == "web_dialog"

    def test_store_with_channel_metadata(self, repo, db_conn):
        """Storing with explicit channel fields persists them."""
        feedback_id = repo.store_feedback(
            message_id="m1",
            question="Q",
            answer="A",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
            channel="matrix",
            feedback_method="reaction",
            external_message_id="$evt:server",
            reactor_identity_hash="hash123",
            reaction_emoji="\U0001f44d",
        )
        row = db_conn.execute(
            "SELECT channel, feedback_method, external_message_id, "
            "reactor_identity_hash, reaction_emoji FROM feedback WHERE id=?",
            (feedback_id,),
        ).fetchone()
        assert row["channel"] == "matrix"
        assert row["feedback_method"] == "reaction"
        assert row["external_message_id"] == "$evt:server"
        assert row["reactor_identity_hash"] == "hash123"
        assert row["reaction_emoji"] == "\U0001f44d"


# =============================================================================
# Repository: reaction tracking
# =============================================================================


class TestRepositoryReactionTracking:
    """Test reaction tracking CRUD methods."""

    def _store_feedback(self, repo):
        return repo.store_feedback(
            message_id="m1",
            question="Q",
            answer="A",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
            channel="matrix",
            feedback_method="reaction",
        )

    def test_upsert_reaction_creates_new(self, repo, db_conn):
        """upsert_reaction_tracking creates a new reaction record."""
        feedback_id = self._store_feedback(repo)
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44d",
            feedback_id=feedback_id,
        )
        row = db_conn.execute(
            "SELECT * FROM feedback_reactions WHERE channel='matrix'"
        ).fetchone()
        assert row is not None
        assert row["reaction_emoji"] == "\U0001f44d"
        assert row["revoked_at"] is None

    def test_upsert_reaction_updates_existing(self, repo, db_conn):
        """upsert_reaction_tracking updates emoji on existing reaction."""
        feedback_id = self._store_feedback(repo)
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44d",
            feedback_id=feedback_id,
        )
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44e",
            feedback_id=feedback_id,
        )
        count = db_conn.execute(
            "SELECT COUNT(*) as c FROM feedback_reactions"
        ).fetchone()["c"]
        assert count == 1
        row = db_conn.execute(
            "SELECT reaction_emoji FROM feedback_reactions"
        ).fetchone()
        assert row["reaction_emoji"] == "\U0001f44e"

    def test_get_reaction_by_key(self, repo, db_conn):
        """get_reaction_by_key returns matching reaction."""
        feedback_id = self._store_feedback(repo)
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44d",
            feedback_id=feedback_id,
        )
        result = repo.get_reaction_by_key("matrix", "$evt:server", "hash1")
        assert result is not None
        assert result["feedback_id"] == feedback_id

    def test_get_reaction_by_key_not_found(self, repo):
        """get_reaction_by_key returns None when not found."""
        result = repo.get_reaction_by_key("matrix", "$evt:server", "hash1")
        assert result is None

    def test_revoke_reaction_tracking(self, repo, db_conn):
        """revoke_reaction_tracking sets revoked_at."""
        feedback_id = self._store_feedback(repo)
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44d",
            feedback_id=feedback_id,
        )
        result = repo.revoke_reaction_tracking("matrix", "$evt:server", "hash1")
        assert result is True
        row = db_conn.execute("SELECT revoked_at FROM feedback_reactions").fetchone()
        assert row["revoked_at"] is not None

    def test_get_active_reaction_rating_returns_rating(self, repo, db_conn):
        feedback_id = self._store_feedback(repo)
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44d",
            feedback_id=feedback_id,
        )
        rating = repo.get_active_reaction_rating("matrix", "$evt:server", "hash1")
        assert rating == 1

    def test_get_active_reaction_rating_returns_none_when_revoked(self, repo, db_conn):
        feedback_id = self._store_feedback(repo)
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44d",
            feedback_id=feedback_id,
        )
        repo.revoke_reaction_tracking("matrix", "$evt:server", "hash1")
        rating = repo.get_active_reaction_rating("matrix", "$evt:server", "hash1")
        assert rating is None


class TestFeedbackServiceReactionProjection:
    """Test that reaction revocation removes active feedback projection."""

    @staticmethod
    def _service_with_repo(repo) -> FeedbackService:
        service = FeedbackService.__new__(FeedbackService)
        service.repository = repo
        service._feedback_cache = None
        service._last_load_time = None
        return service

    def test_revoke_reaction_feedback_removes_feedback_row(self, repo, db_conn):
        feedback_id = repo.store_feedback(
            message_id="m1",
            question="Q",
            answer="A",
            rating=0,
            timestamp="2024-01-01T00:00:00Z",
            channel="matrix",
            feedback_method="reaction",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44e",
        )
        repo.upsert_reaction_tracking(
            channel="matrix",
            external_message_id="$evt:server",
            reactor_identity_hash="hash1",
            reaction_emoji="\U0001f44e",
            feedback_id=feedback_id,
        )
        service = self._service_with_repo(repo)

        result = service.revoke_reaction_feedback("matrix", "$evt:server", "hash1")

        assert result is True
        feedback_count = db_conn.execute(
            "SELECT COUNT(*) AS c FROM feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()["c"]
        assert feedback_count == 0


# =============================================================================
# Repository: channel stats
# =============================================================================


class TestRepositoryChannelStats:
    """Test channel-based statistics queries."""

    def _store_entries(self, repo):
        repo.store_feedback(
            message_id="m1",
            question="Q1",
            answer="A1",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
            channel="web",
            feedback_method="web_dialog",
        )
        repo.store_feedback(
            message_id="m2",
            question="Q2",
            answer="A2",
            rating=0,
            timestamp="2024-01-01T00:00:00Z",
            channel="matrix",
            feedback_method="reaction",
        )
        repo.store_feedback(
            message_id="m3",
            question="Q3",
            answer="A3",
            rating=1,
            timestamp="2024-01-01T00:00:00Z",
            channel="matrix",
            feedback_method="reaction",
        )

    def test_get_feedback_stats_by_channel(self, repo):
        """get_feedback_stats_by_channel returns per-channel breakdown."""
        self._store_entries(repo)
        stats = repo.get_feedback_stats_by_channel()
        assert "web" in stats
        assert "matrix" in stats
        assert stats["web"]["total"] == 1
        assert stats["matrix"]["total"] == 2

    def test_get_feedback_count_by_method(self, repo):
        """get_feedback_count_by_method returns per-method breakdown."""
        self._store_entries(repo)
        stats = repo.get_feedback_count_by_method()
        assert "web_dialog" in stats
        assert "reaction" in stats
        assert stats["web_dialog"]["total"] == 1
        assert stats["reaction"]["total"] == 2
