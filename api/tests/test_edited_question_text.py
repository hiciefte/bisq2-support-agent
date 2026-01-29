"""
TDD Tests for edited_question_text feature.

This feature allows reviewers to edit the FAQ question before approval,
similar to how edited_staff_answer works for answers.

Tests follow RED-GREEN-REFACTOR cycle:
1. RED: Write failing tests
2. GREEN: Implement minimal code to pass
3. REFACTOR: Clean up while keeping tests green
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.training.unified_repository import (
    UnifiedFAQCandidate,
    UnifiedFAQCandidateRepository,
)

# =============================================================================
# TASK 1: Database Layer Tests
# =============================================================================


class TestEditedQuestionTextDatabaseLayer:
    """Test database schema and migration for edited_question_text."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_edited_question.db"

    def test_edited_question_text_column_exists_in_new_database(self, temp_db_path):
        """RED: New databases should have edited_question_text column."""
        # Arrange & Act - instantiation creates the database with schema
        UnifiedFAQCandidateRepository(str(temp_db_path))

        # Assert - Check column exists
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(unified_faq_candidates)")
        columns = {col[1] for col in cursor.fetchall()}
        conn.close()

        assert (
            "edited_question_text" in columns
        ), "edited_question_text column should exist in unified_faq_candidates table"

    def test_edited_question_text_migration_adds_column(self, temp_db_path):
        """RED: Migration should add edited_question_text to existing databases."""
        # Arrange - Create database WITHOUT edited_question_text column
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()

        # Create minimal table without edited_question_text
        cursor.execute("""
            CREATE TABLE unified_faq_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL CHECK (source IN ('bisq2', 'matrix')),
                source_event_id TEXT NOT NULL,
                source_timestamp TEXT NOT NULL,
                question_text TEXT NOT NULL,
                staff_answer TEXT NOT NULL,
                generated_answer TEXT,
                staff_sender TEXT,
                embedding_similarity REAL,
                factual_alignment REAL,
                contradiction_score REAL,
                completeness REAL,
                hallucination_risk REAL,
                final_score REAL,
                llm_reasoning TEXT,
                routing TEXT NOT NULL CHECK (routing IN ('AUTO_APPROVE', 'SPOT_CHECK', 'FULL_REVIEW')),
                review_status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TEXT,
                rejection_reason TEXT,
                faq_id TEXT,
                is_calibration_sample BOOLEAN DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                skip_order INTEGER DEFAULT 0,
                protocol TEXT,
                edited_staff_answer TEXT,
                category TEXT DEFAULT 'General'
            )
        """)

        # Create calibration_state table (required by repository)
        cursor.execute("""
            CREATE TABLE calibration_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                samples_collected INTEGER DEFAULT 0,
                samples_required INTEGER DEFAULT 100,
                auto_approve_threshold REAL DEFAULT 0.90,
                spot_check_threshold REAL DEFAULT 0.75,
                calibration_complete BOOLEAN DEFAULT FALSE,
                last_updated TEXT
            )
        """)
        cursor.execute("""
            INSERT INTO calibration_state
            (id, samples_collected, samples_required, auto_approve_threshold, spot_check_threshold, calibration_complete)
            VALUES (1, 0, 100, 0.90, 0.75, FALSE)
        """)
        conn.commit()

        # Verify column doesn't exist yet
        cursor.execute("PRAGMA table_info(unified_faq_candidates)")
        columns_before = {col[1] for col in cursor.fetchall()}
        assert "edited_question_text" not in columns_before
        conn.close()

        # Act - Initialize repository (should trigger migration)
        UnifiedFAQCandidateRepository(str(temp_db_path))

        # Assert - Column should now exist
        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(unified_faq_candidates)")
        columns_after = {col[1] for col in cursor.fetchall()}
        conn.close()

        assert (
            "edited_question_text" in columns_after
        ), "Migration should add edited_question_text column"


# =============================================================================
# TASK 2: Repository Layer Tests
# =============================================================================


