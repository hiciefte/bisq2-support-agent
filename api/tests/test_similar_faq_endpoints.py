"""
Tests for Similar FAQ Review Queue API endpoints (Phase 7.1.4).

TDD: Write tests first, then implement endpoints to pass these tests.
"""

import os
import tempfile

import pytest
from app.core.security import verify_admin_access
from fastapi import FastAPI
from fastapi.testclient import TestClient


def mock_admin_access():
    """Mock admin access verification - always passes."""
    return True


class TestSimilarFaqEndpointsAuth:
    """Tests for authentication on similar FAQ endpoints."""

    @pytest.fixture
    def app(self):
        """Create a FastAPI app with the similar FAQ routes."""
        from app.routes.admin.similar_faqs import router

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return TestClient(app)

    def test_get_pending_requires_auth(self, client):
        """Test that GET /pending requires admin authentication."""
        response = client.get("/admin/similar-faqs/pending")
        assert response.status_code == 401

    def test_approve_requires_auth(self, client):
        """Test that POST /approve requires admin authentication."""
        response = client.post("/admin/similar-faqs/some-id/approve")
        assert response.status_code == 401

    def test_merge_requires_auth(self, client):
        """Test that POST /merge requires admin authentication."""
        response = client.post(
            "/admin/similar-faqs/some-id/merge", json={"mode": "replace"}
        )
        assert response.status_code == 401

    def test_dismiss_requires_auth(self, client):
        """Test that POST /dismiss requires admin authentication."""
        response = client.post("/admin/similar-faqs/some-id/dismiss")
        assert response.status_code == 401


class TestSimilarFaqEndpointsGetPending:
    """Tests for GET /admin/similar-faqs/pending endpoint."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database file for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def mock_repository(self, temp_db_path):
        """Create a mock repository with sample data."""
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        # No need to insert FAQs - matched_faq_id references external faqs.db
        yield repo
        repo.close()

    @pytest.fixture
    def app_with_mock_auth(self, mock_repository):
        """Create app with mocked auth and repository."""
        from app.routes.admin.similar_faqs import router

        app = FastAPI()
        app.include_router(router)

        # Override auth dependency
        app.dependency_overrides[verify_admin_access] = mock_admin_access

        # Set repository in app state
        app.state.similar_faq_repository = mock_repository

        return app

    @pytest.fixture
    def authenticated_client(self, app_with_mock_auth):
        """Create an authenticated test client."""
        return TestClient(app_with_mock_auth)

    def test_get_pending_returns_empty_list(self, authenticated_client):
        """Test GET /pending returns empty list when no pending candidates."""
        response = authenticated_client.get("/admin/similar-faqs/pending")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_pending_returns_candidates(
        self, authenticated_client, mock_repository
    ):
        """Test GET /pending returns pending candidates."""
        # Add a candidate with matched FAQ details (denormalized)
        mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=42,
            similarity=0.92,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.get("/admin/similar-faqs/pending")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["extracted_question"] == "How do I buy bitcoin?"
        assert data["items"][0]["matched_question"] == "How can I purchase BTC?"


class TestSimilarFaqEndpointsApprove:
    """Tests for POST /admin/similar-faqs/{id}/approve endpoint."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def mock_repository(self, temp_db_path):
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        # No need to insert FAQs - matched_faq_id references external faqs.db
        yield repo
        repo.close()

    @pytest.fixture
    def app_with_mock_auth(self, mock_repository):
        from app.routes.admin.similar_faqs import router

        app = FastAPI()
        app.include_router(router)

        # Override auth dependency
        app.dependency_overrides[verify_admin_access] = mock_admin_access

        # Set repository in app state
        app.state.similar_faq_repository = mock_repository

        return app

    @pytest.fixture
    def authenticated_client(self, app_with_mock_auth):
        return TestClient(app_with_mock_auth)

    def test_approve_success(self, authenticated_client, mock_repository):
        """Test successful approval of a candidate."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/approve"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify candidate status changed
        updated = mock_repository.get_candidate_by_id(candidate.id)
        assert updated.status == "approved"

    def test_approve_nonexistent_returns_404(self, authenticated_client):
        """Test approving non-existent candidate returns 404."""
        response = authenticated_client.post(
            "/admin/similar-faqs/non-existent-id/approve"
        )

        assert response.status_code == 404

    def test_approve_already_resolved_returns_409(
        self, authenticated_client, mock_repository
    ):
        """Test approving already resolved candidate returns 409."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )
        mock_repository.approve_candidate(candidate.id, "admin1@example.com")

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/approve"
        )

        assert response.status_code == 409


