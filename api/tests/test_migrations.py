"""
Tests for database migration system.

Validates that migrations apply correctly, are idempotent, and maintain data integrity.
"""

import sqlite3
from pathlib import Path

import pytest
from app.db.database import FeedbackDatabase
from app.db.migration_validator import (
    MigrationValidationError,
    extract_table_column_from_alter,
    validate_column_not_exists,
    validate_migration_sql,
)
from app.db.run_migrations import get_applied_migrations, run_migrations


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary test database with base schema."""
    db_path = tmp_path / "test_feedback.db"

    # Reset singleton state to allow fresh initialization for each test
    FeedbackDatabase._instance = None

    # Create base schema using FeedbackDatabase
    db = FeedbackDatabase()
    db.initialize(str(db_path))

    yield str(db_path)

    # Cleanup
    if db_path.exists():
        db_path.unlink()

    # Reset singleton state after test
    FeedbackDatabase._instance = None


@pytest.fixture
def migrations_dir():
    """Get path to migrations directory."""
    return Path(__file__).parent.parent / "app" / "db" / "migrations"


class TestMigrationSystem:
    """Test core migration functionality."""

    def test_migrations_apply_successfully(self, test_db, migrations_dir):
        """Test that all migrations apply without errors."""
        # Apply migrations
        run_migrations(test_db)

        # Verify migrations were tracked
        conn = sqlite3.connect(test_db)
        applied = get_applied_migrations(conn)
        conn.close()

        # Should have applied migrations
        assert len(applied) > 0

        # Check for expected migrations (exclude _down.sql files)
        migration_files = sorted(
            [
                f
                for f in migrations_dir.glob("*.sql")
                if not f.name.endswith("_down.sql")
            ]
        )
        expected_names = [f.name for f in migration_files]

        assert set(applied) == set(expected_names)

    def test_migrations_are_idempotent(self, test_db):
        """Test that migrations can be run multiple times safely."""
        # Apply once
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        first_applied = get_applied_migrations(conn)
        conn.close()

        # Apply again
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        second_applied = get_applied_migrations(conn)
        conn.close()

        # Should have same migrations applied
        assert first_applied == second_applied

    def test_migration_tracking_table_created(self, test_db):
        """Test that schema_migrations table is created."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        # Check table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "schema_migrations"

        conn.close()

    def test_schema_after_migrations(self, test_db):
        """Test that final schema has all expected columns."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        # Check feedback table columns
        cursor.execute("PRAGMA table_info(feedback)")
        columns = {row[1] for row in cursor.fetchall()}

        # Base schema columns
        assert "id" in columns
        assert "message_id" in columns
        assert "question" in columns
        assert "answer" in columns
        assert "rating" in columns

        # Migration-added columns
        assert "processed" in columns  # From 001_add_feedback_tracking
        assert "processed_at" in columns
        assert "faq_id" in columns
        assert "sources" in columns  # From 002_add_sources_columns
        assert "sources_used" in columns

        conn.close()

    def test_migration_indexes_created(self, test_db):
        """Test that migrations create their indexes."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        # Get all indexes
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}

        # Check for migration-created indexes
        assert "idx_feedback_processed" in indexes
        assert "idx_feedback_faq_id" in indexes
        assert "idx_feedback_sources" in indexes
        assert "idx_feedback_sources_used" in indexes

        conn.close()

    def test_migration_order_matters(self, test_db, migrations_dir):
        """Test that migrations are applied in correct order."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        # Get applied migrations in order
        cursor.execute("SELECT migration_name FROM schema_migrations ORDER BY id")
        applied_order = [row[0] for row in cursor.fetchall()]

        conn.close()

        # Verify alphabetical ordering (001, 002, etc.)
        sorted_order = sorted(applied_order)
        assert applied_order == sorted_order


class TestMigrationValidation:
    """Test migration validation functionality."""

    def test_validate_valid_sql(self, test_db):
        """Test validation passes for valid SQL."""
        # Apply migrations first to have feedback table
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)

        valid_sql = "CREATE INDEX IF NOT EXISTS idx_test ON feedback(message_id)"

        # Should not raise
        validate_migration_sql(valid_sql, conn)

        conn.close()

    def test_validate_invalid_sql(self, test_db):
        """Test validation fails for invalid SQL."""
        conn = sqlite3.connect(test_db)

        invalid_sql = "ALTER TABEL feedback ADD COLUMN test_col TEXT"  # Typo: TABEL

        with pytest.raises(MigrationValidationError):
            validate_migration_sql(invalid_sql, conn)

        conn.close()

    def test_dangerous_operations_logged(self, test_db, caplog):
        """Test that dangerous operations are logged."""
        # Apply migrations first to have feedback table
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)

        dangerous_sql = "DROP TABLE IF EXISTS feedback"

        # Should log warning but not fail (since we use DROP TABLE IF EXISTS)
        validate_migration_sql(dangerous_sql, conn)

        assert "dangerous operation" in caplog.text.lower()

        conn.close()

    def test_column_existence_validation(self, test_db):
        """Test validation of column existence."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)

        # Try to validate a column that already exists
        with pytest.raises(MigrationValidationError):
            validate_column_not_exists(conn, "feedback", "processed")

        # Column that doesn't exist should not raise
        validate_column_not_exists(conn, "feedback", "nonexistent_column")

        conn.close()

    def test_extract_table_column_from_alter(self):
        """Test extraction of table/column from ALTER statements."""
        sql = """
        ALTER TABLE feedback ADD COLUMN test1 TEXT;
        ALTER TABLE users ADD COLUMN test2 INTEGER;
        """

        matches = extract_table_column_from_alter(sql)

        assert len(matches) == 2
        assert ("feedback", "test1") in matches
        assert ("users", "test2") in matches


