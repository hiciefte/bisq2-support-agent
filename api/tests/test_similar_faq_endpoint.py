"""
Tests for Similar FAQ check endpoint.

TDD Phase 3: Tests for POST /admin/faqs/check-similar endpoint.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient


class TestCheckSimilarEndpoint:
    """Tests for POST /admin/faqs/check-similar endpoint."""

    @pytest.fixture
    def mock_rag_service(self):
        """Create a mock RAG service with search_faq_similarity method."""
        mock = MagicMock()
        mock.search_faq_similarity = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def client(self, mock_rag_service):
        """Create test client with mocked dependencies."""
        # Set test admin API key (24+ chars to pass security validation)
        os.environ["ADMIN_API_KEY"] = "test-admin-key-with-sufficient-length-24chars"

        from app.main import app

        # Override the RAG service dependency
        app.state.rag_service = mock_rag_service

        # Use Bearer token format for authentication
        return TestClient(
            app,
            headers={
                "Authorization": "Bearer test-admin-key-with-sufficient-length-24chars"
            },
        )

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_similar_faqs(
        self, client, mock_rag_service
    ):
        """Test that empty response is returned when no similar FAQs exist."""
        mock_rag_service.search_faq_similarity.return_value = []

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "How do I buy bitcoin safely?"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "similar_faqs" in data
        assert data["similar_faqs"] == []

    @pytest.mark.asyncio
    async def test_returns_similar_faqs_with_all_fields(self, client, mock_rag_service):
        """Test that similar FAQs are returned with all expected fields."""
        mock_rag_service.search_faq_similarity.return_value = [
            {
                "id": 1,
                "question": "How do I buy bitcoin?",
                "answer": "Use Bisq Easy to buy bitcoin safely.",
                "similarity": 0.85,
                "category": "Trading",
                "protocol": "bisq_easy",
            },
            {
                "id": 2,
                "question": "What's the safest way to buy?",
                "answer": "Choose reputable sellers with high ratings.",
                "similarity": 0.72,
                "category": "Trading",
                "protocol": None,
            },
        ]

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "How can I purchase BTC safely?"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["similar_faqs"]) == 2

        # Check first FAQ fields
        faq1 = data["similar_faqs"][0]
        assert faq1["id"] == 1
        assert faq1["question"] == "How do I buy bitcoin?"
        assert faq1["answer"] == "Use Bisq Easy to buy bitcoin safely."
        assert faq1["similarity"] == 0.85
        assert faq1["category"] == "Trading"
        assert faq1["protocol"] == "bisq_easy"

        # Check second FAQ fields
        faq2 = data["similar_faqs"][1]
        assert faq2["id"] == 2
        assert faq2["protocol"] is None

    @pytest.mark.asyncio
    async def test_validates_question_min_length(self, client, mock_rag_service):
        """Test that question shorter than 5 characters is rejected."""
        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Hi"},  # Too short
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_validates_question_max_length(self, client, mock_rag_service):
        """Test that question longer than 1000 characters is rejected."""
        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "x" * 1001},  # Too long
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_accepts_custom_threshold(self, client, mock_rag_service):
        """Test that custom threshold is passed to service."""
        mock_rag_service.search_faq_similarity.return_value = []

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "threshold": 0.8},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_rag_service.search_faq_similarity.assert_called_once()
        call_kwargs = mock_rag_service.search_faq_similarity.call_args[1]
        assert call_kwargs["threshold"] == 0.8

    @pytest.mark.asyncio
    async def test_accepts_custom_limit(self, client, mock_rag_service):
        """Test that custom limit is passed to service."""
        mock_rag_service.search_faq_similarity.return_value = []

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "limit": 10},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_rag_service.search_faq_similarity.assert_called_once()
        call_kwargs = mock_rag_service.search_faq_similarity.call_args[1]
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_accepts_exclude_id(self, client, mock_rag_service):
        """Test that exclude_id is passed to service (for edit mode)."""
        mock_rag_service.search_faq_similarity.return_value = []

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "exclude_id": 42},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_rag_service.search_faq_similarity.assert_called_once()
        call_kwargs = mock_rag_service.search_faq_similarity.call_args[1]
        assert call_kwargs["exclude_id"] == 42

    @pytest.mark.asyncio
    async def test_validates_threshold_range(self, client, mock_rag_service):
        """Test that threshold must be between 0 and 1."""
        # Too low
        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "threshold": -0.1},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Too high
        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "threshold": 1.5},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_validates_limit_range(self, client, mock_rag_service):
        """Test that limit must be between 1 and 20."""
        # Too low
        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "limit": 0},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Too high
        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question", "limit": 21},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """Test that endpoint requires admin authentication."""
        from app.main import app

        # Create client without auth header
        client = TestClient(app)

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_uses_default_values_when_not_provided(
        self, client, mock_rag_service
    ):
        """Test that default threshold and limit are used when not provided."""
        mock_rag_service.search_faq_similarity.return_value = []

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_rag_service.search_faq_similarity.assert_called_once()
        call_kwargs = mock_rag_service.search_faq_similarity.call_args[1]
        assert call_kwargs["threshold"] == 0.65  # Default
        assert call_kwargs["limit"] == 5  # Default
        assert call_kwargs["exclude_id"] is None  # Default

    @pytest.mark.asyncio
    async def test_handles_service_error_gracefully(self, client, mock_rag_service):
        """Test that service errors return empty list (graceful degradation)."""
        mock_rag_service.search_faq_similarity.side_effect = Exception("Service error")

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question"},
        )

        # Should return 200 with empty list (graceful degradation)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["similar_faqs"] == []

    @pytest.mark.asyncio
    async def test_response_model_validation(self, client, mock_rag_service):
        """Test that response conforms to SimilarFAQResponse model."""
        mock_rag_service.search_faq_similarity.return_value = [
            {
                "id": 1,
                "question": "Question",
                "answer": "Answer",
                "similarity": 0.9,
                "category": "General",
                "protocol": "bisq_easy",
            }
        ]

        response = client.post(
            "/admin/faqs/check-similar",
            json={"question": "Test question"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Check response structure
        assert "similar_faqs" in data
        assert isinstance(data["similar_faqs"], list)

        # Check each item has required fields
        for faq in data["similar_faqs"]:
            assert "id" in faq
            assert "question" in faq
            assert "answer" in faq
            assert "similarity" in faq
            assert "category" in faq
            assert "protocol" in faq
