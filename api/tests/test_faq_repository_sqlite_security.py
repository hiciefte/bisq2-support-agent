"""
Security-focused tests for SQLite FAQ repository implementation.

Tests CRITICAL and HIGH security vulnerabilities identified in migration analysis:
- SQL injection prevention (CRITICAL)
- Race condition prevention in add_faq (CRITICAL)
- File permission handling (HIGH)
- Input validation in migration (HIGH)

Following TDD approach: These tests are written BEFORE implementation.
All tests should FAIL initially, then pass after implementing security fixes.
"""

import concurrent.futures
import json
import os
import tempfile
from pathlib import Path
from typing import List

import pytest
from app.models.faq import FAQItem


class TestSQLInjectionPrevention:
    """Test suite for SQL injection vulnerability (CRITICAL)."""

    def test_get_faqs_category_sql_injection_blocked(self, sqlite_faq_repo):
        """Test that malicious category input doesn't execute SQL."""
        # Attempt SQL injection via category parameter
        malicious_category = "General'; DROP TABLE faqs; --"

        result = sqlite_faq_repo.get_faqs_paginated(
            page=1, page_size=10, category=malicious_category
        )

        # Should return empty results, not execute DROP TABLE
        assert result["total"] == 0
        assert len(result["items"]) == 0

        # Verify table still exists and wasn't dropped
        cursor = sqlite_faq_repo._reader_conn.execute("SELECT COUNT(*) FROM faqs")
        count = cursor.fetchone()[0]
        assert count >= 0  # Table exists and can be queried

    def test_get_faqs_search_text_sql_injection_blocked(self, sqlite_faq_repo):
        """Test that malicious search text doesn't execute SQL."""
        # Add a legitimate FAQ first
        faq = FAQItem(
            question="How to trade BTC?",
            answer="Use Bisq Easy",
            category="Trading",
            source="Manual",
        )
        sqlite_faq_repo.add_faq(faq)

        # Attempt SQL injection via search_text parameter
        malicious_search = "BTC' OR '1'='1'; DELETE FROM faqs; --"

        result = sqlite_faq_repo.get_faqs_paginated(
            page=1, page_size=10, search_text=malicious_search
        )

        # Malicious query should not match anything (exact search)
        assert result["total"] == 0

        # Verify FAQ wasn't deleted
        all_faqs = sqlite_faq_repo.get_faqs_paginated(page=1, page_size=10)
        assert all_faqs["total"] >= 1

    def test_get_faqs_source_sql_injection_blocked(self, sqlite_faq_repo):
        """Test that malicious source filter doesn't execute SQL."""
        malicious_source = "Manual'; UPDATE faqs SET verified=1; --"

        result = sqlite_faq_repo.get_faqs_paginated(
            page=1, page_size=10, source=malicious_source
        )

        assert result["total"] == 0

        # Verify no FAQs were incorrectly verified
        cursor = sqlite_faq_repo._reader_conn.execute(
            "SELECT COUNT(*) FROM faqs WHERE verified = 1"
        )
        verified_count = cursor.fetchone()[0]
        assert verified_count == 0  # No FAQs should be verified yet

    def test_update_faq_sql_injection_in_values(self, sqlite_faq_repo):
        """Test that malicious values in update don't execute SQL."""
        # Add legitimate FAQ
        faq = FAQItem(
            question="Original question",
            answer="Original answer",
            category="General",
        )
        added = sqlite_faq_repo.add_faq(faq)

        # Attempt SQL injection in answer field
        malicious_answer = "New answer'; DROP TABLE faqs; --"

        updated_faq = FAQItem(
            question="Original question",
            answer=malicious_answer,
            category="General",
        )

        sqlite_faq_repo.update_faq(added.id, updated_faq)

        # Verify table still exists
        cursor = sqlite_faq_repo._reader_conn.execute(
            "SELECT answer FROM faqs WHERE id = ?", (added.id,)
        )
        result = cursor.fetchone()

        # Answer should be stored as literal string, not executed
        assert result[0] == malicious_answer


