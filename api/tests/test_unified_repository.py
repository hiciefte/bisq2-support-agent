"""
TDD Tests for UnifiedFAQCandidateRepository.

These tests follow the RED-GREEN-REFACTOR cycle from the plan:
/Users/takahiro/.claude/plans/cheerful-discovering-blanket.md

Phase 1: Unified Repository Tests
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

# Import will fail until implementation exists - that's the RED phase
try:
    from app.services.training.unified_repository import (
        CalibrationStatus,
        UnifiedFAQCandidate,
        UnifiedFAQCandidateRepository,
    )

    IMPLEMENTATION_EXISTS = True
except ImportError:
    IMPLEMENTATION_EXISTS = False
    UnifiedFAQCandidateRepository = None
    UnifiedFAQCandidate = None
    CalibrationStatus = None


# Skip all tests if implementation doesn't exist yet (RED phase)
pytestmark = pytest.mark.skipif(
    not IMPLEMENTATION_EXISTS,
    reason="UnifiedFAQCandidateRepository not yet implemented (RED phase)",
)


# =============================================================================
# TASK 1.1: Repository Schema & Init
# =============================================================================


class TestRepositoryInit:
    """Test repository initialization and table creation."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    def test_creates_tables_on_init(self, temp_db_path):
        """Cycle 1.1.1: Test unified_faq_candidates and calibration_state tables are created."""
        # Arrange & Act - repo creation triggers table creation
        _repo = UnifiedFAQCandidateRepository(str(temp_db_path))  # noqa: F841

        # Assert - Check tables exist
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()

        # Check unified_faq_candidates table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='unified_faq_candidates'"
        )
        assert (
            cursor.fetchone() is not None
        ), "unified_faq_candidates table should exist"

        # Check calibration_state table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='calibration_state'"
        )
        assert cursor.fetchone() is not None, "calibration_state table should exist"

        conn.close()

    def test_source_must_be_bisq2_or_matrix(self, temp_db_path):
        """Cycle 1.1.2: Test source column has CHECK constraint for valid values."""
        _repo = UnifiedFAQCandidateRepository(str(temp_db_path))  # noqa: F841

        # Try to insert with invalid source - should fail
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()

        try:
            with pytest.raises(sqlite3.IntegrityError):
                cursor.execute("""
                    INSERT INTO unified_faq_candidates
                    (source, source_event_id, source_timestamp, question_text, staff_answer, routing, created_at)
                    VALUES ('invalid_source', 'test_id', '2025-01-01', 'question', 'answer', 'FULL_REVIEW', '2025-01-01')
                    """)
                conn.commit()
        finally:
            conn.close()

    def test_creates_indexes(self, temp_db_path):
        """Test that required indexes are created for performance."""
        _repo = UnifiedFAQCandidateRepository(str(temp_db_path))  # noqa: F841

        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()

        # Check indexes exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row[0] for row in cursor.fetchall()}

        assert "idx_ufc_source" in indexes, "Source index should exist"
        assert "idx_ufc_routing" in indexes, "Routing index should exist"
        assert "idx_ufc_review_status" in indexes, "Review status index should exist"
        assert (
            "idx_ufc_source_routing" in indexes
        ), "Source+routing composite index should exist"

        conn.close()


# =============================================================================
# TASK 1.2: CRUD Operations
# =============================================================================