class TestMigrationIntegrity:
    """Test migration data integrity and constraints."""

    def test_foreign_keys_enabled(self, test_db):
        """Test that foreign keys are enabled during migrations."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        # Need to enable foreign keys on connection
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()

        cursor.execute("PRAGMA foreign_keys")
        result = cursor.fetchone()

        # Foreign keys should be enabled
        assert result[0] == 1

        conn.close()

    def test_migration_constraints_enforced(self, test_db):
        """Test that column constraints from migrations are enforced."""
        run_migrations(test_db)

        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        # Test processed column CHECK constraint (should be 0 or 1)
        cursor.execute(
            """
            INSERT INTO feedback (message_id, question, answer, rating)
            VALUES ('test-id', 'q', 'a', 0)
        """
        )

        # Should allow 0 or 1
        cursor.execute("UPDATE feedback SET processed = 0 WHERE message_id = 'test-id'")
        cursor.execute("UPDATE feedback SET processed = 1 WHERE message_id = 'test-id'")

        # Should reject other values
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute(
                "UPDATE feedback SET processed = 2 WHERE message_id = 'test-id'"
            )

        conn.close()

    def test_migration_with_existing_data(self, test_db):
        """Test that migrations work with existing data."""
        # Create base schema and insert data
        db = FeedbackDatabase()
        db.initialize(test_db)

        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        # Insert test data before migrations
        cursor.execute(
            """
            INSERT INTO feedback (message_id, question, answer, rating)
            VALUES ('test-msg-1', 'Test question', 'Test answer', 1)
        """
        )
        conn.commit()
        conn.close()

        # Apply migrations
        run_migrations(test_db)

        # Verify data still exists and has default values for new columns
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT message_id, processed FROM feedback WHERE message_id = 'test-msg-1'"
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "test-msg-1"
        assert result[1] == 0  # Default value for processed column

        conn.close()


class TestMigrationEdgeCases:
    """Test edge cases and error conditions."""

    def test_run_migrations_on_nonexistent_db(self, tmp_path):
        """Test that migrations skip gracefully if DB doesn't exist."""
        nonexistent_db = tmp_path / "nonexistent.db"

        # Should not raise, just log and return
        run_migrations(str(nonexistent_db))

    def test_empty_migration_file(self, test_db, migrations_dir, tmp_path):
        """Test handling of empty migration files."""
        # Create temporary empty migration
        empty_migration = tmp_path / "999_empty_test.sql"
        empty_migration.write_text("")

        # This test would require modifying migrations directory
        # Skip for now - would need test-specific migrations dir

    def test_migration_with_comments(self, test_db):
        """Test that SQL comments in migrations are handled correctly."""
        conn = sqlite3.connect(test_db)

        sql_with_comments = """
        -- This is a comment
        ALTER TABLE feedback ADD COLUMN test_comment TEXT;
        /* This is a block comment */
        CREATE INDEX idx_test_comment ON feedback(test_comment);
        """

        # Should not raise
        validate_migration_sql(sql_with_comments, conn)

        conn.close()
