"""TDD Tests for PendingResponseService."""

import json
import os
import tempfile
from pathlib import Path

import pytest
from app.core.config import Settings
from app.services.pending_response_service import PendingResponseService


@pytest.fixture
def test_settings():
    """Create test settings with temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Settings(
            OPENAI_API_KEY="test-key",
            ADMIN_API_KEY="test-admin-key",
            DATA_DIR_PATH=tmpdir,
            FEEDBACK_DIR_PATH=os.path.join(tmpdir, "feedback"),
        )
        os.makedirs(settings.FEEDBACK_DIR_PATH, exist_ok=True)
        yield settings


@pytest.fixture
def pending_service(test_settings):
    """Create PendingResponseService instance with clean state."""
    service = PendingResponseService(test_settings)
    # Ensure clean state by removing any existing file
    if service.pending_file.exists():
        service.pending_file.unlink()
    return service


class TestQueueResponse:
    """Test suite for queue_response method."""

    @pytest.mark.asyncio
    async def test_queue_response_returns_id(self, pending_service):
        """Queuing a response should return a unique ID."""
        response_id = await pending_service.queue_response(
            question="What is Bisq?",
            answer="Bisq is a decentralized exchange.",
            confidence=0.75,
            routing_action="queue_medium",
            sources=[],
        )

        assert response_id is not None
        assert len(response_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_queue_response_stores_data(self, pending_service):
        """Queued response should be retrievable."""
        response_id = await pending_service.queue_response(
            question="Test question?",
            answer="Test answer",
            confidence=0.60,
            routing_action="queue_low",
            sources=[{"title": "Test", "type": "wiki", "content": "..."}],
            metadata={"detected_version": "Bisq 2"},
        )

        response = await pending_service.get_response_by_id(response_id)

        assert response is not None
        assert response["question"] == "Test question?"
        assert response["answer"] == "Test answer"
        assert response["confidence"] == 0.60
        assert response["routing_action"] == "queue_low"
        assert response["status"] == "pending"
        assert response["metadata"]["detected_version"] == "Bisq 2"

    @pytest.mark.asyncio
    async def test_queue_response_with_channel(self, pending_service):
        """Queued response should include channel information."""
        response_id = await pending_service.queue_response(
            question="Test?",
            answer="Answer",
            confidence=0.80,
            routing_action="queue_medium",
            sources=[],
            channel="matrix",
        )

        response = await pending_service.get_response_by_id(response_id)
        assert response["channel"] == "matrix"

    @pytest.mark.asyncio
    async def test_queue_multiple_responses(self, pending_service):
        """Multiple responses can be queued."""
        id1 = await pending_service.queue_response(
            question="Q1?",
            answer="A1",
            confidence=0.7,
            routing_action="queue_medium",
            sources=[],
        )
        id2 = await pending_service.queue_response(
            question="Q2?",
            answer="A2",
            confidence=0.5,
            routing_action="queue_low",
            sources=[],
        )

        assert id1 != id2

        result = await pending_service.get_pending_responses()
        assert result["total"] == 2


class TestGetPendingResponses:
    """Test suite for get_pending_responses method."""

    @pytest.mark.asyncio
    async def test_empty_queue(self, pending_service):
        """Empty queue should return empty list."""
        result = await pending_service.get_pending_responses()

        assert result["responses"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_filter_by_status(self, pending_service):
        """Should filter by status."""
        # Queue responses
        id1 = await pending_service.queue_response(
            question="Q1?",
            answer="A1",
            confidence=0.7,
            routing_action="queue_medium",
            sources=[],
        )
        await pending_service.queue_response(
            question="Q2?",
            answer="A2",
            confidence=0.5,
            routing_action="queue_low",
            sources=[],
        )

        # Approve one
        await pending_service.update_response(id1, "approved")

        # Filter pending only
        pending = await pending_service.get_pending_responses(status="pending")
        assert pending["total"] == 1

        # Filter approved only
        approved = await pending_service.get_pending_responses(status="approved")
        assert approved["total"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_priority(self, pending_service):
        """Should filter by priority (high = queue_low, normal = queue_medium)."""
        await pending_service.queue_response(
            question="Q1?",
            answer="A1",
            confidence=0.8,
            routing_action="queue_medium",
            sources=[],
        )
        await pending_service.queue_response(
            question="Q2?",
            answer="A2",
            confidence=0.5,
            routing_action="queue_low",
            sources=[],
        )

        high_priority = await pending_service.get_pending_responses(priority="high")
        assert high_priority["total"] == 1
        assert high_priority["responses"][0]["routing_action"] == "queue_low"

        normal_priority = await pending_service.get_pending_responses(priority="normal")
        assert normal_priority["total"] == 1
        assert normal_priority["responses"][0]["routing_action"] == "queue_medium"

    @pytest.mark.asyncio
    async def test_pagination(self, pending_service):
        """Should support pagination."""
        # Queue 5 responses
        for i in range(5):
            await pending_service.queue_response(
                question=f"Q{i}?",
                answer=f"A{i}",
                confidence=0.7,
                routing_action="queue_medium",
                sources=[],
            )

        # Get first page
        page1 = await pending_service.get_pending_responses(limit=2, offset=0)
        assert len(page1["responses"]) == 2
        assert page1["total"] == 5

        # Get second page
        page2 = await pending_service.get_pending_responses(limit=2, offset=2)
        assert len(page2["responses"]) == 2

        # Get last page
        page3 = await pending_service.get_pending_responses(limit=2, offset=4)
        assert len(page3["responses"]) == 1


class TestUpdateResponse:
    """Test suite for update_response method."""

    @pytest.mark.asyncio
    async def test_approve_response(self, pending_service):
        """Should approve a pending response."""
        response_id = await pending_service.queue_response(
            question="Q?",
            answer="A",
            confidence=0.8,
            routing_action="queue_medium",
            sources=[],
        )

        success = await pending_service.update_response(
            response_id, "approved", reviewed_by="admin"
        )

        assert success is True

        response = await pending_service.get_response_by_id(response_id)
        assert response["status"] == "approved"
        assert response["reviewed_by"] == "admin"
        assert response["reviewed_at"] is not None

    @pytest.mark.asyncio
    async def test_reject_response(self, pending_service):
        """Should reject a pending response."""
        response_id = await pending_service.queue_response(
            question="Q?",
            answer="A",
            confidence=0.5,
            routing_action="queue_low",
            sources=[],
        )

        success = await pending_service.update_response(
            response_id, "rejected", reviewed_by="admin", review_notes="Not accurate"
        )

        assert success is True

        response = await pending_service.get_response_by_id(response_id)
        assert response["status"] == "rejected"
        assert response["review_notes"] == "Not accurate"

    @pytest.mark.asyncio
    async def test_modify_response(self, pending_service):
        """Should modify a pending response."""
        response_id = await pending_service.queue_response(
            question="Q?",
            answer="Original answer",
            confidence=0.6,
            routing_action="queue_low",
            sources=[],
        )

        success = await pending_service.update_response(
            response_id,
            "modified",
            reviewed_by="admin",
            modified_answer="Better answer with more detail",
        )

        assert success is True

        response = await pending_service.get_response_by_id(response_id)
        assert response["status"] == "modified"
        assert response["modified_answer"] == "Better answer with more detail"

    @pytest.mark.asyncio
    async def test_update_nonexistent_response(self, pending_service):
        """Should return False for nonexistent response."""
        success = await pending_service.update_response("nonexistent-id", "approved")

        assert success is False


class TestGetQueueStats:
    """Test suite for get_queue_stats method."""

    @pytest.mark.asyncio
    async def test_empty_queue_stats(self, pending_service):
        """Empty queue should return zero stats."""
        stats = await pending_service.get_queue_stats()

        assert stats["pending"] == 0
        assert stats["approved"] == 0
        assert stats["high_priority"] == 0

    @pytest.mark.asyncio
    async def test_queue_stats_counts(self, pending_service):
        """Should count responses by status and priority."""
        # Queue mixed responses
        id1 = await pending_service.queue_response(
            question="Q1?",
            answer="A1",
            confidence=0.8,
            routing_action="queue_medium",
            sources=[],
        )
        await pending_service.queue_response(
            question="Q2?",
            answer="A2",
            confidence=0.5,
            routing_action="queue_low",
            sources=[],
        )
        await pending_service.queue_response(
            question="Q3?",
            answer="A3",
            confidence=0.4,
            routing_action="queue_low",
            sources=[],
        )

        # Approve one
        await pending_service.update_response(id1, "approved")

        stats = await pending_service.get_queue_stats()

        assert stats["pending"] == 2
        assert stats["approved"] == 1
        assert stats["high_priority"] == 2  # queue_low = high priority
        assert stats["normal_priority"] == 0  # The queue_medium one was approved

    @pytest.mark.asyncio
    async def test_average_confidence(self, pending_service):
        """Should calculate average confidence for pending responses."""
        await pending_service.queue_response(
            question="Q1?",
            answer="A1",
            confidence=0.8,
            routing_action="queue_medium",
            sources=[],
        )
        await pending_service.queue_response(
            question="Q2?",
            answer="A2",
            confidence=0.6,
            routing_action="queue_medium",
            sources=[],
        )

        stats = await pending_service.get_queue_stats()

        assert stats["avg_confidence"] == pytest.approx(0.7, rel=0.01)


class TestDeleteResponse:
    """Test suite for delete_response method."""

    @pytest.mark.asyncio
    async def test_delete_existing_response(self, pending_service):
        """Should delete an existing response."""
        response_id = await pending_service.queue_response(
            question="Q?",
            answer="A",
            confidence=0.7,
            routing_action="queue_medium",
            sources=[],
        )

        success = await pending_service.delete_response(response_id)

        assert success is True

        response = await pending_service.get_response_by_id(response_id)
        assert response is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_response(self, pending_service):
        """Should return False for nonexistent response."""
        success = await pending_service.delete_response("nonexistent-id")

        assert success is False


class TestGetResponseById:
    """Test suite for get_response_by_id method."""

    @pytest.mark.asyncio
    async def test_get_existing_response(self, pending_service):
        """Should retrieve existing response."""
        response_id = await pending_service.queue_response(
            question="Test?",
            answer="Answer",
            confidence=0.75,
            routing_action="queue_medium",
            sources=[],
        )

        response = await pending_service.get_response_by_id(response_id)

        assert response is not None
        assert response["id"] == response_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_response(self, pending_service):
        """Should return None for nonexistent response."""
        response = await pending_service.get_response_by_id("nonexistent-id")

        assert response is None
