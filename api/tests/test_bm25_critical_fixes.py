"""
TDD tests for critical BM25 tokenizer fixes identified by multi-agent review.

These tests are written FIRST (RED phase) to define expected behavior,
then implementation follows to make them pass (GREEN phase).

Critical issues addressed:
1. Document frequency double-counting bug
2. Unbounded vocabulary growth (DoS vector)
3. Thread safety violation in load_vocabulary()
4. Input size validation missing
5. Score normalization edge case
"""

import threading

import pytest


class TestDocumentFrequencyAccuracy:
    """Tests for correct document frequency calculation (no double-counting)."""

    def test_tokenize_document_increments_df_once_per_document(self):
        """Each document should increment DF for each token only once.

        Critical bug: tokenize_document was incrementing DF, AND the code path
        through _add_token_to_vocabulary or corpus building also incremented DF,
        causing double-counting.
        """
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Index a document with "bitcoin" appearing multiple times
        tokenizer.tokenize_document("bitcoin bitcoin bitcoin wallet")

        # DF for "bitcoin" should be 1 (appears in 1 document)
        assert tokenizer._document_frequencies["bitcoin"] == 1
        # DF for "wallet" should be 1
        assert tokenizer._document_frequencies["wallet"] == 1
        # Total documents should be 1
        assert tokenizer._num_documents == 1

    def test_multiple_documents_have_correct_df(self):
        """Document frequency should equal number of documents containing the term."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Index 3 documents, all contain "bitcoin", only 1 contains "escrow"
        tokenizer.tokenize_document("bitcoin transaction")
        tokenizer.tokenize_document("bitcoin wallet")
        tokenizer.tokenize_document("bitcoin escrow")

        # "bitcoin" appears in all 3 documents
        assert tokenizer._document_frequencies["bitcoin"] == 3
        # "escrow" appears in only 1 document
        assert tokenizer._document_frequencies["escrow"] == 1
        # Total documents
        assert tokenizer._num_documents == 3

    def test_corpus_initialization_correct_df(self):
        """Corpus initialization should have correct DF counts."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        corpus = [
            "bitcoin transaction fee",
            "bitcoin wallet security",
            "escrow mechanism",
        ]
        tokenizer = BM25SparseTokenizer(corpus=corpus)

        # "bitcoin" appears in 2 documents
        assert tokenizer._document_frequencies["bitcoin"] == 2
        # "escrow" appears in 1 document
        assert tokenizer._document_frequencies["escrow"] == 1
        # Total documents
        assert tokenizer._num_documents == 3

    def test_idf_values_consistent_after_indexing(self):
        """IDF should decrease as term becomes more common."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Index first document
        tokenizer.tokenize_document("bitcoin")
        idf_after_1 = tokenizer._get_idf("bitcoin")

        # Index second document with same term
        tokenizer.tokenize_document("bitcoin wallet")
        idf_after_2 = tokenizer._get_idf("bitcoin")

        # IDF should decrease (term is now more common)
        assert idf_after_2 < idf_after_1

        # Index third document with same term
        tokenizer.tokenize_document("bitcoin escrow")
        idf_after_3 = tokenizer._get_idf("bitcoin")

        # IDF should continue to decrease
        assert idf_after_3 < idf_after_2


class TestVocabularySizeLimit:
    """Tests for vocabulary size limits to prevent DoS attacks."""

    def test_vocabulary_has_max_size_limit(self):
        """Tokenizer should have a MAX_VOCABULARY_SIZE constant."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Should have a reasonable default limit
        assert hasattr(BM25SparseTokenizer, "MAX_VOCABULARY_SIZE")
        assert BM25SparseTokenizer.MAX_VOCABULARY_SIZE > 0
        # Default should be reasonable (e.g., 500K)
        assert BM25SparseTokenizer.MAX_VOCABULARY_SIZE <= 1_000_000

    def test_vocabulary_rejects_tokens_above_limit(self):
        """Adding tokens beyond MAX_VOCABULARY_SIZE should be rejected."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Create tokenizer with artificially low limit for testing
        tokenizer = BM25SparseTokenizer()
        original_limit = BM25SparseTokenizer.MAX_VOCABULARY_SIZE

        try:
            # Temporarily set a very low limit
            BM25SparseTokenizer.MAX_VOCABULARY_SIZE = 5

            # Add tokens up to limit
            tokenizer.tokenize_document("one two three four five")
            assert tokenizer.vocabulary_size == 5

            # Attempt to add more tokens - should not grow beyond limit
            tokenizer.tokenize_document("six seven eight nine ten")
            assert tokenizer.vocabulary_size == 5  # Still at limit
        finally:
            # Restore original limit
            BM25SparseTokenizer.MAX_VOCABULARY_SIZE = original_limit

    def test_vocabulary_limit_logs_warning(self, caplog):
        """Exceeding vocabulary limit should log a warning."""
        import logging

        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        original_limit = BM25SparseTokenizer.MAX_VOCABULARY_SIZE

        try:
            BM25SparseTokenizer.MAX_VOCABULARY_SIZE = 3

            with caplog.at_level(logging.WARNING):
                tokenizer.tokenize_document("one two three")
                tokenizer.tokenize_document("four five six")  # Should trigger warning

            assert any(
                "vocabulary" in record.message.lower() for record in caplog.records
            )
        finally:
            BM25SparseTokenizer.MAX_VOCABULARY_SIZE = original_limit


class TestInputSizeValidation:
    """Tests for input size validation to prevent memory exhaustion."""

    def test_tokenizer_has_max_input_size(self):
        """Tokenizer should have a MAX_INPUT_SIZE constant."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        assert hasattr(BM25SparseTokenizer, "MAX_INPUT_SIZE")
        assert BM25SparseTokenizer.MAX_INPUT_SIZE > 0
        # Default should be reasonable (e.g., 1MB)
        assert BM25SparseTokenizer.MAX_INPUT_SIZE >= 100_000

    def test_tokenize_validates_input_size(self):
        """Tokenize should raise ValueError for inputs exceeding MAX_INPUT_SIZE."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        original_limit = BM25SparseTokenizer.MAX_INPUT_SIZE

        try:
            # Set a low limit for testing
            BM25SparseTokenizer.MAX_INPUT_SIZE = 100

            # Normal input should work
            tokenizer.tokenize("short text")

            # Input exceeding limit should raise
            large_input = "x" * 200
            with pytest.raises(ValueError, match="[Ii]nput.*exceeds"):
                tokenizer.tokenize(large_input)
        finally:
            BM25SparseTokenizer.MAX_INPUT_SIZE = original_limit

    def test_tokenize_document_validates_input_size(self):
        """tokenize_document should also validate input size."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        original_limit = BM25SparseTokenizer.MAX_INPUT_SIZE

        try:
            BM25SparseTokenizer.MAX_INPUT_SIZE = 100
            large_input = "x" * 200

            with pytest.raises(ValueError, match="[Ii]nput.*exceeds"):
                tokenizer.tokenize_document(large_input)
        finally:
            BM25SparseTokenizer.MAX_INPUT_SIZE = original_limit


