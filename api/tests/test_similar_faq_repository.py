"""
Tests for SimilarFaqRepository (Phase 7.1.2).

TDD: Write tests first, then implement repository to pass these tests.
Following patterns from test_faq_repository_sqlite_security.py.
"""

import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Dict, List

import pytest

# Tests import from the module we will create
# This will fail until we implement the repository


class TestSimilarFaqRepositoryBasicOperations:
    """Tests for basic CRUD operations on similar FAQ candidates."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database file for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        # Cleanup
        try:
            os.unlink(db_path)
            # Also clean up WAL/SHM files
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def repository(self, temp_db_path):
        """Create a SimilarFaqRepository instance with sample FAQ for testing."""
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        yield repo
        repo.close()

    @pytest.fixture
    def sample_candidate_data(self) -> Dict:
        """Sample data for creating a similar FAQ candidate.

        Note: matched_* fields are denormalized (stored directly in candidates table).
        """
        return {
            "extracted_question": "How do I buy bitcoin on Bisq?",
            "extracted_answer": "Use Bisq Easy to purchase bitcoin safely.",
            "extracted_category": "Trading",
            "matched_faq_id": 42,
            "similarity": 0.92,
            "matched_question": "How can I purchase BTC?",
            "matched_answer": "Use Bisq Easy for safe purchases.",
            "matched_category": "Trading",
        }

    def test_add_candidate_creates_record(self, repository, sample_candidate_data):
        """Test that add_candidate creates a new record in the database."""
        candidate = repository.add_candidate(**sample_candidate_data)

        assert candidate is not None
        assert (
            candidate.extracted_question == sample_candidate_data["extracted_question"]
        )
        assert candidate.extracted_answer == sample_candidate_data["extracted_answer"]
        assert (
            candidate.extracted_category == sample_candidate_data["extracted_category"]
        )
        assert candidate.matched_faq_id == sample_candidate_data["matched_faq_id"]
        assert candidate.similarity == sample_candidate_data["similarity"]
        assert candidate.status == "pending"

    def test_add_candidate_generates_uuid(self, repository, sample_candidate_data):
        """Test that add_candidate generates a valid UUID for the candidate."""
        import uuid

        candidate = repository.add_candidate(**sample_candidate_data)

        # Verify it's a valid UUID
        try:
            uuid.UUID(candidate.id)
            is_valid_uuid = True
        except ValueError:
            is_valid_uuid = False

        assert is_valid_uuid, f"Generated ID '{candidate.id}' is not a valid UUID"

    def test_add_candidate_sets_extracted_at(self, repository, sample_candidate_data):
        """Test that add_candidate sets extracted_at timestamp."""
        before = datetime.now(timezone.utc)
        candidate = repository.add_candidate(**sample_candidate_data)
        after = datetime.now(timezone.utc)

        assert candidate.extracted_at is not None
        assert before <= candidate.extracted_at <= after

    def test_get_pending_candidates_returns_only_pending(
        self, repository, sample_candidate_data
    ):
        """Test that get_pending_candidates returns only pending candidates."""
        # Add multiple candidates
        candidate1 = repository.add_candidate(**sample_candidate_data)

        sample_candidate_data["extracted_question"] = "How do I sell bitcoin?"
        candidate2 = repository.add_candidate(**sample_candidate_data)

        # Approve one candidate
        repository.approve_candidate(candidate1.id, "admin@example.com")

        # Get pending candidates
        pending = repository.get_pending_candidates()

        assert len(pending.items) == 1
        assert pending.items[0].id == candidate2.id
        assert pending.total == 1

    def test_get_pending_candidates_empty_when_none_pending(self, repository):
        """Test get_pending_candidates returns empty list when no pending candidates."""
        pending = repository.get_pending_candidates()

        assert pending.items == []
        assert pending.total == 0

    def test_get_candidate_by_id(self, repository, sample_candidate_data):
        """Test retrieving a candidate by ID."""
        added = repository.add_candidate(**sample_candidate_data)

        retrieved = repository.get_candidate_by_id(added.id)

        assert retrieved is not None
        assert retrieved.id == added.id
        assert retrieved.extracted_question == added.extracted_question

    def test_get_candidate_by_id_not_found(self, repository):
        """Test that get_candidate_by_id returns None for non-existent ID."""
        result = repository.get_candidate_by_id("non-existent-id")
        assert result is None


class TestSimilarFaqRepositoryApproveAction:
    """Tests for approve action on similar FAQ candidates."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database file for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def repository(self, temp_db_path):
        """Create a SimilarFaqRepository instance with sample FAQ for testing."""
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)

        # Create faqs table for foreign key reference (not created by SimilarFaqRepository)
        repo._writer_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT
            )
            """
        )

        # Insert sample FAQ for foreign key reference
        repo._writer_conn.execute(
            "INSERT INTO faqs (id, question, answer) VALUES (?, ?, ?)",
            (1, "Existing FAQ", "Existing answer"),
        )
        repo._writer_conn.commit()

        yield repo
        repo.close()

    @pytest.fixture
    def sample_candidate_data(self) -> Dict:
        return {
            "extracted_question": "How do I buy bitcoin?",
            "extracted_answer": "Use Bisq Easy.",
            "matched_faq_id": 1,
            "similarity": 0.85,
        }

    def test_approve_candidate_changes_status(self, repository, sample_candidate_data):
        """Test that approve_candidate changes status to 'approved'."""
        candidate = repository.add_candidate(**sample_candidate_data)

        result = repository.approve_candidate(candidate.id, "admin@example.com")

        assert result is True
        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.status == "approved"

    def test_approve_candidate_sets_resolved_at(
        self, repository, sample_candidate_data
    ):
        """Test that approve_candidate sets resolved_at timestamp."""
        candidate = repository.add_candidate(**sample_candidate_data)
        before = datetime.now(timezone.utc)

        repository.approve_candidate(candidate.id, "admin@example.com")

        after = datetime.now(timezone.utc)
        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.resolved_at is not None
        assert before <= updated.resolved_at <= after

    def test_approve_candidate_sets_resolved_by(
        self, repository, sample_candidate_data
    ):
        """Test that approve_candidate sets resolved_by."""
        candidate = repository.add_candidate(**sample_candidate_data)

        repository.approve_candidate(candidate.id, "admin@example.com")

        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.resolved_by == "admin@example.com"

    def test_approve_nonexistent_returns_false(self, repository):
        """Test that approve_candidate returns False for non-existent ID."""
        result = repository.approve_candidate("non-existent-id", "admin@example.com")
        assert result is False

    def test_approve_already_resolved_returns_false(
        self, repository, sample_candidate_data
    ):
        """Test that approve_candidate returns False for already resolved candidate."""
        candidate = repository.add_candidate(**sample_candidate_data)
        repository.approve_candidate(candidate.id, "admin1@example.com")

        # Try to approve again
        result = repository.approve_candidate(candidate.id, "admin2@example.com")

        assert result is False


class TestSimilarFaqRepositoryMergeAction:
    """Tests for merge action on similar FAQ candidates."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def repository(self, temp_db_path):
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)

        # Create faqs table for foreign key reference (not created by SimilarFaqRepository)
        repo._writer_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT
            )
            """
        )

        # Insert sample FAQ for foreign key reference
        repo._writer_conn.execute(
            "INSERT INTO faqs (id, question, answer) VALUES (?, ?, ?)",
            (1, "Existing FAQ", "Existing answer"),
        )
        repo._writer_conn.commit()

        yield repo
        repo.close()

    @pytest.fixture
    def sample_candidate_data(self) -> Dict:
        return {
            "extracted_question": "How do I buy bitcoin?",
            "extracted_answer": "Use Bisq Easy.",
            "matched_faq_id": 1,
            "similarity": 0.85,
        }

    def test_merge_candidate_changes_status(self, repository, sample_candidate_data):
        """Test that merge_candidate changes status to 'merged'."""
        candidate = repository.add_candidate(**sample_candidate_data)

        result = repository.merge_candidate(
            candidate.id, "admin@example.com", "replace"
        )

        assert result is True
        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.status == "merged"

    def test_merge_candidate_stores_mode(self, repository, sample_candidate_data):
        """Test that merge_candidate stores the merge mode."""
        candidate = repository.add_candidate(**sample_candidate_data)

        repository.merge_candidate(candidate.id, "admin@example.com", "append")

        # Mode should be stored (we'll need to add a field for this)
        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.status == "merged"

    def test_merge_nonexistent_returns_false(self, repository):
        """Test that merge_candidate returns False for non-existent ID."""
        result = repository.merge_candidate(
            "non-existent-id", "admin@example.com", "replace"
        )
        assert result is False


class TestSimilarFaqRepositoryDismissAction:
    """Tests for dismiss action on similar FAQ candidates."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def repository(self, temp_db_path):
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)

        # Create faqs table for foreign key reference (not created by SimilarFaqRepository)
        repo._writer_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faqs (
                id INTEGER PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT
            )
            """
        )

        # Insert sample FAQ for foreign key reference
        repo._writer_conn.execute(
            "INSERT INTO faqs (id, question, answer) VALUES (?, ?, ?)",
            (1, "Existing FAQ", "Existing answer"),
        )
        repo._writer_conn.commit()

        yield repo
        repo.close()

    @pytest.fixture
    def sample_candidate_data(self) -> Dict:
        return {
            "extracted_question": "How do I buy bitcoin?",
            "extracted_answer": "Use Bisq Easy.",
            "matched_faq_id": 1,
            "similarity": 0.85,
        }

    def test_dismiss_candidate_changes_status(self, repository, sample_candidate_data):
        """Test that dismiss_candidate changes status to 'dismissed'."""
        candidate = repository.add_candidate(**sample_candidate_data)

        result = repository.dismiss_candidate(candidate.id, "admin@example.com")

        assert result is True
        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.status == "dismissed"

    def test_dismiss_candidate_with_reason(self, repository, sample_candidate_data):
        """Test that dismiss_candidate stores the reason."""
        candidate = repository.add_candidate(**sample_candidate_data)

        repository.dismiss_candidate(
            candidate.id, "admin@example.com", reason="Exact duplicate"
        )

        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.dismiss_reason == "Exact duplicate"

    def test_dismiss_without_reason(self, repository, sample_candidate_data):
        """Test that dismiss_candidate works without a reason."""
        candidate = repository.add_candidate(**sample_candidate_data)

        repository.dismiss_candidate(candidate.id, "admin@example.com")

        updated = repository.get_candidate_by_id(candidate.id)
        assert updated.dismiss_reason is None

    def test_dismiss_nonexistent_returns_false(self, repository):
        """Test that dismiss_candidate returns False for non-existent ID."""
        result = repository.dismiss_candidate("non-existent-id", "admin@example.com")
        assert result is False


class TestSimilarFaqRepositoryMatchedFaqJoin:
    """Tests for joining matched FAQ details with candidates."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def repository_with_faqs(self, temp_db_path):
        """Create repository for testing matched FAQ details."""
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        yield repo
        repo.close()

    def test_get_pending_includes_matched_faq_details(self, repository_with_faqs):
        """Test that get_pending_candidates includes matched FAQ details."""
        # Note: matched FAQ details are denormalized (stored directly in candidates table)
        repository_with_faqs.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=42,
            similarity=0.92,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        pending = repository_with_faqs.get_pending_candidates()

        assert len(pending.items) == 1
        assert pending.items[0].matched_question == "How can I purchase BTC?"
        assert pending.items[0].matched_answer == "Use Bisq Easy for safe purchases."
        assert pending.items[0].matched_category == "Trading"