class TestRaceConditionPrevention:
    """Test suite for race condition vulnerability in add_faq (CRITICAL)."""

    def test_concurrent_add_identical_faqs_no_duplicates(self, sqlite_faq_repo):
        """Test that concurrent adds of identical FAQs don't create duplicates."""
        faq_data = FAQItem(
            question="How to trade BTC?",
            answer="Use Bisq Easy for quick trades",
            category="Trading",
            source="in-app",
        )

        # Simulate 10 concurrent requests to add same FAQ
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(sqlite_faq_repo.add_faq, faq_data) for _ in range(10)
            ]
            results = [f.result() for f in futures]

        # All threads should return same FAQ ID (UPSERT deduplication)
        unique_ids = set(r.id for r in results)
        assert len(unique_ids) == 1, f"Expected 1 unique ID, got {len(unique_ids)}"

        # Verify only 1 FAQ exists in database
        cursor = sqlite_faq_repo._reader_conn.execute(
            "SELECT COUNT(*) FROM faqs WHERE question = ?", (faq_data.question,)
        )
        count = cursor.fetchone()[0]
        assert count == 1, f"Expected 1 FAQ, found {count}"

    def test_concurrent_add_different_faqs_all_inserted(self, sqlite_faq_repo):
        """Test that concurrent adds of different FAQs all succeed."""
        faqs = [
            FAQItem(
                question=f"Question {i}?",
                answer=f"Answer {i}",
                category="General",
            )
            for i in range(20)
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(sqlite_faq_repo.add_faq, faq) for faq in faqs]
            results = [f.result() for f in futures]

        # All FAQs should be inserted with unique IDs
        assert len(results) == 20
        unique_ids = set(r.id for r in results)
        assert len(unique_ids) == 20

        # Verify all FAQs exist in database
        cursor = sqlite_faq_repo._reader_conn.execute("SELECT COUNT(*) FROM faqs")
        count = cursor.fetchone()[0]
        assert count == 20

    def test_concurrent_update_same_faq_no_data_loss(self, sqlite_faq_repo):
        """Test that concurrent updates don't lose data."""
        # Add initial FAQ
        faq = FAQItem(
            question="Original question",
            answer="Original answer",
            category="General",
        )
        added = sqlite_faq_repo.add_faq(faq)

        # Prepare 10 different updates
        updates = [
            FAQItem(
                question="Original question",
                answer=f"Updated answer {i}",
                category="General",
            )
            for i in range(10)
        ]

        # Execute concurrent updates
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(sqlite_faq_repo.update_faq, added.id, update)
                for update in updates
            ]
            [f.result() for f in futures]

        # Verify FAQ still exists (not corrupted)
        cursor = sqlite_faq_repo._reader_conn.execute(
            "SELECT answer FROM faqs WHERE id = ?", (added.id,)
        )
        result = cursor.fetchone()
        assert result is not None
        # Answer should be one of the updates (last-write-wins)
        assert result[0].startswith("Updated answer")

    def test_concurrent_read_write_no_deadlock(self, sqlite_faq_repo):
        """Test that concurrent reads and writes don't deadlock."""
        # Add initial FAQs
        for i in range(5):
            faq = FAQItem(
                question=f"Question {i}",
                answer=f"Answer {i}",
                category="General",
            )
            sqlite_faq_repo.add_faq(faq)

        def read_operation():
            return sqlite_faq_repo.get_faqs_paginated(page=1, page_size=10)

        def write_operation(i):
            faq = FAQItem(
                question=f"New question {i}",
                answer=f"New answer {i}",
                category="General",
            )
            return sqlite_faq_repo.add_faq(faq)

        # Mix reads and writes concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            read_futures = [executor.submit(read_operation) for _ in range(50)]
            write_futures = [executor.submit(write_operation, i) for i in range(10)]

            # All operations should complete without deadlock (timeout would fail test)
            read_results = [f.result(timeout=5) for f in read_futures]
            write_results = [f.result(timeout=5) for f in write_futures]

        assert len(read_results) == 50
        assert len(write_results) == 10


