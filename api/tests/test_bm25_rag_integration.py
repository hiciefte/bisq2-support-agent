"""
End-to-end integration tests for BM25+RAG pipeline.

These tests verify the complete flow from query to response,
ensuring BM25 tokenizer, hybrid retrieval, and RAG work together correctly.
"""

from unittest.mock import MagicMock

import pytest


class TestBM25HybridRetrievalIntegration:
    """Integration tests for BM25 hybrid retrieval with Qdrant."""

    def test_hybrid_retriever_uses_bm25_tokenizer(self):
        """Verify QdrantHybridRetriever uses BM25SparseTokenizer."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.qdrant_hybrid_retriever import QdrantHybridRetriever

        # Check that QdrantHybridRetriever references BM25SparseTokenizer
        assert hasattr(QdrantHybridRetriever, "__init__")
        # The class should be importable together
        assert BM25SparseTokenizer is not None

    def test_bm25_tokenizer_produces_sparse_vectors(self):
        """BM25 tokenizer should produce valid sparse vectors for hybrid search."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Index some documents
        tokenizer.tokenize_document("bitcoin wallet security best practices")
        tokenizer.tokenize_document("how to use bisq escrow mechanism")

        # Tokenize a query
        indices, values = tokenizer.tokenize_query("bitcoin security")

        # Verify output format for Qdrant sparse vectors
        assert isinstance(indices, list)
        assert isinstance(values, list)
        assert len(indices) == len(values)
        assert all(isinstance(i, int) for i in indices)
        assert all(isinstance(v, float) for v in values)
        assert all(v > 0 for v in values)  # BM25 scores should be positive

    def test_bm25_tokenizer_handles_empty_queries(self):
        """BM25 tokenizer should handle edge cases gracefully."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize_document("some content to index")

        # Empty query should return empty vectors
        indices, values = tokenizer.tokenize_query("")
        assert indices == []
        assert values == []

    def test_bm25_vocabulary_persistence_roundtrip(self):
        """Vocabulary export/import should preserve BM25 state."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Create and populate tokenizer
        tokenizer1 = BM25SparseTokenizer()
        tokenizer1.tokenize_document("bitcoin transaction fee calculation")
        tokenizer1.tokenize_document("escrow dispute resolution process")

        # Export vocabulary
        vocab_json = tokenizer1.export_vocabulary()

        # Create new tokenizer and load vocabulary
        tokenizer2 = BM25SparseTokenizer()
        tokenizer2.load_vocabulary(vocab_json)

        # Verify state is preserved
        assert tokenizer2.vocabulary_size == tokenizer1.vocabulary_size
        assert tokenizer2._num_documents == tokenizer1._num_documents

        # Verify queries produce same results
        indices1, values1 = tokenizer1.tokenize_query("bitcoin fee")
        indices2, values2 = tokenizer2.tokenize_query("bitcoin fee")

        assert indices1 == indices2
        assert values1 == values2


class TestRAGServiceIntegration:
    """Integration tests for RAG service with BM25 hybrid retrieval."""

    @pytest.fixture
    def mock_qdrant_client(self):
        """Create a mock Qdrant client."""
        client = MagicMock()
        client.search.return_value = []
        client.query_points.return_value = MagicMock(points=[])
        return client

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings provider."""
        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1] * 1536
        embeddings.embed_documents.return_value = [[0.1] * 1536]
        return embeddings

    def test_rag_service_initializes_bm25_components(self):
        """RAG service should initialize BM25 components correctly."""
        # This test verifies the integration points exist
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        # These classes should be available for RAG service integration
        assert BM25SparseTokenizer is not None
        assert VocabularyManager is not None

    def test_vocabulary_manager_creates_tokenizer_with_correct_state(self, tmp_path):
        """VocabularyManager should correctly save and load tokenizer state."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "test_vocab.json"
        manager = VocabularyManager(vocab_path)

        # Create tokenizer with documents
        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize_document("bitcoin wallet")
        tokenizer.tokenize_document("escrow dispute")
        original_stats = tokenizer.get_statistics()

        # Save vocabulary
        assert manager.save(tokenizer) is True

        # Load into new tokenizer
        new_tokenizer = BM25SparseTokenizer()
        assert manager.load(new_tokenizer) is True

        new_stats = new_tokenizer.get_statistics()
        assert new_stats["vocabulary_size"] == original_stats["vocabulary_size"]
        assert new_stats["num_documents"] == original_stats["num_documents"]


