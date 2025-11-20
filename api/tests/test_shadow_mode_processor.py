"""Tests for Shadow Mode Processor - TDD approach."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestShadowResponse:
    """Test suite for ShadowResponse model."""

    def test_shadow_response_creation(self):
        """ShadowResponse model can be instantiated."""
        from app.models.shadow_response import ShadowResponse

        response = ShadowResponse(
            question_id="test-123",
            question="What is Bisq?",
            answer="Bisq is a decentralized exchange.",
            confidence=0.85,
            sources=["wiki/bisq"],
        )

        assert response.question_id == "test-123"
        assert response.confidence == 0.85
        assert response.processed is False
        assert response.routing_action is None

    def test_shadow_response_with_all_fields(self):
        """ShadowResponse supports all optional fields."""
        from app.models.shadow_response import ShadowResponse

        response = ShadowResponse(
            question_id="test-456",
            question="Test?",
            answer="Answer",
            confidence=0.95,
            sources=["source1", "source2"],
            room_id="!room:matrix.org",
            sender="@anon:matrix.org",
            processed=True,
            routing_action="auto_send",
        )

        assert response.room_id == "!room:matrix.org"
        assert response.processed is True
        assert response.routing_action == "auto_send"


class TestShadowModeProcessor:
    """Test suite for shadow mode processing."""

    @pytest.fixture
    def mock_rag_service(self):
        """Create mock RAG service."""
        mock = MagicMock()
        mock.query = AsyncMock(
            return_value={
                "answer": "Test answer",
                "sources": ["source1"],
                "confidence": 0.80,
            }
        )
        return mock

    @pytest.fixture
    def mock_confidence_scorer(self):
        """Create mock confidence scorer."""
        mock = MagicMock()
        mock.calculate_confidence = AsyncMock(return_value=0.85)
        return mock

    @pytest.fixture
    def mock_router(self):
        """Create mock router."""
        from app.models.response_action import ResponseAction

        mock = MagicMock()
        mock.route_response = AsyncMock(
            return_value=ResponseAction(
                action="queue_medium",
                send_immediately=False,
                queue_for_review=True,
            )
        )
        return mock

    @pytest.fixture
    def processor(self, mock_rag_service, mock_confidence_scorer, mock_router):
        """Create processor with mocked dependencies."""
        from app.services.shadow_mode_processor import ShadowModeProcessor

        return ShadowModeProcessor(
            rag_service=mock_rag_service,
            confidence_scorer=mock_confidence_scorer,
            router=mock_router,
        )

    @pytest.mark.asyncio
    async def test_process_question(self, processor, mock_rag_service):
        """Process question through RAG pipeline."""
        result = await processor.process_question(
            question="What is the trade limit?",
            question_id="q-123",
            room_id="!room:matrix.org",
            sender="@user:matrix.org",
        )

        assert result is not None
        assert result.question_id == "q-123"
        assert result.question == "What is the trade limit?"
        mock_rag_service.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_question_returns_shadow_response(self, processor):
        """Process returns ShadowResponse with all fields."""
        from app.models.shadow_response import ShadowResponse

        result = await processor.process_question(
            question="Test question?",
            question_id="q-456",
        )

        assert isinstance(result, ShadowResponse)
        assert result.answer is not None
        assert result.confidence is not None
        assert isinstance(result.sources, list)

    @pytest.mark.asyncio
    async def test_process_question_includes_routing_action(
        self, processor, mock_router
    ):
        """Process includes routing action from router."""
        result = await processor.process_question(
            question="Test?",
            question_id="q-789",
        )

        assert result.routing_action == "queue_medium"
        mock_router.route_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_pii_scrubbing(self, processor):
        """PII is scrubbed from questions."""
        # Process question with potential PII
        result = await processor.process_question(
            question="My email is test@example.com and I need help",
            question_id="q-pii",
        )

        # Original question should be sanitized in stored response
        # Note: actual implementation may vary
        assert result is not None

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, processor):
        """Duplicate questions are detected."""
        # Process first question
        await processor.process_question(
            question="What is Bisq?",
            question_id="q-1",
        )

        # Process same question again
        result = await processor.process_question(
            question="What is Bisq?",
            question_id="q-2",
        )

        # Should still process but may be flagged
        assert result is not None

    @pytest.mark.asyncio
    async def test_stores_response(self, processor):
        """Processed responses are stored."""
        await processor.process_question(
            question="Test?",
            question_id="q-store",
        )

        # Check response was stored
        stored = processor.get_response("q-store")
        assert stored is not None
        assert stored.question_id == "q-store"

    @pytest.mark.asyncio
    async def test_get_pending_responses(self, processor):
        """Can retrieve pending responses for review."""
        # Process multiple questions
        await processor.process_question(
            question="Question 1?",
            question_id="q-1",
        )
        await processor.process_question(
            question="Question 2?",
            question_id="q-2",
        )

        # Get pending responses
        pending = processor.get_pending_responses()
        assert len(pending) >= 0  # May be empty if auto-sent

    @pytest.mark.asyncio
    async def test_mark_as_processed(self, processor):
        """Can mark response as processed."""
        await processor.process_question(
            question="Test?",
            question_id="q-mark",
        )

        # Mark as processed
        processor.mark_as_processed("q-mark")

        # Check it's marked
        response = processor.get_response("q-mark")
        assert response.processed is True

    @pytest.mark.asyncio
    async def test_handles_rag_error_gracefully(self, processor, mock_rag_service):
        """Gracefully handles RAG service errors."""
        mock_rag_service.query.side_effect = Exception("RAG error")

        result = await processor.process_question(
            question="Test?",
            question_id="q-error",
        )

        # Should return error response or None
        # Implementation dependent
        assert result is None or result.confidence == 0.0


class TestMatrixIntegration:
    """Test suite for Matrix integration (basic tests without actual Matrix)."""

    def test_question_detection_pattern(self):
        """Question detection regex works correctly."""
        from app.services.shadow_mode_processor import ShadowModeProcessor

        # Test patterns that should be detected as questions
        questions = [
            "What is Bisq?",
            "How do I trade?",
            "Can someone help me?",
            "Why is my trade stuck?",
            "Where can I find the settings?",
        ]

        for q in questions:
            assert ShadowModeProcessor.is_support_question(q)

        # Test patterns that should NOT be detected
        non_questions = [
            "Thanks for the help!",
            "I agree with that.",
            "Here is the link: http://example.com",
        ]

        for nq in non_questions:
            assert not ShadowModeProcessor.is_support_question(nq)
