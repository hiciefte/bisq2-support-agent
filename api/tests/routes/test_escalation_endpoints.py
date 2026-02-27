"""
Tests for Escalation Learning Pipeline API Routes (E07).

TDD Phase: API Routes for the escalation learning pipeline.
Following RED-GREEN-REFACTOR cycle.

Tests cover:
- Admin escalation endpoints (list, counts, claim, respond, generate-faq, close)
- User polling endpoint (get response status)
- Authentication and error handling
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Try to import the routers - skip tests if not implemented
try:
    from app.routes.admin.escalations import router as admin_escalation_router

    ADMIN_ROUTER_EXISTS = True
except ImportError:
    ADMIN_ROUTER_EXISTS = False
    admin_escalation_router = None

try:
    from app.routes.escalation_polling import router as polling_router

    POLLING_ROUTER_EXISTS = True
except ImportError:
    POLLING_ROUTER_EXISTS = False
    polling_router = None

from app.models.escalation import (
    Escalation,
    EscalationAlreadyClaimedError,
    EscalationCountsResponse,
    EscalationDeliveryStatus,
    EscalationListResponse,
    EscalationNotFoundError,
    EscalationNotRespondedError,
    EscalationPriority,
    EscalationStatus,
)
from app.services.faq.duplicate_guard import DuplicateFAQError

# Mark tests to skip if routers don't exist yet (RED phase)
admin_router_tests = pytest.mark.skipif(
    not ADMIN_ROUTER_EXISTS,
    reason="Admin escalation router not yet implemented (RED phase)",
)

polling_router_tests = pytest.mark.skipif(
    not POLLING_ROUTER_EXISTS,
    reason="Polling router not yet implemented (RED phase)",
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_escalations.db"


@pytest.fixture
def mock_escalation_service():
    """Create a mock escalation service."""
    service = MagicMock()

    # Mock sample escalation data
    sample_escalation = Escalation(
        id=1,
        message_id="12345678-1234-1234-1234-123456789abc",
        channel="matrix",
        user_id="@user:matrix.org",
        username="testuser",
        channel_metadata={"room_id": "!room:matrix.org"},
        question="How do I set up Bisq?",
        ai_draft_answer="Here's how to set up Bisq...",
        confidence_score=0.65,
        routing_action="needs_human",
        routing_reason="Low confidence on setup questions",
        sources=[],
        staff_answer=None,
        staff_id=None,
        delivery_status=EscalationDeliveryStatus.NOT_REQUIRED,
        delivery_error=None,
        delivery_attempts=0,
        last_delivery_at=None,
        generated_faq_id=None,
        status=EscalationStatus.PENDING,
        priority=EscalationPriority.NORMAL,
        created_at=datetime(2025, 1, 15, 10, 0, 0),
        claimed_at=None,
        responded_at=None,
        closed_at=None,
    )

    # Mock list_escalations (async, returns EscalationListResponse)
    service.list_escalations = AsyncMock(
        return_value=EscalationListResponse(
            escalations=[sample_escalation],
            total=1,
            limit=20,
            offset=0,
        )
    )

    # Mock get_escalation_counts (async, returns EscalationCountsResponse)
    service.get_escalation_counts = AsyncMock(
        return_value=EscalationCountsResponse(
            pending=5,
            in_review=2,
            responded=10,
            closed=3,
            total=20,
        )
    )

    # Mock repository for direct access
    mock_repository = MagicMock()
    mock_repository.get_by_id = AsyncMock(return_value=sample_escalation)
    mock_repository.get_by_message_id = AsyncMock(return_value=sample_escalation)
    service.repository = mock_repository

    # Mock claim_escalation (async)
    claimed_escalation = Escalation(
        **{
            **sample_escalation.model_dump(),
            "status": EscalationStatus.IN_REVIEW,
            "staff_id": "admin1",
            "claimed_at": datetime(2025, 1, 15, 11, 0, 0),
        }
    )
    service.claim_escalation = AsyncMock(return_value=claimed_escalation)

    # Mock respond_to_escalation (async)
    responded_escalation = Escalation(
        **{
            **sample_escalation.model_dump(),
            "status": EscalationStatus.RESPONDED,
            "staff_answer": "Here is the answer...",
            "staff_id": "admin1",
            "responded_at": datetime(2025, 1, 15, 12, 0, 0),
        }
    )
    service.respond_to_escalation = AsyncMock(return_value=responded_escalation)

    # Mock generate_faq_from_escalation (async)
    service.generate_faq_from_escalation = AsyncMock(
        return_value={"faq_id": "faq_123", "status": "created"}
    )

    # Mock close_escalation (async)
    closed_escalation = Escalation(
        **{
            **sample_escalation.model_dump(),
            "status": EscalationStatus.CLOSED,
            "closed_at": datetime(2025, 1, 15, 13, 0, 0),
        }
    )
    service.close_escalation = AsyncMock(return_value=closed_escalation)

    return service


@pytest.fixture
def admin_app(mock_escalation_service):
    """Create FastAPI app with admin escalation router and mocked service."""
    if not ADMIN_ROUTER_EXISTS:
        pytest.skip("Admin router not implemented yet")

    app = FastAPI()
    app.include_router(admin_escalation_router)
    app.state.escalation_service = mock_escalation_service

    # Override admin access verification
    from app.core.security import verify_admin_access
    from app.routes.admin.escalations import get_escalation_service

    app.dependency_overrides[verify_admin_access] = lambda: None
    # Override the service dependency to return our mock
    app.dependency_overrides[get_escalation_service] = lambda: mock_escalation_service

    return app


@pytest.fixture
def admin_client(admin_app):
    """Create test client for admin routes."""
    return TestClient(admin_app)


@pytest.fixture
def polling_app(mock_escalation_service):
    """Create FastAPI app with polling router and mocked service."""
    if not POLLING_ROUTER_EXISTS:
        pytest.skip("Polling router not implemented yet")

    app = FastAPI()
    app.include_router(polling_router)
    app.state.escalation_service = mock_escalation_service

    # Override the service dependency to return our mock
    from app.routes.admin.escalations import get_escalation_service

    app.dependency_overrides[get_escalation_service] = lambda: mock_escalation_service

    return app


@pytest.fixture
def polling_client(polling_app):
    """Create test client for polling routes."""
    return TestClient(polling_app)


# =============================================================================
# Admin Endpoint Tests
# =============================================================================


@admin_router_tests
class TestListEscalationsEndpoint:
    """Tests for GET /admin/escalations."""

    def test_list_requires_admin_auth(self):
        """Test that listing escalations requires admin authentication."""
        if not ADMIN_ROUTER_EXISTS:
            pytest.skip("Admin router not implemented yet")

        # Create app without auth override
        app = FastAPI()
        app.include_router(admin_escalation_router)
        client = TestClient(app)

        response = client.get("/admin/escalations")
        assert response.status_code in [401, 403]

    def test_list_returns_paginated_results(
        self, admin_client, mock_escalation_service
    ):
        """Test that list returns paginated EscalationListResponse."""
        response = admin_client.get("/admin/escalations")
        assert response.status_code == 200

        data = response.json()
        assert "escalations" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert data["total"] == 1
        assert len(data["escalations"]) == 1

        # Verify service was called correctly
        mock_escalation_service.list_escalations.assert_called_once()

    def test_list_filter_by_status(self, admin_client, mock_escalation_service):
        """Test filtering escalations by status."""
        response = admin_client.get("/admin/escalations?status=pending")
        assert response.status_code == 200

        # Verify filter was passed to service
        call_kwargs = mock_escalation_service.list_escalations.call_args[1]
        assert call_kwargs["status"] == EscalationStatus.PENDING

    def test_list_filter_by_channel(self, admin_client, mock_escalation_service):
        """Test filtering escalations by channel."""
        response = admin_client.get("/admin/escalations?channel=matrix")
        assert response.status_code == 200

        # Verify filter was passed to service
        call_kwargs = mock_escalation_service.list_escalations.call_args[1]
        assert call_kwargs["channel"] == "matrix"

    def test_list_filter_by_search(self, admin_client, mock_escalation_service):
        """Test filtering escalations by free-text search."""
        response = admin_client.get("/admin/escalations?search=Bisq+Easy")
        assert response.status_code == 200

        call_kwargs = mock_escalation_service.list_escalations.call_args[1]
        assert call_kwargs["search"] == "Bisq Easy"


@admin_router_tests
class TestGetEscalationCountsEndpoint:
    """Tests for GET /admin/escalations/counts."""

    def test_counts_returns_all_statuses(self, admin_client, mock_escalation_service):
        """Test that counts endpoint returns all status counts."""
        response = admin_client.get("/admin/escalations/counts")
        assert response.status_code == 200

        data = response.json()
        assert "pending" in data
        assert "in_review" in data
        assert "responded" in data
        assert "closed" in data
        assert "total" in data

        assert data["pending"] == 5
        assert data["total"] == 20

    def test_counts_requires_admin_auth(self):
        """Test that counts endpoint requires admin authentication."""
        if not ADMIN_ROUTER_EXISTS:
            pytest.skip("Admin router not implemented yet")

        # Create app without auth override
        app = FastAPI()
        app.include_router(admin_escalation_router)
        client = TestClient(app)

        response = client.get("/admin/escalations/counts")
        assert response.status_code in [401, 403]


@admin_router_tests
class TestClaimEndpoint:
    """Tests for POST /admin/escalations/{escalation_id}/claim."""

    def test_claim_returns_updated_escalation(
        self, admin_client, mock_escalation_service
    ):
        """Test that claiming an escalation returns the updated escalation."""
        claim_request = {"staff_id": "admin1"}

        response = admin_client.post("/admin/escalations/1/claim", json=claim_request)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "in_review"
        assert data["staff_id"] == "admin1"
        assert data["claimed_at"] is not None

        # Verify service was called
        mock_escalation_service.claim_escalation.assert_called_once_with(1, "admin1")

    def test_claim_already_claimed_returns_409(
        self, admin_client, mock_escalation_service
    ):
        """Test that claiming an already claimed escalation returns 409."""
        mock_escalation_service.claim_escalation.side_effect = (
            EscalationAlreadyClaimedError("Already claimed")
        )

        claim_request = {"staff_id": "admin2"}
        response = admin_client.post("/admin/escalations/1/claim", json=claim_request)
        assert response.status_code == 409

    def test_claim_nonexistent_returns_404(self, admin_client, mock_escalation_service):
        """Test that claiming a nonexistent escalation returns 404."""
        mock_escalation_service.claim_escalation.side_effect = EscalationNotFoundError(
            "Not found"
        )

        claim_request = {"staff_id": "admin1"}
        response = admin_client.post("/admin/escalations/999/claim", json=claim_request)
        assert response.status_code == 404


@admin_router_tests
class TestRespondEndpoint:
    """Tests for POST /admin/escalations/{escalation_id}/respond."""

    def test_respond_returns_updated_escalation(
        self, admin_client, mock_escalation_service
    ):
        """Test that responding to an escalation returns the updated escalation."""
        respond_request = {
            "staff_answer": "Here is the answer...",
            "staff_id": "admin1",
        }

        response = admin_client.post(
            "/admin/escalations/1/respond", json=respond_request
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "responded"
        assert data["staff_answer"] == "Here is the answer..."
        assert data["responded_at"] is not None

        # Verify service was called
        mock_escalation_service.respond_to_escalation.assert_called_once()

    def test_respond_empty_answer_returns_422(self, admin_client):
        """Test that responding with empty answer returns 422 validation error."""
        respond_request = {"staff_answer": "", "staff_id": "admin1"}

        response = admin_client.post(
            "/admin/escalations/1/respond", json=respond_request
        )
        assert response.status_code == 422

    def test_respond_nonexistent_returns_404(
        self, admin_client, mock_escalation_service
    ):
        """Test that responding to a nonexistent escalation returns 404."""
        mock_escalation_service.respond_to_escalation.side_effect = (
            EscalationNotFoundError("Not found")
        )

        respond_request = {
            "staff_answer": "Here is the answer...",
            "staff_id": "admin1",
        }
        response = admin_client.post(
            "/admin/escalations/999/respond", json=respond_request
        )
        assert response.status_code == 404


@admin_router_tests
class TestGenerateFAQEndpoint:
    """Tests for POST /admin/escalations/{escalation_id}/generate-faq."""

    def test_generate_faq_returns_faq_data(self, admin_client, mock_escalation_service):
        """Test that generating FAQ returns FAQ creation data."""
        faq_request = {
            "question": "How do I set up Bisq?",
            "answer": "Here is how...",
            "category": "General",
        }

        response = admin_client.post(
            "/admin/escalations/1/generate-faq", json=faq_request
        )
        assert response.status_code == 200

        data = response.json()
        assert "faq_id" in data
        assert data["faq_id"] == "faq_123"

        # Verify service was called
        mock_escalation_service.generate_faq_from_escalation.assert_called_once()
        args = mock_escalation_service.generate_faq_from_escalation.call_args.args
        assert args[-1] is False

    def test_generate_faq_not_responded_returns_400(
        self, admin_client, mock_escalation_service
    ):
        """Test that generating FAQ from non-responded escalation returns 400."""
        mock_escalation_service.generate_faq_from_escalation.side_effect = (
            EscalationNotRespondedError("Not responded yet")
        )

        faq_request = {
            "question": "How do I set up Bisq?",
            "answer": "Here is how...",
            "category": "General",
        }

        response = admin_client.post(
            "/admin/escalations/1/generate-faq", json=faq_request
        )
        assert response.status_code == 400

    def test_generate_faq_duplicate_returns_409(
        self, admin_client, mock_escalation_service
    ):
        mock_escalation_service.generate_faq_from_escalation.side_effect = (
            DuplicateFAQError(
                "Cannot create FAQ: 1 similar FAQ(s) already exist",
                similar_faqs=[
                    {
                        "id": 77,
                        "question": "How do I set up Bisq?",
                        "answer": "Install and run.",
                        "similarity": 0.92,
                        "category": "General",
                        "protocol": "bisq_easy",
                    }
                ],
            )
        )

        faq_request = {
            "question": "How do I set up Bisq?",
            "answer": "Here is how...",
            "category": "General",
        }

        response = admin_client.post(
            "/admin/escalations/1/generate-faq", json=faq_request
        )

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["error"] == "duplicate_faq"
        assert data["detail"]["escalation_id"] == 1
        assert data["detail"]["similar_faqs"][0]["id"] == 77

    def test_generate_faq_force_override_passed_to_service(
        self, admin_client, mock_escalation_service
    ):
        faq_request = {
            "question": "How do I set up Bisq?",
            "answer": "Here is how...",
            "category": "General",
            "force": True,
        }

        response = admin_client.post(
            "/admin/escalations/1/generate-faq", json=faq_request
        )

        assert response.status_code == 200
        args = mock_escalation_service.generate_faq_from_escalation.call_args.args
        assert args[-1] is True


@admin_router_tests
class TestCloseEndpoint:
    """Tests for POST /admin/escalations/{escalation_id}/close."""

    def test_close_returns_updated_escalation(
        self, admin_client, mock_escalation_service
    ):
        """Test that closing an escalation returns the updated escalation."""
        response = admin_client.post("/admin/escalations/1/close")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "closed"
        assert data["closed_at"] is not None

        # Verify service was called
        mock_escalation_service.close_escalation.assert_called_once_with(1)


# =============================================================================
# User Polling Endpoint Tests
# =============================================================================


@polling_router_tests
class TestPollingEndpoint:
    """Tests for GET /escalations/{message_id}/response."""

    def test_poll_pending_returns_pending_status(
        self, polling_client, mock_escalation_service
    ):
        """Test polling a pending escalation returns pending status."""
        # Mock pending escalation
        pending_escalation = Escalation(
            id=1,
            message_id="12345678-1234-1234-1234-123456789abc",
            channel="matrix",
            user_id="@user:matrix.org",
            username="testuser",
            channel_metadata={},
            question="Test question",
            ai_draft_answer="Draft answer",
            confidence_score=0.65,
            routing_action="needs_human",
            routing_reason=None,
            sources=[],
            staff_answer=None,
            staff_id=None,
            delivery_status=EscalationDeliveryStatus.NOT_REQUIRED,
            delivery_error=None,
            delivery_attempts=0,
            last_delivery_at=None,
            generated_faq_id=None,
            status=EscalationStatus.PENDING,
            priority=EscalationPriority.NORMAL,
            created_at=datetime(2025, 1, 15, 10, 0, 0),
            claimed_at=None,
            responded_at=None,
            closed_at=None,
        )
        mock_escalation_service.repository.get_by_message_id.return_value = (
            pending_escalation
        )

        response = polling_client.get(
            "/escalations/12345678-1234-1234-1234-123456789abc/response"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "pending"
        assert data["staff_answer"] is None

    def test_poll_responded_returns_answer(
        self, polling_client, mock_escalation_service
    ):
        """Test polling a responded escalation returns the staff answer."""
        # Mock responded escalation
        responded_escalation = Escalation(
            id=1,
            message_id="12345678-1234-1234-1234-123456789abc",
            channel="matrix",
            user_id="@user:matrix.org",
            username="testuser",
            channel_metadata={},
            question="Test question",
            ai_draft_answer="Draft answer",
            confidence_score=0.65,
            routing_action="needs_human",
            routing_reason=None,
            sources=[],
            staff_answer="Final staff answer",
            staff_id="admin1",
            delivery_status=EscalationDeliveryStatus.DELIVERED,
            delivery_error=None,
            delivery_attempts=1,
            last_delivery_at=datetime(2025, 1, 15, 12, 30, 0),
            generated_faq_id=None,
            status=EscalationStatus.RESPONDED,
            priority=EscalationPriority.NORMAL,
            created_at=datetime(2025, 1, 15, 10, 0, 0),
            claimed_at=datetime(2025, 1, 15, 11, 0, 0),
            responded_at=datetime(2025, 1, 15, 12, 0, 0),
            closed_at=None,
        )
        mock_escalation_service.repository.get_by_message_id.return_value = (
            responded_escalation
        )

        response = polling_client.get(
            "/escalations/12345678-1234-1234-1234-123456789abc/response"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "resolved"
        assert data["staff_answer"] == "Final staff answer"
        assert data["responded_at"] is not None
        assert data["resolution"] == "responded"

    def test_poll_closed_returns_resolved_without_answer(
        self, polling_client, mock_escalation_service
    ):
        """Test polling a closed escalation returns resolved status."""
        # Mock closed escalation without answer
        closed_escalation = Escalation(
            id=1,
            message_id="12345678-1234-1234-1234-123456789abc",
            channel="matrix",
            user_id="@user:matrix.org",
            username="testuser",
            channel_metadata={},
            question="Test question",
            ai_draft_answer="Draft answer",
            confidence_score=0.65,
            routing_action="needs_human",
            routing_reason=None,
            sources=[],
            staff_answer=None,
            staff_id=None,
            delivery_status=EscalationDeliveryStatus.NOT_REQUIRED,
            delivery_error=None,
            delivery_attempts=0,
            last_delivery_at=None,
            generated_faq_id=None,
            status=EscalationStatus.CLOSED,
            priority=EscalationPriority.NORMAL,
            created_at=datetime(2025, 1, 15, 10, 0, 0),
            claimed_at=None,
            responded_at=None,
            closed_at=datetime(2025, 1, 15, 13, 0, 0),
        )
        mock_escalation_service.repository.get_by_message_id.return_value = (
            closed_escalation
        )

        response = polling_client.get(
            "/escalations/12345678-1234-1234-1234-123456789abc/response"
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "resolved"
        assert data["staff_answer"] is None
        assert data["resolution"] == "closed"
        assert data["closed_at"] is not None

    def test_poll_invalid_uuid_returns_422(self, polling_client):
        """Test polling with invalid UUID format returns 422."""
        response = polling_client.get("/escalations/invalid-uuid/response")
        assert response.status_code == 422

    def test_poll_not_found_returns_404(self, polling_client, mock_escalation_service):
        """Test polling unknown message_id returns 404 with not_found status."""
        mock_escalation_service.repository.get_by_message_id.return_value = None

        response = polling_client.get(
            "/escalations/00000000-0000-0000-0000-000000000000/response"
        )
        assert response.status_code == 404

        data = response.json()
        assert data["detail"]["status"] == "not_found"
