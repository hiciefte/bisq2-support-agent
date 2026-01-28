"""
TDD tests for BM25 Vocabulary Incremental Update.

This module tests the incremental vocabulary update mechanism that allows
adding new documents to an existing BM25 vocabulary without full rebuilds.

Key requirements tested:
1. Incremental document addition updates vocabulary
2. IDF recalculation after adding documents
3. Persistence of updated vocabulary
4. Thread safety during updates
5. Integration with FAQ and wiki ingestion pipelines
"""

import threading
from pathlib import Path
from typing import List


class TestBM25VocabularyIncrementalUpdate:
    """TDD specification tests for incremental vocabulary updates."""

    # ==========================================================================
    # Basic Incremental Update Tests
    # ==========================================================================

    def test_update_vocabulary_adds_new_tokens(self):
        """update_vocabulary should add new tokens from documents."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Start with initial corpus
        tokenizer = BM25SparseTokenizer(corpus=["bitcoin transaction"])
        initial_size = tokenizer.vocabulary_size

        # Update with new document containing new terms
        tokenizer.update_vocabulary(["escrow mediator arbitration"])

        # Vocabulary should grow
        assert tokenizer.vocabulary_size > initial_size
        assert tokenizer._token_to_index.get("escrow") is not None
        assert tokenizer._token_to_index.get("mediator") is not None

    def test_update_vocabulary_increments_document_count(self):
        """update_vocabulary should increment num_documents."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["doc one", "doc two"])
        initial_count = tokenizer._num_documents
        assert initial_count == 2

        tokenizer.update_vocabulary(["doc three", "doc four"])

        assert tokenizer._num_documents == 4

    def test_update_vocabulary_updates_document_frequencies(self):
        """update_vocabulary should update df counts for existing tokens."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin price"])
        initial_df = tokenizer._document_frequencies.get("bitcoin", 0)
        assert initial_df == 1

        # Add another document with "bitcoin"
        tokenizer.update_vocabulary(["bitcoin transaction"])

        assert tokenizer._document_frequencies["bitcoin"] == 2

    def test_update_vocabulary_recalculates_idf(self):
        """IDF values should change after vocabulary update."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Initial corpus with "bitcoin" appearing once
        tokenizer = BM25SparseTokenizer(corpus=["bitcoin", "wallet"])

        # Get initial IDF for bitcoin
        initial_idf = tokenizer._get_idf("bitcoin")

        # Add more documents, some with bitcoin
        tokenizer.update_vocabulary(["bitcoin transaction", "another bitcoin doc"])

        # IDF should decrease (term is now more common)
        new_idf = tokenizer._get_idf("bitcoin")
        assert new_idf < initial_idf

    def test_update_vocabulary_with_empty_list(self):
        """update_vocabulary should handle empty document list gracefully."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin"])
        initial_count = tokenizer._num_documents

        tokenizer.update_vocabulary([])

        assert tokenizer._num_documents == initial_count

    def test_update_vocabulary_with_empty_documents(self):
        """update_vocabulary should skip empty documents."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin"])
        initial_count = tokenizer._num_documents

        tokenizer.update_vocabulary(["", "   ", None])  # type: ignore

        # Empty docs should not count
        assert tokenizer._num_documents == initial_count

    def test_update_vocabulary_preserves_existing_indices(self):
        """Existing token indices should not change after update."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin wallet"])
        bitcoin_idx = tokenizer._token_to_index["bitcoin"]
        wallet_idx = tokenizer._token_to_index["wallet"]

        # Update with new terms
        tokenizer.update_vocabulary(["escrow mediator"])

        # Original indices unchanged
        assert tokenizer._token_to_index["bitcoin"] == bitcoin_idx
        assert tokenizer._token_to_index["wallet"] == wallet_idx

    # ==========================================================================
    # Single Document Update Tests
    # ==========================================================================

    def test_update_single_document(self):
        """update_single_document should add a single document efficiently."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["initial doc"])
        initial_count = tokenizer._num_documents

        tokenizer.update_single_document("new single document with escrow")

        assert tokenizer._num_documents == initial_count + 1
        assert tokenizer._token_to_index.get("escrow") is not None

    def test_update_single_document_returns_new_tokens(self):
        """update_single_document should return list of newly added tokens."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin wallet"])

        new_tokens = tokenizer.update_single_document("escrow mediator")

        assert "escrow" in new_tokens
        assert "mediator" in new_tokens
        assert "bitcoin" not in new_tokens  # Already existed

    # ==========================================================================
    # Persistence Tests
    # ==========================================================================

    def test_export_includes_update_metadata(self):
        """Exported vocabulary should include update timestamp."""
        import json

        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin"])
        tokenizer.update_vocabulary(["wallet"])

        vocab_json = tokenizer.export_vocabulary()
        vocab_data = json.loads(vocab_json)

        # Should have all necessary fields for reconstruction
        assert "token_to_index" in vocab_data
        assert "document_frequencies" in vocab_data
        assert "num_documents" in vocab_data
        assert vocab_data["num_documents"] == 2

    def test_load_preserves_update_state(self):
        """Loading vocabulary should preserve incremental update state."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        # Create and update tokenizer
        tokenizer1 = BM25SparseTokenizer(corpus=["bitcoin"])
        tokenizer1.update_vocabulary(["wallet escrow"])
        vocab_json = tokenizer1.export_vocabulary()

        # Load into new tokenizer
        tokenizer2 = BM25SparseTokenizer()
        tokenizer2.load_vocabulary(vocab_json)

        # Should have same state
        assert tokenizer2._num_documents == tokenizer1._num_documents
        assert tokenizer2.vocabulary_size == tokenizer1.vocabulary_size
        assert (
            tokenizer2._document_frequencies["bitcoin"]
            == tokenizer1._document_frequencies["bitcoin"]
        )

    # ==========================================================================
    # Thread Safety Tests
    # ==========================================================================

    def test_update_vocabulary_thread_safe(self):
        """Concurrent updates should not corrupt vocabulary."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["initial"])
        errors = []

        def update_worker(docs: List[str]):
            try:
                for doc in docs:
                    tokenizer.update_single_document(doc)
            except Exception as e:
                errors.append(e)

        # Create threads with different documents
        threads = [
            threading.Thread(
                target=update_worker, args=([f"thread1 doc{i}" for i in range(10)],)
            ),
            threading.Thread(
                target=update_worker, args=([f"thread2 doc{i}" for i in range(10)],)
            ),
            threading.Thread(
                target=update_worker, args=([f"thread3 doc{i}" for i in range(10)],)
            ),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # Document count should be correct (1 initial + 30 from threads)
        assert tokenizer._num_documents == 31


class TestVocabularyManager:
    """Tests for VocabularyManager - handles vocabulary persistence and updates."""

    def test_vocabulary_manager_save_and_load(self, tmp_path: Path):
        """VocabularyManager should save and load vocabulary files."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "bm25_vocab.json"
        manager = VocabularyManager(vocab_path)

        # Create tokenizer with some data
        tokenizer = BM25SparseTokenizer(corpus=["bitcoin wallet escrow"])

        # Save
        manager.save(tokenizer)
        assert vocab_path.exists()

        # Load into new tokenizer
        new_tokenizer = BM25SparseTokenizer()
        manager.load(new_tokenizer)

        assert new_tokenizer.vocabulary_size == tokenizer.vocabulary_size

    def test_vocabulary_manager_atomic_save(self, tmp_path: Path):
        """Vocabulary save should be atomic (write to temp, then rename)."""
        import json

        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "bm25_vocab.json"
        manager = VocabularyManager(vocab_path)

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin"])
        manager.save(tokenizer)

        # Verify content is valid JSON
        content = vocab_path.read_text()
        data = json.loads(content)
        assert "token_to_index" in data

    def test_vocabulary_manager_backup_on_update(self, tmp_path: Path):
        """VocabularyManager should create backup before overwriting."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "bm25_vocab.json"
        manager = VocabularyManager(vocab_path, backup_on_save=True)

        # Initial save
        tokenizer1 = BM25SparseTokenizer(corpus=["bitcoin"])
        manager.save(tokenizer1)

        # Update save (should create backup)
        tokenizer2 = BM25SparseTokenizer(corpus=["bitcoin wallet escrow"])
        manager.save(tokenizer2)

        # Check backup exists
        backup_files = list(tmp_path.glob("bm25_vocab.json.bak*"))
        assert len(backup_files) >= 1

    def test_vocabulary_manager_handles_missing_file(self, tmp_path: Path):
        """VocabularyManager should handle missing vocabulary file gracefully."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "nonexistent.json"
        manager = VocabularyManager(vocab_path)

        tokenizer = BM25SparseTokenizer()
        result = manager.load(tokenizer)

        # Should return False but not crash
        assert result is False
        assert tokenizer.vocabulary_size == 0

    def test_vocabulary_manager_file_locking(self, tmp_path: Path):
        """VocabularyManager should use file locking for concurrent access."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "bm25_vocab.json"
        manager = VocabularyManager(vocab_path)

        errors = []

        def save_worker(thread_id: int):
            try:
                tokenizer = BM25SparseTokenizer(corpus=[f"thread{thread_id} content"])
                manager.save(tokenizer)
            except Exception as e:
                errors.append(e)

        # Concurrent saves should not corrupt the file
        threads = [threading.Thread(target=save_worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        # File should be valid JSON
        import json

        content = vocab_path.read_text()
        json.loads(content)  # Should not raise


class TestVocabularyUpdateIntegration:
    """Integration tests for vocabulary updates with FAQ/Wiki pipelines."""

    def test_faq_addition_triggers_vocabulary_update(self):
        """Adding a new FAQ should trigger vocabulary update."""
        from unittest.mock import MagicMock, patch

        from app.services.rag.vocabulary_manager import VocabularyManager

        # Mock the vocabulary manager
        mock_manager = MagicMock(spec=VocabularyManager)

        # Simulate FAQ service with vocabulary update hook
        with patch(
            "app.services.rag.vocabulary_manager.get_vocabulary_manager",
            return_value=mock_manager,
        ):
            # Simulate adding FAQ would call update_vocabulary_for_content
            from app.services.rag.vocabulary_manager import (
                update_vocabulary_for_content,
            )

            update_vocabulary_for_content(
                "What is escrow in Bisq?",
                "Escrow is a security mechanism for trades.",
            )

            # Vocabulary manager should have been called
            mock_manager.update_and_save.assert_called_once()

    def test_wiki_sync_triggers_vocabulary_update(self):
        """Wiki document sync should trigger vocabulary update."""
        from unittest.mock import MagicMock, patch

        from app.services.rag.vocabulary_manager import VocabularyManager

        mock_manager = MagicMock(spec=VocabularyManager)

        with patch(
            "app.services.rag.vocabulary_manager.get_vocabulary_manager",
            return_value=mock_manager,
        ):
            from app.services.rag.vocabulary_manager import (
                update_vocabulary_for_documents,
            )

            documents = [
                {"content": "Wiki article about trading"},
                {"content": "Wiki article about security"},
            ]
            update_vocabulary_for_documents(documents)

            mock_manager.update_and_save.assert_called_once()

    def test_batch_faq_import_efficient_update(self, tmp_path: Path, monkeypatch):
        """Batch FAQ import should update vocabulary once, not per-FAQ."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        mock_save_count = 0
        original_save = VocabularyManager.save

        def counting_save(self, tokenizer):
            nonlocal mock_save_count
            mock_save_count += 1
            return original_save(self, tokenizer)

        # Monkeypatch VocabularyManager.save with counting_save
        monkeypatch.setattr(VocabularyManager, "save", counting_save)

        # Create a manager and tokenizer
        vocab_path = tmp_path / "bm25_vocab.json"
        manager = VocabularyManager(vocab_path)
        tokenizer = BM25SparseTokenizer()

        # Simulate batch import of 100 FAQs
        faqs = [f"FAQ {i} about topic {i}" for i in range(100)]

        # Batch update via manager should result in a single save
        manager.update_and_save(tokenizer, faqs)

        # Only one save call (not 100)
        assert mock_save_count == 1
        # All 100 documents should be processed
        assert tokenizer._num_documents == 100


class TestVocabularyUpdateMetrics:
    """Tests for vocabulary update metrics and monitoring."""

    def test_update_returns_statistics(self):
        """update_vocabulary should return update statistics."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin"])

        stats = tokenizer.update_vocabulary(["escrow mediator"], return_stats=True)

        assert "new_tokens_added" in stats
        assert "documents_added" in stats
        assert "vocabulary_size" in stats
        assert stats["new_tokens_added"] == 2  # escrow, mediator
        assert stats["documents_added"] == 1

    def test_get_vocabulary_drift_metrics(self):
        """Should provide metrics on vocabulary drift from original."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer(corpus=["bitcoin wallet"])
        initial_size = tokenizer.vocabulary_size

        # Add new content
        tokenizer.update_vocabulary(["escrow mediator arbitration security"])

        metrics = tokenizer.get_vocabulary_drift_metrics(initial_size)

        assert "tokens_added" in metrics
        assert "growth_percentage" in metrics
        assert metrics["tokens_added"] == 4