class TestCRUDOperations:
    """Test create, read, update, delete operations."""

    @pytest.fixture
    def repo(self):
        """Create a repository with temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_unified.db"
            yield UnifiedFAQCandidateRepository(str(db_path))

    @pytest.fixture
    def sample_candidate_data(self):
        """Sample data for creating a candidate."""
        return {
            "source": "bisq2",
            "source_event_id": "msg_123",
            "source_timestamp": "2025-01-15T10:00:00Z",
            "question_text": "How do I start trading on Bisq Easy?",
            "staff_answer": "Go to Trade > Trade Wizard. New users can trade up to $600.",
            "generated_answer": "Navigate to Trade tab and select Trade Wizard. Limit is $600.",
            "staff_sender": "support-staff",
            "embedding_similarity": 0.92,
            "factual_alignment": 0.95,
            "contradiction_score": 0.03,
            "completeness": 0.90,
            "hallucination_risk": 0.05,
            "final_score": 0.92,
            "llm_reasoning": "High alignment, both mention Trade Wizard and $600 limit.",
            "routing": "AUTO_APPROVE",
            "is_calibration_sample": False,
        }

    def test_create_candidate_from_bisq2(self, repo, sample_candidate_data):
        """Cycle 1.2.1: Test creating a candidate from Bisq 2 source."""
        # Act
        candidate = repo.create(**sample_candidate_data)

        # Assert
        assert candidate is not None
        assert candidate.id > 0
        assert candidate.source == "bisq2"
        assert candidate.source_event_id == "msg_123"
        assert candidate.question_text == sample_candidate_data["question_text"]
        assert candidate.routing == "AUTO_APPROVE"
        assert candidate.review_status == "pending"

    def test_create_candidate_from_matrix(self, repo, sample_candidate_data):
        """Cycle 1.2.2: Test creating a candidate from Matrix source."""
        # Arrange
        sample_candidate_data["source"] = "matrix"
        sample_candidate_data["source_event_id"] = "$matrix_event_456:matrix.org"

        # Act
        candidate = repo.create(**sample_candidate_data)

        # Assert
        assert candidate is not None
        assert candidate.id > 0
        assert candidate.source == "matrix"
        assert candidate.source_event_id == "$matrix_event_456:matrix.org"

    def test_get_by_id_returns_candidate(self, repo, sample_candidate_data):
        """Cycle 1.2.3: Test retrieving a candidate by ID."""
        # Arrange
        created = repo.create(**sample_candidate_data)

        # Act
        retrieved = repo.get_by_id(created.id)

        # Assert
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.source == created.source
        assert retrieved.question_text == created.question_text

    def test_get_by_id_returns_none_for_missing(self, repo):
        """Cycle 1.2.3: Test get_by_id returns None for non-existent ID."""
        # Act
        result = repo.get_by_id(99999)

        # Assert
        assert result is None

    def test_exists_by_event_id_true(self, repo, sample_candidate_data):
        """Cycle 1.2.4: Test exists_by_event_id returns True for existing event."""
        # Arrange
        repo.create(**sample_candidate_data)

        # Act
        exists = repo.exists_by_event_id("msg_123")

        # Assert
        assert exists is True

    def test_exists_by_event_id_false(self, repo):
        """Cycle 1.2.4: Test exists_by_event_id returns False for non-existent event."""
        # Act
        exists = repo.exists_by_event_id("nonexistent_event_id")

        # Assert
        assert exists is False


# =============================================================================
# TASK 1.3: Source Filtering
# =============================================================================


class TestSourceFiltering:
    """Test filtering candidates by source."""

    @pytest.fixture
    def repo_with_mixed_candidates(self):
        """Create repository with candidates from both sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_unified.db"
            repo = UnifiedFAQCandidateRepository(str(db_path))

            # Create 2 bisq2 candidates
            for i in range(2):
                repo.create(
                    source="bisq2",
                    source_event_id=f"bisq_msg_{i}",
                    source_timestamp="2025-01-15T10:00:00Z",
                    question_text=f"Bisq question {i}",
                    staff_answer=f"Bisq answer {i}",
                    routing="FULL_REVIEW",
                )

            # Create 2 matrix candidates
            for i in range(2):
                repo.create(
                    source="matrix",
                    source_event_id=f"$matrix_event_{i}:matrix.org",
                    source_timestamp="2025-01-15T10:00:00Z",
                    question_text=f"Matrix question {i}",
                    staff_answer=f"Matrix answer {i}",
                    routing="SPOT_CHECK",
                )

            yield repo

    def test_get_pending_returns_all_when_no_filter(self, repo_with_mixed_candidates):
        """Cycle 1.3.1: Test get_pending returns all candidates when no source filter."""
        # Act
        results = repo_with_mixed_candidates.get_pending(source=None)

        # Assert
        assert len(results) == 4

    def test_get_pending_filters_by_bisq2(self, repo_with_mixed_candidates):
        """Cycle 1.3.2: Test get_pending filters by bisq2 source."""
        # Act
        results = repo_with_mixed_candidates.get_pending(source="bisq2")

        # Assert
        assert len(results) == 2
        assert all(c.source == "bisq2" for c in results)

    def test_get_pending_filters_by_matrix(self, repo_with_mixed_candidates):
        """Cycle 1.3.3: Test get_pending filters by matrix source."""
        # Act
        results = repo_with_mixed_candidates.get_pending(source="matrix")

        # Assert
        assert len(results) == 2
        assert all(c.source == "matrix" for c in results)

    def test_get_queue_counts_all_sources(self, repo_with_mixed_candidates):
        """Cycle 1.3.4: Test get_queue_counts returns counts for all sources."""
        # Act
        counts = repo_with_mixed_candidates.get_queue_counts(source=None)

        # Assert
        assert isinstance(counts, dict)
        # 2 bisq2 with FULL_REVIEW, 2 matrix with SPOT_CHECK
        assert counts.get("FULL_REVIEW", 0) == 2
        assert counts.get("SPOT_CHECK", 0) == 2
        assert counts.get("AUTO_APPROVE", 0) == 0

    def test_get_queue_counts_by_source(self, repo_with_mixed_candidates):
        """Cycle 1.3.4: Test get_queue_counts filters by source."""
        # Act
        bisq_counts = repo_with_mixed_candidates.get_queue_counts(source="bisq2")
        matrix_counts = repo_with_mixed_candidates.get_queue_counts(source="matrix")

        # Assert
        assert bisq_counts.get("FULL_REVIEW", 0) == 2
        assert bisq_counts.get("SPOT_CHECK", 0) == 0
        assert matrix_counts.get("FULL_REVIEW", 0) == 0
        assert matrix_counts.get("SPOT_CHECK", 0) == 2


