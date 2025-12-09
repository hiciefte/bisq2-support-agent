"""Unit tests for pending responses API endpoints.

TDD Implementation: Tests written BEFORE endpoint implementation.
Following design principles:
- Test behavior, not implementation details
- Test happy paths and error cases
- Test validation and edge cases
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.services.pending_response_service import PendingResponseService


@pytest.fixture
async def setup_pending_responses(test_settings):
    """Create real pending responses for testing."""
    pending_service = PendingResponseService(test_settings)

    # Create test responses (service generates its own IDs)
    response_1_id = await pending_service.queue_response(
        question="How do I restore my wallet in Bisq 2?",
        answer="To restore your wallet in Bisq 2, go to Settings...",
        confidence=0.75,
        routing_action="queue_medium",
        sources=[
            {
                "title": "Bisq 2 Wallet Guide",
                "url": "https://bisq.wiki/Bisq_2_Wallet",
            }
        ],
        metadata={"detected_version": "Bisq 2"},
        channel="web",
    )

    response_2_id = await pending_service.queue_response(
        question="What are the trading fees?",
        answer="Bisq 2 trading fees are 0.1% for makers and 0.3% for takers",
        confidence=0.55,
        routing_action="queue_low",
        sources=[],
        metadata={"detected_version": "Bisq 2"},
        channel="matrix",
    )

    yield {"response_1_id": response_1_id, "response_2_id": response_2_id}

    # Cleanup: Remove test data file
    pending_file = (
        Path(test_settings.FEEDBACK_DIR_PATH).parent / "pending_responses.jsonl"
    )
    if pending_file.exists():
        pending_file.unlink()


class TestGetPendingResponses:
    """Tests for GET /admin/pending endpoint."""

    async def test_get_pending_responses_success(
        self, test_client, setup_pending_responses
    ):
        """Should return list of pending responses."""
        response = test_client.get(
            "/admin/pending",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "responses" in data
        assert len(data["responses"]) == 2
        assert data["total"] == 2

    async def test_get_pending_responses_empty_queue(self, test_client):
        """Should return empty list when no pending responses."""
        response = test_client.get(
            "/admin/pending",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["responses"] == []
        assert data["total"] == 0

    def test_get_pending_responses_unauthorized(self, test_client):
        """Should return 401 when no API key provided."""
        response = test_client.get("/admin/pending")
        assert response.status_code == 401

    def test_get_pending_responses_invalid_api_key(self, test_client):
        """Should return 403 with invalid API key."""
        response = test_client.get(
            "/admin/pending",
            headers={"X-API-Key": "invalid_key"},
        )
        assert response.status_code == 403


class TestApproveResponse:
    """Tests for POST /admin/pending/{id}/approve endpoint."""

    async def test_approve_response_success(self, test_client, setup_pending_responses):
        """Should approve response and return success."""
        response_ids = setup_pending_responses
        response = test_client.post(
            f"/admin/pending/{response_ids['response_1_id']}/approve",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "approved" in data["message"].lower()

    async def test_approve_response_not_found(self, test_client):
        """Should return 404 when response not found."""
        response = test_client.post(
            "/admin/pending/nonexistent-id-12345/approve",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_approve_response_unauthorized(self, test_client):
        """Should return 401 when no API key provided."""
        response = test_client.post("/admin/pending/response-1/approve")
        assert response.status_code == 401


class TestRejectResponse:
    """Tests for POST /admin/pending/{id}/reject endpoint."""

    async def test_reject_response_success(self, test_client, setup_pending_responses):
        """Should reject response and return success."""
        response_ids = setup_pending_responses
        response = test_client.post(
            f"/admin/pending/{response_ids['response_2_id']}/reject",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "rejected" in data["message"].lower()

    async def test_reject_response_not_found(self, test_client):
        """Should return 404 when response not found."""
        response = test_client.post(
            "/admin/pending/nonexistent-id-12345/reject",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 404


class TestEditResponse:
    """Tests for POST /admin/pending/{id}/edit endpoint."""

    async def test_edit_response_success(self, test_client, setup_pending_responses):
        """Should edit and approve response."""
        response_ids = setup_pending_responses
        edited_answer = "Edited answer with improvements"
        response = test_client.post(
            f"/admin/pending/{response_ids['response_1_id']}/edit",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
            json={"answer": edited_answer},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "saved" in data["message"].lower()

    async def test_edit_response_missing_answer(
        self, test_client, setup_pending_responses
    ):
        """Should return 422 when answer field is missing."""
        response_ids = setup_pending_responses
        response = test_client.post(
            f"/admin/pending/{response_ids['response_1_id']}/edit",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
            json={},
        )

        assert response.status_code == 422

    async def test_edit_response_empty_answer(
        self, test_client, setup_pending_responses
    ):
        """Should return 400 when answer is empty string."""
        response_ids = setup_pending_responses
        response = test_client.post(
            f"/admin/pending/{response_ids['response_1_id']}/edit",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
            json={"answer": ""},
        )

        assert response.status_code == 400
        data = response.json()
        assert "cannot be empty" in data["detail"].lower()

    async def test_edit_response_whitespace_only(
        self, test_client, setup_pending_responses
    ):
        """Should return 400 when answer is only whitespace."""
        response_ids = setup_pending_responses
        response = test_client.post(
            f"/admin/pending/{response_ids['response_1_id']}/edit",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
            json={"answer": "   "},
        )

        assert response.status_code == 400

    async def test_edit_response_not_found(self, test_client):
        """Should return 404 when response not found."""
        response = test_client.post(
            "/admin/pending/nonexistent-id-12345/edit",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
            json={"answer": "Edited answer"},
        )

        assert response.status_code == 404


class TestResponseFormat:
    """Tests for response format and data transformation."""

    async def test_response_has_required_fields(
        self, test_client, setup_pending_responses
    ):
        """Should return responses with all required fields."""
        response = test_client.get(
            "/admin/pending",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 200
        data = response.json()

        first_response = data["responses"][0]
        required_fields = [
            "id",
            "question",
            "answer",
            "confidence",
            "sources",
            "created_at",
        ]

        for field in required_fields:
            assert field in first_response, f"Missing required field: {field}"

    async def test_response_detected_version_mapping(
        self, test_client, setup_pending_responses
    ):
        """Should map detected_version from metadata to top-level field."""
        response = test_client.get(
            "/admin/pending",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 200
        data = response.json()

        first_response = data["responses"][0]
        # Frontend expects detected_version at top level
        assert "detected_version" in first_response
        assert first_response["detected_version"] == "Bisq 2"


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    async def test_service_exception_handling(
        self, test_client, test_settings, monkeypatch
    ):
        """Should return 500 when service raises exception."""

        async def mock_get_pending_responses(*args, **kwargs):
            raise Exception("Database error")

        monkeypatch.setattr(
            "app.services.pending_response_service.PendingResponseService.get_pending_responses",
            mock_get_pending_responses,
        )

        response = test_client.get(
            "/admin/pending",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 500
        data = response.json()
        assert "failed" in data["detail"].lower()

    async def test_approve_with_service_exception(
        self, test_client, test_settings, monkeypatch
    ):
        """Should return 500 when approve operation fails with exception."""

        async def mock_update_response(*args, **kwargs):
            raise Exception("Update failed")

        monkeypatch.setattr(
            "app.services.pending_response_service.PendingResponseService.update_response",
            mock_update_response,
        )

        response = test_client.post(
            "/admin/pending/response-1/approve",
            headers={"X-API-Key": "test-admin-key-with-sufficient-length-24chars"},
        )

        assert response.status_code == 500
