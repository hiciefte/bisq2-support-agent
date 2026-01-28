"""
Tests for Qdrant Hybrid Retriever.

Tests the hybrid search functionality with mocked Qdrant client.
"""

from unittest.mock import MagicMock, patch

import pytest

# Skip tests if qdrant_client is not installed
pytest.importorskip("qdrant_client")

from app.services.rag.interfaces import RetrievedDocument  # noqa: E402
from app.services.rag.qdrant_hybrid_retriever import QdrantHybridRetriever  # noqa: E402


class TestQdrantHybridRetriever:
    """Test suite for QdrantHybridRetriever."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.QDRANT_HOST = "localhost"
        settings.QDRANT_PORT = 6333
        settings.QDRANT_COLLECTION = "test_collection"
        settings.HYBRID_SEMANTIC_WEIGHT = 0.7
        settings.HYBRID_KEYWORD_WEIGHT = 0.3
        settings.OPENAI_API_KEY = "test-api-key"
        settings.OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
        return settings

    @pytest.fixture
    def mock_qdrant_client(self):
        """Create mock Qdrant client."""
        with patch("app.services.rag.qdrant_hybrid_retriever.QdrantClient") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings."""
        with patch("langchain_openai.OpenAIEmbeddings") as mock:
            embeddings = MagicMock()
            embeddings.embed_query.return_value = [0.1] * 1536
            mock.return_value = embeddings
            yield embeddings

    def test_initialization(self, mock_settings, mock_qdrant_client, mock_embeddings):
        """Test retriever initialization."""
        retriever = QdrantHybridRetriever(mock_settings)

        assert retriever.settings == mock_settings
        assert retriever.collection_name == "test_collection"

    def test_health_check_healthy(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test health check when Qdrant is healthy."""
        # Mock get_collections to return a list with our collection
        mock_collection = MagicMock()
        mock_collection.name = "test_collection"
        mock_collections = MagicMock()
        mock_collections.collections = [mock_collection]
        mock_qdrant_client.get_collections.return_value = mock_collections

        retriever = QdrantHybridRetriever(mock_settings)
        result = retriever.health_check()

        assert result is True
        mock_qdrant_client.get_collections.assert_called_once()

    def test_health_check_unhealthy(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test health check when Qdrant is unhealthy."""
        mock_qdrant_client.get_collections.side_effect = Exception("Connection failed")

        retriever = QdrantHybridRetriever(mock_settings)
        result = retriever.health_check()

        assert result is False

    def test_retrieve_returns_documents(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test retrieve returns list of RetrievedDocument objects."""
        # Setup mock search results
        mock_result = MagicMock()
        mock_result.id = "doc1"
        mock_result.score = 0.95
        mock_result.payload = {
            "content": "Test document content",
            "source": "test.md",
            "title": "Test Title",
        }
        mock_qdrant_client.search.return_value = [mock_result]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve("test query", k=5)

        assert len(docs) == 1
        assert isinstance(docs[0], RetrievedDocument)
        assert docs[0].content == "Test document content"
        assert docs[0].metadata["source"] == "test.md"

    def test_retrieve_with_filter(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test retrieve with metadata filters."""
        mock_qdrant_client.search.return_value = []

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve("test query", k=5, filter_dict={"category": "faq"})

        assert len(docs) == 0
        # Verify search was called with filter
        mock_qdrant_client.search.assert_called()

    def test_retrieve_with_scores(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test retrieve_with_scores returns documents with scores."""
        mock_result = MagicMock()
        mock_result.id = "doc1"
        mock_result.score = 0.85
        mock_result.payload = {
            "content": "Document with score",
            "source": "scored.md",
        }
        # retrieve_with_scores uses hybrid search with keyword_weight > 0,
        # so it uses query_points instead of search
        mock_query_response = MagicMock()
        mock_query_response.points = [mock_result]
        mock_qdrant_client.query_points.return_value = mock_query_response

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_with_scores("test query", k=5)

        assert len(docs) == 1
        assert docs[0].score == 0.85

    def test_retrieve_handles_empty_results(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test retrieve handles empty results gracefully."""
        mock_qdrant_client.search.return_value = []

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve("no results query", k=5)

        assert docs == []

    def test_retrieve_handles_exceptions(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test retrieve handles exceptions gracefully."""
        mock_qdrant_client.search.side_effect = Exception("Search failed")

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve("failing query", k=5)

        assert docs == []

    def test_get_collection_info(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test getting collection information."""
        mock_collection_info = MagicMock()
        mock_collection_info.points_count = 500
        mock_collection_info.vectors_count = 500
        mock_collection_info.status = "green"
        mock_qdrant_client.get_collection.return_value = mock_collection_info

        retriever = QdrantHybridRetriever(mock_settings)
        info = retriever.get_collection_info()

        assert info["points_count"] == 500
        assert info["status"] == "green"
        assert info["name"] == "test_collection"