# =============================================================================
# TASK 1.4: Review Actions
# =============================================================================


class TestReviewActions:
    """Test approve, reject, and skip operations."""

    @pytest.fixture
    def repo_with_candidate(self):
        """Create repository with a single pending candidate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_unified.db"
            repo = UnifiedFAQCandidateRepository(str(db_path))

            candidate = repo.create(
                source="bisq2",
                source_event_id="msg_to_review",
                source_timestamp="2025-01-15T10:00:00Z",
                question_text="How do I trade?",
                staff_answer="Go to Trade Wizard.",
                routing="FULL_REVIEW",
            )

            yield repo, candidate

    def test_approve_updates_status_and_faq_id(self, repo_with_candidate):
        """Cycle 1.4.1: Test approve updates status, faq_id, reviewer, and timestamp."""
        repo, candidate = repo_with_candidate

        # Act
        repo.approve(candidate.id, reviewer="admin", faq_id="faq_123")

        # Assert
        updated = repo.get_by_id(candidate.id)
        assert updated.review_status == "approved"
        assert updated.faq_id == "faq_123"
        assert updated.reviewed_by == "admin"
        assert updated.reviewed_at is not None

    def test_reject_stores_reason(self, repo_with_candidate):
        """Cycle 1.4.2: Test reject stores reason and updates status."""
        repo, candidate = repo_with_candidate

        # Act
        repo.reject(candidate.id, reviewer="admin", reason="Incorrect information")

        # Assert
        updated = repo.get_by_id(candidate.id)
        assert updated.review_status == "rejected"
        assert updated.rejection_reason == "Incorrect information"
        assert updated.reviewed_by == "admin"
        assert updated.reviewed_at is not None

    def test_skip_moves_to_end_of_queue(self, repo_with_candidate):
        """Cycle 1.4.3: Test skip moves candidate to end of queue."""
        repo, first_candidate = repo_with_candidate

        # Add more candidates
        second = repo.create(
            source="bisq2",
            source_event_id="msg_second",
            source_timestamp="2025-01-15T10:01:00Z",
            question_text="Second question",
            staff_answer="Second answer",
            routing="FULL_REVIEW",
        )
        _third = repo.create(  # noqa: F841
            source="bisq2",
            source_event_id="msg_third",
            source_timestamp="2025-01-15T10:02:00Z",
            question_text="Third question",
            staff_answer="Third answer",
            routing="FULL_REVIEW",
        )

        # Act - Skip the first candidate
        repo.skip(first_candidate.id)

        # Assert - Get current item should return second candidate (first is now at end)
        current = repo.get_current_item("FULL_REVIEW", source="bisq2")
        assert current is not None
        assert current.id == second.id


# =============================================================================
# TASK 1.5: Calibration Logic
# =============================================================================


class TestCalibrationLogic:
    """Test calibration mode and threshold management."""

    @pytest.fixture
    def repo(self):
        """Create a fresh repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_unified.db"
            yield UnifiedFAQCandidateRepository(str(db_path))

    def test_is_calibration_mode_initially_true(self, repo):
        """Cycle 1.5.1: Test calibration mode is active on fresh repository."""
        # Act
        is_calibration = repo.is_calibration_mode()

        # Assert
        assert is_calibration is True

    def test_increment_calibration_count(self, repo):
        """Cycle 1.5.2: Test incrementing calibration sample count."""
        # Act
        repo.increment_calibration_count()

        # Assert
        status = repo.get_calibration_status()
        assert status.samples_collected == 1

    def test_calibration_completes_at_100(self, repo):
        """Cycle 1.5.3: Test calibration completes after 100 samples."""
        # Arrange - Set count to 99
        conn = sqlite3.connect(repo.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE calibration_state SET samples_collected = 99 WHERE id = 1"
        )
        conn.commit()
        conn.close()

        # Act - Increment to 100
        repo.increment_calibration_count()

        # Assert
        assert repo.is_calibration_mode() is False
        status = repo.get_calibration_status()
        assert status.is_complete is True
        assert status.samples_collected == 100

    def test_get_calibration_status_returns_dto(self, repo):
        """Cycle 1.5.4: Test get_calibration_status returns proper DTO."""
        # Act
        status = repo.get_calibration_status()

        # Assert
        assert isinstance(status, CalibrationStatus)
        assert hasattr(status, "samples_collected")
        assert hasattr(status, "samples_required")
        assert hasattr(status, "is_complete")
        assert hasattr(status, "auto_approve_threshold")
        assert hasattr(status, "spot_check_threshold")

        # Check defaults
        assert status.samples_required == 100
        assert status.auto_approve_threshold == 0.90
        assert status.spot_check_threshold == 0.75


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


