"""
TDD Tests for UnifiedPipelineService.

These tests follow the RED-GREEN-REFACTOR cycle from the plan:
/Users/takahiro/.claude/plans/cheerful-discovering-blanket.md

Phase 2: Unified Pipeline Service Tests
"""

import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Import will fail until implementation exists - that's the RED phase
try:
    from app.services.training.unified_pipeline_service import (
        DuplicateFAQError,
        UnifiedPipelineService,
    )

    IMPLEMENTATION_EXISTS = True
except ImportError:
    IMPLEMENTATION_EXISTS = False
    UnifiedPipelineService = None
    DuplicateFAQError = None

# Import repository (should exist from Phase 1)
from app.services.training.unified_repository import (
    CalibrationStatus,
    UnifiedFAQCandidateRepository,
)

# Skip all tests if implementation doesn't exist yet (RED phase)
pytestmark = pytest.mark.skipif(
    not IMPLEMENTATION_EXISTS,
    reason="UnifiedPipelineService not yet implemented (RED phase)",
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_unified.db"


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock()
    settings.OPENAI_API_KEY = "test-key"
    # Configure staff users for Bisq conversation processing
    # Must match author values in sample_bisq_conversation fixture
    settings.BISQ_STAFF_USERS = ["support-staff", "suddenwhipvapor"]
    return settings


@pytest.fixture
def mock_rag_service():
    """Create a mocked RAG service.

    IMPORTANT: The key must be "answer" (not "response") to match the
    actual SimplifiedRAGService.query() return format.
    """
    mock = MagicMock()
    mock.query = AsyncMock(
        return_value={
            "answer": (  # NOTE: Must be "answer" not "response"!
                "To trade on Bisq Easy, navigate to Trade > Trade Wizard. "
                "New users have a limit of $600 per trade."
            ),
            "sources": [
                {"type": "wiki", "title": "Bisq Easy Trading Guide"},
            ],
            "response_time": 0.5,
        }
    )
    mock.setup = AsyncMock()
    # For duplicate FAQ detection in approve_candidate
    mock.search_faq_similarity = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_faq_service():
    """Create a mocked FAQ service."""
    mock = MagicMock()
    mock.add_faq = MagicMock(return_value="faq_test_123")
    return mock


@pytest.fixture
def mock_comparison_engine():
    """Create a mocked comparison engine."""
    mock = MagicMock()
    # Default to high score for AUTO_APPROVE
    mock.compare = AsyncMock(
        return_value=MagicMock(
            question_event_id="test_event",
            embedding_similarity=0.92,
            factual_alignment=0.95,
            contradiction_score=0.03,
            completeness=0.90,
            hallucination_risk=0.05,
            final_score=0.92,
            llm_reasoning="High alignment between answers.",
            routing="AUTO_APPROVE",
            is_calibration=False,
        )
    )
    return mock


@pytest.fixture
def sample_bisq_conversation() -> Dict[str, Any]:
    """Sample Bisq 2 conversation for testing.

    Uses flat API format matching real Bisq 2 API response:
    - "message" key for text content
    - "messageId" key for ID
    - "author" key for sender (staff detection via staff_users list)
    - "date" key for timestamp
    """
    return {
        "thread_id": "test-thread-123",
        "channel_id": "support-general",
        "timestamp": "2025-01-15T10:00:00Z",
        "messages": [
            {
                "messageId": "msg1",
                "message": "How do I start trading on Bisq Easy?",
                "author": "user123",
                "date": "2025-01-15T10:00:00Z",
            },
            {
                "messageId": "msg2",
                "message": (
                    "To start trading on Bisq Easy, go to the Trade tab and select "
                    "'Trade wizard'. You can browse existing offers or create your own. "
                    "The maximum trade amount is $600 for new users."
                ),
                "author": "suddenwhipvapor",  # Staff user
                "date": "2025-01-15T10:05:00Z",
            },
        ],
    }


# =============================================================================
# TASK 2.1: Service Initialization
# =============================================================================


class TestServiceInit:
    """Test service initialization and component setup."""

    @pytest_asyncio.fixture
    async def service(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create a pipeline service instance."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_service_initializes_components(self, service):
        """Cycle 2.1.1: Test service initializes with all required components."""
        # Assert
        assert service is not None
        assert service.repository is not None
        assert isinstance(service.repository, UnifiedFAQCandidateRepository)
        assert service.rag_service is not None
        assert service.faq_service is not None


# =============================================================================
# TASK 2.2: Bisq2 Processing
# =============================================================================


class TestBisq2Processing:
    """Test processing of Bisq 2 conversations."""

    @pytest_asyncio.fixture
    async def service(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create a pipeline service instance."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_process_bisq_conversation_creates_candidate(
        self, service, sample_bisq_conversation
    ):
        """Cycle 2.2.1: Test processing Bisq conversation creates a candidate."""
        # Act
        result = await service.process_bisq_conversation(sample_bisq_conversation)

        # Assert
        assert result is not None
        assert result.source == "bisq2"
        # Event ID includes thread and message ID for uniqueness
        assert "msg2" in result.source_event_id
        assert result.candidate_id is not None
        assert result.candidate_id > 0

    @pytest.mark.asyncio
    async def test_process_bisq_skips_duplicate(
        self, service, sample_bisq_conversation
    ):
        """Cycle 2.2.2: Test processing same conversation twice skips duplicate."""
        # Act
        first = await service.process_bisq_conversation(sample_bisq_conversation)
        second = await service.process_bisq_conversation(sample_bisq_conversation)

        # Assert
        assert first is not None
        assert first.candidate_id is not None
        # Second returns a result indicating skip (not None)
        assert second is not None
        assert second.skipped_reason == "duplicate"
        assert second.candidate_id is None

        # Verify only one candidate exists
        candidates = service.repository.get_pending(source="bisq2")
        assert len(candidates) == 1


# =============================================================================
# TASK 2.3: Matrix Processing
# =============================================================================


class TestMatrixProcessing:
    """Test processing of Matrix staff answers."""

    @pytest_asyncio.fixture
    async def service(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create a pipeline service instance."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_process_matrix_answer_creates_candidate(self, service):
        """Cycle 2.3.1: Test processing Matrix answer creates a candidate."""
        # Act
        candidate = await service.process_matrix_answer(
            event_id="$matrix_event_123:matrix.org",
            staff_answer="To trade on Bisq Easy, go to Trade Wizard.",
            reply_to_event_id="$question_456:matrix.org",
            question_text="How do I trade on Bisq?",
            staff_sender="@support:matrix.org",
        )

        # Assert
        assert candidate is not None
        assert candidate.source == "matrix"
        assert candidate.source_event_id == "$matrix_event_123:matrix.org"

    @pytest.mark.asyncio
    async def test_process_matrix_skips_duplicate(self, service):
        """Cycle 2.3.2: Test processing same Matrix answer twice skips duplicate."""
        # Act
        first = await service.process_matrix_answer(
            event_id="$matrix_event_123:matrix.org",
            staff_answer="Answer text",
            reply_to_event_id="$question_456:matrix.org",
            question_text="Question text",
            staff_sender="@support:matrix.org",
        )
        second = await service.process_matrix_answer(
            event_id="$matrix_event_123:matrix.org",  # Same event ID
            staff_answer="Answer text",
            reply_to_event_id="$question_456:matrix.org",
            question_text="Question text",
            staff_sender="@support:matrix.org",
        )

        # Assert
        assert first is not None
        assert first.candidate_id is not None
        # Second returns a result indicating skip (not None)
        assert second is not None
        assert second.skipped_reason == "duplicate"
        assert second.candidate_id is None


# =============================================================================
# TASK 2.4: Routing Logic
# =============================================================================


class TestRoutingLogic:
    """Test score-based routing logic."""

    @pytest_asyncio.fixture
    async def service_with_mock_comparison(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create service with mockable comparison engine."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        # We'll patch the comparison engine per test
        return service

    @pytest.mark.asyncio
    async def test_routing_auto_approve_for_high_score(
        self, service_with_mock_comparison
    ):
        """Cycle 2.4.1: Test high score routes to AUTO_APPROVE."""
        service = service_with_mock_comparison

        # Mock comparison to return high score
        with patch.object(service, "comparison_engine") as mock_engine:
            mock_engine.compare = AsyncMock(
                return_value=MagicMock(
                    final_score=0.95,
                    embedding_similarity=0.95,
                    factual_alignment=0.95,
                    contradiction_score=0.02,
                    completeness=0.95,
                    hallucination_risk=0.03,
                    llm_reasoning="Excellent alignment.",
                    is_calibration=False,
                )
            )
            # Set calibration to complete so AUTO_APPROVE works
            service.repository._init_database()
            conn = __import__("sqlite3").connect(service.repository.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE calibration_state SET calibration_complete = TRUE WHERE id = 1"
            )
            conn.commit()
            conn.close()

            # Act
            candidate = await service.process_matrix_answer(
                event_id="$high_score_event:matrix.org",
                staff_answer="Great answer",
                reply_to_event_id="$q:matrix.org",
                question_text="Question?",
                staff_sender="@staff:matrix.org",
            )

            # Assert
            assert candidate is not None
            assert candidate.routing == "AUTO_APPROVE"

    @pytest.mark.asyncio
    async def test_routing_spot_check_for_medium_score(
        self, service_with_mock_comparison
    ):
        """Cycle 2.4.2: Test medium score routes to SPOT_CHECK."""
        service = service_with_mock_comparison

        with patch.object(service, "comparison_engine") as mock_engine:
            mock_engine.compare = AsyncMock(
                return_value=MagicMock(
                    final_score=0.82,  # Medium score
                    embedding_similarity=0.80,
                    factual_alignment=0.85,
                    contradiction_score=0.10,
                    completeness=0.80,
                    hallucination_risk=0.12,
                    llm_reasoning="Good alignment.",
                    is_calibration=False,
                )
            )
            # Set calibration complete
            conn = __import__("sqlite3").connect(service.repository.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE calibration_state SET calibration_complete = TRUE WHERE id = 1"
            )
            conn.commit()
            conn.close()

            # Act
            candidate = await service.process_matrix_answer(
                event_id="$medium_score:matrix.org",
                staff_answer="Good answer",
                reply_to_event_id="$q:matrix.org",
                question_text="Question?",
                staff_sender="@staff:matrix.org",
            )

            # Assert
            assert candidate is not None
            assert candidate.routing == "SPOT_CHECK"

    @pytest.mark.asyncio
    async def test_routing_full_review_for_low_score(
        self, service_with_mock_comparison
    ):
        """Cycle 2.4.3: Test low score routes to FULL_REVIEW."""
        service = service_with_mock_comparison

        with patch.object(service, "comparison_engine") as mock_engine:
            mock_engine.compare = AsyncMock(
                return_value=MagicMock(
                    final_score=0.55,  # Low score
                    embedding_similarity=0.50,
                    factual_alignment=0.55,
                    contradiction_score=0.30,
                    completeness=0.50,
                    hallucination_risk=0.35,
                    llm_reasoning="Significant differences.",
                    is_calibration=False,
                )
            )
            # Set calibration complete
            conn = __import__("sqlite3").connect(service.repository.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE calibration_state SET calibration_complete = TRUE WHERE id = 1"
            )
            conn.commit()
            conn.close()

            # Act
            candidate = await service.process_matrix_answer(
                event_id="$low_score:matrix.org",
                staff_answer="Some answer",
                reply_to_event_id="$q:matrix.org",
                question_text="Question?",
                staff_sender="@staff:matrix.org",
            )

            # Assert
            assert candidate is not None
            assert candidate.routing == "FULL_REVIEW"


# =============================================================================
# TASK 2.5: Calibration Behavior
# =============================================================================


class TestCalibrationBehavior:
    """Test calibration mode behavior."""

    @pytest_asyncio.fixture
    async def service(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create a pipeline service instance."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_calibration_forces_full_review(self, service):
        """Cycle 2.5.1: Test calibration mode forces FULL_REVIEW for all scores."""
        # Calibration is active by default (samples_collected = 0)
        with patch.object(service, "comparison_engine") as mock_engine:
            mock_engine.compare = AsyncMock(
                return_value=MagicMock(
                    final_score=0.95,  # High score that would normally AUTO_APPROVE
                    embedding_similarity=0.95,
                    factual_alignment=0.95,
                    contradiction_score=0.02,
                    completeness=0.95,
                    hallucination_risk=0.03,
                    llm_reasoning="Excellent alignment.",
                    is_calibration=True,  # Marked as calibration sample
                )
            )

            # Act
            candidate = await service.process_matrix_answer(
                event_id="$calibration_test:matrix.org",
                staff_answer="Great answer",
                reply_to_event_id="$q:matrix.org",
                question_text="Question?",
                staff_sender="@staff:matrix.org",
            )

            # Assert - Should be FULL_REVIEW despite high score
            assert candidate is not None
            assert candidate.routing == "FULL_REVIEW"
            assert candidate.is_calibration_sample is True

    @pytest.mark.asyncio
    async def test_auto_approve_after_calibration_complete(self, service):
        """Cycle 2.5.2: Test AUTO_APPROVE works after calibration is complete."""
        # Complete calibration
        conn = __import__("sqlite3").connect(service.repository.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE calibration_state SET samples_collected = 100, calibration_complete = TRUE WHERE id = 1"
        )
        conn.commit()
        conn.close()

        with patch.object(service, "comparison_engine") as mock_engine:
            mock_engine.compare = AsyncMock(
                return_value=MagicMock(
                    final_score=0.95,
                    embedding_similarity=0.95,
                    factual_alignment=0.95,
                    contradiction_score=0.02,
                    completeness=0.95,
                    hallucination_risk=0.03,
                    llm_reasoning="Excellent alignment.",
                    is_calibration=False,  # NOT a calibration sample
                )
            )

            # Act
            candidate = await service.process_matrix_answer(
                event_id="$post_calibration:matrix.org",
                staff_answer="Great answer",
                reply_to_event_id="$q:matrix.org",
                question_text="Question?",
                staff_sender="@staff:matrix.org",
            )

            # Assert - Should be AUTO_APPROVE now
            assert candidate is not None
            assert candidate.routing == "AUTO_APPROVE"


# =============================================================================
# TASK 2.6: Review Actions (with source preservation and auto-verification)
# =============================================================================


class TestReviewActions:
    """Test approve and reject operations."""

    @pytest_asyncio.fixture
    async def service_with_candidate(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create service with a pending candidate."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        # Create a candidate directly in repository
        candidate = service.repository.create(
            source="matrix",
            source_event_id="$review_test:matrix.org",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="How do I trade?",
            staff_answer="Go to Trade Wizard.",
            routing="FULL_REVIEW",
        )

        return service, candidate

    @pytest.mark.asyncio
    async def test_approve_candidate_creates_verified_faq(
        self, service_with_candidate, mock_faq_service
    ):
        """Cycle 2.6.1: Test approve creates FAQ with source preservation and verification."""
        service, candidate = service_with_candidate

        # Act
        faq_id = await service.approve_candidate(candidate.id, reviewer="admin")

        # Assert - Check FAQ service was called with FAQItem
        mock_faq_service.add_faq.assert_called_once()
        # add_faq is called with FAQItem as positional argument
        call_args = mock_faq_service.add_faq.call_args
        faq_item = call_args[0][0]  # First positional argument

        # Verify human-readable source name
        assert faq_item.source == "Matrix Support"

        # Verify auto-verification (pipeline approval = admin verification)
        assert faq_item.verified is True
        assert faq_item.verified_at is not None

        # Verify FAQ ID returned
        assert faq_id == "faq_test_123"

    @pytest.mark.asyncio
    async def test_approve_preserves_bisq2_source(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Cycle 2.6.1: Test approve uses human-readable source for bisq2."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        # Create bisq2 candidate
        candidate = service.repository.create(
            source="bisq2",
            source_event_id="bisq_msg_123",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="Bisq question",
            staff_answer="Bisq answer",
            routing="FULL_REVIEW",
        )

        # Act
        await service.approve_candidate(candidate.id, reviewer="admin")

        # Assert - add_faq is called with FAQItem as positional argument
        call_args = mock_faq_service.add_faq.call_args
        faq_item = call_args[0][0]  # First positional argument
        # Source should be human-readable, not "Extracted:bisq2"
        assert faq_item.source == "Bisq Support Chat"
        assert faq_item.verified is True

    @pytest.mark.asyncio
    async def test_approve_preserves_matrix_source(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Test approve uses human-readable source for matrix."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        # Create matrix candidate
        candidate = service.repository.create(
            source="matrix",
            source_event_id="$matrix_msg_123",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="Matrix question",
            staff_answer="Matrix answer",
            routing="FULL_REVIEW",
        )

        # Act
        await service.approve_candidate(candidate.id, reviewer="admin")

        # Assert - add_faq is called with FAQItem as positional argument
        call_args = mock_faq_service.add_faq.call_args
        faq_item = call_args[0][0]  # First positional argument
        # Source should be human-readable, not "Extracted:matrix"
        assert faq_item.source == "Matrix Support"
        assert faq_item.verified is True

    def test_source_display_name_helper_function(self):
        """Test get_faq_source_display_name helper function."""
        from app.services.training.unified_pipeline_service import (
            get_faq_source_display_name,
        )

        # Known sources return human-readable names
        assert get_faq_source_display_name("bisq2") == "Bisq Support Chat"
        assert get_faq_source_display_name("matrix") == "Matrix Support"

        # Unknown sources fall back to "Extracted:source" format
        # (Database CHECK constraint prevents unknown sources, but function handles it)
        assert get_faq_source_display_name("telegram") == "Extracted:telegram"
        assert get_faq_source_display_name("unknown") == "Extracted:unknown"

    @pytest.mark.asyncio
    async def test_reject_candidate_updates_status(self, service_with_candidate):
        """Cycle 2.6.2: Test reject updates candidate status."""
        service, candidate = service_with_candidate

        # Act
        result = await service.reject_candidate(
            candidate.id, reviewer="admin", reason="Incorrect information"
        )

        # Assert
        assert result is True
        updated = service.repository.get_by_id(candidate.id)
        assert updated.review_status == "rejected"
        assert updated.rejection_reason == "Incorrect information"

    @pytest.mark.asyncio
    async def test_approve_blocks_on_duplicate_faq(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """TASK 7.1: Test approve blocks when similar FAQ already exists."""
        # Set up RAG service to return similar FAQs (simulating existing duplicates)
        mock_rag_service.search_faq_similarity = AsyncMock(
            return_value=[
                {
                    "id": 42,
                    "question": "How do I start trading on Bisq Easy?",
                    "answer": "Navigate to Trade > Trade Wizard...",
                    "similarity": 0.92,
                    "category": "Trading",
                }
            ]
        )

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        # Create a candidate
        candidate = service.repository.create(
            source="matrix",
            source_event_id="$duplicate_test:matrix.org",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="How do I trade on Bisq Easy?",
            staff_answer="Go to Trade Wizard.",
            routing="FULL_REVIEW",
        )

        # Act & Assert - Should raise DuplicateFAQError
        with pytest.raises(DuplicateFAQError) as exc_info:
            await service.approve_candidate(candidate.id, reviewer="admin")

        # Verify exception contains correct information
        error = exc_info.value
        assert error.candidate_id == candidate.id
        assert len(error.similar_faqs) == 1
        assert error.similar_faqs[0]["id"] == 42
        assert error.similar_faqs[0]["similarity"] == 0.92
        assert "similar faq" in str(error).lower()

        # Verify FAQ was NOT created
        mock_faq_service.add_faq.assert_not_called()

        # Verify candidate status unchanged (still pending)
        unchanged = service.repository.get_by_id(candidate.id)
        assert unchanged.review_status == "pending"

    @pytest.mark.asyncio
    async def test_approve_succeeds_when_no_duplicate(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """TASK 7.1: Test approve succeeds when no similar FAQ exists."""
        # Set up RAG service to return empty list (no duplicates)
        mock_rag_service.search_faq_similarity = AsyncMock(return_value=[])

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        # Create a candidate
        candidate = service.repository.create(
            source="bisq2",
            source_event_id="unique_msg_123",
            source_timestamp="2025-01-15T10:00:00Z",
            question_text="A completely unique question?",
            staff_answer="A unique answer.",
            routing="FULL_REVIEW",
        )

        # Act - Should succeed
        faq_id = await service.approve_candidate(candidate.id, reviewer="admin")

        # Assert
        assert faq_id == "faq_test_123"
        mock_faq_service.add_faq.assert_called_once()


# =============================================================================
# TASK 2.7: Query Methods with Source Filtering
# =============================================================================


class TestQueryMethods:
    """Test query methods with source filtering."""

    @pytest_asyncio.fixture
    async def service_with_mixed_candidates(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create service with candidates from both sources."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        # Create mixed candidates
        for i in range(2):
            service.repository.create(
                source="bisq2",
                source_event_id=f"bisq_{i}",
                source_timestamp="2025-01-15T10:00:00Z",
                question_text=f"Bisq question {i}",
                staff_answer=f"Bisq answer {i}",
                routing="FULL_REVIEW",
            )

        for i in range(2):
            service.repository.create(
                source="matrix",
                source_event_id=f"$matrix_{i}:matrix.org",
                source_timestamp="2025-01-15T10:00:00Z",
                question_text=f"Matrix question {i}",
                staff_answer=f"Matrix answer {i}",
                routing="SPOT_CHECK",
            )

        return service

    @pytest.mark.asyncio
    async def test_get_pending_reviews_with_source_filter(
        self, service_with_mixed_candidates
    ):
        """Cycle 2.7.1: Test get_pending_reviews filters by source."""
        service = service_with_mixed_candidates

        # Act (synchronous methods)
        bisq_pending = service.get_pending_reviews(source="bisq2")
        matrix_pending = service.get_pending_reviews(source="matrix")

        # Assert
        assert len(bisq_pending) == 2
        assert len(matrix_pending) == 2
        assert all(c.source == "bisq2" for c in bisq_pending)
        assert all(c.source == "matrix" for c in matrix_pending)

    @pytest.mark.asyncio
    async def test_get_current_item_with_source_filter(
        self, service_with_mixed_candidates
    ):
        """Cycle 2.7.2: Test get_current_item filters by source."""
        service = service_with_mixed_candidates

        # Act (synchronous methods)
        current_matrix = service.get_current_item(routing="SPOT_CHECK", source="matrix")
        current_bisq = service.get_current_item(routing="FULL_REVIEW", source="bisq2")

        # Assert
        assert current_matrix is not None
        assert current_matrix.source == "matrix"
        assert current_bisq is not None
        assert current_bisq.source == "bisq2"

    @pytest.mark.asyncio
    async def test_get_queue_counts_with_source_filter(
        self, service_with_mixed_candidates
    ):
        """Cycle 2.7.3: Test get_queue_counts filters by source."""
        service = service_with_mixed_candidates

        # Act (synchronous methods)
        all_counts = service.get_queue_counts(source=None)
        bisq_counts = service.get_queue_counts(source="bisq2")
        matrix_counts = service.get_queue_counts(source="matrix")

        # Assert
        assert all_counts["FULL_REVIEW"] == 2  # 2 bisq2
        assert all_counts["SPOT_CHECK"] == 2  # 2 matrix
        assert bisq_counts["FULL_REVIEW"] == 2
        assert bisq_counts["SPOT_CHECK"] == 0
        assert matrix_counts["FULL_REVIEW"] == 0
        assert matrix_counts["SPOT_CHECK"] == 2

    @pytest.mark.asyncio
    async def test_get_calibration_status(self, service_with_mixed_candidates):
        """Test get_calibration_status returns proper status."""
        service = service_with_mixed_candidates

        # Act (synchronous method)
        status = service.get_calibration_status()

        # Assert
        assert isinstance(status, CalibrationStatus)
        assert status.samples_required == 100
        assert status.is_complete is False


# =============================================================================
# BUG FIX TESTS: Empty Generated Answer Handling
# =============================================================================


class TestEmptyGeneratedAnswerHandling:
    """Test that empty RAG answers are handled correctly, not given fake 'good' scores."""

    @pytest_asyncio.fixture
    async def service_with_empty_rag(
        self, temp_db_path, mock_settings, mock_faq_service
    ):
        """Create service where RAG returns empty response."""
        mock_rag = MagicMock()
        mock_rag.query = AsyncMock(
            return_value={
                "response": "",  # Empty response!
                "sources": [],
            }
        )
        mock_rag.search_faq_similarity = AsyncMock(return_value=[])

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_empty_generated_answer_routes_to_full_review(
        self, service_with_empty_rag
    ):
        """BUG FIX: Empty generated answer should route to FULL_REVIEW, not fake 'good' scores."""
        service = service_with_empty_rag

        # Act - Process a Matrix answer when RAG returns empty
        result = await service.process_matrix_answer(
            event_id="$empty_rag_test:matrix.org",
            staff_answer="This is a proper staff answer with useful information.",
            reply_to_event_id="$question:matrix.org",
            question_text="How do I start trading?",
            staff_sender="@staff:matrix.org",
        )

        # Assert - Should NOT get fake "good" scores
        assert result is not None
        assert result.routing == "FULL_REVIEW"

        # Verify the candidate was created with appropriate reasoning
        candidate = service.repository.get_by_id(result.candidate_id)
        assert candidate is not None
        # Should indicate RAG failed, not "Good alignment"
        assert "good alignment" not in candidate.llm_reasoning.lower()

    @pytest.mark.asyncio
    async def test_empty_generated_answer_has_low_score(self, service_with_empty_rag):
        """BUG FIX: Empty generated answer should have low final_score, not 0.85."""
        service = service_with_empty_rag

        result = await service.process_matrix_answer(
            event_id="$low_score_test:matrix.org",
            staff_answer="Detailed answer about Bisq trading.",
            reply_to_event_id="$q:matrix.org",
            question_text="Question?",
            staff_sender="@staff:matrix.org",
        )

        # Assert - Score should be low (not the fake 0.85)
        assert result is not None
        assert result.final_score < 0.5  # Should be low, not 0.85

    @pytest.mark.asyncio
    async def test_bisq_conversation_with_empty_rag_routes_correctly(
        self, service_with_empty_rag
    ):
        """BUG FIX: Bisq conversation with empty RAG should also route to FULL_REVIEW."""
        service = service_with_empty_rag

        conversation = {
            "thread_id": "empty-rag-thread",
            "messages": [
                {
                    "messageId": "q1",
                    "message": "How do I verify my payment account?",
                    "author": "user123",
                    "date": "2025-01-15T10:00:00Z",
                },
                {
                    "messageId": "a1",
                    "message": "Go to Account > Payment Accounts and click verify.",
                    "author": "suddenwhipvapor",
                    "date": "2025-01-15T10:05:00Z",
                },
            ],
        }

        result = await service.process_bisq_conversation(conversation)

        # Assert - Should route to FULL_REVIEW due to empty RAG answer
        assert result is not None
        assert result.routing == "FULL_REVIEW"
        assert result.final_score < 0.5


# =============================================================================
# BUG FIX TESTS: Comparison Engine Required
# =============================================================================


class TestComparisonEngineRequired:
    """Test that comparison_engine is properly used when provided."""

    @pytest_asyncio.fixture
    async def service_with_comparison_engine(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create service WITH a real comparison engine mock."""
        mock_comparison = MagicMock()
        mock_comparison.compare = AsyncMock(
            return_value=MagicMock(
                embedding_similarity=0.75,
                factual_alignment=0.70,
                contradiction_score=0.15,
                completeness=0.65,
                hallucination_risk=0.20,
                final_score=0.72,
                llm_reasoning="Moderate alignment with some differences.",
            )
        )

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
            comparison_engine=mock_comparison,
        )
        return service, mock_comparison

    @pytest.mark.asyncio
    async def test_comparison_engine_is_called_when_provided(
        self, service_with_comparison_engine
    ):
        """Test that comparison_engine.compare() is actually called."""
        service, mock_comparison = service_with_comparison_engine

        await service.process_matrix_answer(
            event_id="$comparison_test:matrix.org",
            staff_answer="Staff answer",
            reply_to_event_id="$q:matrix.org",
            question_text="Question?",
            staff_sender="@staff:matrix.org",
        )

        # Assert - comparison engine should have been called
        mock_comparison.compare.assert_called_once()

    @pytest.mark.asyncio
    async def test_comparison_engine_scores_are_used(
        self, service_with_comparison_engine
    ):
        """Test that scores from comparison_engine are used, not hardcoded values."""
        service, mock_comparison = service_with_comparison_engine

        result = await service.process_matrix_answer(
            event_id="$score_test:matrix.org",
            staff_answer="Staff answer",
            reply_to_event_id="$q:matrix.org",
            question_text="Question?",
            staff_sender="@staff:matrix.org",
        )

        # Assert - Should use the comparison engine's score (0.72), not hardcoded 0.85
        assert result is not None
        assert result.final_score == 0.72  # From mock, not 0.85


# =============================================================================
# REMOVED: Bisq 2 Citation-Based Q&A Extraction Tests
# =============================================================================
# These tests were for the OLD citation-based extraction approach.
# The new architecture uses LLM-based extraction via UnifiedFAQExtractor,
# which doesn't rely on citation fields. Q&A extraction is now done by
# sending all messages to the LLM for intelligent extraction.
#
# See test_unified_faq_extractor.py for LLM extraction tests.
# =============================================================================


# =============================================================================
# BUG FIX TESTS: RAG Response Key Mismatch
# Issue: Pipeline uses rag_response.get("response", "") but RAG returns {"answer": ...}
# =============================================================================


# =============================================================================
# TASK: Protocol Detection in Pipeline (TDD Step 3)
# =============================================================================


class TestPipelineProtocolDetection:
    """Test that pipeline uses ProtocolDetector for direct protocol detection.

    TDD Step 3: RED - These tests should FAIL until pipeline is refactored
    to use ProtocolDetector.detect_protocol_from_text() directly.
    """

    @pytest_asyncio.fixture
    async def service(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create a pipeline service instance."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    def test_pipeline_has_protocol_detector(self, service):
        """Pipeline should have protocol_detector attribute."""
        assert hasattr(service, "protocol_detector")
        from app.services.rag.protocol_detector import ProtocolDetector

        assert isinstance(service.protocol_detector, ProtocolDetector)

    def test_detect_protocol_with_fallback_exists(self, service):
        """Pipeline should have _detect_protocol_with_fallback method."""
        assert hasattr(service, "_detect_protocol_with_fallback")
        assert callable(service._detect_protocol_with_fallback)

    def test_detect_protocol_with_fallback_from_question(self, service):
        """Should detect protocol from question text (Bisq 1 DAO keyword)."""
        protocol = service._detect_protocol_with_fallback(
            "How does DAO voting work?",  # Bisq 1 keyword
            "You can vote in the DAO by...",
        )
        assert protocol == "multisig_v1"

    def test_detect_protocol_with_fallback_bisq2(self, service):
        """Should detect protocol from question text (Bisq 2 keyword)."""
        protocol = service._detect_protocol_with_fallback(
            "How does reputation work in Bisq Easy?",  # Bisq 2 keyword
            "Reputation is built by...",
        )
        assert protocol == "bisq_easy"

    def test_detect_protocol_with_fallback_from_answer(self, service):
        """Should fallback to staff answer for detection."""
        protocol = service._detect_protocol_with_fallback(
            "How do I trade?",  # No clear indicator
            "In Bisq Easy, you can navigate to Trade Wizard...",  # Bisq 2 keyword in answer
        )
        assert protocol == "bisq_easy"

    def test_detect_protocol_with_fallback_unknown(self, service):
        """Should return None when protocol cannot be determined."""
        protocol = service._detect_protocol_with_fallback(
            "Hello there", "Hi, how can I help?"  # No indicators  # No indicators
        )
        assert protocol is None

    @pytest.mark.asyncio
    async def test_process_matrix_answer_stores_protocol(self, service):
        """Protocol should be stored directly without version conversion."""
        # Complete calibration so we get consistent routing
        conn = __import__("sqlite3").connect(service.repository.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE calibration_state SET samples_collected = 100, calibration_complete = TRUE WHERE id = 1"
        )
        conn.commit()
        conn.close()

        result = await service.process_matrix_answer(
            event_id="$protocol_test:matrix.org",
            staff_answer="Use the DAO voting page to cast your vote with BSQ.",
            reply_to_event_id="$q:matrix.org",
            question_text="How do I vote in the DAO?",  # Bisq 1 keyword
            staff_sender="@staff:matrix.org",
        )

        candidate = service.repository.get_by_id(result.candidate_id)
        assert candidate.protocol == "multisig_v1"

    @pytest.mark.asyncio
    async def test_process_matrix_answer_stores_bisq_easy_protocol(self, service):
        """Bisq Easy questions should store bisq_easy protocol."""
        result = await service.process_matrix_answer(
            event_id="$bisq_easy_protocol:matrix.org",
            staff_answer="To build reputation in Bisq Easy, you need to...",
            reply_to_event_id="$q:matrix.org",
            question_text="How does reputation work?",  # Bisq 2 keyword
            staff_sender="@staff:matrix.org",
        )

        candidate = service.repository.get_by_id(result.candidate_id)
        assert candidate.protocol == "bisq_easy"

    @pytest.mark.asyncio
    async def test_process_bisq_conversation_stores_protocol(
        self, service, sample_bisq_conversation
    ):
        """Bisq conversation processing should store correct protocol."""
        result = await service.process_bisq_conversation(sample_bisq_conversation)

        candidate = service.repository.get_by_id(result.candidate_id)
        # The sample conversation mentions "Bisq Easy" and trade limits
        assert candidate.protocol == "bisq_easy"


class TestRAGResponseKeyMismatch:
    """Test that the pipeline correctly extracts answers from RAG service responses.

    BUG DESCRIPTION:
    - The SimplifiedRAGService.query() returns {"answer": "...", "sources": [...], ...}
    - The UnifiedPipelineService was using rag_response.get("response", "")
    - This caused generated_answer to always be empty string
    - Result: All candidates had empty RAG answers and 0.0 final scores

    This test class verifies the fix by using mocks that match the ACTUAL
    RAG service response format (with "answer" key, not "response").
    """

    @pytest_asyncio.fixture
    async def service_with_real_rag_format(
        self, temp_db_path, mock_settings, mock_faq_service
    ):
        """Create service with RAG mock using ACTUAL response format.

        The real SimplifiedRAGService.query() returns:
        {
            "answer": "...",      # NOT "response"!
            "sources": [...],
            "response_time": ...,
            ...
        }
        """
        mock_rag = MagicMock()
        # Use the ACTUAL key name from SimplifiedRAGService
        mock_rag.query = AsyncMock(
            return_value={
                "answer": "To trade on Bisq Easy, navigate to Trade > Trade Wizard.",
                "sources": [{"type": "wiki", "title": "Bisq Easy Guide"}],
                "response_time": 0.5,
            }
        )
        mock_rag.search_faq_similarity = AsyncMock(return_value=[])

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_pipeline_extracts_answer_from_correct_key(
        self, service_with_real_rag_format
    ):
        """BUG FIX: Pipeline should extract answer using 'answer' key, not 'response'.

        Before fix: generated_answer was always "" because wrong key was used
        After fix: generated_answer contains the actual RAG response
        """
        service = service_with_real_rag_format

        result = await service.process_matrix_answer(
            event_id="$key_mismatch_test:matrix.org",
            staff_answer="Go to Trade Wizard to start trading on Bisq Easy.",
            reply_to_event_id="$q:matrix.org",
            question_text="How do I trade on Bisq?",
            staff_sender="@staff:matrix.org",
        )

        # Get the candidate to check generated_answer
        candidate = service.repository.get_by_id(result.candidate_id)

        # CRITICAL ASSERTION: generated_answer should NOT be empty
        assert candidate.generated_answer is not None
        assert candidate.generated_answer != ""
        assert "Trade Wizard" in candidate.generated_answer

    @pytest.mark.asyncio
    async def test_non_empty_rag_answer_allows_comparison(
        self, service_with_real_rag_format
    ):
        """BUG FIX: When RAG returns valid answer, comparison should produce real scores.

        Before fix: final_score was always 0.0 because generated_answer was empty
        After fix: final_score reflects actual comparison (mock returns 0.50 without engine)
        """
        service = service_with_real_rag_format

        result = await service.process_matrix_answer(
            event_id="$comparison_possible:matrix.org",
            staff_answer="Navigate to Trade tab and select Trade Wizard.",
            reply_to_event_id="$q:matrix.org",
            question_text="How do I start trading?",
            staff_sender="@staff:matrix.org",
        )

        # Without comparison_engine, mock comparison returns 0.50 (not 0.0)
        # 0.0 would indicate the empty-answer path was taken
        assert result.final_score > 0.0
        # Mock comparison returns 0.50 when no comparison_engine is set
        assert result.final_score == 0.50

        # LLM reasoning should NOT say "RAG system returned empty response"
        candidate = service.repository.get_by_id(result.candidate_id)
        assert "empty response" not in candidate.llm_reasoning.lower()

    @pytest.mark.asyncio
    async def test_bisq_conversation_extracts_answer_correctly(
        self, service_with_real_rag_format
    ):
        """BUG FIX: Bisq conversation processing should also use correct key."""
        service = service_with_real_rag_format

        conversation = {
            "thread_id": "key-fix-test",
            "messages": [
                {
                    "messageId": "q1",
                    "message": "What is the trade limit?",
                    "author": "user456",
                    "date": "2025-01-15T10:00:00Z",
                },
                {
                    "messageId": "a1",
                    "message": "The trade limit is $600 for new users.",
                    "author": "suddenwhipvapor",
                    "date": "2025-01-15T10:05:00Z",
                },
            ],
        }

        result = await service.process_bisq_conversation(conversation)

        # Verify RAG answer was properly extracted
        candidate = service.repository.get_by_id(result.candidate_id)
        assert candidate.generated_answer is not None
        assert candidate.generated_answer != ""
        assert result.final_score > 0.0


# =============================================================================
# BUG FIX TESTS: original_staff_answer and staff_sender Propagation
# =============================================================================


class TestOriginalStaffAnswerPropagation:
    """Test that original_staff_answer is properly passed through the pipeline.

    BUG: _process_extracted_faq() doesn't pass original_staff_answer to repository.create()
    FIX: Add original_staff_answer parameter and pass it through

    Related: EditableAnswer.tsx shows "View Original Staff Answer" collapsible only when
    originalAnswer && originalAnswer !== displayAnswer
    """

    @pytest_asyncio.fixture
    async def service_with_mock_extractor(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create service for testing extract_faqs_batch."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_extract_faqs_batch_propagates_original_staff_answer(
        self, service_with_mock_extractor, mock_settings
    ):
        """BUG FIX: original_staff_answer from extractor should be stored in candidate.

        The extractor outputs 'original_staff_answer' in to_pipeline_format(),
        but _process_extracted_faq() was not passing it to repository.create().
        """
        service = service_with_mock_extractor

        # Sample messages with conversational staff answer
        messages = [
            {
                "messageId": "q1",
                "message": "How do I trade on Bisq?",
                "author": "user123",
                "date": "2025-01-20T10:00:00Z",
            },
            {
                "messageId": "a1",
                "message": "Hey! Yeah, so you want to go to the Trade tab and click on Trade Wizard. That'll get you started. Let me know if you need more help!",
                "author": "suddenwhipvapor",  # Staff user matching mock_settings
                "date": "2025-01-20T10:05:00Z",
            },
        ]

        # Mock the extractor to return a known original_staff_answer
        # Note: We patch in unified_faq_extractor module, then the import inside extract_faqs_batch uses it
        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "How do I trade on Bisq?",
                    "staff_answer": "Navigate to the Trade tab and click Trade Wizard.",  # LLM transformed
                    "source": "bisq2",
                    "source_event_id": "a1",
                    "staff_sender": "suddenwhipvapor",
                    "category": "Trading",
                    "original_staff_answer": "Hey! Yeah, so you want to go to the Trade tab and click on Trade Wizard. That'll get you started. Let me know if you need more help!",  # Original conversational
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=messages,
                source="bisq2",
                staff_identifiers=["suddenwhipvapor"],
            )

        # Assert - Should have created a candidate
        assert len(results) == 1
        result = results[0]
        assert result.candidate_id is not None

        # CRITICAL: original_staff_answer should be stored in the candidate
        candidate = service.repository.get_by_id(result.candidate_id)
        assert candidate is not None
        assert candidate.original_staff_answer is not None, (
            "original_staff_answer should be set but was None - "
            "_process_extracted_faq() needs to pass this to repository.create()"
        )
        assert (
            "Hey! Yeah, so you want to go to the Trade tab"
            in candidate.original_staff_answer
        ), "original_staff_answer should contain the conversational text"

        # Verify staff_answer contains the LLM-transformed version
        assert "Navigate to the Trade tab" in candidate.staff_answer

    @pytest.mark.asyncio
    async def test_original_staff_answer_differs_from_staff_answer(
        self, service_with_mock_extractor
    ):
        """BUG FIX: Verify original differs from transformed (enables UI collapsible).

        EditableAnswer.tsx shows "View Original Staff Answer" only when:
        originalAnswer && originalAnswer !== displayAnswer
        """
        service = service_with_mock_extractor

        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "What is the trade limit?",
                    "staff_answer": "The trade limit is $600 for new users.",  # Clean
                    "source": "matrix",
                    "source_event_id": "$answer:matrix.org",
                    "staff_sender": "@mod:matrix.org",
                    "category": "Trading",
                    "original_staff_answer": "oh hey the trade limit is like $600 for new users I think, let me check... yeah $600",  # Conversational
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=[],  # Messages don't matter with mocked extractor
                source="matrix",
                staff_identifiers=["@mod:matrix.org"],
            )

        assert len(results) == 1
        candidate = service.repository.get_by_id(results[0].candidate_id)

        # Both fields should exist
        assert candidate.staff_answer is not None
        assert candidate.original_staff_answer is not None

        # They should be different (LLM transformation happened)
        assert candidate.staff_answer != candidate.original_staff_answer, (
            "staff_answer and original_staff_answer should differ "
            "(LLM transformation vs original conversational)"
        )


class TestStaffSenderExtraction:
    """Test that staff_sender is properly extracted and stored.

    BUG: staff_sender was empty string for most candidates because:
    1. Field name inconsistencies (id vs messageId, author vs sender)
    2. Message ID lookup failing due to mismatched keys
    """

    @pytest_asyncio.fixture
    async def service_for_staff_sender(
        self, temp_db_path, mock_settings, mock_rag_service, mock_faq_service
    ):
        """Create service for testing staff_sender extraction."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_extract_faqs_batch_stores_staff_sender(
        self, service_for_staff_sender
    ):
        """BUG FIX: staff_sender from extractor should be stored in candidate."""
        service = service_for_staff_sender

        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "How do I start trading?",
                    "staff_answer": "Go to Trade > Trade Wizard.",
                    "source": "matrix",
                    "source_event_id": "$evt:matrix.org",
                    "staff_sender": "@helpful_mod:matrix.org",  # Staff sender
                    "category": "Trading",
                    "original_staff_answer": "Go to Trade > Trade Wizard.",
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=[],
                source="matrix",
                staff_identifiers=["@helpful_mod:matrix.org"],
            )

        assert len(results) == 1
        candidate = service.repository.get_by_id(results[0].candidate_id)

        # CRITICAL: staff_sender should be stored
        assert candidate.staff_sender is not None, "staff_sender should not be None"
        assert candidate.staff_sender != "", (
            "staff_sender should not be empty - "
            "it should contain '@helpful_mod:matrix.org'"
        )
        assert candidate.staff_sender == "@helpful_mod:matrix.org"

    @pytest.mark.asyncio
    async def test_bisq_staff_sender_from_author_field(self, service_for_staff_sender):
        """BUG FIX: Bisq messages use 'author' field, should be mapped correctly."""
        service = service_for_staff_sender

        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "What payment methods are supported?",
                    "staff_answer": "SEPA, Zelle, Strike, and many others.",
                    "source": "bisq2",
                    "source_event_id": "msg_12345",
                    "staff_sender": "suddenwhipvapor",  # Bisq username
                    "category": "Payments",
                    "original_staff_answer": "SEPA, Zelle, Strike, and many others.",
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=[],
                source="bisq2",
                staff_identifiers=["suddenwhipvapor"],
            )

        assert len(results) == 1
        candidate = service.repository.get_by_id(results[0].candidate_id)

        assert (
            candidate.staff_sender == "suddenwhipvapor"
        ), f"Expected 'suddenwhipvapor' but got '{candidate.staff_sender}'"


# =============================================================================
# CYCLE 2: Generation Confidence Capture
# =============================================================================


class TestGenerationConfidenceCapture:
    """Test that pipeline captures generation_confidence from RAG service.

    Key insight: generation_confidence (RAG's own confidence) is DIFFERENT from
    final_score (comparison between staff and RAG answers).
    """

    @pytest_asyncio.fixture
    async def service_with_confidence(
        self, temp_db_path, mock_settings, mock_faq_service
    ):
        """Create a pipeline service with RAG returning confidence."""
        mock_rag = MagicMock()
        mock_rag.query = AsyncMock(
            return_value={
                "answer": "Test answer from RAG",
                "sources": [{"type": "wiki", "title": "Test Doc"}],
                "confidence": 0.82,  # RAG confidence
                "response_time": 0.3,
            }
        )
        mock_rag.setup = AsyncMock()
        mock_rag.search_faq_similarity = AsyncMock(return_value=[])

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )
        return service

    @pytest.mark.asyncio
    async def test_pipeline_captures_generation_confidence(
        self, service_with_confidence
    ):
        """Test pipeline extracts confidence from RAG response."""
        service = service_with_confidence

        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "How does confidence scoring work?",
                    "staff_answer": "RAG confidence measures how confident RAG is.",
                    "source": "bisq2",
                    "source_event_id": "conf_capture_test",
                    "staff_sender": "staff_user",
                    "category": "General",
                    "original_staff_answer": "RAG confidence measures how confident RAG is.",
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=[],
                source="bisq2",
                staff_identifiers=["staff_user"],
            )

        assert len(results) == 1
        candidate = service.repository.get_by_id(results[0].candidate_id)

        # CRITICAL: generation_confidence should come from RAG, not comparison
        assert candidate.generation_confidence == 0.82

    @pytest.mark.asyncio
    async def test_generation_confidence_differs_from_final_score(
        self, temp_db_path, mock_settings, mock_faq_service
    ):
        """Test that generation_confidence and final_score are independent."""
        # Set up RAG with 0.82 confidence
        mock_rag = MagicMock()
        mock_rag.query = AsyncMock(
            return_value={
                "answer": "Test answer",
                "sources": [],
                "confidence": 0.82,  # RAG confidence
            }
        )
        mock_rag.setup = AsyncMock()
        mock_rag.search_faq_similarity = AsyncMock(return_value=[])

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "Test question",
                    "staff_answer": "Test staff answer",
                    "source": "bisq2",
                    "source_event_id": "conf_vs_score_test",
                    "staff_sender": "staff",
                    "category": "General",
                    "original_staff_answer": "Test staff answer",
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=[],
                source="bisq2",
                staff_identifiers=["staff"],
            )

        candidate = service.repository.get_by_id(results[0].candidate_id)

        # generation_confidence from RAG (0.82)
        # final_score from comparison (should be different - set by comparison engine)
        assert candidate.generation_confidence == 0.82
        # final_score comes from comparison, will be different (0.92 from mock)
        assert candidate.final_score != candidate.generation_confidence

    @pytest.mark.asyncio
    async def test_generation_confidence_null_when_rag_doesnt_return_it(
        self, temp_db_path, mock_settings, mock_faq_service
    ):
        """Test backward compatibility when RAG doesn't return confidence."""
        # Set up RAG without confidence field
        mock_rag = MagicMock()
        mock_rag.query = AsyncMock(
            return_value={
                "answer": "Test answer without confidence",
                "sources": [],
                # NO confidence field
            }
        )
        mock_rag.setup = AsyncMock()
        mock_rag.search_faq_similarity = AsyncMock(return_value=[])

        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
        )

        with patch(
            "app.services.training.unified_faq_extractor.UnifiedFAQExtractor"
        ) as MockExtractor:
            mock_extractor_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.extracted_count = 1
            mock_result.to_pipeline_format.return_value = [
                {
                    "question_text": "Test question",
                    "staff_answer": "Test staff answer",
                    "source": "bisq2",
                    "source_event_id": "no_conf_test",
                    "staff_sender": "staff",
                    "category": "General",
                    "original_staff_answer": "Test staff answer",
                }
            ]
            mock_extractor_instance.extract_faqs = AsyncMock(return_value=mock_result)
            MockExtractor.return_value = mock_extractor_instance

            results = await service.extract_faqs_batch(
                messages=[],
                source="bisq2",
                staff_identifiers=["staff"],
            )

        candidate = service.repository.get_by_id(results[0].candidate_id)

        # Should be None when RAG doesn't provide confidence
        assert candidate.generation_confidence is None


# =============================================================================
# PHASE 2 CYCLE 12: Pipeline Integration with Threads
# =============================================================================


class TestPipelineThreadIntegration:
    """Test conversation thread integration with pipeline processing.

    Cycle 12: Pipeline creates threads before candidates and links them properly.
    This enables multi-poll conversation handling where questions and answers
    may arrive in separate polling intervals.
    """

    @pytest_asyncio.fixture
    async def service(
        self,
        temp_db_path,
        mock_settings,
        mock_rag_service,
        mock_faq_service,
        mock_comparison_engine,
    ):
        """Create a pipeline service instance with comparison engine."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
            comparison_engine=mock_comparison_engine,
        )
        return service

    @pytest.mark.asyncio
    async def test_process_matrix_creates_thread_with_candidate(self, service):
        """Test that processing a Matrix answer creates a thread linked to candidate.

        When processing a staff answer that replies to a question, the pipeline
        should create a conversation thread that tracks both messages.
        """
        result = await service.process_matrix_answer(
            event_id="$answer123",
            staff_answer="To start trading, go to Trade > Trade Wizard.",
            reply_to_event_id="$question123",
            question_text="How do I start a trade?",
            staff_sender="@staff:matrix.org",
            source_timestamp="2026-01-22T10:00:00Z",
        )

        assert result is not None
        assert result.candidate_id is not None

        # Verify thread was created and linked
        thread = service.repository.find_thread_by_message("$question123")
        assert thread is not None, "Thread should be created for the question"
        assert thread.source == "matrix"
        assert thread.first_question_id == "$question123"
        assert thread.candidate_id == result.candidate_id

        # Verify thread contains both messages
        messages = service.repository.get_thread_messages(thread.id)
        assert len(messages) == 2
        message_ids = {m.message_id for m in messages}
        assert "$question123" in message_ids
        assert "$answer123" in message_ids

    @pytest.mark.asyncio
    async def test_process_matrix_existing_thread_reuses_it(self, service):
        """Test that processing answer for existing thread reuses thread."""
        # First, create a thread for a question (simulating first poll)
        thread = service.repository.create_thread(
            source="matrix",
            first_question_id="$question_first",
            room_id="!room:matrix.org",
        )
        service.repository.add_message_to_thread(
            thread_id=thread.id,
            message_id="$question_first",
            message_type="question",
            content="What is Bisq Easy?",
            sender_id="@user:matrix.org",
            timestamp="2026-01-22T09:00:00Z",
        )

        # Now process the staff answer (simulating second poll)
        result = await service.process_matrix_answer(
            event_id="$answer_second",
            staff_answer="Bisq Easy is a simple trading mode for beginners.",
            reply_to_event_id="$question_first",
            question_text="What is Bisq Easy?",
            staff_sender="@staff:matrix.org",
            source_timestamp="2026-01-22T10:00:00Z",
        )

        assert result is not None

        # Should reuse existing thread, not create a new one
        found_thread = service.repository.find_thread_by_message("$question_first")
        assert found_thread is not None
        assert found_thread.id == thread.id

        # Thread should now have candidate linked
        updated_thread = service.repository.get_thread(thread.id)
        assert updated_thread.candidate_id == result.candidate_id

        # Thread should have both messages
        messages = service.repository.get_thread_messages(thread.id)
        assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_process_bisq_creates_thread_for_qa_pair(
        self, service, sample_bisq_conversation
    ):
        """Test that processing Bisq conversation creates threads for Q&A pairs."""
        result = await service.process_bisq_conversation(sample_bisq_conversation)

        assert result is not None
        assert result.candidate_id is not None

        # Verify thread was created
        # Thread should be findable by the question message ID
        thread = service.repository.find_thread_by_message("msg1")
        assert thread is not None, "Thread should be created for Bisq Q&A"
        assert thread.source == "bisq2"
        assert thread.candidate_id == result.candidate_id

    @pytest.mark.asyncio
    async def test_thread_state_transitions_on_processing(self, service):
        """Test that thread state transitions properly during processing."""
        result = await service.process_matrix_answer(
            event_id="$ans_state",
            staff_answer="Navigate to settings to configure that.",
            reply_to_event_id="$q_state",
            question_text="How do I configure settings?",
            staff_sender="@staff:matrix.org",
        )

        assert result is not None

        thread = service.repository.find_thread_by_message("$q_state")
        assert thread is not None

        # After processing with candidate, state should be candidate_created
        assert thread.state == "candidate_created"

        # Verify transition audit exists
        transitions = service.repository.get_thread_transitions(thread.id)
        assert len(transitions) >= 1

        # Should have transition to candidate_created (transitions are dicts)
        states = [t["to_state"] for t in transitions]
        assert "candidate_created" in states

    @pytest.mark.asyncio
    async def test_thread_closed_on_approve(
        self, service, mock_faq_service, mock_rag_service
    ):
        """Test that approving a candidate closes the thread.

        When a candidate is approved and an FAQ is created,
        the associated thread should transition to 'closed' state.
        """
        # Create candidate via pipeline
        result = await service.process_matrix_answer(
            event_id="$ans_close",
            staff_answer="Click the backup button to save your wallet.",
            reply_to_event_id="$q_close",
            question_text="How do I backup my wallet?",
            staff_sender="@staff:matrix.org",
        )

        assert result is not None
        assert result.candidate_id is not None

        # Approve the candidate
        faq_id = await service.approve_candidate(
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        assert faq_id is not None

        # Thread should now be closed
        thread = service.repository.find_thread_by_message("$q_close")
        assert thread is not None
        assert thread.state == "closed"
        assert thread.faq_id == faq_id

    @pytest.mark.asyncio
    async def test_duplicate_skip_does_not_create_thread(self, service):
        """Test that duplicate processing doesn't create redundant threads."""
        # Process first time - should create thread
        result1 = await service.process_matrix_answer(
            event_id="$dup_ans",
            staff_answer="Use the fee slider to adjust.",
            reply_to_event_id="$dup_q",
            question_text="How do I change the fee?",
            staff_sender="@staff:matrix.org",
        )

        assert result1 is not None
        assert result1.candidate_id is not None

        # Process same event again - should be skipped
        result2 = await service.process_matrix_answer(
            event_id="$dup_ans",
            staff_answer="Use the fee slider to adjust.",
            reply_to_event_id="$dup_q",
            question_text="How do I change the fee?",
            staff_sender="@staff:matrix.org",
        )

        # Second should be skipped (duplicate)
        assert result2 is not None
        assert result2.routing == "SKIPPED"
        assert result2.skipped_reason == "duplicate"

        # Should still only have one thread
        thread = service.repository.find_thread_by_message("$dup_q")
        assert thread is not None
        # Thread should have candidate from first processing
        assert thread.candidate_id == result1.candidate_id


class TestPipelinePreApprovalCorrections:
    """Test pre-approval correction handling.

    Cycle 13: Handle corrections that arrive before FAQ approval.
    When a staff member corrects their answer before the candidate is approved,
    the system should UPDATE the existing candidate rather than create a new one.
    """

    @pytest_asyncio.fixture
    async def service(
        self,
        temp_db_path,
        mock_settings,
        mock_rag_service,
        mock_faq_service,
        mock_comparison_engine,
    ):
        """Create a pipeline service instance with comparison engine."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
            comparison_engine=mock_comparison_engine,
        )
        return service

    @pytest.mark.asyncio
    async def test_correction_updates_existing_candidate(self, service):
        """Test that correction message updates existing candidate, doesn't create new.

        When a staff member sends a correction to an answer that's still pending review,
        the candidate should be UPDATED with the corrected answer, not duplicated.
        """
        # Create initial Q&A candidate
        result = await service.process_matrix_answer(
            event_id="$original_answer",
            staff_answer="The limit is 500 USD per trade.",
            reply_to_event_id="$question_correct",
            question_text="What's the trade limit?",
            staff_sender="@staff:matrix.org",
            source_timestamp="2026-01-22T10:00:00Z",
            room_id="!room:matrix.org",
        )

        assert result is not None
        assert result.candidate_id is not None
        original_candidate_id = result.candidate_id

        # Get original candidate to verify initial state
        original_candidate = service.repository.get_by_id(original_candidate_id)
        assert original_candidate.staff_answer == "The limit is 500 USD per trade."

        # Process a correction (reply to the same question)
        correction_result = await service.process_correction(
            event_id="$correction_msg",
            correction_content="Actually, the limit is 600 USD per trade, not 500.",
            reply_to_event_id="$question_correct",
            staff_sender="@staff:matrix.org",
            source_timestamp="2026-01-22T10:05:00Z",
        )

        assert correction_result is not None

        # Verify the correction was applied to the SAME candidate (no duplicate)
        # The candidate ID in the correction result should match the original
        assert (
            correction_result.candidate_id == original_candidate_id
        ), "Correction should update existing candidate, not create new"

        # The existing candidate should be updated with the correction
        updated_candidate = service.repository.get_by_id(original_candidate_id)
        assert updated_candidate is not None
        assert "600 USD" in updated_candidate.staff_answer
        assert updated_candidate.has_correction is True

    @pytest.mark.asyncio
    async def test_correction_transitions_thread_to_has_correction_state(self, service):
        """Test that correction transitions thread state to 'has_correction'."""
        # Create initial Q&A
        result = await service.process_matrix_answer(
            event_id="$ans_corr_state",
            staff_answer="Click the Send button.",
            reply_to_event_id="$q_corr_state",
            question_text="How do I send funds?",
            staff_sender="@staff:matrix.org",
        )

        assert result is not None
        thread = service.repository.find_thread_by_message("$q_corr_state")
        assert thread is not None
        assert thread.state == "candidate_created"

        # Process correction
        await service.process_correction(
            event_id="$correction_state",
            correction_content="Actually, first verify the address, then click Send.",
            reply_to_event_id="$q_corr_state",
            staff_sender="@staff:matrix.org",
        )

        # Thread state should be has_correction
        updated_thread = service.repository.get_thread(thread.id)
        assert updated_thread.state == "has_correction"

        # Verify transition audit
        transitions = service.repository.get_thread_transitions(thread.id)
        states = [t["to_state"] for t in transitions]
        assert "has_correction" in states

    @pytest.mark.asyncio
    async def test_correction_adds_message_to_thread(self, service):
        """Test that correction message is added to thread_messages."""
        # Create initial Q&A
        _result = await service.process_matrix_answer(  # noqa: F841
            event_id="$ans_msg_add",
            staff_answer="Use the export feature.",
            reply_to_event_id="$q_msg_add",
            question_text="How do I backup?",
            staff_sender="@staff:matrix.org",
        )

        thread = service.repository.find_thread_by_message("$q_msg_add")
        initial_messages = service.repository.get_thread_messages(thread.id)
        initial_count = len(initial_messages)

        # Process correction
        await service.process_correction(
            event_id="$correction_msg_add",
            correction_content="Actually, use the Backup option in File menu.",
            reply_to_event_id="$q_msg_add",
            staff_sender="@staff:matrix.org",
        )

        # Thread should have additional message
        messages = service.repository.get_thread_messages(thread.id)
        assert len(messages) == initial_count + 1

        # Correction message should be tracked
        correction_msg = next(
            (m for m in messages if m.message_id == "$correction_msg_add"), None
        )
        assert correction_msg is not None
        assert correction_msg.message_type == "correction"

    @pytest.mark.asyncio
    async def test_correction_reruns_comparison(self, service, mock_comparison_engine):
        """Test that correction triggers re-comparison with RAG answer."""
        # Reset mock to track calls
        mock_comparison_engine.compare.reset_mock()

        # Create initial Q&A
        _result = await service.process_matrix_answer(  # noqa: F841
            event_id="$ans_recompare",
            staff_answer="Initial answer.",
            reply_to_event_id="$q_recompare",
            question_text="Test question?",
            staff_sender="@staff:matrix.org",
        )

        initial_compare_count = mock_comparison_engine.compare.call_count

        # Process correction
        await service.process_correction(
            event_id="$correction_recompare",
            correction_content="Corrected answer with more detail.",
            reply_to_event_id="$q_recompare",
            staff_sender="@staff:matrix.org",
        )

        # Comparison should have been called again for the correction
        assert mock_comparison_engine.compare.call_count > initial_compare_count

    @pytest.mark.asyncio
    async def test_correction_to_approved_candidate_is_ignored(
        self, service, mock_faq_service
    ):
        """Test that corrections to already-approved candidates don't update them.

        Pre-approval corrections should only work on pending candidates.
        Corrections after approval are handled by Cycle 17 (post-approval).
        """
        # Create and approve a candidate
        result = await service.process_matrix_answer(
            event_id="$ans_approved",
            staff_answer="Original approved answer.",
            reply_to_event_id="$q_approved",
            question_text="Approved question?",
            staff_sender="@staff:matrix.org",
        )

        # Approve the candidate
        await service.approve_candidate(
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        # Get candidate after approval
        approved_candidate = service.repository.get_by_id(result.candidate_id)
        assert approved_candidate.review_status == "approved"

        # Try to process a correction (should not update the approved candidate)
        correction_result = await service.process_correction(
            event_id="$correction_approved",
            correction_content="Late correction to approved answer.",
            reply_to_event_id="$q_approved",
            staff_sender="@staff:matrix.org",
        )

        # Correction result should indicate the candidate was already approved
        assert correction_result is not None
        assert correction_result.skipped_reason == "candidate_already_approved"

        # Original candidate should NOT be modified
        unchanged_candidate = service.repository.get_by_id(result.candidate_id)
        assert unchanged_candidate.staff_answer == "Original approved answer."

    @pytest.mark.asyncio
    async def test_correction_without_existing_thread_creates_new(self, service):
        """Test that correction to unknown question creates new thread/candidate."""
        # Process a "correction" that doesn't match any existing thread
        # This could happen if the original question wasn't processed
        result = await service.process_correction(
            event_id="$orphan_correction",
            correction_content="Correction to unknown question.",
            reply_to_event_id="$unknown_question",
            staff_sender="@staff:matrix.org",
        )

        # Should still create a candidate (treating correction as a new answer)
        assert result is not None
        assert result.skipped_reason == "no_existing_thread"


class TestPipelinePostApprovalCorrections:
    """Test post-approval correction handling.

    Cycle 17: Handle corrections that arrive AFTER FAQ approval.
    When a staff member corrects their answer after the FAQ has been created,
    the system should FLAG the FAQ for review (not automatically update it).
    """

    @pytest_asyncio.fixture
    async def service(
        self,
        temp_db_path,
        mock_settings,
        mock_rag_service,
        mock_faq_service,
        mock_comparison_engine,
    ):
        """Create a pipeline service instance with comparison engine."""
        service = UnifiedPipelineService(
            settings=mock_settings,
            rag_service=mock_rag_service,
            faq_service=mock_faq_service,
            db_path=str(temp_db_path),
            comparison_engine=mock_comparison_engine,
        )
        return service

    @pytest.mark.asyncio
    async def test_thread_stores_faq_id_after_approval(self, service):
        """Test that thread stores faq_id after candidate approval."""
        # Create Q&A candidate
        result = await service.process_matrix_answer(
            event_id="$answer_for_faq",
            staff_answer="The answer for FAQ creation.",
            reply_to_event_id="$question_for_faq",
            question_text="What is the question?",
            staff_sender="@staff:matrix.org",
        )

        thread = service.repository.find_thread_by_message("$question_for_faq")
        assert thread is not None
        assert thread.faq_id is None  # No FAQ yet

        # Approve candidate
        _faq_result = await service.approve_candidate(  # noqa: F841
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        # Thread should now have faq_id
        updated_thread = service.repository.get_thread(thread.id)
        assert updated_thread.faq_id is not None
        assert updated_thread.state == "closed"

    @pytest.mark.asyncio
    async def test_post_approval_correction_flags_faq_for_review(
        self, service, mock_faq_service
    ):
        """Test that correction after approval flags the FAQ for review.

        This is the core test for Cycle 17: When a correction arrives after
        a candidate has been approved and an FAQ created, the system should
        flag the FAQ for review rather than silently ignoring the correction.
        """
        # Create Q&A and approve it
        result = await service.process_matrix_answer(
            event_id="$ans_post_correct",
            staff_answer="Original answer before correction.",
            reply_to_event_id="$q_post_correct",
            question_text="Question that gets corrected later?",
            staff_sender="@staff:matrix.org",
        )

        await service.approve_candidate(
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        # Verify thread is closed with faq_id
        thread = service.repository.find_thread_by_message("$q_post_correct")
        assert thread.state == "closed"
        assert thread.faq_id is not None

        # Now process a post-approval correction
        correction_result = await service.process_post_approval_correction(
            event_id="$late_correction",
            correction_content="Actually, the correct answer is different!",
            reply_to_event_id="$q_post_correct",
            staff_sender="@staff:matrix.org",
        )

        # FAQ should be flagged for review
        assert correction_result is not None
        assert correction_result.faq_flagged is True

        # Thread should be reopened
        updated_thread = service.repository.get_thread(thread.id)
        assert updated_thread.state == "reopened_for_correction"

    @pytest.mark.asyncio
    async def test_post_approval_correction_records_reason(
        self, service, mock_faq_service
    ):
        """Test that flagged FAQ includes correction reason."""
        # Create and approve
        result = await service.process_matrix_answer(
            event_id="$ans_reason",
            staff_answer="Answer to be corrected.",
            reply_to_event_id="$q_reason",
            question_text="Question with correction reason?",
            staff_sender="@staff:matrix.org",
        )

        await service.approve_candidate(
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        thread = service.repository.find_thread_by_message("$q_reason")

        # Process post-approval correction
        await service.process_post_approval_correction(
            event_id="$correction_reason",
            correction_content="Better answer with more details.",
            reply_to_event_id="$q_reason",
            staff_sender="@staff:matrix.org",
        )

        # Check that FAQ flagging includes reason
        updated_thread = service.repository.get_thread(thread.id)
        assert updated_thread.correction_reason is not None
        assert "staff_correction" in updated_thread.correction_reason

    @pytest.mark.asyncio
    async def test_post_approval_correction_stores_correction_content(
        self, service, mock_faq_service
    ):
        """Test that correction content is stored for admin review."""
        # Create and approve
        result = await service.process_matrix_answer(
            event_id="$ans_content",
            staff_answer="Original answer.",
            reply_to_event_id="$q_content",
            question_text="Question for content test?",
            staff_sender="@staff:matrix.org",
        )

        await service.approve_candidate(
            candidate_id=result.candidate_id,
            reviewer="admin",
        )

        thread = service.repository.find_thread_by_message("$q_content")

        # Process correction with specific content
        correction_text = "This is the corrected answer with new information."
        await service.process_post_approval_correction(
            event_id="$correction_content",
            correction_content=correction_text,
            reply_to_event_id="$q_content",
            staff_sender="@staff:matrix.org",
        )

        # Correction should be stored in thread messages
        messages = service.repository.get_thread_messages(thread.id)
        correction_msg = next(
            (m for m in messages if m.message_type == "post_approval_correction"), None
        )
        assert correction_msg is not None
        assert correction_msg.content == correction_text

    @pytest.mark.asyncio
    async def test_post_approval_correction_to_non_faq_thread_is_skipped(self, service):
        """Test that post-approval correction to thread without FAQ is skipped."""
        # Create candidate but DON'T approve
        _result = await service.process_matrix_answer(  # noqa: F841
            event_id="$ans_no_faq",
            staff_answer="Answer without approval.",
            reply_to_event_id="$q_no_faq",
            question_text="Unapproved question?",
            staff_sender="@staff:matrix.org",
        )

        # Verify thread is in candidate_created state (not closed)
        thread = service.repository.find_thread_by_message("$q_no_faq")
        assert thread is not None
        assert thread.state == "candidate_created"  # Not closed
        assert thread.faq_id is None  # No FAQ created

        # Try to process as post-approval correction (should return None)
        correction_result = await service.process_post_approval_correction(
            event_id="$correction_no_faq",
            correction_content="Correction to unapproved.",
            reply_to_event_id="$q_no_faq",
            staff_sender="@staff:matrix.org",
        )

        # Should return None - no FAQ to flag (thread not closed)
        assert correction_result is None


# =============================================================================
# Tests for Threshold Constants (TDD: Task #2)
# =============================================================================


class TestThresholdConstants:
    """Tests for unified threshold constants across pipeline and learning engine.

    RED phase: These tests ensure threshold constants are defined once and shared.
    """

    def test_threshold_constants_exist_in_config(self):
        """Threshold constants should be defined in a central location."""
        from app.core.config import (
            PIPELINE_AUTO_APPROVE_THRESHOLD,
            PIPELINE_DUPLICATE_FAQ_THRESHOLD,
            PIPELINE_SPOT_CHECK_THRESHOLD,
        )

        assert PIPELINE_AUTO_APPROVE_THRESHOLD == 0.90
        assert PIPELINE_SPOT_CHECK_THRESHOLD == 0.75
        assert PIPELINE_DUPLICATE_FAQ_THRESHOLD == 0.85

    def test_pipeline_uses_shared_constants(self):
        """Pipeline service should use shared threshold constants."""
        from app.core.config import (
            PIPELINE_AUTO_APPROVE_THRESHOLD,
            PIPELINE_SPOT_CHECK_THRESHOLD,
        )
        from app.services.training.unified_pipeline_service import (
            AUTO_APPROVE_THRESHOLD,
            SPOT_CHECK_THRESHOLD,
        )

        # Verify pipeline constants match config
        assert AUTO_APPROVE_THRESHOLD == PIPELINE_AUTO_APPROVE_THRESHOLD
        assert SPOT_CHECK_THRESHOLD == PIPELINE_SPOT_CHECK_THRESHOLD

    def test_learning_engine_uses_shared_constants(self):
        """Learning engine should use shared threshold constants."""
        from app.core.config import (
            PIPELINE_AUTO_APPROVE_THRESHOLD,
            PIPELINE_SPOT_CHECK_THRESHOLD,
        )
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()
        # Default thresholds should match config constants
        assert engine.auto_send_threshold == PIPELINE_AUTO_APPROVE_THRESHOLD
        assert engine.queue_high_threshold == PIPELINE_SPOT_CHECK_THRESHOLD

    def test_learning_engine_routing_uses_thresholds(self):
        """Learning engine routing should respect threshold constants."""
        from app.core.config import (
            PIPELINE_AUTO_APPROVE_THRESHOLD,
            PIPELINE_SPOT_CHECK_THRESHOLD,
        )
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()

        # Above auto_approve threshold
        assert (
            engine.get_routing_recommendation(PIPELINE_AUTO_APPROVE_THRESHOLD)
            == "AUTO_APPROVE"
        )
        assert engine.get_routing_recommendation(0.95) == "AUTO_APPROVE"

        # Between spot_check and auto_approve
        assert (
            engine.get_routing_recommendation(PIPELINE_SPOT_CHECK_THRESHOLD)
            == "SPOT_CHECK"
        )
        assert engine.get_routing_recommendation(0.80) == "SPOT_CHECK"

        # Below spot_check threshold
        assert engine.get_routing_recommendation(0.70) == "FULL_REVIEW"
        assert engine.get_routing_recommendation(0.50) == "FULL_REVIEW"


# =============================================================================
# Tests for Automatic State Persistence (TDD: Task #3)
# =============================================================================


class TestLearningEngineStatePersistence:
    """Tests for automatic LearningEngine state persistence."""

    def test_learning_engine_accepts_repository_in_init(self):
        """LearningEngine should accept optional repository for auto-persistence."""
        from unittest.mock import MagicMock

        from app.services.rag.learning_engine import LearningEngine

        # Without repository - should work (backward compatible)
        engine = LearningEngine()
        assert engine is not None

        # With repository - should store it for auto-save
        mock_repo = MagicMock()
        mock_repo.get_learning_state.return_value = None
        engine_with_repo = LearningEngine(repository=mock_repo)
        assert engine_with_repo._repository is mock_repo

    def test_auto_save_after_threshold_update(self):
        """LearningEngine should auto-save when thresholds are updated."""
        from unittest.mock import MagicMock

        from app.services.rag.learning_engine import LearningEngine

        mock_repo = MagicMock()
        mock_repo.get_learning_state.return_value = None
        engine = LearningEngine(repository=mock_repo)

        # Record enough reviews to trigger a threshold update
        for i in range(55):
            engine.record_review(
                question_id=f"q_{i}",
                confidence=0.85,
                admin_action="approved",
                routing_action="SPOT_CHECK",
            )

        # Verify save_learning_state was called
        assert mock_repo.save_learning_state.called

    def test_loads_state_on_init_with_repository(self):
        """LearningEngine should load state from repository on init."""
        from unittest.mock import MagicMock

        from app.services.rag.learning_engine import LearningEngine

        mock_repo = MagicMock()
        mock_repo.get_learning_state.return_value = {
            "auto_send_threshold": 0.88,
            "queue_high_threshold": 0.72,
            "reject_threshold": 0.45,
            "review_history": [],
            "threshold_history": [],
        }

        engine = LearningEngine(repository=mock_repo)

        # Verify state was loaded
        assert engine.auto_send_threshold == 0.88
        assert engine.queue_high_threshold == 0.72
        assert engine.reject_threshold == 0.45

    def test_no_auto_save_without_repository(self):
        """LearningEngine should not fail when no repository provided."""
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()  # No repository

        # Record reviews - should not fail
        for i in range(55):
            engine.record_review(
                question_id=f"q_{i}",
                confidence=0.85,
                admin_action="approved",
                routing_action="SPOT_CHECK",
            )

        # Should complete without error
        assert len(engine._review_history) == 55