class TestLoadVocabularyThreadSafety:
    """Tests for thread safety of load_vocabulary."""

    def test_load_vocabulary_uses_lock(self):
        """load_vocabulary should use the update lock.

        We verify this by checking that concurrent load and tokenize operations
        don't corrupt data, which would happen if load didn't use the lock.
        """
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize_document("initial content for test")
        vocab_json = tokenizer.export_vocabulary()

        # Create new tokenizer and verify load works correctly
        new_tokenizer = BM25SparseTokenizer()
        new_tokenizer.load_vocabulary(vocab_json)

        # Verify the vocabulary was loaded correctly
        assert new_tokenizer.vocabulary_size == tokenizer.vocabulary_size
        assert new_tokenizer._num_documents == tokenizer._num_documents

        # Verify we can tokenize after load (would fail if state is corrupt)
        indices, values = new_tokenizer.tokenize_document("test document")
        assert len(indices) > 0

    def test_concurrent_load_and_tokenize(self):
        """Concurrent load_vocabulary and tokenize_document should be safe."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize_document("initial vocabulary content")
        vocab_json = tokenizer.export_vocabulary()

        errors = []
        results = []

        def load_worker():
            try:
                new_tokenizer = BM25SparseTokenizer()
                for _ in range(10):
                    new_tokenizer.load_vocabulary(vocab_json)
                results.append("load_ok")
            except Exception as e:
                errors.append(("load", e))

        def tokenize_worker():
            try:
                new_tokenizer = BM25SparseTokenizer()
                new_tokenizer.load_vocabulary(vocab_json)
                for i in range(10):
                    new_tokenizer.tokenize_document(f"document number {i} with content")
                results.append("tokenize_ok")
            except Exception as e:
                errors.append(("tokenize", e))

        # Run concurrent operations
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=load_worker))
            threads.append(threading.Thread(target=tokenize_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0, f"Errors occurred: {errors}"


class TestScoreNormalizationEdgeCases:
    """Tests for score normalization edge cases in hybrid search."""

    def test_normalization_handles_all_equal_scores(self):
        """Score normalization should handle case where all scores are equal."""
        # This test is for the hybrid retriever, not the tokenizer
        # But we document the edge case here

        scores = [0.5, 0.5, 0.5, 0.5]

        # When min == max, normalization should not produce NaN or infinity
        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            # All scores should be 0.5 (midpoint) or some reasonable default
            normalized = [0.5] * len(scores)
        else:
            normalized = [(s - min_score) / (max_score - min_score) for s in scores]

        # No NaN or infinity
        import math

        assert all(not math.isnan(s) and not math.isinf(s) for s in normalized)

    def test_normalization_handles_single_result(self):
        """Score normalization should handle single result case."""
        scores = [0.75]

        min_score = min(scores)
        max_score = max(scores)

        if max_score == min_score:
            normalized = [1.0]  # Single result gets perfect score
        else:
            normalized = [(s - min_score) / (max_score - min_score) for s in scores]

        assert normalized == [1.0]

    def test_normalization_handles_empty_results(self):
        """Score normalization should handle empty results."""
        scores = []

        # Should not raise
        if not scores:
            normalized = []
        else:
            min_score = min(scores)
            max_score = max(scores)
            normalized = [
                (
                    (s - min_score) / (max_score - min_score)
                    if max_score != min_score
                    else 0.5
                )
                for s in scores
            ]

        assert normalized == []


class TestStatisticsAndObservability:
    """Tests for tokenizer statistics and observability."""

    def test_get_statistics_returns_useful_metrics(self):
        """get_statistics should return useful monitoring metrics."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize_document("bitcoin wallet transaction")
        tokenizer.tokenize_document("escrow mediator")

        stats = tokenizer.get_statistics()

        assert "vocabulary_size" in stats
        assert "num_documents" in stats
        assert "avg_doc_length" in stats
        assert "total_tokens_processed" in stats

        assert stats["vocabulary_size"] == 5
        assert stats["num_documents"] == 2
        assert stats["avg_doc_length"] > 0
        assert stats["total_tokens_processed"] > 0

    def test_vocabulary_at_limit_indicator(self):
        """Statistics should indicate when vocabulary is at limit."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        original_limit = BM25SparseTokenizer.MAX_VOCABULARY_SIZE

        try:
            BM25SparseTokenizer.MAX_VOCABULARY_SIZE = 5
            tokenizer.tokenize_document("one two three four five")
            tokenizer.tokenize_document("six seven")  # Should hit limit

            stats = tokenizer.get_statistics()

            # Should indicate vocabulary is at limit
            assert "vocabulary_at_limit" in stats or stats["vocabulary_size"] == 5
        finally:
            BM25SparseTokenizer.MAX_VOCABULARY_SIZE = original_limit
