"""
Tests for ColBERT Reranker.

Tests the reranking functionality with mocked RAGatouille model.
"""

import sys
from typing import List
from unittest.mock import MagicMock

import pytest
from app.services.rag.colbert_reranker import ColBERTReranker
from app.services.rag.interfaces import RetrievedDocument

# Create a mock for ragatouille since it's not installed
mock_ragatouille = MagicMock()
mock_ragatouille.RAGPretrainedModel = MagicMock()
sys.modules["ragatouille"] = mock_ragatouille


class TestColBERTReranker:
    """Test suite for ColBERTReranker."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.COLBERT_MODEL = "colbert-ir/colbertv2.0"
        settings.COLBERT_TOP_N = 5
        settings.ENABLE_COLBERT_RERANK = True
        return settings

    @pytest.fixture
    def sample_documents(self) -> List[RetrievedDocument]:
        """Create sample documents for testing."""
        return [
            RetrievedDocument(
                content="How to create a Bisq Easy offer",
                metadata={"source": "wiki/bisq-easy.md", "title": "Bisq Easy"},
                score=0.8,
                id="doc1",
            ),
            RetrievedDocument(
                content="Bisq 2 installation guide for Linux",
                metadata={"source": "wiki/install.md", "title": "Installation"},
                score=0.75,
                id="doc2",
            ),
            RetrievedDocument(
                content="Trading fees in Bisq network",
                metadata={"source": "wiki/fees.md", "title": "Fees"},
                score=0.7,
                id="doc3",
            ),
            RetrievedDocument(
                content="Security deposit requirements",
                metadata={"source": "wiki/security.md", "title": "Security"},
                score=0.65,
                id="doc4",
            ),
            RetrievedDocument(
                content="Payment methods supported by Bisq",
                metadata={"source": "wiki/payments.md", "title": "Payments"},
                score=0.6,
                id="doc5",
            ),
        ]

    def test_initialization(self, mock_settings):
        """Test reranker initialization."""
        reranker = ColBERTReranker(mock_settings)

        assert reranker.model_name == "colbert-ir/colbertv2.0"
        assert reranker.top_n == 5
        assert reranker.is_loaded() is False

    def test_is_loaded_before_loading(self, mock_settings):
        """Test is_loaded returns False before model is loaded."""
        reranker = ColBERTReranker(mock_settings)
        assert reranker.is_loaded() is False

    def test_load_model_success(self, mock_settings):
        """Test successful model loading."""
        mock_model_instance = MagicMock()
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = (
            mock_model_instance
        )

        reranker = ColBERTReranker(mock_settings)
        reranker.load_model()

        assert reranker.is_loaded() is True
        mock_ragatouille.RAGPretrainedModel.from_pretrained.assert_called_with(
            "colbert-ir/colbertv2.0"
        )

    def test_load_model_failure(self, mock_settings):
        """Test model loading failure."""
        mock_ragatouille.RAGPretrainedModel.from_pretrained.side_effect = Exception(
            "Model loading failed"
        )

        reranker = ColBERTReranker(mock_settings)

        with pytest.raises(RuntimeError, match="ColBERT model loading failed"):
            reranker.load_model()

        assert reranker.is_loaded() is False

        # Reset the side effect for other tests
        mock_ragatouille.RAGPretrainedModel.from_pretrained.side_effect = None

    def test_rerank_empty_documents(self, mock_settings):
        """Test rerank with empty document list."""
        reranker = ColBERTReranker(mock_settings)
        result = reranker.rerank("test query", [])

        assert result == []

    def test_rerank_disabled(self, mock_settings, sample_documents):
        """Test rerank when disabled returns original order."""
        mock_settings.ENABLE_COLBERT_RERANK = False
        reranker = ColBERTReranker(mock_settings)

        result = reranker.rerank("test query", sample_documents, top_n=3)

        assert len(result) == 3
        assert result[0].content == sample_documents[0].content
        assert result[1].content == sample_documents[1].content
        assert result[2].content == sample_documents[2].content

    def test_rerank_success(self, mock_settings, sample_documents):
        """Test successful reranking."""
        mock_model_instance = MagicMock()
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = (
            mock_model_instance
        )

        # Mock rerank to return documents in different order with new scores
        mock_model_instance.rerank.return_value = [
            {"content": "How to create a Bisq Easy offer", "score": 0.95},
            {"content": "Trading fees in Bisq network", "score": 0.88},
            {"content": "Bisq 2 installation guide for Linux", "score": 0.82},
        ]

        reranker = ColBERTReranker(mock_settings)
        reranker.load_model()
        result = reranker.rerank("Bisq Easy trading", sample_documents, top_n=3)

        assert len(result) == 3
        assert result[0].content == "How to create a Bisq Easy offer"
        assert result[0].score == 0.95
        assert result[1].content == "Trading fees in Bisq network"
        assert result[1].score == 0.88

    def test_rerank_preserves_metadata(self, mock_settings, sample_documents):
        """Test that reranking preserves document metadata."""
        mock_model_instance = MagicMock()
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = (
            mock_model_instance
        )
        mock_model_instance.rerank.return_value = [
            {"content": "How to create a Bisq Easy offer", "score": 0.95},
        ]

        reranker = ColBERTReranker(mock_settings)
        reranker.load_model()
        result = reranker.rerank("query", sample_documents, top_n=1)

        assert result[0].metadata["source"] == "wiki/bisq-easy.md"
        assert result[0].metadata["title"] == "Bisq Easy"
        assert result[0].id == "doc1"

    def test_rerank_with_threshold(self, mock_settings, sample_documents):
        """Test rerank_with_threshold filters by score."""
        mock_model_instance = MagicMock()
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = (
            mock_model_instance
        )
        mock_model_instance.rerank.return_value = [
            {"content": "How to create a Bisq Easy offer", "score": 0.95},
            {"content": "Trading fees in Bisq network", "score": 0.65},
            {"content": "Bisq 2 installation guide for Linux", "score": 0.45},
        ]

        reranker = ColBERTReranker(mock_settings)
        reranker.load_model()
        result = reranker.rerank_with_threshold(
            "query", sample_documents, top_n=5, score_threshold=0.6
        )

        assert len(result) == 2
        assert all(doc.score >= 0.6 for doc in result)

    def test_rerank_handles_exception(self, mock_settings, sample_documents):
        """Test rerank handles exceptions gracefully."""
        mock_model_instance = MagicMock()
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = (
            mock_model_instance
        )
        mock_model_instance.rerank.side_effect = Exception("Reranking failed")

        reranker = ColBERTReranker(mock_settings)
        reranker.load_model()
        result = reranker.rerank("query", sample_documents, top_n=3)

        # Should return original documents without reranking
        assert len(result) == 3
        assert result[0].content == sample_documents[0].content

    def test_get_model_info_before_loading(self, mock_settings):
        """Test get_model_info before model is loaded."""
        reranker = ColBERTReranker(mock_settings)
        info = reranker.get_model_info()

        assert info["model_name"] == "colbert-ir/colbertv2.0"
        assert info["is_loaded"] is False
        assert info["enabled"] is True
        assert info["top_n"] == 5
        assert info["load_error"] is None

    def test_get_model_info_after_loading(self, mock_settings):
        """Test get_model_info after model is loaded."""
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = MagicMock()

        reranker = ColBERTReranker(mock_settings)
        reranker.load_model()
        info = reranker.get_model_info()

        assert info["is_loaded"] is True
        assert info["load_error"] is None

    def test_custom_model_name(self, mock_settings):
        """Test custom model name override."""
        reranker = ColBERTReranker(mock_settings, model_name="custom/model", top_n=10)

        assert reranker.model_name == "custom/model"
        assert reranker.top_n == 10

    def test_thread_safe_loading(self, mock_settings):
        """Test that model loading is thread-safe."""
        import threading

        # Reset call count before test
        mock_ragatouille.RAGPretrainedModel.from_pretrained.reset_mock()
        mock_ragatouille.RAGPretrainedModel.from_pretrained.return_value = MagicMock()

        reranker = ColBERTReranker(mock_settings)

        threads = []
        for _ in range(5):
            t = threading.Thread(target=reranker.load_model)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Model should only be loaded once
        mock_ragatouille.RAGPretrainedModel.from_pretrained.assert_called_once()
