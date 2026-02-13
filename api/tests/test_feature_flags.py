"""Tests for RAG retriever feature flags and graceful degradation behavior."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Set up ragatouille mock before any imports that might need it.
if "ragatouille" not in sys.modules:
    _mock_ragatouille = MagicMock()
    _mock_ragatouille.RAGPretrainedModel = MagicMock()
    sys.modules["ragatouille"] = _mock_ragatouille


class TestRetrieverBackendSettings:
    """Test suite for RETRIEVER_BACKEND configuration."""

    def test_default_backend_is_qdrant(self):
        from app.core.config import Settings

        settings = Settings()
        assert settings.RETRIEVER_BACKEND == "qdrant"

    def test_valid_backend_values(self):
        for backend in ["qdrant"]:
            with patch.dict("os.environ", {"RETRIEVER_BACKEND": backend}):
                from app.core.config import Settings

                settings = Settings()
                assert settings.RETRIEVER_BACKEND == backend

    def test_qdrant_settings_defaults(self):
        from app.core.config import Settings

        settings = Settings()
        assert settings.QDRANT_HOST == "qdrant"
        assert settings.QDRANT_PORT == 6333
        assert settings.QDRANT_COLLECTION == "bisq_docs"

    def test_colbert_settings_defaults(self):
        from app.core.config import Settings

        settings = Settings()
        assert settings.COLBERT_MODEL == "colbert-ir/colbertv2.0"
        assert settings.COLBERT_TOP_N == 5
        assert settings.ENABLE_COLBERT_RERANK is False

    def test_hybrid_weights_defaults(self):
        from app.core.config import Settings

        settings = Settings()
        assert settings.HYBRID_SEMANTIC_WEIGHT == 0.6
        assert settings.HYBRID_KEYWORD_WEIGHT == 0.4

    def test_hybrid_weights_sum_to_one(self):
        from app.core.config import Settings

        settings = Settings()
        total = settings.HYBRID_SEMANTIC_WEIGHT + settings.HYBRID_KEYWORD_WEIGHT
        assert abs(total - 1.0) < 0.01

    def test_invalid_retriever_backend_rejected(self):
        with patch.dict("os.environ", {"RETRIEVER_BACKEND": "invalid_backend"}):
            from app.core.config import Settings

            with pytest.raises(ValueError, match="must be one of"):
                Settings()


class TestRAGServiceBackendSettings:
    """Sanity checks for backend-related test fixtures."""

    @pytest.fixture
    def mock_settings_qdrant(self):
        settings = MagicMock()
        settings.RETRIEVER_BACKEND = "qdrant"
        settings.QDRANT_HOST = "localhost"
        settings.QDRANT_PORT = 6333
        settings.QDRANT_COLLECTION = "test_collection"
        settings.ENABLE_COLBERT_RERANK = True
        settings.COLBERT_MODEL = "colbert-ir/colbertv2.0"
        settings.COLBERT_TOP_N = 5
        settings.HYBRID_SEMANTIC_WEIGHT = 0.6
        settings.HYBRID_KEYWORD_WEIGHT = 0.4
        settings.DATA_DIR = "/data"
        settings.OPENAI_API_KEY = "test-key"
        return settings

    def test_qdrant_backend_selected(self, mock_settings_qdrant):
        assert mock_settings_qdrant.RETRIEVER_BACKEND == "qdrant"


class TestColBERTFeatureFlag:
    """Test suite for ColBERT reranking feature flag."""

    def test_colbert_disabled_by_default(self):
        from app.core.config import Settings

        settings = Settings()
        assert settings.ENABLE_COLBERT_RERANK is False

    def test_colbert_can_be_disabled(self):
        with patch.dict("os.environ", {"ENABLE_COLBERT_RERANK": "false"}):
            from app.core.config import Settings

            settings = Settings()
            assert settings.ENABLE_COLBERT_RERANK is False

    def test_colbert_model_configurable(self):
        custom_model = "custom/colbert-model"

        with patch.dict("os.environ", {"COLBERT_MODEL": custom_model}):
            from app.core.config import Settings

            settings = Settings()
            assert settings.COLBERT_MODEL == custom_model


class TestGracefulDegradation:
    """Test suite for graceful degradation behavior."""

    def test_fallback_on_primary_failure(self):
        from app.services.rag.interfaces import RetrievedDocument
        from app.services.rag.resilient_retriever import ResilientRetriever

        primary = MagicMock()
        primary.retrieve.side_effect = Exception("Primary retriever failed")
        primary.health_check.return_value = False

        fallback = MagicMock()
        fallback.retrieve.return_value = [
            RetrievedDocument(
                content="Fallback document",
                metadata={"source": "fallback"},
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
        mock_rag = sys.modules.get("ragatouille")
        if mock_rag:
            mock_rag.reset_mock()
            mock_rag.RAGPretrainedModel = MagicMock()
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

        docs = [
            RetrievedDocument(content="Doc 1", metadata={}, score=0.9),
            RetrievedDocument(content="Doc 2", metadata={}, score=0.8),
        ]

        result = reranker.rerank("query", docs, top_n=2)

        assert len(result) == 2
        assert result[0].content == "Doc 1"
        assert result[1].content == "Doc 2"
