"""Tests for confirm_version API endpoint - Unknown Version Enhancement.

CRITICAL: This test file verifies Pydantic validation for the Unknown version enhancement:
- training_protocol REQUIRED when confirmed_version="Unknown" (400 error if missing)
- training_protocol must be "multisig_v1" or "bisq_easy" (enum validation)
- clarification endpoint saves with source="rag_bot_clarification"
- clarification endpoint sets 1.5x source weight
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.routes.admin.shadow_mode import router
from app.services.shadow_mode.repository import ShadowModeRepository
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_shadow.db"
        yield str(db_path)


@pytest.fixture
def repository(temp_db):
    """Create repository instance with temporary database."""
    return ShadowModeRepository(temp_db)


@pytest.fixture
def sample_response(repository):
    """Create and save a sample ShadowResponse for testing."""
    response = ShadowResponse(
        id="test-endpoint-1",
        channel_id="channel-1",
        user_id="user-1",
        messages=[{"role": "user", "content": "How do I trade?"}],
        synthesized_question="How do I trade?",
        detected_version="Unknown",
        version_confidence=0.30,
        status=ShadowStatus.PENDING_VERSION_REVIEW,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repository.add_response(response)
    return response


@pytest.fixture
def app(temp_db):
    """Create FastAPI test app with repository."""
    test_app = FastAPI()
    test_app.include_router(router)

    # Mock RAG service
    mock_rag_service = AsyncMock()
    mock_rag_service.query.return_value = {
        "answer": "Test RAG response",
        "sources": [],
        "confidence": 0.85,
        "routing_action": "send",
    }
    test_app.state.rag_service = mock_rag_service

    # Override repository singleton to use temp_db
    with patch("app.routes.admin.shadow_mode._db_path", temp_db):
        with patch("app.routes.admin.shadow_mode._repository", None):
            yield test_app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestPydanticValidation:
    """Test suite for Pydantic validation of ConfirmVersionRequest."""

    def test_confirm_version_unknown_without_training_protocol_returns_422(
        self, client, sample_response
    ):
        """Test that confirming 'Unknown' without training_protocol returns 422.

        FIXED: Changed @field_validator to mode='before' to trigger validation
        even when field is omitted from JSON.
        """
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "version_change_reason": "Ambiguous question",
                # Missing training_protocol - should trigger validation
            },
        )

        assert response.status_code == 422, (
            f"Expected 422 (Pydantic validation error), got {response.status_code}. "
            f"Response: {response.json()}"
        )

    def test_confirm_version_unknown_with_null_training_protocol_returns_422(
        self, client, sample_response
    ):
        """Test that confirming 'Unknown' with training_protocol=null returns 422."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "training_protocol": None,  # Explicit null - should fail
                "version_change_reason": "Needs clarification",
            },
        )

        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    def test_confirm_version_unknown_with_invalid_training_protocol_returns_422(
        self, client, sample_response
    ):
        """Test that invalid training_protocol enum returns 422."""
        # Try invalid value
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "training_protocol": "Bisq 3",  # Invalid - not in enum
                "version_change_reason": "Ambiguous",
            },
        )

        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        error_detail = response.json()
        error_msg = json.dumps(error_detail).lower()
        assert "multisig_v1" in error_msg or "bisq_easy" in error_msg

    def test_confirm_version_unknown_with_valid_training_protocol_returns_200(
        self, client, sample_response
    ):
        """Test that confirming 'Unknown' with valid training_protocol succeeds."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "training_protocol": "bisq_easy",  # Valid enum value
                "version_change_reason": "Generic question",
            },
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "message" in data
        assert "confirmed" in data["message"].lower()

    def test_confirm_version_bisq1_without_training_protocol_returns_200(
        self, client, sample_response
    ):
        """Test that confirming 'Bisq 1' WITHOUT training_protocol succeeds."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Bisq 1",
                "version_change_reason": "DAO keywords detected",
                # NO training_protocol - should succeed for non-Unknown
            },
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    def test_confirm_version_bisq2_without_training_protocol_returns_200(
        self, client, sample_response
    ):
        """Test that confirming 'Bisq 2' WITHOUT training_protocol succeeds."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Bisq 2",
                "version_change_reason": "Reputation keywords",
                # NO training_protocol - should succeed for non-Unknown
            },
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"


class TestClarificationEndpoint:
    """Test suite for /responses/clarification endpoint."""

    def test_clarification_endpoint_saves_with_correct_source(self, client, temp_db):
        """Verify /responses/clarification sets source='rag_bot_clarification'."""
        response = client.post(
            "/admin/shadow-mode/responses/clarification",
            params={
                "channel_id": "test-channel-1",
                "user_id": "test-user-1",
                "question": "How do I restore my wallet?",
                "clarifying_question": "Which Bisq version's wallet?",
                "user_answer": "I'm using Bisq 2",
                "detected_version": "Bisq 2",
            },
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "response_id" in data
        assert "source_weight" in data
        assert "1.5x" in data["source_weight"]

        # Verify saved to database with correct source
        repo = ShadowModeRepository(temp_db)
        saved_response = repo.get_response(data["response_id"])

        assert saved_response is not None
        assert saved_response.source == "rag_bot_clarification"
        assert saved_response.clarification_answer == "I'm using Bisq 2"
        assert saved_response.detected_version == "Bisq 2"
        assert saved_response.version_confidence == 0.95  # High confidence

    def test_clarification_endpoint_stores_all_fields(self, client, temp_db):
        """Verify clarification endpoint stores all required fields."""
        question = "What are the fees?"
        clarifying_q = "Are you asking about Bisq 1 or Bisq 2 fees?"
        user_answer = "Bisq 1"

        response = client.post(
            "/admin/shadow-mode/responses/clarification",
            params={
                "channel_id": "channel-2",
                "user_id": "user-2",
                "question": question,
                "clarifying_question": clarifying_q,
                "user_answer": user_answer,
                "detected_version": "Bisq 1",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify database storage
        repo = ShadowModeRepository(temp_db)
        saved = repo.get_response(data["response_id"])

        assert saved.synthesized_question == question
        assert saved.clarifying_question == clarifying_q
        assert saved.clarification_answer == user_answer
        assert saved.detected_version == "Bisq 1"
        assert saved.confirmed_version == "Bisq 1"  # Auto-confirmed
        assert not saved.requires_clarification  # Already clarified

    def test_clarification_endpoint_sets_high_confidence(self, client, temp_db):
        """Verify clarification endpoint sets confidence=0.95."""
        response = client.post(
            "/admin/shadow-mode/responses/clarification",
            params={
                "channel_id": "channel-3",
                "user_id": "user-3",
                "question": "How do I trade?",
                "clarifying_question": "Which Bisq version?",
                "user_answer": "Bisq 2",
                "detected_version": "Bisq 2",
            },
        )

        data = response.json()
        repo = ShadowModeRepository(temp_db)
        saved = repo.get_response(data["response_id"])

        assert saved.version_confidence == 0.95, "Should set 95% confidence"


class TestConfirmVersionStorageAndRAG:
    """Test suite for confirm_version storage and RAG integration."""

    def test_confirm_version_stores_custom_clarifying_question(
        self, client, sample_response, temp_db
    ):
        """Verify custom_clarifying_question is stored correctly."""
        custom_question = "Are you asking about Bisq 1's DAO or Bisq 2's reputation?"

        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "training_protocol": "multisig_v1",
                "custom_clarifying_question": custom_question,
            },
        )

        assert response.status_code == 200

        # Verify stored in database
        repo = ShadowModeRepository(temp_db)
        saved = repo.get_response(sample_response.id)
        assert saved.clarifying_question == custom_question

    def test_confirm_version_uses_training_protocol_for_rag(
        self, client, sample_response, app
    ):
        """Verify RAG uses training_protocol when confirmed_version='Unknown'."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "training_protocol": "multisig_v1",
                "version_change_reason": "Ambiguous",
            },
        )

        assert response.status_code == 200

        # Verify RAG was called with training_protocol
        mock_rag = app.state.rag_service
        mock_rag.query.assert_called_once()
        call_kwargs = mock_rag.query.call_args.kwargs
        assert call_kwargs["override_version"] == "multisig_v1"

    def test_confirm_version_uses_confirmed_version_for_rag_bisq1(
        self, client, sample_response, app
    ):
        """Verify RAG uses confirmed_version when not Unknown."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Bisq 1",
                "version_change_reason": "DAO keywords",
            },
        )

        assert response.status_code == 200

        # Verify RAG was called with confirmed_version
        mock_rag = app.state.rag_service
        call_kwargs = mock_rag.query.call_args.kwargs
        assert call_kwargs["override_version"] == "Bisq 1"

    def test_confirm_version_sets_requires_clarification_true(
        self, client, sample_response, temp_db
    ):
        """Verify requires_clarification=True when confirmed_version='Unknown'."""
        response = client.post(
            f"/admin/shadow-mode/responses/{sample_response.id}/confirm-version",
            json={
                "confirmed_version": "Unknown",
                "training_protocol": "bisq_easy",
            },
        )

        assert response.status_code == 200

        repo = ShadowModeRepository(temp_db)
        saved = repo.get_response(sample_response.id)
        assert saved.requires_clarification  # Should be True for Unknown


class TestErrorHandling:
    """Test suite for error handling in endpoints."""

    def test_confirm_version_nonexistent_response_returns_404(self, client):
        """Test confirming version for non-existent response returns 404."""
        response = client.post(
            "/admin/shadow-mode/responses/nonexistent-id/confirm-version",
            json={
                "confirmed_version": "Bisq 1",
            },
        )

        assert response.status_code == 404

    def test_clarification_endpoint_missing_params_returns_422(self, client):
        """Test clarification endpoint with missing params returns 422."""
        response = client.post(
            "/admin/shadow-mode/responses/clarification",
            params={
                "channel_id": "test",
                # Missing required params
            },
        )

        assert response.status_code == 422