# =============================================================================
# TASK: Original Staff Answer Support
# =============================================================================


class TestOriginalStaffAnswer:
    """Test original_staff_answer column for preserving unedited conversational answers."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    @pytest.fixture
    def repo(self, temp_db_path):
        """Create a repository with temporary database."""
        yield UnifiedFAQCandidateRepository(str(temp_db_path))

    def test_original_staff_answer_column_exists(self, temp_db_path):
        """Test original_staff_answer column is created."""
        _repo = UnifiedFAQCandidateRepository(str(temp_db_path))  # noqa: F841

        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(unified_faq_candidates)")
        columns = [col[1] for col in cursor.fetchall()]
        conn.close()

        assert "original_staff_answer" in columns

    def test_create_candidate_with_original_answer(self, repo):
        """Test creating candidate with original staff answer."""
        from datetime import datetime

        candidate = repo.create(
            source="bisq2",
            source_event_id="test_orig_123",
            source_timestamp=datetime.now().isoformat(),
            question_text="How do I backup?",
            staff_answer="Navigate to Wallet and select Backup.",
            original_staff_answer="hey! just go to wallet and click backup",
            routing="FULL_REVIEW",
        )

        assert (
            candidate.original_staff_answer == "hey! just go to wallet and click backup"
        )

    def test_retrieve_candidate_preserves_original_answer(self, repo):
        """Test that retrieved candidate has original_staff_answer intact."""
        from datetime import datetime

        created = repo.create(
            source="matrix",
            source_event_id="test_orig_456",
            source_timestamp=datetime.now().isoformat(),
            question_text="How do I withdraw funds?",
            staff_answer="Navigate to Wallet and select Withdraw Funds.",
            original_staff_answer="yeah so you just go to wallet area and click withdraw",
            routing="SPOT_CHECK",
        )

        retrieved = repo.get_by_id(created.id)

        assert retrieved is not None
        assert (
            retrieved.original_staff_answer
            == "yeah so you just go to wallet area and click withdraw"
        )

    def test_original_answer_can_be_null(self, repo):
        """Test that original_staff_answer can be null (for backward compatibility)."""
        from datetime import datetime

        candidate = repo.create(
            source="bisq2",
            source_event_id="test_orig_789",
            source_timestamp=datetime.now().isoformat(),
            question_text="What is Bisq?",
            staff_answer="Bisq is a decentralized exchange.",
            routing="AUTO_APPROVE",
        )

        assert candidate.original_staff_answer is None


# =============================================================================
# TASK: Generation Confidence for Adaptive Threshold Learning
# =============================================================================


class TestGenerationConfidence:
    """Test generation_confidence column for RAG confidence tracking."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    @pytest.fixture
    def repo(self, temp_db_path):
        """Create a repository with temporary database."""
        yield UnifiedFAQCandidateRepository(str(temp_db_path))

    def test_generation_confidence_column_exists(self, temp_db_path):
        """Test generation_confidence column is created."""
        _repo = UnifiedFAQCandidateRepository(str(temp_db_path))  # noqa: F841

        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(unified_faq_candidates)")
        columns = [col[1] for col in cursor.fetchall()]
        conn.close()

        assert "generation_confidence" in columns

    def test_candidate_stores_generation_confidence(self, repo):
        """Test that generation_confidence is stored in database."""
        candidate = repo.create(
            source="bisq2",
            source_event_id="conf_test_1",
            source_timestamp="2026-01-22T10:00:00Z",
            question_text="Test question",
            staff_answer="Test answer",
            final_score=0.85,
            generation_confidence=0.78,  # NEW field
            routing="SPOT_CHECK",
        )

        retrieved = repo.get_by_id(candidate.id)
        assert retrieved.generation_confidence == 0.78

    def test_generation_confidence_can_be_null(self, repo):
        """Test that generation_confidence can be null for backward compatibility."""
        candidate = repo.create(
            source="bisq2",
            source_event_id="conf_test_null",
            source_timestamp="2026-01-22T10:00:00Z",
            question_text="Test question",
            staff_answer="Test answer",
            routing="FULL_REVIEW",
        )

        assert candidate.generation_confidence is None

    def test_generation_confidence_different_from_final_score(self, repo):
        """Test generation_confidence is stored independently from final_score."""
        # This verifies we're not accidentally mixing up the two metrics
        candidate = repo.create(
            source="matrix",
            source_event_id="conf_test_diff",
            source_timestamp="2026-01-22T10:00:00Z",
            question_text="Test question",
            staff_answer="Test answer",
            final_score=0.85,  # Comparison score
            generation_confidence=0.72,  # RAG confidence (different!)
            routing="SPOT_CHECK",
        )

        retrieved = repo.get_by_id(candidate.id)
        assert retrieved.final_score == 0.85
        assert retrieved.generation_confidence == 0.72
        assert retrieved.final_score != retrieved.generation_confidence


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def repo(self):
        """Create a fresh repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_unified.db"
            yield UnifiedFAQCandidateRepository(str(db_path))

    def test_duplicate_event_id_raises_error(self, repo):
        """Test that duplicate source_event_id raises an error."""
        # Arrange
        repo.create(
            source="bisq2",
            source_event_id="unique_id",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="First question",
            staff_answer="First answer",
            routing="FULL_REVIEW",
        )

        # Act & Assert
        with pytest.raises(Exception):  # Could be IntegrityError or custom exception
            repo.create(
                source="matrix",
                source_event_id="unique_id",  # Same ID
                source_timestamp="2025-01-15T10:01:00Z",
                question_text="Second question",
                staff_answer="Second answer",
                routing="FULL_REVIEW",
            )

    def test_get_current_item_returns_none_when_empty(self, repo):
        """Test get_current_item returns None when queue is empty."""
        # Act
        result = repo.get_current_item("FULL_REVIEW", source=None)

        # Assert
        assert result is None

    def test_get_current_item_excludes_reviewed(self, repo):
        """Test get_current_item excludes already reviewed candidates."""
        # Arrange
        candidate = repo.create(
            source="bisq2",
            source_event_id="reviewed_id",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="Reviewed question",
            staff_answer="Reviewed answer",
            routing="FULL_REVIEW",
        )
        repo.approve(candidate.id, reviewer="admin", faq_id="faq_1")

        # Act
        result = repo.get_current_item("FULL_REVIEW", source=None)

        # Assert - Should be None as only candidate is already reviewed
        assert result is None


# =============================================================================
# CYCLE 9: Conversation Thread Tables
# =============================================================================


class TestConversationThreadTables:
    """Test conversation thread table creation and basic operations."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    @pytest.fixture
    def repo(self, temp_db_path):
        """Create repository instance."""
        return UnifiedFAQCandidateRepository(str(temp_db_path))

    def test_thread_tables_exist(self, temp_db_path, repo):
        """Cycle 9.1: Verify conversation_threads and thread_messages tables exist."""
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()

        # Check conversation_threads table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_threads'"
        )
        assert cursor.fetchone() is not None, "conversation_threads table should exist"

        # Check thread_messages table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thread_messages'"
        )
        assert cursor.fetchone() is not None, "thread_messages table should exist"

        # Check conversation_state_transitions table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_state_transitions'"
        )
        assert (
            cursor.fetchone() is not None
        ), "conversation_state_transitions table should exist"

        conn.close()

    def test_create_thread(self, repo):
        """Cycle 9.2: Test thread creation."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$msg123",
        )

        assert thread.id is not None
        assert thread.source == "matrix"
        assert thread.room_id == "!room:matrix.org"
        assert thread.first_question_id == "$msg123"
        assert thread.state == "pending_question"

    def test_get_thread(self, repo):
        """Cycle 9.3: Test retrieving a thread by ID."""
        thread = repo.create_thread(
            source="bisq2",
            room_id=None,
            first_question_id="bisq_q1",
        )

        retrieved = repo.get_thread(thread.id)
        assert retrieved is not None
        assert retrieved.id == thread.id
        assert retrieved.source == "bisq2"
        assert retrieved.first_question_id == "bisq_q1"

    def test_add_message_to_thread(self, repo):
        """Cycle 9.4: Test adding messages to a thread."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )

        repo.add_message_to_thread(
            thread_id=thread.id,
            message_id="$q1",
            message_type="question",
            content="How do I verify?",
            sender_id="@user:matrix.org",
            timestamp="2026-01-22T10:00:00Z",
        )

        messages = repo.get_thread_messages(thread.id)
        assert len(messages) == 1
        assert messages[0].message_id == "$q1"
        assert messages[0].message_type == "question"
        assert messages[0].content == "How do I verify?"


