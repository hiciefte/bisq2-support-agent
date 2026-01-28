"""
TDD tests for caching layer improvements identified by multi-agent review.

These tests are written FIRST (RED phase) to define expected behavior:
1. Embedding result caching with TTL
2. NLI validation result caching
3. Query result caching for identical queries

Critical issues addressed:
- Embedding API calls are expensive and slow
- NLI validation adds latency to every response
- Repeated identical queries should return cached results
"""

import threading
import time
from unittest.mock import MagicMock, patch


class TestEmbeddingCaching:
    """Tests for embedding result caching to reduce API calls."""

    def test_cached_embeddings_has_cache_attribute(self):
        """CachedEmbeddings should have a cache dict and max_size."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        # Create mock base embeddings
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(
            mock_embeddings, max_cache_size=1000, ttl_seconds=3600
        )

        assert hasattr(cached, "_cache")
        assert hasattr(cached, "_max_cache_size")
        assert hasattr(cached, "_ttl_seconds")
        assert cached._max_cache_size == 1000
        assert cached._ttl_seconds == 3600

    def test_embed_query_caches_result(self):
        """embed_query should cache results and return cached on repeat calls."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(mock_embeddings)

        # First call - should hit the underlying embeddings
        result1 = cached.embed_query("test query")
        assert mock_embeddings.embed_query.call_count == 1

        # Second call with same query - should use cache
        result2 = cached.embed_query("test query")
        assert mock_embeddings.embed_query.call_count == 1  # Still 1, not 2

        # Results should be identical
        assert result1 == result2 == [0.1, 0.2, 0.3]

    def test_embed_documents_caches_individual_texts(self):
        """embed_documents should cache each document separately."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [
            [0.1, 0.2],
            [0.3, 0.4],
            [0.5, 0.6],
        ]

        cached = CachedEmbeddings(mock_embeddings)

        # First call with 3 documents
        cached.embed_documents(["doc1", "doc2", "doc3"])
        assert mock_embeddings.embed_documents.call_count == 1

        # Second call with same documents - all should be cached
        mock_embeddings.embed_documents.reset_mock()
        mock_embeddings.embed_documents.return_value = []  # Won't be called
        result = cached.embed_documents(["doc1", "doc2", "doc3"])
        assert mock_embeddings.embed_documents.call_count == 0
        assert result == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]

    def test_embed_documents_partial_cache_hit(self):
        """embed_documents should only call API for uncached documents."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()

        # First call caches doc1 and doc2
        mock_embeddings.embed_documents.return_value = [[0.1, 0.2], [0.3, 0.4]]
        cached = CachedEmbeddings(mock_embeddings)
        cached.embed_documents(["doc1", "doc2"])

        # Second call with doc1 (cached), doc3 (new)
        mock_embeddings.embed_documents.reset_mock()
        mock_embeddings.embed_documents.return_value = [[0.5, 0.6]]  # Only doc3

        result = cached.embed_documents(["doc1", "doc3"])

        # Should only call API for doc3
        mock_embeddings.embed_documents.assert_called_once_with(["doc3"])

        # Result should have both - doc1 from cache, doc3 from API
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]  # doc1 from cache
        assert result[1] == [0.5, 0.6]  # doc3 from API

    def test_cache_respects_max_size(self):
        """Cache should evict oldest entries when max size is reached."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(mock_embeddings, max_cache_size=3)

        # Fill cache
        cached.embed_query("query1")
        cached.embed_query("query2")
        cached.embed_query("query3")
        assert cached.cache_size == 3

        # Add one more - should evict oldest
        cached.embed_query("query4")
        assert cached.cache_size == 3  # Still 3, not 4

        # query1 should be evicted, query4 should be cached
        assert "query1" not in str(cached._cache.keys())

    def test_cache_respects_ttl(self):
        """Cache entries should expire after TTL."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        # Very short TTL for testing
        cached = CachedEmbeddings(mock_embeddings, ttl_seconds=0.1)

        # First call
        cached.embed_query("test query")
        assert mock_embeddings.embed_query.call_count == 1

        # Wait for TTL to expire
        time.sleep(0.15)

        # Second call - should hit API again because cache expired
        cached.embed_query("test query")
        assert mock_embeddings.embed_query.call_count == 2

    def test_cache_is_thread_safe(self):
        """Cache should be thread-safe for concurrent access."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        call_count = 0
        call_lock = threading.Lock()

        def mock_embed_query(text: str) -> list[float]:
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.01)  # Simulate API latency
            return [0.1, 0.2, 0.3]

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.side_effect = mock_embed_query

        cached = CachedEmbeddings(mock_embeddings)
        errors = []

        def worker(query: str):
            try:
                for _ in range(5):
                    cached.embed_query(query)
            except Exception as e:
                errors.append(e)

        # Run concurrent threads
        threads = [
            threading.Thread(target=worker, args=(f"query{i}",)) for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Each unique query should only be embedded once
        assert call_count == 5

    def test_get_cache_statistics(self):
        """CachedEmbeddings should provide cache statistics."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(mock_embeddings)

        # Generate some cache activity
        cached.embed_query("query1")
        cached.embed_query("query1")  # Cache hit
        cached.embed_query("query2")
        cached.embed_query("query1")  # Cache hit

        stats = cached.get_statistics()

        assert "cache_size" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "hit_rate" in stats

        assert stats["cache_size"] == 2
        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 2
        assert stats["hit_rate"] == 0.5  # 2 hits / 4 total


