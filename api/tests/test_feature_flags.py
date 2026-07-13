"""Tests for RAG retriever feature flags and graceful degradation behavior."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Set up ragatouille mock before any imports that might need it.
if "ragatouille" not in sys.modules:
    _mock_ragatouille = MagicMock()
    _mock_ragatouille.RAGPretrainedModel = MagicMock()
    sys.modules["ragatouille"] = _mock_ragatouille


class TestQdrantSettings:
    """Test suite for Qdrant retrieval configuration."""

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

    def test_fail_closed_rag_defaults(self):
        from app.core.config import Settings

        settings = Settings()
        assert settings.RAG_RETRIEVAL_RELEVANCE_FLOOR == 0.65
        assert settings.MCP_LIVE_DATA_TIMEOUT_SECONDS == 30.0

    def test_retrieval_floor_is_configurable_and_bounded(self):
        from app.core.config import Settings

        settings = Settings(
            _env_file=None,
            RAG_RETRIEVAL_RELEVANCE_FLOOR=0.72,
        )
        assert settings.RAG_RETRIEVAL_RELEVANCE_FLOOR == 0.72

        with pytest.raises(ValueError):
            Settings(
                _env_file=None,
                RAG_RETRIEVAL_RELEVANCE_FLOOR=1.01,
            )

    def test_hybrid_weights_sum_to_one(self):
        from app.core.config import Settings

        settings = Settings()
        total = settings.HYBRID_SEMANTIC_WEIGHT + settings.HYBRID_KEYWORD_WEIGHT
        assert abs(total - 1.0) < 0.01


class TestProductionSecretSettings:
    """Production-only secret validation."""

    def test_reactor_identity_salt_required_for_prod_alias(self):
        from app.core.config import Settings

        with pytest.raises(ValueError, match="REACTOR_IDENTITY_SALT"):
            Settings(
                _env_file=None,
                ENVIRONMENT="prod",
                CORS_ORIGINS=["https://example.com"],
                ADMIN_API_KEY="test-admin-key-with-sufficient-length-24chars",
                TRUST_MONITOR_ACTOR_KEY_SECRET="test-trust-monitor-secret",
                REACTOR_IDENTITY_SALT="",
            )

    def test_reactor_identity_salt_is_trimmed(self):
        from app.core.config import Settings

        settings = Settings(
            _env_file=None,
            ENVIRONMENT="production",
            CORS_ORIGINS=["https://example.com"],
            ADMIN_API_KEY="test-admin-key-with-sufficient-length-24chars",
            TRUST_MONITOR_ACTOR_KEY_SECRET="test-trust-monitor-secret",
            REACTOR_IDENTITY_SALT=" test-reactor-salt ",
        )

        assert settings.REACTOR_IDENTITY_SALT == "test-reactor-salt"


class TestRAGServiceBackendSettings:
    """Sanity checks for backend-related settings."""

    def test_qdrant_settings_load_from_environment(self):
        from app.core.config import Settings

        with patch.dict(
            "os.environ",
            {
                "QDRANT_HOST": "localhost",
                "QDRANT_PORT": "6334",
                "QDRANT_COLLECTION": "test_collection",
            },
        ):
            settings = Settings(_env_file=None)

        assert settings.QDRANT_HOST == "localhost"
        assert settings.QDRANT_PORT == 6334
        assert settings.QDRANT_COLLECTION == "test_collection"


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
