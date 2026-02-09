"""Tests for migration 003: reaction feedback schema extensions.

Verifies:
- New columns on feedback table (channel, feedback_method, etc.)
- feedback_reactions table creation with uniqueness constraint
- Indexes on channel and method
- Default values for backwards compatibility
"""

import sqlite3

import pytest


@pytest.fixture()
def migrated_db(tmp_path):
    """Create an in-memory DB with base schema + migration 003 applied."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Create base feedback table (simplified from real schema)
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
            faq_id TEXT
        )
    """)

    # Apply migration 003
    conn.execute("ALTER TABLE feedback ADD COLUMN channel TEXT DEFAULT 'web' NOT NULL")
    conn.execute(
        "ALTER TABLE feedback ADD COLUMN feedback_method TEXT DEFAULT 'web_dialog' NOT NULL"
    )
    conn.execute("ALTER TABLE feedback ADD COLUMN external_message_id TEXT")
    conn.execute("ALTER TABLE feedback ADD COLUMN reactor_identity_hash TEXT")
    conn.execute("ALTER TABLE feedback ADD COLUMN reaction_emoji TEXT")

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_channel ON feedback(channel, timestamp)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_method ON feedback(feedback_method)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_reactions (
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
    conn.commit()
    yield conn
    conn.close()


class TestFeedbackTableExtensions:
    """Test new columns on feedback table."""

    def test_channel_default_is_web(self, migrated_db):
        migrated_db.execute(
            "INSERT INTO feedback (message_id, question, answer, rating, timestamp) "
            "VALUES ('m1', 'Q', 'A', 1, '2024-01-01T00:00:00Z')"
        )
        row = migrated_db.execute(
            "SELECT channel FROM feedback WHERE message_id='m1'"
        ).fetchone()
        assert row["channel"] == "web"

    def test_feedback_method_default_is_web_dialog(self, migrated_db):
        migrated_db.execute(
            "INSERT INTO feedback (message_id, question, answer, rating, timestamp) "
            "VALUES ('m1', 'Q', 'A', 1, '2024-01-01T00:00:00Z')"
        )
        row = migrated_db.execute(
            "SELECT feedback_method FROM feedback WHERE message_id='m1'"
        ).fetchone()
        assert row["feedback_method"] == "web_dialog"

    def test_channel_can_be_set(self, migrated_db):
        migrated_db.execute(
            "INSERT INTO feedback (message_id, question, answer, rating, timestamp, channel) "
            "VALUES ('m1', 'Q', 'A', 1, '2024-01-01T00:00:00Z', 'matrix')"
        )
        row = migrated_db.execute(
            "SELECT channel FROM feedback WHERE message_id='m1'"
        ).fetchone()
        assert row["channel"] == "matrix"

    def test_reaction_fields_nullable(self, migrated_db):
        migrated_db.execute(
            "INSERT INTO feedback (message_id, question, answer, rating, timestamp) "
            "VALUES ('m1', 'Q', 'A', 1, '2024-01-01T00:00:00Z')"
        )
        row = migrated_db.execute(
            "SELECT external_message_id, reactor_identity_hash, reaction_emoji "
            "FROM feedback WHERE message_id='m1'"
        ).fetchone()
        assert row["external_message_id"] is None
        assert row["reactor_identity_hash"] is None
        assert row["reaction_emoji"] is None

    def test_reaction_fields_can_be_set(self, migrated_db):
        migrated_db.execute(
            "INSERT INTO feedback "
            "(message_id, question, answer, rating, timestamp, channel, "
            "feedback_method, external_message_id, reactor_identity_hash, reaction_emoji) "
            "VALUES ('m1', 'Q', 'A', 1, '2024-01-01T00:00:00Z', 'matrix', "
            "'reaction', '$evt:server', 'hash123', '👍')"
        )
        row = migrated_db.execute(
            "SELECT external_message_id, reactor_identity_hash, reaction_emoji "
            "FROM feedback WHERE message_id='m1'"
        ).fetchone()
        assert row["external_message_id"] == "$evt:server"
        assert row["reactor_identity_hash"] == "hash123"
        assert row["reaction_emoji"] == "\U0001f44d"


class TestFeedbackReactionsTable:
    """Test feedback_reactions table."""

    def _insert_feedback(self, conn, msg_id="m1"):
        conn.execute(
            "INSERT INTO feedback (message_id, question, answer, rating, timestamp) "
            f"VALUES ('{msg_id}', 'Q', 'A', 1, '2024-01-01T00:00:00Z')"
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_insert_reaction(self, migrated_db):
        feedback_id = self._insert_feedback(migrated_db)
        migrated_db.execute(
            "INSERT INTO feedback_reactions "
            "(channel, external_message_id, reactor_identity_hash, "
            "reaction_emoji, feedback_id, created_at, last_updated_at) "
            "VALUES ('matrix', '$evt:server', 'hash1', '👍', ?, "
            "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')",
            (feedback_id,),
        )
        migrated_db.commit()
        row = migrated_db.execute(
            "SELECT * FROM feedback_reactions WHERE channel='matrix'"
        ).fetchone()
        assert row["reaction_emoji"] == "\U0001f44d"

    def test_uniqueness_constraint(self, migrated_db):
        feedback_id = self._insert_feedback(migrated_db)
        migrated_db.execute(
            "INSERT INTO feedback_reactions "
            "(channel, external_message_id, reactor_identity_hash, "
            "reaction_emoji, feedback_id, created_at, last_updated_at) "
            "VALUES ('matrix', '$evt:server', 'hash1', '👍', ?, "
            "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')",
            (feedback_id,),
        )
        migrated_db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            migrated_db.execute(
                "INSERT INTO feedback_reactions "
                "(channel, external_message_id, reactor_identity_hash, "
                "reaction_emoji, feedback_id, created_at, last_updated_at) "
                "VALUES ('matrix', '$evt:server', 'hash1', '👎', ?, "
                "'2024-01-01T00:01:00Z', '2024-01-01T00:01:00Z')",
                (feedback_id,),
            )

    def test_different_reactors_allowed(self, migrated_db):
        feedback_id = self._insert_feedback(migrated_db)
        migrated_db.execute(
            "INSERT INTO feedback_reactions "
            "(channel, external_message_id, reactor_identity_hash, "
            "reaction_emoji, feedback_id, created_at, last_updated_at) "
            "VALUES ('matrix', '$evt:server', 'hash1', '👍', ?, "
            "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')",
            (feedback_id,),
        )
        migrated_db.execute(
            "INSERT INTO feedback_reactions "
            "(channel, external_message_id, reactor_identity_hash, "
            "reaction_emoji, feedback_id, created_at, last_updated_at) "
            "VALUES ('matrix', '$evt:server', 'hash2', '👍', ?, "
            "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')",
            (feedback_id,),
        )
        migrated_db.commit()
        count = migrated_db.execute(
            "SELECT COUNT(*) as c FROM feedback_reactions"
        ).fetchone()["c"]
        assert count == 2

    def test_cascade_delete(self, migrated_db):
        feedback_id = self._insert_feedback(migrated_db)
        migrated_db.execute(
            "INSERT INTO feedback_reactions "
            "(channel, external_message_id, reactor_identity_hash, "
            "reaction_emoji, feedback_id, created_at, last_updated_at) "
            "VALUES ('matrix', '$evt:server', 'hash1', '👍', ?, "
            "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')",
            (feedback_id,),
        )
        migrated_db.commit()
        migrated_db.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        migrated_db.commit()
        count = migrated_db.execute(
            "SELECT COUNT(*) as c FROM feedback_reactions"
        ).fetchone()["c"]
        assert count == 0

    def test_revoked_at_nullable(self, migrated_db):
        feedback_id = self._insert_feedback(migrated_db)
        migrated_db.execute(
            "INSERT INTO feedback_reactions "
            "(channel, external_message_id, reactor_identity_hash, "
            "reaction_emoji, feedback_id, created_at, last_updated_at) "
            "VALUES ('matrix', '$evt:server', 'hash1', '👍', ?, "
            "'2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')",
            (feedback_id,),
        )
        migrated_db.commit()
        row = migrated_db.execute(
            "SELECT revoked_at FROM feedback_reactions"
        ).fetchone()
        assert row["revoked_at"] is None


class TestIndexes:
    """Test that indexes exist."""

    def test_channel_index_exists(self, migrated_db):
        rows = migrated_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_feedback_channel'"
        ).fetchall()
        assert len(rows) == 1

    def test_method_index_exists(self, migrated_db):
        rows = migrated_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_feedback_method'"
        ).fetchall()
        assert len(rows) == 1
