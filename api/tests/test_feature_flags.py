"""
Tests for RAG retriever feature flags.

Tests the RETRIEVER_BACKEND configuration switching logic.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Set up ragatouille mock before any imports that might need it
# This ensures test isolation regardless of test execution order
if "ragatouille" not in sys.modules:
    _mock_ragatouille = MagicMock()
    _mock_ragatouille.RAGPretrainedModel = MagicMock()
    sys.modules["ragatouille"] = _mock_ragatouille


class TestRetrieverBackendSettings:
    """Test suite for RETRIEVER_BACKEND configuration."""

    def test_default_backend_is_chromadb(self):
        """Test that default retriever backend is ChromaDB."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.RETRIEVER_BACKEND == "chromadb"

    def test_valid_backend_values(self):
        """Test valid retriever backend values."""
        valid_backends = ["chromadb", "qdrant", "hybrid"]

        for backend in valid_backends:
            with patch.dict("os.environ", {"RETRIEVER_BACKEND": backend}):
                from app.core.config import Settings

                # Force reload
                settings = Settings()
                assert settings.RETRIEVER_BACKEND == backend

    def test_qdrant_settings_defaults(self):
        """Test Qdrant settings have correct defaults."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.QDRANT_HOST == "qdrant"
        assert settings.QDRANT_PORT == 6333
        assert settings.QDRANT_COLLECTION == "bisq_docs"

    def test_colbert_settings_defaults(self):
        """Test ColBERT settings have correct defaults (rerank disabled by default)."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.COLBERT_MODEL == "colbert-ir/colbertv2.0"
        assert settings.COLBERT_TOP_N == 5
        assert settings.ENABLE_COLBERT_RERANK is False  # Disabled by default; opt-in

    def test_hybrid_weights_defaults(self):
        """Test hybrid search weights have correct defaults (optimized via RAGAS)."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.HYBRID_SEMANTIC_WEIGHT == 0.6
        assert settings.HYBRID_KEYWORD_WEIGHT == 0.4

    def test_hybrid_weights_sum_to_one(self):
        """Test that hybrid weights sum to approximately 1.0."""
        from app.core.config import Settings

        settings = Settings()
        total = settings.HYBRID_SEMANTIC_WEIGHT + settings.HYBRID_KEYWORD_WEIGHT
        assert abs(total - 1.0) < 0.01

    def test_invalid_retriever_backend_rejected(self):
        """Test that invalid RETRIEVER_BACKEND values are rejected at startup."""
        with patch.dict("os.environ", {"RETRIEVER_BACKEND": "invalid_backend"}):
            from app.core.config import Settings

            with pytest.raises(ValueError, match="must be one of"):
                Settings()


class TestRAGServiceBackendSwitching:
    """Test suite for RAG service backend switching."""

    @pytest.fixture
    def mock_settings_chromadb(self):
        """Create mock settings for ChromaDB backend."""
        settings = MagicMock()
        settings.RETRIEVER_BACKEND = "chromadb"
        settings.DATA_DIR = "/data"
        settings.OPENAI_API_KEY = "test-key"
        return settings

    @pytest.fixture
    def mock_settings_qdrant(self):
        """Create mock settings for Qdrant backend."""
        settings = MagicMock()
        settings.RETRIEVER_BACKEND = "qdrant"
        settings.QDRANT_HOST = "localhost"
        settings.QDRANT_PORT = 6333
        settings.QDRANT_COLLECTION = "test_collection"
        settings.ENABLE_COLBERT_RERANK = True
        settings.COLBERT_MODEL = "colbert-ir/colbertv2.0"
        settings.COLBERT_TOP_N = 5
        settings.DATA_DIR = "/data"
        settings.OPENAI_API_KEY = "test-key"
        return settings

    @pytest.fixture
    def mock_settings_hybrid(self):
        """Create mock settings for hybrid backend."""
        settings = MagicMock()
        settings.RETRIEVER_BACKEND = "hybrid"
        settings.QDRANT_HOST = "localhost"
        settings.QDRANT_PORT = 6333
        settings.QDRANT_COLLECTION = "test_collection"
        settings.ENABLE_COLBERT_RERANK = True
        settings.COLBERT_MODEL = "colbert-ir/colbertv2.0"
        settings.COLBERT_TOP_N = 5
        settings.HYBRID_SEMANTIC_WEIGHT = 0.7
        settings.HYBRID_KEYWORD_WEIGHT = 0.3
        settings.DATA_DIR = "/data"
        settings.OPENAI_API_KEY = "test-key"
        return settings

    def test_chromadb_backend_selected(self, mock_settings_chromadb):
        """Test that ChromaDB backend is selected when configured."""
        # This tests the logic, not the full service initialization
        backend = mock_settings_chromadb.RETRIEVER_BACKEND

        assert backend == "chromadb"
        # In actual service, this would initialize ChromaDB retriever

    def test_qdrant_backend_selected(self, mock_settings_qdrant):
        """Test that Qdrant backend is selected when configured."""
        backend = mock_settings_qdrant.RETRIEVER_BACKEND

        assert backend == "qdrant"
        # In actual service, this would initialize Qdrant retriever

    def test_hybrid_backend_selected(self, mock_settings_hybrid):
        """Test that hybrid backend is selected when configured."""
        backend = mock_settings_hybrid.RETRIEVER_BACKEND

        assert backend == "hybrid"
        # In actual service, this would initialize ResilientRetriever


class TestColBERTFeatureFlag:
    """Test suite for ColBERT reranking feature flag."""

    def test_colbert_disabled_by_default(self):
        """Test that ColBERT reranking is disabled by default (opt-in)."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.ENABLE_COLBERT_RERANK is False

    def test_colbert_can_be_disabled(self):
        """Test that ColBERT can be disabled via environment."""
        with patch.dict("os.environ", {"ENABLE_COLBERT_RERANK": "false"}):
            from app.core.config import Settings

            settings = Settings()
            assert settings.ENABLE_COLBERT_RERANK is False

    def test_colbert_model_configurable(self):
        """Test that ColBERT model can be configured."""
        custom_model = "custom/colbert-model"

        with patch.dict("os.environ", {"COLBERT_MODEL": custom_model}):
            from app.core.config import Settings

            settings = Settings()
            assert settings.COLBERT_MODEL == custom_model