class TestEditedQuestionTextRepository:
    """Test repository operations for edited_question_text."""

    @pytest.fixture
    def repo(self):
        """Create a repository with temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_repo.db"
            yield UnifiedFAQCandidateRepository(str(db_path))

    @pytest.fixture
    def sample_candidate(self, repo):
        """Create and return a sample candidate."""
        return repo.create(
            source="bisq2",
            source_event_id="msg_test_123",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="Original question text",
            staff_answer="Staff answer text",
            routing="FULL_REVIEW",
        )

    def test_dataclass_has_edited_question_text_field(self):
        """RED: UnifiedFAQCandidate should have edited_question_text field."""
        # Create a candidate instance to check field exists
        candidate = UnifiedFAQCandidate(
            id=1,
            source="bisq2",
            source_event_id="test",
            source_timestamp="2025-01-01",
            question_text="Original question",
            staff_answer="Answer",
            edited_question_text="Edited question",  # New field
        )

        assert hasattr(candidate, "edited_question_text")
        assert candidate.edited_question_text == "Edited question"

    def test_update_candidate_with_edited_question_text(self, repo, sample_candidate):
        """RED: update_candidate should accept and save edited_question_text."""
        # Act
        updated = repo.update_candidate(
            candidate_id=sample_candidate.id,
            edited_question_text="How do I trade on Bisq Easy?",
        )

        # Assert
        assert updated is not None
        assert updated.edited_question_text == "How do I trade on Bisq Easy?"
        assert updated.question_text == "Original question text"  # Original unchanged

    def test_get_by_id_returns_edited_question_text(self, repo, sample_candidate):
        """RED: get_by_id should return edited_question_text field."""
        # Arrange - Update with edited question
        repo.update_candidate(
            candidate_id=sample_candidate.id,
            edited_question_text="Edited version of the question",
        )

        # Act
        retrieved = repo.get_by_id(sample_candidate.id)

        # Assert
        assert retrieved is not None
        assert retrieved.edited_question_text == "Edited version of the question"

    def test_edited_question_text_defaults_to_none(self, repo, sample_candidate):
        """RED: New candidates should have edited_question_text = None."""
        # Act
        retrieved = repo.get_by_id(sample_candidate.id)

        # Assert
        assert retrieved is not None
        assert retrieved.edited_question_text is None


# =============================================================================
# TASK 3: Service Layer Tests
# =============================================================================


class TestEditedQuestionTextService:
    """Test pipeline service uses edited_question_text when approving."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for UnifiedPipelineService."""
        mock_repo = MagicMock()
        mock_rag_service = MagicMock()
        mock_faq_service = MagicMock()

        # Setup mock FAQ service to return a mock FAQ with ID
        mock_faq = MagicMock()
        mock_faq.id = "faq_123"
        mock_faq_service.add_faq.return_value = mock_faq

        # Setup mock RAG service to return no duplicates
        mock_rag_service.search_faq_similarity = AsyncMock(return_value=[])

        return mock_repo, mock_rag_service, mock_faq_service

    @pytest.mark.asyncio
    async def test_approve_candidate_uses_edited_question_when_available(
        self, mock_dependencies
    ):
        """RED: approve_candidate should use edited_question_text for FAQ question."""
        from app.services.training.unified_pipeline_service import (
            UnifiedPipelineService,
        )

        mock_repo, mock_rag_service, mock_faq_service = mock_dependencies

        # Setup candidate with edited question
        mock_candidate = MagicMock()
        mock_candidate.id = 1
        mock_candidate.source = "bisq2"
        mock_candidate.question_text = "Original conversational question?"
        mock_candidate.edited_question_text = "How do I start trading on Bisq Easy?"
        mock_candidate.staff_answer = "Go to Trade Wizard."
        mock_candidate.edited_staff_answer = None
        mock_candidate.protocol = "bisq_easy"
        mock_candidate.category = "Trading"
        mock_repo.get_by_id.return_value = mock_candidate

        # Create service
        service = UnifiedPipelineService(
            repository=mock_repo,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
        )

        # Act
        await service.approve_candidate(candidate_id=1, reviewer="admin")

        # Assert - FAQ should be created with edited question
        mock_faq_service.add_faq.assert_called_once()
        faq_item = mock_faq_service.add_faq.call_args[0][0]
        assert faq_item.question == "How do I start trading on Bisq Easy?"

    @pytest.mark.asyncio
    async def test_approve_candidate_uses_original_question_when_not_edited(
        self, mock_dependencies
    ):
        """RED: approve_candidate should use original question_text when not edited."""
        from app.services.training.unified_pipeline_service import (
            UnifiedPipelineService,
        )

        mock_repo, mock_rag_service, mock_faq_service = mock_dependencies

        # Setup candidate WITHOUT edited question
        mock_candidate = MagicMock()
        mock_candidate.id = 1
        mock_candidate.source = "bisq2"
        mock_candidate.question_text = "Original question text"
        mock_candidate.edited_question_text = None  # Not edited
        mock_candidate.staff_answer = "Answer text"
        mock_candidate.edited_staff_answer = None
        mock_candidate.protocol = "bisq_easy"
        mock_candidate.category = "General"
        mock_repo.get_by_id.return_value = mock_candidate

        # Create service
        service = UnifiedPipelineService(
            repository=mock_repo,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
        )

        # Act
        await service.approve_candidate(candidate_id=1, reviewer="admin")

        # Assert - FAQ should be created with original question
        mock_faq_service.add_faq.assert_called_once()
        faq_item = mock_faq_service.add_faq.call_args[0][0]
        assert faq_item.question == "Original question text"