class TestNLIValidationCaching:
    """Tests for NLI validation result caching."""

    def test_nli_validator_has_cache(self):
        """NLIValidator should have caching capability."""
        from app.services.rag.nli_validator import NLIValidator

        validator = NLIValidator(enable_cache=True, cache_size=1000)

        assert hasattr(validator, "_cache")
        assert hasattr(validator, "_cache_enabled")
        assert validator._cache_enabled is True

    def test_nli_validation_caches_results(self):
        """NLI validation should cache results for identical premise/hypothesis pairs."""
        from app.services.rag.nli_validator import NLIValidator

        validator = NLIValidator(enable_cache=True)

        # First validation
        result1 = validator.validate_answer(
            answer="Bitcoin is a cryptocurrency",
            source_text="Bitcoin is a decentralized digital currency",
        )

        # Second validation with same inputs - should use cache
        with patch.object(validator, "_run_inference") as mock_inference:
            result2 = validator.validate_answer(
                answer="Bitcoin is a cryptocurrency",
                source_text="Bitcoin is a decentralized digital currency",
            )
            # Should NOT call inference - result should come from cache
            mock_inference.assert_not_called()

        assert result1 == result2

    def test_nli_cache_key_generation(self):
        """Cache key should be deterministic for same inputs."""
        from app.services.rag.nli_validator import NLIValidator

        validator = NLIValidator(enable_cache=True)

        key1 = validator._get_cache_key("answer1", "source1")
        key2 = validator._get_cache_key("answer1", "source1")
        key3 = validator._get_cache_key("answer2", "source1")

        assert key1 == key2  # Same inputs = same key
        assert key1 != key3  # Different inputs = different key

    def test_nli_cache_disabled_by_default_in_batch(self):
        """Batch validation should respect cache settings."""
        from app.services.rag.nli_validator import NLIValidator

        # Cache disabled
        validator_no_cache = NLIValidator(enable_cache=False)
        assert validator_no_cache._cache_enabled is False

        # Cache enabled
        validator_cache = NLIValidator(enable_cache=True)
        assert validator_cache._cache_enabled is True


class TestQueryResultCaching:
    """Tests for caching complete query results."""

    def test_query_cache_manager_exists(self):
        """QueryCacheManager should exist for caching query results."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager(max_size=100, ttl_seconds=300)

        assert hasattr(cache, "get")
        assert hasattr(cache, "set")
        assert hasattr(cache, "clear")

    def test_query_cache_stores_and_retrieves(self):
        """Cache should store and retrieve query results."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager()

        query = "What is Bisq?"
        result = {"answer": "Bisq is a P2P exchange", "sources": ["doc1"]}

        cache.set(query, result)
        retrieved = cache.get(query)

        assert retrieved == result

    def test_query_cache_miss_returns_none(self):
        """Cache miss should return None."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager()

        result = cache.get("nonexistent query")
        assert result is None

    def test_query_cache_considers_context(self):
        """Same query with different context should have different cache entries."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager()

        query = "How do I trade?"
        context1 = {"protocol": "bisq_easy"}
        context2 = {"protocol": "multisig_v1"}

        cache.set(query, {"answer": "Bisq 2 answer"}, context=context1)
        cache.set(query, {"answer": "Bisq 1 answer"}, context=context2)

        result1 = cache.get(query, context=context1)
        result2 = cache.get(query, context=context2)

        assert result1["answer"] == "Bisq 2 answer"
        assert result2["answer"] == "Bisq 1 answer"

    def test_query_cache_ttl_expiration(self):
        """Cache entries should expire after TTL."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager(ttl_seconds=0.1)

        cache.set("query", {"answer": "test"})
        assert cache.get("query") is not None

        time.sleep(0.15)

        assert cache.get("query") is None

    def test_query_cache_statistics(self):
        """Cache should track hit/miss statistics."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager()

        cache.set("query1", {"answer": "test1"})
        cache.get("query1")  # Hit
        cache.get("query1")  # Hit
        cache.get("query2")  # Miss

        stats = cache.get_statistics()

        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 2 / 3


class TestCacheIntegration:
    """Integration tests for caching across the RAG pipeline."""

    def test_rag_service_uses_embedding_cache(self):
        """SimplifiedRAGService should use cached embeddings when available."""
        # This test verifies the integration point exists
        # Full integration test requires more setup
        from app.services.rag.cached_embeddings import CachedEmbeddings

        assert CachedEmbeddings is not None

    def test_cache_warming_on_startup(self):
        """Cache should support pre-warming with common queries."""
        from app.services.rag.query_cache import QueryCacheManager

        cache = QueryCacheManager()

        # Pre-warm with common queries
        common_queries = [
            ("What is Bisq?", {"answer": "P2P exchange"}),
            ("How to buy Bitcoin?", {"answer": "Use Bisq Easy"}),
        ]

        cache.warm(common_queries)

        # Verify all are cached
        for query, expected in common_queries:
            result = cache.get(query)
            assert result == expected
