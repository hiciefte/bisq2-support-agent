"""Tests for Auto-Send Router - TDD approach."""

import pytest
from langchain_core.documents import Document


class TestResponseAction:
    """Test suite for ResponseAction model."""

    def test_response_action_creation(self):
        """ResponseAction model can be instantiated."""
        from app.models.response_action import ResponseAction

        action = ResponseAction(
            action="auto_send",
            send_immediately=True,
            queue_for_review=False,
        )

        assert action.action == "auto_send"
        assert action.send_immediately is True
        assert action.queue_for_review is False
        assert action.priority == "normal"  # Default
        assert action.flag is None  # Default

    def test_response_action_with_flag(self):
        """ResponseAction supports optional flag."""
        from app.models.response_action import ResponseAction

        action = ResponseAction(
            action="queue_low",
            send_immediately=False,
            queue_for_review=True,
            priority="high",
            flag="needs_human_expertise",
        )

        assert action.flag == "needs_human_expertise"
        assert action.priority == "high"


class TestAutoSendRouter:
    """Test suite for auto-send routing logic."""

    @pytest.fixture
    def router(self):
        """Create router instance."""
        from app.services.rag.auto_send_router import AutoSendRouter

        return AutoSendRouter()

    @pytest.mark.asyncio
    async def test_high_confidence_auto_sends(self, router):
        """AC-1.2.1: >95% confidence auto-sends immediately."""
        action = await router.route_response(
            confidence=0.96,
            question="Test question?",
            answer="Test answer",
            sources=[],
        )

        assert action.action == "auto_send"
        assert action.send_immediately is True
        assert action.queue_for_review is False

    @pytest.mark.asyncio
    async def test_exactly_95_percent_auto_sends(self, router):
        """Exactly 95% threshold triggers auto-send."""
        action = await router.route_response(
            confidence=0.95,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "auto_send"
        assert action.send_immediately is True

    @pytest.mark.asyncio
    async def test_medium_confidence_queues(self, router):
        """AC-1.2.2: 70-95% confidence queues for moderator review."""
        action = await router.route_response(
            confidence=0.80,
            question="Test question?",
            answer="Test answer",
            sources=[],
        )

        assert action.action == "queue_medium"
        assert action.send_immediately is False
        assert action.queue_for_review is True
        assert action.priority == "normal"

    @pytest.mark.asyncio
    async def test_exactly_70_percent_queues_medium(self, router):
        """Exactly 70% threshold queues for review."""
        action = await router.route_response(
            confidence=0.70,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "queue_medium"
        assert action.queue_for_review is True

    @pytest.mark.asyncio
    async def test_low_confidence_flags(self, router):
        """AC-1.2.3: <70% confidence queues + flags as high priority."""
        action = await router.route_response(
            confidence=0.50,
            question="Test question?",
            answer="Test answer",
            sources=[],
        )

        assert action.action == "needs_human"
        assert action.send_immediately is False
        assert action.queue_for_review is True
        assert action.priority == "high"
        assert action.flag == "needs_human_expertise"

    @pytest.mark.asyncio
    async def test_very_low_confidence(self, router):
        """Very low confidence still flags correctly."""
        action = await router.route_response(
            confidence=0.10,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "needs_human"
        assert action.flag == "needs_human_expertise"

    @pytest.mark.asyncio
    async def test_zero_confidence(self, router):
        """Zero confidence flags correctly."""
        action = await router.route_response(
            confidence=0.0,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "needs_human"
        assert action.flag == "needs_human_expertise"

    @pytest.mark.asyncio
    async def test_perfect_confidence(self, router):
        """Perfect 1.0 confidence auto-sends."""
        action = await router.route_response(
            confidence=1.0,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "auto_send"
        assert action.send_immediately is True

    @pytest.mark.asyncio
    async def test_boundary_below_95(self, router):
        """Just below 95% threshold queues for review."""
        action = await router.route_response(
            confidence=0.949,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "queue_medium"
        assert action.queue_for_review is True

    @pytest.mark.asyncio
    async def test_boundary_below_70(self, router):
        """Just below 70% threshold flags as low confidence."""
        action = await router.route_response(
            confidence=0.699,
            question="Test?",
            answer="Answer",
            sources=[],
        )

        assert action.action == "needs_human"
        assert action.flag == "needs_human_expertise"

    @pytest.mark.asyncio
    async def test_sources_passed_through(self, router):
        """Router accepts sources parameter."""
        sources = [Document(page_content="Test content", metadata={"title": "Test"})]

        action = await router.route_response(
            confidence=0.80,
            question="Test?",
            answer="Answer",
            sources=sources,
        )

        # Should work without error
        assert action is not None

    def test_threshold_constants(self, router):
        """Verify threshold constants are set correctly."""
        assert router.HIGH_CONFIDENCE_THRESHOLD == 0.95
        assert router.MEDIUM_CONFIDENCE_THRESHOLD == 0.70