# =============================================================================
# TASK 4: API Layer Tests
# =============================================================================


class TestEditedQuestionTextAPI:
    """Test API routes support edited_question_text."""

    def test_update_candidate_request_accepts_edited_question_text(self):
        """RED: UpdateCandidateRequest should accept edited_question_text field."""
        from app.routes.admin.training import UpdateCandidateRequest

        # Act - Create request with edited_question_text
        request = UpdateCandidateRequest(
            edited_question_text="How do I trade on Bisq?",
            edited_staff_answer="Use the Trade Wizard.",
        )

        # Assert
        assert request.edited_question_text == "How do I trade on Bisq?"

    def test_candidate_response_includes_edited_question_text(self):
        """RED: UnifiedCandidateResponse should include edited_question_text."""
        from app.routes.admin.training import UnifiedCandidateResponse

        # Act - Create response with edited_question_text
        response = UnifiedCandidateResponse(
            id=1,
            source="bisq2",
            source_event_id="msg_123",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="Original question",
            staff_answer="Answer",
            generated_answer=None,
            staff_sender=None,
            embedding_similarity=None,
            factual_alignment=None,
            contradiction_score=None,
            completeness=None,
            hallucination_risk=None,
            final_score=None,
            generation_confidence=None,
            llm_reasoning=None,
            routing="FULL_REVIEW",
            review_status="pending",
            reviewed_by=None,
            reviewed_at=None,
            rejection_reason=None,
            faq_id=None,
            is_calibration_sample=False,
            created_at="2025-01-15T10:00:00Z",
            updated_at=None,
            edited_question_text="Edited question",  # New field
        )

        # Assert
        assert response.edited_question_text == "Edited question"

    def test_candidate_to_dict_includes_edited_question_text(self):
        """RED: _candidate_to_dict should include edited_question_text in response."""
        from app.routes.admin.training import _candidate_to_dict

        # Create a mock candidate with edited_question_text
        mock_candidate = MagicMock()
        mock_candidate.id = 1
        mock_candidate.source = "bisq2"
        mock_candidate.source_event_id = "msg_123"
        mock_candidate.source_timestamp = "2025-01-15T10:00:00Z"
        mock_candidate.question_text = "Original question"
        mock_candidate.staff_answer = "Answer"
        mock_candidate.generated_answer = None
        mock_candidate.staff_sender = None
        mock_candidate.embedding_similarity = None
        mock_candidate.factual_alignment = None
        mock_candidate.contradiction_score = None
        mock_candidate.completeness = None
        mock_candidate.hallucination_risk = None
        mock_candidate.final_score = None
        mock_candidate.llm_reasoning = None
        mock_candidate.routing = "FULL_REVIEW"
        mock_candidate.review_status = "pending"
        mock_candidate.reviewed_by = None
        mock_candidate.reviewed_at = None
        mock_candidate.rejection_reason = None
        mock_candidate.faq_id = None
        mock_candidate.is_calibration_sample = False
        mock_candidate.created_at = "2025-01-15T10:00:00Z"
        mock_candidate.updated_at = None
        mock_candidate.edited_question_text = "Edited question text"

        # Act
        result = _candidate_to_dict(mock_candidate)

        # Assert
        assert "edited_question_text" in result
        assert result["edited_question_text"] == "Edited question text"
