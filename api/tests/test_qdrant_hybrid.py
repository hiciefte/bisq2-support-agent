"""
Tests for Qdrant Hybrid Retriever.

Tests the hybrid search functionality with mocked Qdrant client.
"""

import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Skip tests if qdrant_client is not installed
pytest.importorskip("qdrant_client")

from app.services.rag.bm25_tokenizer import BM25SparseTokenizer  # noqa: E402
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
        with patch(
            "app.services.rag.embeddings_provider.OpenAIEmbeddingsProvider"
        ) as mock:
            embeddings = MagicMock()
            embeddings.embed_query.return_value = [0.1] * 1536
            mock.from_settings.return_value = embeddings
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
        # retrieve_with_scores uses true weighted hybrid search,
        # which runs separate dense and sparse searches
        mock_qdrant_client.search.return_value = [mock_result]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_with_scores("test query", k=5)

        assert len(docs) == 1
        # Score may be normalized from the weighted combination
        assert docs[0].score >= 0.0

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


class TestBM25TokenizerIntegration:
    """Test suite for BM25 tokenizer integration with QdrantHybridRetriever."""

    @pytest.fixture
    def mock_settings(self, tmp_path):
        """Create mock settings with vocabulary path."""
        settings = MagicMock()
        settings.QDRANT_HOST = "localhost"
        settings.QDRANT_PORT = 6333
        settings.QDRANT_COLLECTION = "test_collection"
        settings.HYBRID_SEMANTIC_WEIGHT = 0.7
        settings.HYBRID_KEYWORD_WEIGHT = 0.3
        settings.OPENAI_API_KEY = "test-api-key"
        settings.OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
        settings.DATA_DIR = str(tmp_path)
        settings.BM25_VOCABULARY_FILE = "bm25_vocabulary.json"
        return settings

    @pytest.fixture
    def sample_vocabulary(self, tmp_path):
        """Create a sample vocabulary file."""
        tokenizer = BM25SparseTokenizer()
        # Build vocabulary from sample documents
        docs = [
            "How do I buy bitcoin on Bisq Easy?",
            "What is the reputation system in Bisq 2?",
            "Can I use SEPA for payments on Bisq?",
            "How do I restore my Bisq wallet backup?",
            "What is BSQ and how do I burn it for reputation?",
        ]
        for doc in docs:
            tokenizer.tokenize_document(doc)

        vocab_path = tmp_path / "bm25_vocabulary.json"
        vocab_path.write_text(tokenizer.export_vocabulary())
        return vocab_path, tokenizer

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
        with patch(
            "app.services.rag.embeddings_provider.OpenAIEmbeddingsProvider"
        ) as mock:
            embeddings = MagicMock()
            embeddings.embed_query.return_value = [0.1] * 1536
            mock.from_settings.return_value = embeddings
            yield embeddings

    def test_retriever_loads_vocabulary_on_init(
        self, mock_settings, sample_vocabulary, mock_qdrant_client, mock_embeddings
    ):
        """Test that retriever loads BM25 vocabulary from file on initialization."""
        vocab_path, original_tokenizer = sample_vocabulary

        retriever = QdrantHybridRetriever(mock_settings)

        # Verify vocabulary was loaded
        assert retriever._bm25_tokenizer is not None
        assert (
            retriever._bm25_tokenizer.vocabulary_size
            == original_tokenizer.vocabulary_size
        )

    def test_retriever_uses_vocabulary_based_tokenization(
        self, mock_settings, sample_vocabulary, mock_qdrant_client, mock_embeddings
    ):
        """Test that retriever uses vocabulary-based tokenization, not hash-based."""
        vocab_path, original_tokenizer = sample_vocabulary

        retriever = QdrantHybridRetriever(mock_settings)

        # Tokenize a query that contains vocabulary words
        indices = retriever._tokenize_query("bisq bitcoin wallet")

        # Indices should match vocabulary (not random hashes)
        # "bisq", "bitcoin", "wallet" should all be in vocabulary
        assert len(indices) > 0
        for idx in indices:
            assert retriever._bm25_tokenizer.has_token(idx)

    def test_retriever_returns_idf_weights_not_uniform(
        self, mock_settings, sample_vocabulary, mock_qdrant_client, mock_embeddings
    ):
        """Test that retriever returns IDF-weighted values, not uniform 1.0."""
        vocab_path, _ = sample_vocabulary

        retriever = QdrantHybridRetriever(mock_settings)

        # Get weights for a query
        weights = retriever._get_bm25_weights("bisq bitcoin reputation")

        # Weights should NOT all be 1.0 (which is the placeholder behavior)
        assert len(weights) > 0
        # At least one weight should differ from 1.0
        assert not all(w == 1.0 for w in weights)

    def test_retriever_handles_missing_vocabulary_file(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Test graceful handling when vocabulary file doesn't exist."""
        # Ensure no vocabulary file exists
        mock_settings.DATA_DIR = tempfile.mkdtemp()

        retriever = QdrantHybridRetriever(mock_settings)

        # Should still work, creating empty tokenizer
        assert retriever._bm25_tokenizer is not None
        # Tokenization should still work (query expansion)
        indices = retriever._tokenize_query("test query")
        assert isinstance(indices, list)

    def test_hybrid_search_uses_proper_sparse_vectors(
        self, mock_settings, sample_vocabulary, mock_qdrant_client, mock_embeddings
    ):
        """Test that hybrid search passes proper BM25 sparse vectors to Qdrant."""
        vocab_path, _ = sample_vocabulary

        # Setup mock response for search calls
        mock_result = MagicMock()
        mock_result.id = "doc1"
        mock_result.score = 0.9
        mock_result.payload = {"content": "Test content", "source": "test.md"}
        mock_qdrant_client.search.return_value = [mock_result]

        retriever = QdrantHybridRetriever(mock_settings)
        retriever.retrieve_with_scores("How do I buy bitcoin?", k=5)

        # With true weighted hybrid search, search is called twice:
        # once for dense and once for sparse
        assert mock_qdrant_client.search.call_count == 2

        # Get all search call arguments
        search_calls = mock_qdrant_client.search.call_args_list

        # Find the sparse search call (the one with SparseVector query)
        sparse_call = None
        for call in search_calls:
            call_kwargs = call[1]
            query_vector = call_kwargs.get("query_vector")
            if isinstance(query_vector, tuple) and query_vector[0] == "sparse":
                sparse_call = call
                break

        assert sparse_call is not None, "No sparse vector search call found"

        # Verify sparse vector has proper indices (from vocabulary, not hashes)
        sparse_query = sparse_call[1]["query_vector"][1]
        sparse_indices = sparse_query.indices
        sparse_values = sparse_query.values

        assert len(sparse_indices) > 0
        assert len(sparse_values) == len(sparse_indices)
        # Values should not all be 1.0
        assert not all(v == 1.0 for v in sparse_values)

    def test_tokenizer_vocabulary_alignment(
        self, mock_settings, sample_vocabulary, mock_qdrant_client, mock_embeddings
    ):
        """Test that query tokenization aligns with document vocabulary."""
        vocab_path, original_tokenizer = sample_vocabulary

        retriever = QdrantHybridRetriever(mock_settings)

        # Query with words from the vocabulary
        query = "bisq reputation"
        indices = retriever._tokenize_query(query)

        # Each index should map back to a known token
        for idx in indices:
            token = retriever._bm25_tokenizer.get_token(idx)
            assert token is not None
            assert token in ["bisq", "reputation"]


def _scored_result(doc_id: str, score: float, payload=None):
    """Build a mock Qdrant scored point."""
    result = MagicMock()
    result.id = doc_id
    result.score = score
    result.payload = payload or {
        "content": f"Content {doc_id}",
        "source": f"{doc_id}.md",
    }
    return result


class TestAbsoluteSimilarityScores:
    """Absolute vs relative score semantics (review finding G1).

    retrieve_semantic_with_scores() must return raw cosine similarity
    (calibrated, absolute) so absolute-threshold consumers like duplicate
    detection work. Min-max normalization stays on the fusion/ranking path,
    but its degenerate case must not fabricate a perfect 1.0.
    """

    @pytest.fixture
    def mock_settings(self):
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
        with patch("app.services.rag.qdrant_hybrid_retriever.QdrantClient") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_embeddings(self):
        with patch(
            "app.services.rag.embeddings_provider.OpenAIEmbeddingsProvider"
        ) as mock:
            embeddings = MagicMock()
            embeddings.embed_query.return_value = [0.1] * 1536
            mock.from_settings.return_value = embeddings
            yield embeddings

    def test_semantic_scores_low_relevance_not_inflated(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """A single barely-related hit keeps its raw cosine score (~0.3)."""
        mock_qdrant_client.search.return_value = [_scored_result("doc1", 0.3)]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_semantic_with_scores("unrelated query", k=5)

        assert len(docs) == 1
        assert docs[0].score == pytest.approx(0.3)
        # Must NOT pass the FAQ-similarity (0.65) or duplicate (0.85) thresholds
        assert docs[0].score < 0.65
        assert docs[0].score < 0.85

    def test_semantic_scores_near_duplicate_passes_threshold(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """A true near-duplicate (cosine ~0.95) passes the 0.85 threshold."""
        mock_qdrant_client.search.return_value = [_scored_result("doc1", 0.95)]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_semantic_with_scores("duplicate question", k=5)

        assert len(docs) == 1
        assert docs[0].score == pytest.approx(0.95)
        assert docs[0].score >= 0.85

    def test_semantic_scores_clamped_to_unit_interval(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Raw scores outside [0, 1] are clamped, not min-max rescaled."""
        mock_qdrant_client.search.return_value = [
            _scored_result("doc1", 1.3),
            _scored_result("doc2", -0.2),
        ]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_semantic_with_scores("query", k=5)

        assert [doc.score for doc in docs] == [1.0, 0.0]

    def test_semantic_scores_handles_errors_gracefully(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        mock_qdrant_client.search.side_effect = Exception("Search failed")

        retriever = QdrantHybridRetriever(mock_settings)

        assert retriever.retrieve_semantic_with_scores("query", k=5) == []

    def test_normalize_scores_degenerate_cases_clamp_raw(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """All-equal/single-result sets must not fabricate 1.0."""
        retriever = QdrantHybridRetriever(mock_settings)

        # Single low-relevance result keeps its raw (clamped) score
        assert retriever._normalize_scores({"a": 0.3}) == {"a": pytest.approx(0.3)}
        # Equal scores above 1.0 clamp to 1.0
        assert retriever._normalize_scores({"a": 1.7, "b": 1.7}) == {
            "a": 1.0,
            "b": 1.0,
        }
        # Negative scores clamp to 0.0
        assert retriever._normalize_scores({"a": -0.4}) == {"a": 0.0}

    def test_weighted_hybrid_single_result_not_certain_duplicate(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Fused score of a lone low-relevance hit must not be 1.0."""
        dense_results = [_scored_result("doc1", 0.3)]
        sparse_results = [_scored_result("doc1", 2.0)]
        mock_qdrant_client.search.side_effect = [dense_results, sparse_results]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_with_scores("query", k=5)

        assert len(docs) == 1
        # 0.7 * clamp(0.3) + 0.3 * clamp(2.0) = 0.21 + 0.3 = 0.51
        assert docs[0].score == pytest.approx(0.51)
        assert docs[0].score < 0.85

    def test_weighted_hybrid_ranking_order_unchanged(
        self, mock_settings, mock_qdrant_client, mock_embeddings
    ):
        """Multi-result fusion still uses min-max ranking (order stable)."""
        dense_results = [
            _scored_result("doc1", 0.9),
            _scored_result("doc2", 0.5),
            _scored_result("doc3", 0.1),
        ]
        sparse_results = [
            _scored_result("doc2", 5.0),
            _scored_result("doc1", 1.0),
        ]
        mock_qdrant_client.search.side_effect = [dense_results, sparse_results]

        retriever = QdrantHybridRetriever(mock_settings)
        docs = retriever.retrieve_with_scores("query", k=5)

        # dense norm: doc1=1.0, doc2=0.5, doc3=0.0; sparse norm: doc2=1.0, doc1=0.0
        # combined: doc1=0.70, doc2=0.65, doc3=0.0
        assert [doc.id for doc in docs] == ["doc1", "doc2", "doc3"]
        assert docs[0].score == pytest.approx(0.70)
        assert docs[1].score == pytest.approx(0.65)
        assert docs[2].score == pytest.approx(0.0)