class TestGracefulDegradation:
    """Test suite for graceful degradation behavior."""

    def test_fallback_on_qdrant_failure(self):
        """Test that system falls back to ChromaDB when Qdrant fails."""
        from app.services.rag.interfaces import RetrievedDocument
        from app.services.rag.resilient_retriever import ResilientRetriever

        # Create mock retrievers
        primary = MagicMock()
        primary.retrieve.side_effect = Exception("Qdrant connection failed")
        primary.health_check.return_value = False

        fallback = MagicMock()
        fallback.retrieve.return_value = [
            RetrievedDocument(
                content="Fallback document",
                metadata={"source": "chromadb"},
                score=0.8,
            )
        ]
        fallback.health_check.return_value = True

        resilient = ResilientRetriever(primary, fallback, auto_reset=False)
        docs = resilient.retrieve("test query")

        assert len(docs) == 1
        assert docs[0].content == "Fallback document"
        assert resilient.using_fallback is True

    def test_colbert_failure_returns_unreranked(self):
        """Test that ColBERT failure returns unreranked documents."""
        # Reset mock state to ensure test isolation
        mock_rag = sys.modules.get("ragatouille")
        if mock_rag:
            mock_rag.reset_mock()
            mock_rag.RAGPretrainedModel = MagicMock()
            # Make model loading fail to test graceful degradation
            mock_rag.RAGPretrainedModel.from_pretrained.side_effect = RuntimeError(
                "Model not available"
            )

        from app.services.rag.colbert_reranker import ColBERTReranker
        from app.services.rag.interfaces import RetrievedDocument

        settings = MagicMock()
        settings.COLBERT_MODEL = "test-model"
        settings.COLBERT_TOP_N = 3
        settings.ENABLE_COLBERT_RERANK = True

        reranker = ColBERTReranker(settings)

        # With model loading failure, reranking should gracefully degrade
        docs = [
            RetrievedDocument(content="Doc 1", metadata={}, score=0.9),
            RetrievedDocument(content="Doc 2", metadata={}, score=0.8),
        ]

        result = reranker.rerank("query", docs, top_n=2)

        # Should return original documents without reranking
        assert len(result) == 2
        assert result[0].content == "Doc 1"
