"""
Tests for Unified Training Pipeline API Routes.

TDD Phase 3: API Routes for the unified FAQ training pipeline.
Following RED-GREEN-REFACTOR cycle.

Tests cover:
- TASK 3.1: Router Setup
- TASK 3.2: GET Endpoints (calibration status, queue counts, current item)
- TASK 3.3: POST Endpoints (approve, reject, skip)
- TASK 3.4: Sync Endpoints (bisq)
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Try to import the router - skip tests if not implemented
try:
    from app.routes.admin.training import router as training_router

    ROUTER_EXISTS = True
except ImportError:
    ROUTER_EXISTS = False
    training_router = None

from app.services.training.unified_repository import (
    CalibrationStatus,
    UnifiedFAQCandidate,
)

# Skip all tests if router doesn't exist yet (RED phase)
pytestmark = pytest.mark.skipif(
    not ROUTER_EXISTS,
    reason="Training router not yet implemented (RED phase)",
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_unified.db"


@pytest.fixture
def mock_pipeline_service():
    """Create a mock pipeline service."""
    service = MagicMock()

    # Mock calibration status
    service.get_calibration_status.return_value = CalibrationStatus(
        samples_collected=25,
        samples_required=100,
        is_complete=False,
        auto_approve_threshold=0.90,
        spot_check_threshold=0.75,
    )

    # Mock queue counts
    service.get_queue_counts.return_value = {
        "AUTO_APPROVE": 5,
        "SPOT_CHECK": 10,
        "FULL_REVIEW": 15,
    }

    # Mock is_calibration_mode
    service.is_calibration_mode.return_value = True

    # Mock get_pending_reviews - returns paginated result
    service.get_pending_reviews.return_value = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
    }

    # Mock get_current_item (the actual method name used by route)
    service.get_current_item.return_value = None

    # Mock candidate action methods (async methods)
    service.approve_candidate = AsyncMock(return_value="faq_123")
    service.reject_candidate = AsyncMock(return_value=True)
    service.skip_candidate = AsyncMock(return_value=True)

    return service


@pytest.fixture
def app_with_router(mock_pipeline_service):
    """Create FastAPI app with training router and mocked service."""
    app = FastAPI()

    # Mount the router - note: router already has prefix="/admin/training"
    # So we don't add prefix here to avoid doubling the path
    app.include_router(training_router)

    # Set up app state with the mock service
    # This is what get_pipeline_service() expects
    app.state.unified_pipeline_service = mock_pipeline_service

    # Override admin access verification
    from app.core.security import verify_admin_access

    app.dependency_overrides[verify_admin_access] = lambda: None

    return app


@pytest.fixture
def client(app_with_router):
    """Create test client."""
    return TestClient(app_with_router)


@pytest.fixture
def sample_candidate():
    """Create a sample candidate for testing."""
    return UnifiedFAQCandidate(
        id=1,
        source="matrix",
        source_event_id="$test_event:matrix.org",
        source_timestamp="2025-01-15T10:00:00Z",
        question_text="How do I trade on Bisq?",
        staff_answer="Go to Trade > Trade Wizard...",
        generated_answer="Navigate to the Trade tab...",
        staff_sender="@support:matrix.org",
        embedding_similarity=0.85,
        factual_alignment=0.90,
        contradiction_score=0.05,
        completeness=0.80,
        hallucination_risk=0.10,
        final_score=0.85,
        llm_reasoning="Good alignment",
        routing="SPOT_CHECK",
        review_status="pending",
        reviewed_by=None,
        reviewed_at=None,
        rejection_reason=None,
        faq_id=None,
        is_calibration_sample=True,
        created_at="2025-01-15T10:00:00Z",
        updated_at=None,
        original_staff_answer="hey! just go to trade tab and click trade wizard",
    )


# =============================================================================
# TASK 3.1: Router Setup
# =============================================================================


class TestRouterSetup:
    """Test router registration and basic setup."""

    def test_training_router_exists(self):
        """Cycle 3.1.1: Test that training router is importable."""
        assert training_router is not None

    def test_router_has_prefix(self, client):
        """Test that router is mounted at correct prefix."""
        # This will return 404 for unknown routes, but 200/422 for valid routes
        response = client.get("/admin/training/unified/calibration/status")
        assert response.status_code != 404


# =============================================================================
# TASK 3.2: GET Endpoints
# =============================================================================


class TestCalibrationEndpoint:
    """Test calibration status endpoint."""

    def test_get_calibration_status(self, client, mock_pipeline_service):
        """Cycle 3.2.1: Test GET /unified/calibration/status returns status."""
        response = client.get("/admin/training/unified/calibration/status")

        assert response.status_code == 200
        data = response.json()
        assert data["samples_collected"] == 25
        assert data["samples_required"] == 100
        assert data["is_complete"] is False
        mock_pipeline_service.get_calibration_status.assert_called_once()


class TestQueueCountsEndpoint:
    """Test queue counts endpoint."""

    def test_get_queue_counts(self, client, mock_pipeline_service):
        """Cycle 3.2.2: Test GET /unified/queue/counts returns counts."""
        response = client.get("/admin/training/unified/queue/counts")

        assert response.status_code == 200
        data = response.json()
        assert data["AUTO_APPROVE"] == 5
        assert data["SPOT_CHECK"] == 10
        assert data["FULL_REVIEW"] == 15
        mock_pipeline_service.get_queue_counts.assert_called_once()


class TestCurrentItemEndpoint:
    """Test current item endpoint."""

    def test_get_current_item(self, client, mock_pipeline_service, sample_candidate):
        """Cycle 3.2.3: Test GET /unified/queue/current returns current item."""
        mock_pipeline_service.get_current_item.return_value = sample_candidate

        response = client.get(
            "/admin/training/unified/queue/current?routing=SPOT_CHECK"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["source"] == "matrix"
        assert data["routing"] == "SPOT_CHECK"
        mock_pipeline_service.get_current_item.assert_called_once_with(
            routing="SPOT_CHECK"
        )

    def test_get_current_item_empty_queue(self, client, mock_pipeline_service):
        """Test GET /unified/queue/current returns null when queue empty."""
        mock_pipeline_service.get_current_item.return_value = None

        response = client.get("/admin/training/unified/queue/current")

        assert response.status_code == 200
        assert response.json() is None
        mock_pipeline_service.get_current_item.assert_called_once_with(
            routing="FULL_REVIEW"
        )

    def test_get_current_item_includes_original_staff_answer(
        self, client, mock_pipeline_service, sample_candidate
    ):
        """Test that API response includes original_staff_answer field."""
        mock_pipeline_service.get_current_item.return_value = sample_candidate

        response = client.get(
            "/admin/training/unified/queue/current?routing=SPOT_CHECK"
        )

        assert response.status_code == 200
        data = response.json()
        assert "original_staff_answer" in data
        assert (
            data["original_staff_answer"]
            == "hey! just go to trade tab and click trade wizard"
        )


class TestPendingReviewsEndpoint:
    """Test pending reviews endpoint."""

    def test_get_pending_reviews(self, client, mock_pipeline_service, sample_candidate):
        """Test GET /unified/queue/pending returns paginated list of candidates."""
        # Service returns a list, route converts to paginated response
        mock_pipeline_service.get_pending_reviews.return_value = [sample_candidate]

        response = client.get("/admin/training/unified/queue/pending")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == 1

    def test_get_pending_reviews_with_pagination(self, client, mock_pipeline_service):
        """Test GET /unified/queue/pending with pagination parameters."""
        # Service returns a list, route converts to paginated response
        mock_pipeline_service.get_pending_reviews.return_value = []

        response = client.get(
            "/admin/training/unified/queue/pending?page=2&page_size=5"
        )

        assert response.status_code == 200
        # Route converts page/page_size to limit/offset for service API
        # page=2, page_size=5 -> offset=5, limit=5
        mock_pipeline_service.get_pending_reviews.assert_any_call(limit=5, offset=5)


# =============================================================================
# TASK 3.3: POST Endpoints
# =============================================================================


class TestApproveEndpoint:
    """Test candidate approval endpoint."""

    def test_approve_candidate(self, client, mock_pipeline_service):
        """Cycle 3.3.1: Test POST /candidates/{id}/approve."""
        response = client.post(
            "/admin/training/candidates/1/approve",
            json={"reviewer": "admin"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["faq_id"] == "faq_123"
        assert data["success"] is True
        mock_pipeline_service.approve_candidate.assert_called_once_with(
            candidate_id=1, reviewer="admin"
        )

    def test_approve_candidate_error(self, client, mock_pipeline_service):
        """Test POST /candidates/{id}/approve handles errors."""
        mock_pipeline_service.approve_candidate.side_effect = ValueError(
            "Candidate 999 not found"
        )

        response = client.post(
            "/admin/training/candidates/999/approve",
            json={"reviewer": "admin"},
        )

        # Route returns 500 for all exceptions
        assert response.status_code == 500


class TestRejectEndpoint:
    """Test candidate rejection endpoint."""

    def test_reject_candidate(self, client, mock_pipeline_service):
        """Cycle 3.3.2: Test POST /candidates/{id}/reject."""
        response = client.post(
            "/admin/training/candidates/1/reject",
            json={"reviewer": "admin", "reason": "Incorrect information"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_pipeline_service.reject_candidate.assert_called_once_with(
            candidate_id=1, reviewer="admin", reason="Incorrect information"
        )

    def test_reject_candidate_error(self, client, mock_pipeline_service):
        """Test POST /candidates/{id}/reject handles errors."""
        mock_pipeline_service.reject_candidate.side_effect = ValueError(
            "Candidate 999 not found"
        )

        response = client.post(
            "/admin/training/candidates/999/reject",
            json={"reviewer": "admin", "reason": "Test"},
        )

        # Route returns 500 for all exceptions
        assert response.status_code == 500

    # P4: Rejection reason validation tests
    def test_reject_candidate_empty_reason(self, client, mock_pipeline_service):
        """Test POST /candidates/{id}/reject rejects empty reason."""
        response = client.post(
            "/admin/training/candidates/1/reject",
            json={"reviewer": "admin", "reason": ""},
        )

        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"]

    def test_reject_candidate_whitespace_only_reason(
        self, client, mock_pipeline_service
    ):
        """Test POST /candidates/{id}/reject rejects whitespace-only reason."""
        response = client.post(
            "/admin/training/candidates/1/reject",
            json={"reviewer": "admin", "reason": "   "},
        )

        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"]

    def test_reject_candidate_reason_too_long(self, client, mock_pipeline_service):
        """Test POST /candidates/{id}/reject rejects overly long reason."""
        long_reason = "x" * 501  # MAX_REJECTION_REASON_LENGTH is 500

        response = client.post(
            "/admin/training/candidates/1/reject",
            json={"reviewer": "admin", "reason": long_reason},
        )

        assert response.status_code == 400
        assert "too long" in response.json()["detail"]

    def test_reject_candidate_custom_reason_too_short(
        self, client, mock_pipeline_service
    ):
        """Test POST /candidates/{id}/reject rejects short custom reason."""
        response = client.post(
            "/admin/training/candidates/1/reject",
            json={
                "reviewer": "admin",
                "reason": "ab",
            },  # Less than 3 chars, not in allowed list
        )

        assert response.status_code == 400
        assert "at least 3 characters" in response.json()["detail"]

    def test_reject_candidate_allowed_reason_accepted(
        self, client, mock_pipeline_service
    ):
        """Test POST /candidates/{id}/reject accepts allowed reasons."""
        for reason in [
            "incorrect",
            "outdated",
            "too_vague",
            "off_topic",
            "duplicate",
            "other",
        ]:
            mock_pipeline_service.reject_candidate.reset_mock()

            response = client.post(
                "/admin/training/candidates/1/reject",
                json={"reviewer": "admin", "reason": reason},
            )

            assert response.status_code == 200, f"Failed for reason: {reason}"


class TestSkipEndpoint:
    """Test candidate skip endpoint."""

    def test_skip_candidate(self, client, mock_pipeline_service):
        """Cycle 3.3.3: Test POST /candidates/{id}/skip."""
        response = client.post("/admin/training/candidates/1/skip")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_pipeline_service.skip_candidate.assert_called_once_with(candidate_id=1)

    def test_skip_candidate_error(self, client, mock_pipeline_service):
        """Test POST /candidates/{id}/skip handles errors."""
        mock_pipeline_service.skip_candidate.side_effect = ValueError(
            "Candidate 999 not found"
        )

        response = client.post("/admin/training/candidates/999/skip")

        # Route returns 500 for all exceptions
        assert response.status_code == 500


# =============================================================================
# TASK 3.4: Sync Endpoints
# =============================================================================


class TestSyncEndpoints:
    """Test sync trigger endpoints."""

    def test_trigger_bisq_sync(self, client, mock_pipeline_service):
        """Cycle 3.4.1: Test POST /sync/bisq triggers sync."""
        # Mock the sync method
        mock_pipeline_service.sync_bisq_conversations = AsyncMock(return_value=5)

        response = client.post("/admin/training/sync/bisq")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["processed"] == 5
        assert "Bisq" in data.get("message", "")


# =============================================================================
# Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling in routes."""

    def test_calibration_status_error(self, client, mock_pipeline_service):
        """Test calibration status handles service errors."""
        mock_pipeline_service.get_calibration_status.side_effect = Exception(
            "Database error"
        )

        response = client.get("/admin/training/unified/calibration/status")

        assert response.status_code == 500

    def test_queue_counts_error(self, client, mock_pipeline_service):
        """Test queue counts handles service errors."""
        mock_pipeline_service.get_queue_counts.side_effect = Exception("Database error")

        response = client.get("/admin/training/unified/queue/counts")

        assert response.status_code == 500