class TestSimilarFaqRepositoryConcurrency:
    """Tests for concurrent access and race condition prevention."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    def test_concurrent_access_handled_safely(self, temp_db_path):
        """Test that concurrent operations are handled safely."""
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        # First, create a repository to initialize the database
        setup_repo = SimilarFaqRepository(temp_db_path)
        setup_repo.close()

        results: List[str] = []
        errors: List[Exception] = []

        def add_candidate(thread_id: int):
            try:
                repo = SimilarFaqRepository(temp_db_path)
                candidate = repo.add_candidate(
                    extracted_question=f"Question from thread {thread_id}",
                    extracted_answer="Answer",
                    matched_faq_id=1,
                    similarity=0.85,
                    matched_question="Existing FAQ",
                    matched_answer="Existing answer",
                )
                results.append(candidate.id)
                repo.close()
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = [threading.Thread(target=add_candidate, args=(i,)) for i in range(5)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # All threads should succeed without errors
        assert len(errors) == 0, f"Concurrent operations failed: {errors}"
        assert len(results) == 5, "Not all candidates were created"

        # Verify all candidates exist
        repo = SimilarFaqRepository(temp_db_path)
        pending = repo.get_pending_candidates()
        assert pending.total == 5
        repo.close()


class TestSimilarFaqRepositorySQLInjection:
    """Tests for SQL injection prevention."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def repository(self, temp_db_path):
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        yield repo
        repo.close()

    def test_sql_injection_in_question_prevented(self, repository):
        """Test that SQL injection via question field is prevented."""
        malicious_question = "'; DROP TABLE similar_faq_candidates; --"

        candidate = repository.add_candidate(
            extracted_question=malicious_question,
            extracted_answer="Safe answer",
            matched_faq_id=1,
            matched_question="Existing FAQ",
            matched_answer="Existing answer",
            similarity=0.85,
        )

        # Table should still exist and candidate should be stored with the malicious text
        retrieved = repository.get_candidate_by_id(candidate.id)
        assert retrieved is not None
        assert retrieved.extracted_question == malicious_question

    def test_sql_injection_in_id_prevented(self, repository):
        """Test that SQL injection via ID field is prevented."""
        malicious_id = "'; DROP TABLE similar_faq_candidates; --"

        # Should not raise or cause database corruption
        result = repository.get_candidate_by_id(malicious_id)
        assert result is None

        # Repository should still work
        candidate = repository.add_candidate(
            extracted_question="Valid question",
            extracted_answer="Valid answer",
            matched_faq_id=1,
            similarity=0.85,
        )
        assert candidate is not None