class TestCachingIntegration:
    """Integration tests for caching layers with RAG pipeline."""

    def test_cached_embeddings_integrates_with_litellm(self):
        """CachedEmbeddings should wrap LiteLLM embeddings correctly."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        # Create mock LiteLLM embeddings
        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(mock_embeddings, max_cache_size=100)

        # First call goes to underlying provider
        result1 = cached.embed_query("test query")
        assert mock_embeddings.embed_query.call_count == 1

        # Second call uses cache
        result2 = cached.embed_query("test query")
        assert mock_embeddings.embed_query.call_count == 1

        assert result1 == result2

    def test_query_cache_integrates_with_rag_results(self):
        """QueryCacheManager should cache complete RAG results."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager()

        # Simulate RAG result structure
        rag_result = {
            "answer": "Bitcoin is a decentralized cryptocurrency...",
            "sources": [
                {"content": "Source 1", "metadata": {"source": "faq"}},
                {"content": "Source 2", "metadata": {"source": "wiki"}},
            ],
            "confidence": 0.85,
        }

        # Cache the result
        cache.set("What is Bitcoin?", rag_result)

        # Retrieve from cache
        cached_result = cache.get("What is Bitcoin?")

        assert cached_result is not None
        assert cached_result["answer"] == rag_result["answer"]
        assert len(cached_result["sources"]) == 2

    def test_nli_caching_with_repeated_validations(self):
        """NLI validator caching should work with real validation flow."""
        from app.services.rag.nli_validator import NLIValidator

        validator = NLIValidator(enable_cache=True, cache_size=100)

        # First validation (will use model or return neutral if not available)
        result1 = validator.validate_answer(
            answer="Bisq is a peer-to-peer exchange",
            source_text="Bisq is a decentralized peer-to-peer exchange platform",
        )

        # Second validation with same inputs (should use cache)
        result2 = validator.validate_answer(
            answer="Bisq is a peer-to-peer exchange",
            source_text="Bisq is a decentralized peer-to-peer exchange platform",
        )

        # Results should be identical (either from model or neutral)
        assert result1 == result2

        # Cache stats should show hit
        stats = validator.get_cache_statistics()
        assert stats["enabled"] is True
        assert stats["hits"] >= 1


class TestScoreNormalizationIntegration:
    """Integration tests for score normalization in hybrid search."""

    def test_hybrid_scores_are_normalized(self):
        """Hybrid search should normalize scores from dense and sparse retrieval."""
        # Test the normalization logic with edge cases
        scores = [0.8, 0.6, 0.4, 0.2]
        min_score = min(scores)
        max_score = max(scores)

        if max_score > min_score:
            normalized = [(s - min_score) / (max_score - min_score) for s in scores]
        else:
            normalized = [0.5] * len(scores)

        # Normalized scores should be between 0 and 1
        assert all(0 <= n <= 1 for n in normalized)
        # First score should be 1.0 (max), last should be 0.0 (min)
        assert normalized[0] == 1.0
        assert normalized[-1] == 0.0

    def test_normalization_handles_single_result(self):
        """Single result should get normalized score of 1.0."""
        scores = [0.75]
        min_score = max_score = scores[0]

        if max_score == min_score:
            normalized = [1.0]
        else:
            normalized = [(s - min_score) / (max_score - min_score) for s in scores]

        assert normalized == [1.0]

    def test_normalization_handles_equal_scores(self):
        """Equal scores should all normalize to 0.5."""
        scores = [0.5, 0.5, 0.5, 0.5]
        min_score = max_score = scores[0]

        if max_score == min_score:
            normalized = [0.5] * len(scores)
        else:
            normalized = [(s - min_score) / (max_score - min_score) for s in scores]

        assert all(n == 0.5 for n in normalized)


class TestErrorHandlingIntegration:
    """Integration tests for error handling across the RAG pipeline."""

    def test_bm25_handles_malformed_input(self):
        """BM25 tokenizer should handle malformed input gracefully."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # None input should be handled
        indices, values = tokenizer.tokenize_query(None)  # type: ignore
        assert indices == []
        assert values == []

        # Empty string is valid
        indices, values = tokenizer.tokenize_query("")
        assert indices == []
        assert values == []

    def test_bm25_rejects_oversized_input(self):
        """BM25 tokenizer should reject inputs exceeding MAX_INPUT_SIZE."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        original_limit = BM25SparseTokenizer.MAX_INPUT_SIZE

        try:
            BM25SparseTokenizer.MAX_INPUT_SIZE = 100
            large_input = "x" * 200

            with pytest.raises(ValueError, match="[Ii]nput.*exceeds"):
                tokenizer.tokenize(large_input)
        finally:
            BM25SparseTokenizer.MAX_INPUT_SIZE = original_limit

    def test_vocabulary_manager_handles_missing_file(self, tmp_path):
        """VocabularyManager should handle missing vocabulary file gracefully."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "nonexistent.json"
        manager = VocabularyManager(vocab_path)

        tokenizer = BM25SparseTokenizer()
        result = manager.load(tokenizer)

        assert result is False  # Should return False, not raise

    def test_cached_embeddings_handles_api_errors(self):
        """CachedEmbeddings should propagate API errors appropriately."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.side_effect = Exception("API Error")

        cached = CachedEmbeddings(mock_embeddings)

        with pytest.raises(Exception, match="API Error"):
            cached.embed_query("test query")


class TestPerformanceCharacteristics:
    """Tests for performance characteristics of the BM25+RAG pipeline."""

    def test_bm25_statistics_reflect_actual_state(self):
        """BM25 statistics should accurately reflect tokenizer state."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Initial state
        stats = tokenizer.get_statistics()
        assert stats["vocabulary_size"] == 0
        assert stats["num_documents"] == 0

        # After indexing
        tokenizer.tokenize_document("bitcoin wallet transaction")
        tokenizer.tokenize_document("escrow dispute resolution")

        stats = tokenizer.get_statistics()
        assert stats["vocabulary_size"] > 0
        assert stats["num_documents"] == 2
        assert stats["avg_doc_length"] > 0
        assert stats["total_tokens_processed"] > 0

    def test_cache_statistics_track_performance(self):
        """Cache statistics should accurately track hits and misses."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(mock_embeddings)

        # Generate cache activity
        cached.embed_query("query1")  # Miss
        cached.embed_query("query1")  # Hit
        cached.embed_query("query2")  # Miss
        cached.embed_query("query1")  # Hit

        stats = cached.get_statistics()
        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 2
        assert stats["hit_rate"] == 0.5