class TestSimilarFaqEndpointsMerge:
    """Tests for POST /admin/similar-faqs/{id}/merge endpoint."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def mock_repository(self, temp_db_path):
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        yield repo
        repo.close()

    @pytest.fixture
    def mock_faq_service(self):
        """Create a mock FAQ service for testing."""
        from unittest.mock import MagicMock

        from app.models.faq import FAQIdentifiedItem

        mock_service = MagicMock()

        # Create a mock FAQ that will be returned by get_all_faqs
        mock_faq = FAQIdentifiedItem(
            id="1",
            question="How can I purchase BTC?",
            answer="Use Bisq Easy for safe purchases.",
            category="Trading",
            source="Manual",
            verified=True,
            protocol="bisq_easy",
        )

        # Setup mock methods
        mock_service.get_all_faqs.return_value = [mock_faq]
        mock_service.update_faq.return_value = mock_faq

        return mock_service

    @pytest.fixture
    def app_with_mock_auth_and_faq_service(self, mock_repository, mock_faq_service):
        from app.routes.admin.similar_faqs import router

        app = FastAPI()
        app.include_router(router)

        # Override auth dependency
        app.dependency_overrides[verify_admin_access] = mock_admin_access

        # Set repository and faq_service in app state
        app.state.similar_faq_repository = mock_repository
        app.state.faq_service = mock_faq_service

        return app

    @pytest.fixture
    def app_with_mock_auth(self, mock_repository):
        """App without mocked FAQ service - for 404 tests."""
        from app.routes.admin.similar_faqs import router

        app = FastAPI()
        app.include_router(router)

        # Override auth dependency
        app.dependency_overrides[verify_admin_access] = mock_admin_access

        # Set repository in app state
        app.state.similar_faq_repository = mock_repository

        return app

    @pytest.fixture
    def authenticated_client(self, app_with_mock_auth_and_faq_service):
        return TestClient(app_with_mock_auth_and_faq_service)

    @pytest.fixture
    def authenticated_client_no_faq_service(self, app_with_mock_auth):
        return TestClient(app_with_mock_auth)

    def test_merge_replace_success(
        self, authenticated_client, mock_repository, mock_faq_service
    ):
        """Test successful merge with replace mode updates FAQ."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/merge",
            json={"mode": "replace"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["merged_faq_id"] == "1"

        # Verify candidate status changed
        updated = mock_repository.get_candidate_by_id(candidate.id)
        assert updated.status == "merged"

        # Verify FAQ was updated with replaced content
        mock_faq_service.update_faq.assert_called_once()
        call_args = mock_faq_service.update_faq.call_args
        assert call_args[0][0] == "1"  # faq_id
        updated_faq_item = call_args[0][1]
        assert updated_faq_item.question == "How do I buy bitcoin?"  # Replaced
        assert updated_faq_item.answer == "Use Bisq Easy."  # Replaced

    def test_merge_append_success(
        self, authenticated_client, mock_repository, mock_faq_service
    ):
        """Test successful merge with append mode appends to FAQ."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Additional tip: Use escrow.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/merge",
            json={"mode": "append"},
        )

        assert response.status_code == 200

        # Verify FAQ was updated with appended content
        mock_faq_service.update_faq.assert_called_once()
        call_args = mock_faq_service.update_faq.call_args
        updated_faq_item = call_args[0][1]
        # Question should be kept original for append mode
        assert updated_faq_item.question == "How can I purchase BTC?"
        # Answer should have both original and new content with separator
        assert "Use Bisq Easy for safe purchases." in updated_faq_item.answer
        assert "---" in updated_faq_item.answer
        assert "Additional tip: Use escrow." in updated_faq_item.answer

    def test_merge_triggers_vectorstore_rebuild(
        self, authenticated_client, mock_repository, mock_faq_service
    ):
        """Test that merge triggers FAQ update which marks vectorstore for rebuild."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/merge",
            json={"mode": "replace"},
        )

        assert response.status_code == 200
        # The update_faq call triggers the vectorstore state manager
        # via the callback mechanism in production
        mock_faq_service.update_faq.assert_called_once()

    def test_merge_invalid_mode_returns_422(
        self, authenticated_client, mock_repository
    ):
        """Test merge with invalid mode returns 422."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/merge",
            json={"mode": "invalid"},
        )

        assert response.status_code == 422

    def test_merge_nonexistent_candidate_returns_404(self, authenticated_client):
        """Test merging non-existent candidate returns 404."""
        response = authenticated_client.post(
            "/admin/similar-faqs/non-existent-id/merge",
            json={"mode": "replace"},
        )

        assert response.status_code == 404

    def test_merge_nonexistent_matched_faq_returns_404(
        self, mock_repository, mock_faq_service
    ):
        """Test merging when matched FAQ doesn't exist returns 404."""
        from app.routes.admin.similar_faqs import router

        # Configure mock to return empty list (no matching FAQ)
        mock_faq_service.get_all_faqs.return_value = []

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[verify_admin_access] = mock_admin_access
        app.state.similar_faq_repository = mock_repository
        app.state.faq_service = mock_faq_service

        client = TestClient(app)

        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=999,  # Non-existent FAQ ID
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = client.post(
            f"/admin/similar-faqs/{candidate.id}/merge",
            json={"mode": "replace"},
        )

        assert response.status_code == 404
        assert "Matched FAQ" in response.json()["detail"]