# =============================================================================
# CYCLE 10: Thread Lookup by Message ID
# =============================================================================


class TestThreadLookupByMessage:
    """Test finding threads by any message ID in the thread."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    @pytest.fixture
    def repo(self, temp_db_path):
        """Create repository instance."""
        return UnifiedFAQCandidateRepository(str(temp_db_path))

    def test_find_thread_by_question_message(self, repo):
        """Cycle 10.1: Find thread by question message ID."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )
        repo.add_message_to_thread(
            thread_id=thread.id,
            message_id="$q1",
            message_type="question",
            content="Question content",
        )

        found = repo.find_thread_by_message("$q1")
        assert found is not None
        assert found.id == thread.id

    def test_find_thread_by_answer_message(self, repo):
        """Cycle 10.2: Find thread by staff answer message ID."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )
        repo.add_message_to_thread(thread.id, "$q1", "question", "Q?")
        repo.add_message_to_thread(thread.id, "$a1", "staff_answer", "Answer")

        # Find by answer
        found_by_a = repo.find_thread_by_message("$a1")
        assert found_by_a is not None
        assert found_by_a.id == thread.id

    def test_find_thread_by_any_message_same_thread(self, repo):
        """Cycle 10.3: Find same thread by any message ID."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )
        repo.add_message_to_thread(thread.id, "$q1", "question", "Question")
        repo.add_message_to_thread(thread.id, "$a1", "staff_answer", "Answer")

        # Both should find same thread
        found_by_q = repo.find_thread_by_message("$q1")
        found_by_a = repo.find_thread_by_message("$a1")
        assert found_by_q.id == found_by_a.id == thread.id

    def test_find_thread_returns_none_for_unknown_message(self, repo):
        """Cycle 10.4: Return None for unknown message ID."""
        found = repo.find_thread_by_message("$unknown")
        assert found is None


