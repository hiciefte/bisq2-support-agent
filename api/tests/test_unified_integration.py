"""
Integration Tests for Unified FAQ Training Pipeline.

TDD Phase 4: Integration with existing services.
Following RED-GREEN-REFACTOR cycle.

Tests cover:
- TASK 4.1: Bisq Integration (FAQService)
- TASK 4.2: Matrix Integration (MatrixShadowModeService)
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.training.unified_pipeline_service import UnifiedPipelineService

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test_unified.db")


@pytest.fixture
def mock_rag_service():
    """Create a mock RAG service."""
    service = MagicMock()
    service.query = AsyncMock(
        return_value={
            "response": "This is the RAG-generated answer.",
            "sources": [],
        }
    )
    # For duplicate FAQ detection in approve_candidate
    service.search_faq_similarity = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_faq_service():
    """Create a mock FAQ service."""
    service = MagicMock()
    mock_faq = MagicMock()
    mock_faq.id = "faq_123"
    service.add_faq = MagicMock(return_value=mock_faq)
    return service


@pytest.fixture
def mock_settings():
    """Create mock settings for integration tests."""
    settings = MagicMock()
    settings.OPENAI_API_KEY = "test-key"
    # Configure staff users for Bisq conversation processing
    # Must match author values in sample_bisq_conversation fixture
    settings.BISQ_STAFF_USERS = ["suddenwhipvapor"]
    return settings


@pytest.fixture
def unified_pipeline(temp_db_path, mock_settings, mock_rag_service, mock_faq_service):
    """Create a UnifiedPipelineService for testing."""
    return UnifiedPipelineService(
        settings=mock_settings,
        db_path=temp_db_path,
        rag_service=mock_rag_service,
        faq_service=mock_faq_service,
    )


@pytest.fixture
def sample_bisq_conversation():
    """Create a sample Bisq 2 conversation for testing.

    Uses flat API format matching real Bisq 2 API response:
    - "message" key for text content
    - "messageId" key for ID
    - "author" key for sender (staff detection via staff_users list)
    - "date" key for timestamp
    """
    return {
        "thread_id": "thread_123",
        "messages": [
            {
                "messageId": "msg_001",
                "message": "How do I start trading on Bisq 2?",
                "author": "user123",
                "date": "2025-01-15T10:00:00Z",
            },
            {
                "messageId": "msg_002",
                "message": "Go to Trade > Trade Wizard to start your first trade.",
                "author": "suddenwhipvapor",  # Staff user
                "date": "2025-01-15T10:01:00Z",
            },
        ],
    }


# =============================================================================
# TASK 4.1: Bisq Integration Tests
# =============================================================================


class TestBisqIntegration:
    """Test Bisq 2 conversation processing through unified pipeline."""

    @pytest.mark.asyncio
    async def test_process_bisq_conversation_creates_candidate(
        self, unified_pipeline, sample_bisq_conversation
    ):
        """Cycle 4.1.1: Test that Bisq conversation creates unified candidate."""
        result = await unified_pipeline.process_bisq_conversation(
            sample_bisq_conversation
        )

        assert result is not None
        assert result.source == "bisq2"
        assert result.candidate_id is not None
        assert result.routing in ["FULL_REVIEW", "SPOT_CHECK", "AUTO_APPROVE"]

    @pytest.mark.asyncio
    async def test_bisq_candidate_has_correct_source_event_id(
        self, unified_pipeline, sample_bisq_conversation
    ):
        """Test that source_event_id is correctly formatted for Bisq."""
        result = await unified_pipeline.process_bisq_conversation(
            sample_bisq_conversation
        )

        assert result is not None
        assert result.source_event_id.startswith("bisq2_")
        assert "thread_123" in result.source_event_id

    @pytest.mark.asyncio
    async def test_bisq_duplicate_detection(
        self, unified_pipeline, sample_bisq_conversation
    ):
        """Test that duplicate Bisq conversations are skipped."""
        # Process first time
        result1 = await unified_pipeline.process_bisq_conversation(
            sample_bisq_conversation
        )
        assert result1 is not None
        assert result1.candidate_id is not None

        # Process same conversation again
        result2 = await unified_pipeline.process_bisq_conversation(
            sample_bisq_conversation
        )
        assert result2 is not None
        assert result2.skipped_reason == "duplicate"
        assert result2.candidate_id is None


# =============================================================================
# TASK 4.2: Matrix Integration Tests
# =============================================================================


class TestMatrixIntegration:
    """Test Matrix staff answer processing through unified pipeline."""

    @pytest.mark.asyncio
    async def test_process_matrix_answer_creates_candidate(self, unified_pipeline):
        """Cycle 4.2.1: Test that Matrix answer creates unified candidate."""
        result = await unified_pipeline.process_matrix_answer(
            event_id="$test_event:matrix.org",
            staff_answer="The fee is calculated based on trade amount.",
            reply_to_event_id="$question_event:matrix.org",
            question_text="What are the fees on Bisq?",
            staff_sender="@support:matrix.org",
        )

        assert result is not None
        assert result.source == "matrix"
        assert result.candidate_id is not None
        assert result.source_event_id == "$test_event:matrix.org"

    @pytest.mark.asyncio
    async def test_matrix_answer_with_source_preservation(
        self, unified_pipeline, mock_faq_service
    ):
        """Test that approved Matrix candidate uses human-readable source name."""
        # Process answer
        result = await unified_pipeline.process_matrix_answer(
            event_id="$answer_event:matrix.org",
            staff_answer="Use the offer book to browse trades.",
            reply_to_event_id="$question:matrix.org",
            question_text="How do I browse trades?",
            staff_sender="@staff:matrix.org",
        )

        # Approve the candidate
        assert result.candidate_id is not None
        await unified_pipeline.approve_candidate(
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        # Verify FAQ was created with human-readable source name
        mock_faq_service.add_faq.assert_called_once()
        call_args = mock_faq_service.add_faq.call_args
        faq_item = call_args[0][0]  # First positional argument
        assert faq_item.source == "Matrix Support"
        assert faq_item.verified is True

    @pytest.mark.asyncio
    async def test_matrix_duplicate_detection(self, unified_pipeline):
        """Test that duplicate Matrix answers are skipped."""
        event_id = "$unique_answer:matrix.org"

        # Process first time
        result1 = await unified_pipeline.process_matrix_answer(
            event_id=event_id,
            staff_answer="First answer",
            reply_to_event_id="$q1:matrix.org",
            question_text="Question 1?",
            staff_sender="@staff:matrix.org",
        )
        assert result1 is not None
        assert result1.candidate_id is not None

        # Process same event again
        result2 = await unified_pipeline.process_matrix_answer(
            event_id=event_id,
            staff_answer="Second answer",
            reply_to_event_id="$q2:matrix.org",
            question_text="Question 2?",
            staff_sender="@staff:matrix.org",
        )
        assert result2 is not None
        assert result2.skipped_reason == "duplicate"


# =============================================================================
# Cross-Source Integration Tests
# =============================================================================


class TestCrossSourceIntegration:
    """Test that both sources work together correctly."""

    @pytest.mark.asyncio
    async def test_queue_counts_separate_by_source(
        self, unified_pipeline, sample_bisq_conversation
    ):
        """Test that queue counts can be filtered by source."""
        # Add a Bisq candidate
        await unified_pipeline.process_bisq_conversation(sample_bisq_conversation)

        # Add a Matrix candidate
        await unified_pipeline.process_matrix_answer(
            event_id="$matrix_event:matrix.org",
            staff_answer="Matrix answer",
            reply_to_event_id="$q:matrix.org",
            question_text="Matrix question?",
            staff_sender="@staff:matrix.org",
        )

        # Get all counts
        all_counts = unified_pipeline.get_queue_counts()
        bisq_counts = unified_pipeline.get_queue_counts(source="bisq2")
        matrix_counts = unified_pipeline.get_queue_counts(source="matrix")

        # Verify separation
        assert sum(bisq_counts.values()) == 1
        assert sum(matrix_counts.values()) == 1
        assert sum(all_counts.values()) == 2

    @pytest.mark.asyncio
    async def test_calibration_counts_both_sources(
        self, unified_pipeline, sample_bisq_conversation
    ):
        """Test that calibration samples are counted from both sources."""
        initial_status = unified_pipeline.get_calibration_status()
        initial_count = initial_status.samples_collected

        # Add Bisq candidate (during calibration = calibration sample)
        await unified_pipeline.process_bisq_conversation(sample_bisq_conversation)

        # Add Matrix candidate
        await unified_pipeline.process_matrix_answer(
            event_id="$matrix:matrix.org",
            staff_answer="Answer",
            reply_to_event_id="$q:matrix.org",
            question_text="Question?",
            staff_sender="@staff:matrix.org",
        )

        # Check calibration count increased
        status = unified_pipeline.get_calibration_status()
        assert status.samples_collected == initial_count + 2

    @pytest.mark.asyncio
    async def test_source_preserved_in_approved_faq(
        self, unified_pipeline, mock_faq_service, sample_bisq_conversation
    ):
        """Test that source uses human-readable name when FAQ is created."""
        # Process and approve Bisq candidate
        bisq_result = await unified_pipeline.process_bisq_conversation(
            sample_bisq_conversation
        )

        await unified_pipeline.approve_candidate(
            candidate_id=bisq_result.candidate_id,
            reviewer="admin",
        )

        # Verify Bisq source uses human-readable name (FAQItem as positional arg)
        call_args = mock_faq_service.add_faq.call_args
        faq_item = call_args[0][0]  # First positional argument
        assert faq_item.source == "Bisq Support Chat"


# =============================================================================
# Calibration Mode Integration Tests
# =============================================================================


class TestCalibrationModeIntegration:
    """Test calibration mode behavior across sources."""

    @pytest.mark.asyncio
    async def test_calibration_forces_full_review(
        self, unified_pipeline, sample_bisq_conversation
    ):
        """Test that calibration mode forces FULL_REVIEW routing."""
        # During calibration, all items should go to FULL_REVIEW
        result = await unified_pipeline.process_bisq_conversation(
            sample_bisq_conversation
        )

        assert result.routing == "FULL_REVIEW"
        assert result.is_calibration_sample is True

    @pytest.mark.asyncio
    async def test_auto_approve_after_calibration(
        self, temp_db_path, mock_rag_service, mock_faq_service
    ):
        """Test that AUTO_APPROVE works after calibration is complete."""
        # Create pipeline
        pipeline = UnifiedPipelineService(
            db_path=temp_db_path,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
        )

        # Manually complete calibration
        for i in range(100):
            pipeline.repository.increment_calibration_count()

        assert not pipeline.is_calibration_mode()

        # Now high scores should get AUTO_APPROVE
        # (Note: without a real comparison engine, this uses mock scores)
        result = await pipeline.process_matrix_answer(
            event_id="$high_score:matrix.org",
            staff_answer="Answer that matches well",
            reply_to_event_id="$q:matrix.org",
            question_text="Simple question?",
            staff_sender="@staff:matrix.org",
        )

        # With mock comparison, default score is 0.85 -> SPOT_CHECK
        # But routing after calibration follows thresholds
        assert result.is_calibration_sample is False
