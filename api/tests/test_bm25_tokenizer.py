"""
TDD tests for BM25 Sparse Vector Tokenizer.

This module tests the BM25SparseTokenizer which creates sparse vectors
for Qdrant hybrid search. The tokenizer must ensure alignment between
document indexing and query tokenization.

Key requirements tested:
1. Deterministic tokenization (same input → same output)
2. Proper vocabulary-based indexing (no hash collisions)
3. TF-IDF/BM25 weighting with corpus statistics
4. Stopword removal for efficiency
5. Alignment between document and query tokenization
"""


class TestBM25SparseTokenizerSpec:
    """Specification tests for BM25SparseTokenizer - TDD approach.

    These tests define the expected behavior BEFORE implementation.
    Run with: pytest api/tests/test_bm25_tokenizer.py -v
    """

    # ==========================================================================
    # Basic Tokenization Tests
    # ==========================================================================

    def test_tokenize_returns_indices_and_values(self):
        """Tokenizer should return (indices, values) tuple for sparse vector."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        indices, values = tokenizer.tokenize("bitcoin transaction")

        assert isinstance(indices, list)
        assert isinstance(values, list)
        assert len(indices) == len(values)
        assert all(isinstance(i, int) for i in indices)
        assert all(isinstance(v, float) for v in values)

    def test_tokenize_deterministic(self):
        """Same input text should produce identical indices (values may vary with corpus)."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        text = "How do I send bitcoin in Bisq?"

        indices1, _ = tokenizer.tokenize(text)

        # Create a fresh tokenizer for determinism test
        tokenizer2 = BM25SparseTokenizer()
        indices2, _ = tokenizer2.tokenize(text)

        # Indices should be the same (same vocabulary order)
        assert indices1 == indices2

    def test_tokenize_case_insensitive(self):
        """Tokenization should be case-insensitive."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        indices1, _ = tokenizer.tokenize("Bitcoin")
        indices2, _ = tokenizer.tokenize("bitcoin")
        indices3, _ = tokenizer.tokenize("BITCOIN")

        assert indices1 == indices2 == indices3

    def test_tokenize_removes_stopwords(self):
        """Common stopwords should not be included in sparse vector."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # "the", "a", "is", "in", "to" are stopwords
        indices, _ = tokenizer.tokenize("the bitcoin is in a wallet")

        # Should only have tokens for "bitcoin" and "wallet"
        assert len(indices) == 2

    def test_tokenize_handles_empty_input(self):
        """Empty input should return empty sparse vector."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        indices, values = tokenizer.tokenize("")

        assert indices == []
        assert values == []

    def test_tokenize_handles_only_stopwords(self):
        """Input with only stopwords should return empty sparse vector."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        indices, values = tokenizer.tokenize("the is a an")

        assert indices == []
        assert values == []

    # ==========================================================================
    # Vocabulary-Based Indexing Tests (No Hash Collisions)
    # ==========================================================================

    def test_vocabulary_unique_indices(self):
        """Each unique token must have a unique index (no collisions)."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Build vocabulary from diverse terms
        terms = ["bitcoin", "transaction", "wallet", "bisq", "trade", "offer"]
        all_indices = set()

        for term in terms:
            indices, _ = tokenizer.tokenize(term)
            all_indices.update(indices)

        # Each term should have produced a unique index
        assert len(all_indices) == len(terms)

    def test_vocabulary_consistency_across_documents(self):
        """Same token in different documents should get same index."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        doc1_indices, _ = tokenizer.tokenize("bitcoin transaction fee")
        doc2_indices, _ = tokenizer.tokenize("high bitcoin price today")

        # "bitcoin" should have same index in both
        # Find the index for "bitcoin" by tokenizing it alone
        bitcoin_idx, _ = tokenizer.tokenize("bitcoin")

        assert bitcoin_idx[0] in doc1_indices
        assert bitcoin_idx[0] in doc2_indices

    def test_vocabulary_indices_non_negative(self):
        """All vocabulary indices must be non-negative integers."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        indices, _ = tokenizer.tokenize("bitcoin wallet transaction fee escrow")

        assert all(i >= 0 for i in indices)

    # ==========================================================================
    # BM25/TF-IDF Weighting Tests
    # ==========================================================================

    def test_term_frequency_affects_weight(self):
        """Repeated terms should have higher weights (TF component)."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Document with repeated term
        indices1, values1 = tokenizer.tokenize("bitcoin bitcoin bitcoin")
        # Document with single term
        indices2, values2 = tokenizer.tokenize("bitcoin")

        # Both should have same index for "bitcoin"
        assert indices1 == indices2

        # Weight should be higher for repeated term (TF effect)
        assert values1[0] > values2[0]

    def test_rare_terms_have_higher_idf(self):
        """Rare terms in corpus should have higher IDF weights."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Build tokenizer with corpus knowledge
        corpus = [
            "bitcoin bitcoin bitcoin",  # common term
            "bitcoin transaction",
            "bitcoin wallet",
            "raretermxyz",  # rare term (single word, no underscore)
        ]
        tokenizer = BM25SparseTokenizer(corpus=corpus)

        # Query with both common and rare terms - use tokenize_query for lookups
        indices, values = tokenizer.tokenize_query("bitcoin raretermxyz")

        # Create a dict mapping indices to values
        idx_to_weight = dict(zip(indices, values))

        # Get the indices for each term
        bitcoin_idx = tokenizer._token_to_index.get("bitcoin")
        rare_idx = tokenizer._token_to_index.get("raretermxyz")

        assert bitcoin_idx is not None, "bitcoin should be in vocabulary"
        assert rare_idx is not None, "raretermxyz should be in vocabulary"

        bitcoin_weight = idx_to_weight[bitcoin_idx]
        rare_weight = idx_to_weight[rare_idx]

        # Rare term should have higher IDF weight
        assert rare_weight > bitcoin_weight

    def test_idf_weights_positive(self):
        """All IDF weights should be positive."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        _, values = tokenizer.tokenize("bitcoin wallet transaction escrow")

        assert all(v > 0 for v in values)

    # ==========================================================================
    # Query Tokenization Tests
    # ==========================================================================

    def test_query_tokenization_aligns_with_documents(self):
        """Query tokenization must use same vocabulary as document indexing."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Index a document
        tokenizer = BM25SparseTokenizer()
        doc_indices, _ = tokenizer.tokenize_document("bitcoin transaction fee")

        # Query should match document vocabulary
        query_indices, _ = tokenizer.tokenize_query("bitcoin fee")

        # All query indices should be valid document indices
        for idx in query_indices:
            assert idx in doc_indices or tokenizer.has_token(idx)

    def test_query_tokenization_for_sparse_vector(self):
        """Query tokenization returns proper format for Qdrant sparse search."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        indices, values = tokenizer.tokenize_query("How send bitcoin Bisq?")

        # Should be ready for Qdrant SparseVector
        assert len(indices) > 0
        assert len(indices) == len(values)

    # ==========================================================================
    # Bisq-Specific Domain Tests
    # ==========================================================================

    def test_tokenize_bisq_terminology(self):
        """Should correctly tokenize Bisq-specific terms."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Bisq-specific terms should be tokenized correctly
        bisq_terms = [
            "bisq",
            "bisq2",
            "multisig",
            "escrow",
            "arbitrator",
            "mediator",
            "fiat",
            "altcoin",
        ]

        for term in bisq_terms:
            indices, values = tokenizer.tokenize(term)
            assert len(indices) == 1, f"Term '{term}' should have exactly one index"
            assert values[0] > 0, f"Term '{term}' should have positive weight"

    def test_tokenize_compound_bisq_terms(self):
        """Should handle compound Bisq terms correctly."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Compound terms
        text = "Bisq-Easy multisig_escrow"

        indices, values = tokenizer.tokenize(text)

        # Should handle both hyphenated and underscore terms
        assert len(indices) >= 2

    def test_tokenize_bitcoin_addresses_excluded(self):
        """Bitcoin addresses should not pollute the vocabulary."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        text = "Send bitcoin to bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

        indices, _ = tokenizer.tokenize(text)

        # Address should be filtered out, only "send" and "bitcoin" remain
        assert len(indices) == 2

    def test_tokenize_preserves_version_numbers(self):
        """Version numbers like 'bisq2' should be kept as single tokens."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # "bisq2" should stay as one token, not split into "bisq" and "2"
        indices, _ = tokenizer.tokenize("bisq2")

        assert len(indices) == 1

    # ==========================================================================
    # Serialization and Persistence Tests
    # ==========================================================================

    def test_vocabulary_serializable(self):
        """Vocabulary should be serializable for persistence."""
        import json

        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize("bitcoin transaction wallet")

        # Should be able to export vocabulary
        vocab_json = tokenizer.export_vocabulary()

        # Should be valid JSON
        vocab_data = json.loads(vocab_json)

        assert "token_to_index" in vocab_data
        assert "idf_scores" in vocab_data

    def test_vocabulary_loadable(self):
        """Should be able to load vocabulary from saved state."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Create and train tokenizer
        tokenizer1 = BM25SparseTokenizer()
        tokenizer1.tokenize("bitcoin transaction wallet")
        vocab_json = tokenizer1.export_vocabulary()

        # Load vocabulary into new tokenizer
        tokenizer2 = BM25SparseTokenizer()
        tokenizer2.load_vocabulary(vocab_json)

        # Should produce same results
        indices1, values1 = tokenizer1.tokenize("bitcoin wallet")
        indices2, values2 = tokenizer2.tokenize("bitcoin wallet")

        assert indices1 == indices2
        assert values1 == values2

    # ==========================================================================
    # Integration with Qdrant Tests
    # ==========================================================================

    def test_sparse_vector_format_for_qdrant(self):
        """Output format should be compatible with Qdrant SparseVector."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()
        indices, values = tokenizer.tokenize("bitcoin transaction")

        # Should work with Qdrant's SparseVector
        # Qdrant expects indices to be List[int] and values to be List[float]
        assert all(isinstance(i, int) for i in indices)
        assert all(isinstance(v, (int, float)) for v in values)

        # Indices should be non-negative and within reasonable range
        assert all(i >= 0 for i in indices)
        assert all(i < 2**31 for i in indices)  # Qdrant uses int32 for indices

    def test_tokenize_document_and_query_match(self):
        """Documents and queries tokenized with same tokenizer should match."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Index a document
        doc_indices, _ = tokenizer.tokenize_document(
            "How to cancel a trade in Bisq Easy"
        )

        # Query that should match
        query_indices, _ = tokenizer.tokenize_query("cancel trade Bisq")

        # Query terms should be in document vocabulary
        matching_indices = set(query_indices) & set(doc_indices)
        assert len(matching_indices) >= 2  # At least "cancel" and "trade" should match


class TestBM25SparseTokenizerPerformance:
    """Performance and edge case tests for BM25SparseTokenizer."""

    def test_tokenize_long_document(self):
        """Should handle long documents efficiently."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Simulate a long document
        long_doc = " ".join(["bitcoin transaction wallet escrow"] * 1000)

        indices, values = tokenizer.tokenize(long_doc)

        # Should still produce reasonable output
        assert len(indices) > 0
        assert len(indices) < 100  # Vocabulary should be deduplicated

    def test_tokenize_special_characters(self):
        """Should handle special characters gracefully."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        text = "bitcoin!!! @#$%^&*() transaction??? <><> wallet..."

        indices, values = tokenizer.tokenize(text)

        # Should extract valid terms despite punctuation
        assert len(indices) >= 2  # At least "bitcoin", "transaction", "wallet"

    def test_tokenize_unicode(self):
        """Should handle unicode characters."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        text = "bitcoin €500 トランザクション"

        # Should not crash
        indices, values = tokenizer.tokenize(text)

        assert isinstance(indices, list)
        assert isinstance(values, list)

    def test_tokenize_numbers_mixed_with_text(self):
        """Should handle numbers mixed with text appropriately."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        text = "Send 0.5 BTC to address at block 800000"

        indices, values = tokenizer.tokenize(text)

        # Should extract meaningful terms
        assert len(indices) >= 2