class TestFilePermissionHandling:
    """Test suite for file permission vulnerability (HIGH)."""

    def test_database_file_created_with_correct_permissions(self):
        """Test that new database file has secure permissions (600)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_faqs.db"

            # Import here to avoid circular dependency
            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            _ = FAQRepositorySQLite(str(db_path))

            # Check file permissions
            stat_info = os.stat(db_path)
            mode = stat_info.st_mode & 0o777

            # Should be 600 (rw-------)
            assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_database_file_not_world_readable(self):
        """Test that database file is not world-readable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_faqs.db"

            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            repo = FAQRepositorySQLite(str(db_path))

            # Add sensitive FAQ data
            faq = FAQItem(
                question="Sensitive question",
                answer="Sensitive answer containing user data",
                category="Privacy",
            )
            repo.add_faq(faq)

            stat_info = os.stat(db_path)
            mode = stat_info.st_mode

            # Verify no world read/write/execute permissions
            assert (mode & 0o007) == 0, "Database should not be world-accessible"

    def test_migration_preserves_data_directory_permissions(self):
        """Test that migration doesn't change data directory permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir(mode=0o755)

            original_mode = os.stat(data_dir).st_mode & 0o777

            # Run migration
            db_path = data_dir / "faqs.db"
            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            _ = FAQRepositorySQLite(str(db_path))

            # Verify directory permissions unchanged
            new_mode = os.stat(data_dir).st_mode & 0o777
            assert new_mode == original_mode


class TestInputValidationInMigration:
    """Test suite for input validation vulnerability (HIGH)."""

    def test_migration_rejects_malformed_jsonl_entry(self):
        """Test that migration handles malformed JSONL entries gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "faqs.jsonl"
            db_path = Path(tmpdir) / "faqs.db"

            # Create JSONL with malformed entry
            with open(jsonl_path, "w") as f:
                # Valid entry
                f.write(json.dumps({"question": "Q1", "answer": "A1"}) + "\n")
                # Malformed JSON
                f.write("{'invalid': json syntax}\n")
                # Another valid entry
                f.write(json.dumps({"question": "Q2", "answer": "A2"}) + "\n")

            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            repo = FAQRepositorySQLite(str(db_path))

            # Migration should skip malformed entry and continue
            repo.migrate_from_jsonl(str(jsonl_path))

            # Verify only valid entries were migrated
            cursor = repo._reader_conn.execute("SELECT COUNT(*) FROM faqs")
            count = cursor.fetchone()[0]
            assert count == 2

    def test_migration_validates_required_fields(self):
        """Test that migration validates required fields exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "faqs.jsonl"
            db_path = Path(tmpdir) / "faqs.db"

            # Create JSONL with missing required fields
            with open(jsonl_path, "w") as f:
                # Missing 'answer' field
                f.write(json.dumps({"question": "Q1", "category": "General"}) + "\n")
                # Missing 'question' field
                f.write(json.dumps({"answer": "A2", "category": "General"}) + "\n")
                # Valid entry
                f.write(json.dumps({"question": "Q3", "answer": "A3"}) + "\n")

            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            repo = FAQRepositorySQLite(str(db_path))
            repo.migrate_from_jsonl(str(jsonl_path))

            # Only valid entry should be migrated
            cursor = repo._reader_conn.execute("SELECT COUNT(*) FROM faqs")
            count = cursor.fetchone()[0]
            assert count == 1

    def test_migration_sanitizes_datetime_values(self):
        """Test that migration handles invalid datetime values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "faqs.jsonl"
            db_path = Path(tmpdir) / "faqs.db"

            # Create JSONL with invalid datetime
            with open(jsonl_path, "w") as f:
                f.write(
                    json.dumps(
                        {
                            "question": "Q1",
                            "answer": "A1",
                            "created_at": "not-a-datetime",
                            "updated_at": "2024-13-45T99:99:99Z",  # Invalid date
                        }
                    )
                    + "\n"
                )

            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            repo = FAQRepositorySQLite(str(db_path))
            repo.migrate_from_jsonl(str(jsonl_path))

            # Should migrate with None timestamps (not crash)
            cursor = repo._reader_conn.execute(
                "SELECT created_at, updated_at FROM faqs"
            )
            result = cursor.fetchone()

            # Invalid datetimes should be replaced with current timestamp or None
            assert result is not None

    def test_add_faq_validates_field_lengths(self):
        """Test that add_faq validates field length constraints."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "faqs.db"

            from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

            repo = FAQRepositorySQLite(str(db_path))

            # Attempt to add FAQ with excessively long question
            long_question = "Q" * 10000  # 10KB question

            faq = FAQItem(
                question=long_question,
                answer="Answer",
                category="General",
            )

            # Should either truncate or raise validation error
            with pytest.raises(ValueError):
                repo.add_faq(faq)


# Pytest fixtures for SQLite repository testing


@pytest.fixture
def sqlite_faq_repo():
    """Create a temporary SQLite FAQ repository for testing."""
    # Create a unique temporary directory for EACH test
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "test_faqs.db"

    # Import here to avoid issues before implementation
    try:
        from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite

        repo = FAQRepositorySQLite(str(db_path))
        yield repo

        # Cleanup
        try:
            repo.close()  # Uses the close() method which closes both connections
        except Exception as e:
            # Log exceptions during teardown to detect resource leaks or race conditions
            # but don't fail the test since cleanup is best-effort
            print(f"Warning: Exception during repository cleanup: {e}")

        # Remove temporary directory
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    except ImportError:
        pytest.skip("FAQRepositorySQLite not yet implemented")


@pytest.fixture
def sample_faqs() -> List[FAQItem]:
    """Generate sample FAQ data for testing."""
    return [
        FAQItem(
            question="How to install Bisq?",
            answer="Download from bisq.network",
            category="Installation",
            source="Manual",
            verified=True,
            protocol="bisq_easy",
        ),
        FAQItem(
            question="How to trade BTC?",
            answer="Use Bisq Easy for beginners",
            category="Trading",
            source="in-app",
            verified=False,
            protocol="bisq_easy",
        ),
        FAQItem(
            question="What is reputation?",
            answer="Reputation builds trust in the network",
            category="General",
            source="Manual",
            verified=True,
            protocol="all",
        ),
    ]
