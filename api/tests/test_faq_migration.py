"""
Integration tests for FAQ migration from JSONL to SQLite.

This test suite follows TDD principles:
1. Write tests first (this file)
2. Tests should fail initially
3. Implement migration functionality
4. Tests pass after implementation
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import portalocker
import pytest
from app.models.faq import FAQItem
from app.services.faq.faq_migration import (
    _get_all_faqs_from_sqlite,
    migrate_jsonl_to_sqlite,
    rollback_sqlite_to_jsonl,
)
from app.services.faq.faq_repository import FAQRepository
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite


class TestJSONLToSQLiteMigration:
    """Test migration from JSONL to SQLite repository."""

    def test_migrate_empty_jsonl_to_sqlite(self, temp_migration_files):
        """Test migration with empty JSONL file."""
        jsonl_path, db_path = temp_migration_files

        # Create empty JSONL file
        jsonl_path.write_text("")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: Both empty
        assert len(jsonl_repo.get_all_faqs()) == 0
        assert len(_get_all_faqs_from_sqlite(sqlite_repo)) == 0

    def test_migrate_single_faq_preserves_all_fields(self, temp_migration_files):
        """Test that migration preserves all FAQ fields."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Add FAQ to JSONL
        now = datetime.now(timezone.utc)
        faq_data = {
            "id": "test-id-123",
            "question": "How to trade BTC?",
            "answer": "Use Bisq Easy for quick trades",
            "category": "Trading",
            "source": "in-app",
            "verified": True,
            "bisq_version": "Bisq 2",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "verified_at": now.isoformat(),
        }
        jsonl_path.write_text(json.dumps(faq_data) + "\n")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: All fields preserved
        sqlite_faqs = _get_all_faqs_from_sqlite(sqlite_repo)
        assert len(sqlite_faqs) == 1

        migrated = sqlite_faqs[0]
        assert migrated.question == faq_data["question"]
        assert migrated.answer == faq_data["answer"]
        assert migrated.category == faq_data["category"]
        assert migrated.source == faq_data["source"]
        assert migrated.verified == faq_data["verified"]
        assert migrated.bisq_version == faq_data["bisq_version"]
        assert migrated.created_at is not None
        assert migrated.updated_at is not None
        assert migrated.verified_at is not None

    def test_migrate_multiple_faqs_preserves_count(self, temp_migration_files):
        """Test that all FAQs are migrated."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Add multiple FAQs to JSONL
        faqs = [
            {
                "id": f"test-id-{i}",
                "question": f"Question {i}?",
                "answer": f"Answer {i}",
                "category": "General",
                "source": "Manual",
            }
            for i in range(50)
        ]

        with open(jsonl_path, "w") as f:
            for faq in faqs:
                f.write(json.dumps(faq) + "\n")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: Count matches
        jsonl_count = len(jsonl_repo.get_all_faqs())
        sqlite_count = len(_get_all_faqs_from_sqlite(sqlite_repo))
        assert sqlite_count == jsonl_count == 50

    def test_migrate_handles_duplicate_questions(self, temp_migration_files):
        """Test that migration handles duplicate questions via UPSERT."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Add duplicate questions to JSONL (should only have 1 in SQLite)
        faqs = [
            {
                "id": "test-id-1",
                "question": "Duplicate question?",
                "answer": "First answer",
                "category": "General",
            },
            {
                "id": "test-id-2",
                "question": "Duplicate question?",
                "answer": "Second answer (updated)",
                "category": "General",
            },
        ]

        with open(jsonl_path, "w") as f:
            for faq in faqs:
                f.write(json.dumps(faq) + "\n")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: Only 1 FAQ (UPSERT merged duplicates)
        sqlite_faqs = _get_all_faqs_from_sqlite(sqlite_repo)
        assert len(sqlite_faqs) == 1
        # Should keep the last version (UPSERT behavior)
        assert sqlite_faqs[0].answer == "Second answer (updated)"

    def test_migrate_preserves_verified_status(self, temp_migration_files):
        """Test that verified/unverified status is preserved."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Mix of verified and unverified FAQs
        faqs = [
            {
                "id": "verified-1",
                "question": "Verified question?",
                "answer": "Answer",
                "verified": True,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "unverified-1",
                "question": "Unverified question?",
                "answer": "Answer",
                "verified": False,
            },
        ]

        with open(jsonl_path, "w") as f:
            for faq in faqs:
                f.write(json.dumps(faq) + "\n")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: Verified status preserved
        sqlite_faqs = _get_all_faqs_from_sqlite(sqlite_repo)
        verified_faqs = [f for f in sqlite_faqs if f.verified]
        unverified_faqs = [f for f in sqlite_faqs if not f.verified]

        assert len(verified_faqs) == 1
        assert len(unverified_faqs) == 1
        assert verified_faqs[0].verified_at is not None
        assert unverified_faqs[0].verified_at is None

    def test_migration_is_idempotent(self, temp_migration_files):
        """Test that running migration twice doesn't duplicate data."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Add FAQs to JSONL
        faqs = [
            {"id": f"test-{i}", "question": f"Q{i}?", "answer": f"A{i}"}
            for i in range(10)
        ]

        with open(jsonl_path, "w") as f:
            for faq in faqs:
                f.write(json.dumps(faq) + "\n")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration TWICE
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)
        migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: Still only 10 FAQs (no duplicates)
        sqlite_faqs = _get_all_faqs_from_sqlite(sqlite_repo)
        assert len(sqlite_faqs) == 10

    def test_migration_statistics_tracking(self, temp_migration_files):
        """Test that migration tracks statistics."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Mix of valid and potentially problematic FAQs
        faqs = [
            {"id": "1", "question": "Q1?", "answer": "A1"},
            {"id": "2", "question": "Q2?", "answer": "A2"},
            {"id": "3", "question": "Q3?", "answer": "A3"},
        ]

        with open(jsonl_path, "w") as f:
            for faq in faqs:
                f.write(json.dumps(faq) + "\n")

        # Create repositories
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))
        sqlite_repo = FAQRepositorySQLite(str(db_path))

        # Perform migration with statistics tracking
        stats = migrate_jsonl_to_sqlite(jsonl_repo, sqlite_repo)

        # Verify: Statistics returned
        assert stats is not None
        assert stats["total"] == 3
        assert stats["migrated"] >= 3
        assert "errors" in stats
        assert "duration_seconds" in stats


class TestSQLiteToJSONLRollback:
    """Test rollback from SQLite to JSONL (for disaster recovery)."""

    def test_rollback_empty_sqlite_to_jsonl(self, temp_migration_files):
        """Test rollback with empty SQLite database."""
        jsonl_path, db_path = temp_migration_files

        # Create empty repositories
        sqlite_repo = FAQRepositorySQLite(str(db_path))
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))

        # Perform rollback
        rollback_sqlite_to_jsonl(sqlite_repo, jsonl_repo)

        # Verify: Both empty
        assert len(_get_all_faqs_from_sqlite(sqlite_repo)) == 0
        assert len(jsonl_repo.get_all_faqs()) == 0

    def test_rollback_preserves_all_fields(self, temp_migration_files):
        """Test that rollback preserves all FAQ fields."""
        jsonl_path, db_path = temp_migration_files

        # Setup: Add FAQ to SQLite
        sqlite_repo = FAQRepositorySQLite(str(db_path))
        faq = FAQItem(
            question="How to trade?",
            answer="Use Bisq Easy",
            category="Trading",
            source="in-app",
            verified=True,
            bisq_version="Bisq 2",
        )
        _ = sqlite_repo.add_faq(faq)

        # Create JSONL repo
        jsonl_repo = FAQRepository(jsonl_path, portalocker.Lock(jsonl_path, "a"))

        # Perform rollback
        rollback_sqlite_to_jsonl(sqlite_repo, jsonl_repo)

        # Verify: All fields preserved in JSONL
        jsonl_faqs = jsonl_repo.get_all_faqs()
        assert len(jsonl_faqs) == 1

        rolled_back = jsonl_faqs[0]
        assert rolled_back.question == faq.question
        assert rolled_back.answer == faq.answer
        assert rolled_back.category == faq.category
        assert rolled_back.verified == faq.verified


# Pytest fixtures
@pytest.fixture
def temp_migration_files():
    """Create temporary JSONL and SQLite files for migration testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        jsonl_path = tmpdir_path / "faqs.jsonl"
        db_path = tmpdir_path / "faqs.db"

        # Create empty JSONL file
        jsonl_path.touch()

        yield jsonl_path, db_path

        # Cleanup is automatic with TemporaryDirectory