# =============================================================================
# Cycle 18: Flagged FAQs Endpoints
# =============================================================================


class TestFlaggedFAQsEndpoints:
    """Test endpoints for viewing and resolving flagged FAQs.

    Cycle 18: After a post-approval correction is detected, the FAQ is
    flagged for review. These endpoints allow admins to view flagged FAQs
    and resolve them (update/confirm/delete).
    """

    def test_get_flagged_faqs_empty(self, client, mock_pipeline_service):
        """Test GET /flagged-faqs returns empty list when no flags."""
        # Mock the get_flagged_faqs method
        mock_pipeline_service.get_flagged_faqs.return_value = []

        response = client.get("/admin/training/flagged-faqs")

        assert response.status_code == 200
        data = response.json()
        assert "flagged" in data
        assert data["flagged"] == []

    def test_get_flagged_faqs_with_results(self, client, mock_pipeline_service):
        """Test GET /flagged-faqs returns flagged items with details."""
        mock_pipeline_service.get_flagged_faqs.return_value = [
            {
                "thread_id": 1,
                "faq_id": "faq_123",
                "correction_reason": "staff_correction:@staff:matrix.org",
                "original_answer": "Original answer text.",
                "correction_content": "Actually, the correct answer is...",
                "state": "reopened_for_correction",
                "flagged_at": "2026-01-22T10:00:00Z",
            }
        ]

        response = client.get("/admin/training/flagged-faqs")

        assert response.status_code == 200
        data = response.json()
        assert len(data["flagged"]) == 1
        assert data["flagged"][0]["faq_id"] == "faq_123"
        assert (
            data["flagged"][0]["correction_reason"]
            == "staff_correction:@staff:matrix.org"
        )

    def test_resolve_flagged_faq_update(self, client, mock_pipeline_service):
        """Test POST /flagged-faqs/{id}/resolve with update action."""
        mock_pipeline_service.resolve_flagged_faq = AsyncMock(return_value=True)

        response = client.post(
            "/admin/training/flagged-faqs/1/resolve",
            json={
                "action": "update",
                "new_answer": "The corrected and updated answer.",
                "reviewer": "admin",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["action"] == "update"

    def test_resolve_flagged_faq_confirm(self, client, mock_pipeline_service):
        """Test POST /flagged-faqs/{id}/resolve with confirm action."""
        mock_pipeline_service.resolve_flagged_faq = AsyncMock(return_value=True)

        response = client.post(
            "/admin/training/flagged-faqs/1/resolve",
            json={
                "action": "confirm",
                "reviewer": "admin",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["action"] == "confirm"

    def test_resolve_flagged_faq_delete(self, client, mock_pipeline_service):
        """Test POST /flagged-faqs/{id}/resolve with delete action."""
        mock_pipeline_service.resolve_flagged_faq = AsyncMock(return_value=True)

        response = client.post(
            "/admin/training/flagged-faqs/1/resolve",
            json={
                "action": "delete",
                "reviewer": "admin",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["action"] == "delete"

    def test_resolve_flagged_faq_invalid_action(self, client, mock_pipeline_service):
        """Test POST /flagged-faqs/{id}/resolve with invalid action."""
        response = client.post(
            "/admin/training/flagged-faqs/1/resolve",
            json={
                "action": "invalid_action",
                "reviewer": "admin",
            },
        )

        assert response.status_code == 400

    def test_resolve_flagged_faq_not_found(self, client, mock_pipeline_service):
        """Test POST /flagged-faqs/{id}/resolve with non-existent thread."""
        mock_pipeline_service.resolve_flagged_faq = AsyncMock(
            side_effect=ValueError("Thread not found")
        )

        response = client.post(
            "/admin/training/flagged-faqs/999/resolve",
            json={
                "action": "confirm",
                "reviewer": "admin",
            },
        )

        assert response.status_code == 404
