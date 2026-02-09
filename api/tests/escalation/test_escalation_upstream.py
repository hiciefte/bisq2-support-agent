"""Tests for upstream prerequisites: requires_human wiring in RAGService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.response_action import ResponseAction


def _setup_rag_mocks(rag_service, routing_action):
    """Configure rag_service mocks to reach the routing code path.

    Bypasses version detection (returns Bisq 2 with high confidence)
    and document retrieval (returns one mock doc).
    """
    mock_doc = MagicMock(
        page_content="Bisq is a decentralized exchange.",
        metadata={
            "source": "wiki",
            "protocol": "all",
            "title": "About Bisq",
            "type": "wiki",
        },
    )
    rag_service.document_retriever.retrieve_with_scores.return_value = (
        [mock_doc],
        [0.85],
    )
    rag_service.document_retriever.retrieve_with_version_priority.return_value = [
        mock_doc
    ]
    # Skip clarification by returning high version confidence
    rag_service.version_detector.detect_version = AsyncMock(
        return_value=("Bisq 2", 0.9, None)
    )
    rag_service.confidence_scorer.calculate_confidence = AsyncMock(return_value=0.80)
    rag_service.auto_send_router.route_response = AsyncMock(return_value=routing_action)
    # rag_chain is called as a callable (not .invoke()) at line 909
    rag_service.rag_chain.return_value = "This is a test response."
    # Ensure MCP path is skipped
    rag_service.mcp_enabled = False


class TestRequiresHumanWiring:
    """Verify SimplifiedRAGService sets requires_human from AutoSendRouter."""

    @pytest.mark.asyncio
    async def test_rag_response_contains_requires_human_key(self, rag_service):
        """RAG response dict includes 'requires_human' key."""
        _setup_rag_mocks(
            rag_service,
            ResponseAction(
                action="auto_send", send_immediately=True, queue_for_review=False
            ),
        )
        response = await rag_service.query("What is Bisq 2?")
        assert "requires_human" in response

    @pytest.mark.asyncio
    async def test_requires_human_true_when_router_returns_needs_human(
        self, rag_service
    ):
        """AutoSendRouter action='needs_human' -> requires_human=True."""
        _setup_rag_mocks(
            rag_service,
            ResponseAction(
                action="needs_human",
                send_immediately=False,
                queue_for_review=True,
                priority="high",
                flag="needs_human_expertise",
            ),
        )
        rag_service.confidence_scorer.calculate_confidence = AsyncMock(
            return_value=0.42
        )
        response = await rag_service.query(
            "How do I restore my Bisq 2 wallet from seed words?"
        )
        assert response["requires_human"] is True

    @pytest.mark.asyncio
    async def test_requires_human_false_when_router_returns_auto_send(
        self, rag_service
    ):
        """AutoSendRouter action='auto_send' -> requires_human=False."""
        _setup_rag_mocks(
            rag_service,
            ResponseAction(
                action="auto_send",
                send_immediately=True,
                queue_for_review=False,
            ),
        )
        rag_service.confidence_scorer.calculate_confidence = AsyncMock(
            return_value=0.96
        )
        response = await rag_service.query("What is Bisq 2?")
        assert response["requires_human"] is False

    @pytest.mark.asyncio
    async def test_requires_human_false_when_router_unavailable(self, rag_service):
        """AutoSendRouter failure -> requires_human=False (safe default)."""
        _setup_rag_mocks(
            rag_service,
            ResponseAction(
                action="auto_send", send_immediately=True, queue_for_review=False
            ),
        )
        # Override router to raise
        rag_service.auto_send_router.route_response = AsyncMock(
            side_effect=RuntimeError("Router unavailable")
        )
        response = await rag_service.query("What is Bisq 2?")
        # Should still get a response, and requires_human defaults False
        assert "answer" in response
        assert response.get("requires_human", False) is False