class TestSimilarFaqEndpointsDismiss:
    """Tests for POST /admin/similar-faqs/{id}/dismiss endpoint."""

    @pytest.fixture
    def temp_db_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
            for suffix in ["-wal", "-shm"]:
                try:
                    os.unlink(db_path + suffix)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass

    @pytest.fixture
    def mock_repository(self, temp_db_path):
        from app.services.faq.similar_faq_repository import SimilarFaqRepository

        repo = SimilarFaqRepository(temp_db_path)
        # No need to insert FAQs - matched_faq_id references external faqs.db
        yield repo
        repo.close()

    @pytest.fixture
    def app_with_mock_auth(self, mock_repository):
        from app.routes.admin.similar_faqs import router

        app = FastAPI()
        app.include_router(router)

        # Override auth dependency
        app.dependency_overrides[verify_admin_access] = mock_admin_access

        # Set repository in app state
        app.state.similar_faq_repository = mock_repository

        return app

    @pytest.fixture
    def authenticated_client(self, app_with_mock_auth):
        return TestClient(app_with_mock_auth)

    def test_dismiss_success(self, authenticated_client, mock_repository):
        """Test successful dismissal of a candidate."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/dismiss"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify candidate status changed
        updated = mock_repository.get_candidate_by_id(candidate.id)
        assert updated.status == "dismissed"

    def test_dismiss_with_reason(self, authenticated_client, mock_repository):
        """Test dismissal with reason."""
        candidate = mock_repository.add_candidate(
            extracted_question="How do I buy bitcoin?",
            extracted_answer="Use Bisq Easy.",
            matched_faq_id=1,
            similarity=0.85,
            matched_question="How can I purchase BTC?",
            matched_answer="Use Bisq Easy for safe purchases.",
            matched_category="Trading",
        )

        response = authenticated_client.post(
            f"/admin/similar-faqs/{candidate.id}/dismiss",
            json={"reason": "Exact duplicate"},
        )

        assert response.status_code == 200

        # Verify reason stored
        updated = mock_repository.get_candidate_by_id(candidate.id)
        assert updated.dismiss_reason == "Exact duplicate"

    def test_dismiss_nonexistent_returns_404(self, authenticated_client):
        """Test dismissing non-existent candidate returns 404."""
        response = authenticated_client.post(
            "/admin/similar-faqs/non-existent-id/dismiss"
        )

        assert response.status_code == 404