# =============================================================================
# CYCLE 11: State Transitions with Audit
# =============================================================================


class TestStateTransitionsWithAudit:
    """Test thread state transitions with audit trail."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    @pytest.fixture
    def repo(self, temp_db_path):
        """Create repository instance."""
        return UnifiedFAQCandidateRepository(str(temp_db_path))

    def test_transition_thread_state(self, repo):
        """Cycle 11.1: Basic state transition updates thread state."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )
        assert thread.state == "pending_question"

        repo.transition_thread_state(
            thread_id=thread.id,
            to_state="has_staff_answer",
            trigger="staff_reply_received",
        )

        updated = repo.get_thread(thread.id)
        assert updated.state == "has_staff_answer"

    def test_transition_creates_audit_record(self, repo):
        """Cycle 11.2: State transition creates audit trail entry."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )

        repo.transition_thread_state(
            thread_id=thread.id,
            to_state="has_staff_answer",
            trigger="staff_reply_received",
            metadata={"staff_id": "user123"},
        )

        transitions = repo.get_thread_transitions(thread.id)
        assert len(transitions) == 1
        assert transitions[0]["from_state"] == "pending_question"
        assert transitions[0]["to_state"] == "has_staff_answer"
        assert transitions[0]["trigger"] == "staff_reply_received"

    def test_multiple_transitions_audit_trail(self, repo):
        """Cycle 11.3: Multiple transitions create multiple audit records."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )

        repo.transition_thread_state(thread.id, "has_staff_answer", "staff_replied")
        repo.transition_thread_state(thread.id, "candidate_created", "rag_compared")
        repo.transition_thread_state(thread.id, "closed", "approved")

        transitions = repo.get_thread_transitions(thread.id)
        assert len(transitions) == 3
        assert transitions[0]["to_state"] == "has_staff_answer"
        assert transitions[1]["to_state"] == "candidate_created"
        assert transitions[2]["to_state"] == "closed"

    def test_transition_metadata_is_stored(self, repo):
        """Cycle 11.4: Transition metadata is preserved in audit."""
        thread = repo.create_thread(
            source="matrix",
            room_id="!room:matrix.org",
            first_question_id="$q1",
        )

        repo.transition_thread_state(
            thread_id=thread.id,
            to_state="candidate_created",
            trigger="faq_candidate_created",
            metadata={"candidate_id": 123, "score": 0.85},
        )

        transitions = repo.get_thread_transitions(thread.id)
        assert len(transitions) == 1
        # Metadata should be JSON parseable
        import json

        metadata = json.loads(transitions[0]["metadata"])
        assert metadata["candidate_id"] == 123
        assert metadata["score"] == 0.85
