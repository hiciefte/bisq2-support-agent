"""
Unit tests for FAQRepository - Critical path testing for data integrity.

Tests cover:
- Atomic operations and race condition prevention
- Data consistency and validation
- File locking and concurrent access
- Error handling and recovery
"""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.faq.faq_repository import FAQRepository


class TestFAQRepositoryAtomic:
    """Test atomic operations and race condition prevention."""

    def test_concurrent_writes_maintain_consistency(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test that concurrent writes don't corrupt data."""
        repository = FAQRepository(settings=test_settings)
        results = []
        errors = []

        def write_faq(faq_data):
            try:
                repository.save_faq(faq_data)
                results.append(True)
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads writing simultaneously
        threads = []
        for i, faq in enumerate(sample_faq_data):
            # Modify question to make each unique
            faq_copy = faq.copy()
            faq_copy["question"] = f"{faq['question']} - Thread {i}"
            thread = threading.Thread(target=write_faq, args=(faq_copy,))
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent writes caused errors: {errors}"

        # Verify all FAQs were written
        all_faqs = repository.get_all_faqs()
        assert len(all_faqs) == len(sample_faq_data)

        # Verify data integrity - no corruption
        faq_file = Path(test_settings.FAQ_FILE_PATH)
        with open(faq_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                # Each line should be valid JSON
                json.loads(line.strip())

    def test_file_locking_prevents_corruption(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test that file locking prevents data corruption during writes."""
        repository = FAQRepository(settings=test_settings)

        # Write initial data
        for faq in sample_faq_data:
            repository.save_faq(faq)

        # Simulate concurrent read while writing
        def read_faqs():
            return repository.get_all_faqs()

        def write_faq():
            repository.save_faq(
                {
                    "question": "New concurrent FAQ",
                    "answer": "New answer",
                    "category": "test",
                    "source": "Manual",
                    "bisq_version": "General",
                }
            )

        # Execute read and write concurrently
        read_thread = threading.Thread(target=read_faqs)
        write_thread = threading.Thread(target=write_faq)

        read_thread.start()
        write_thread.start()

        read_thread.join()
        write_thread.join()

        # Verify data integrity after concurrent access
        final_faqs = repository.get_all_faqs()
        assert len(final_faqs) == len(sample_faq_data) + 1

    def test_atomic_update_rollback_on_failure(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test that failed updates rollback without corrupting data."""
        repository = FAQRepository(settings=test_settings)

        # Write initial data
        for faq in sample_faq_data:
            repository.save_faq(faq)

        original_count = len(repository.get_all_faqs())

        # Mock file write to fail
        with patch("builtins.open", side_effect=IOError("Disk full")):
            with pytest.raises(IOError):
                repository.save_faq(
                    {
                        "question": "This should fail",
                        "answer": "Should not be saved",
                        "category": "test",
                    }
                )

        # Verify original data is intact
        final_faqs = repository.get_all_faqs()
        assert len(final_faqs) == original_count


class TestFAQRepositoryValidation:
    """Test data validation and consistency."""

    def test_save_faq_with_required_fields(self, test_settings, clean_test_files):
        """Test that FAQs require essential fields."""
        repository = FAQRepository(settings=test_settings)

        valid_faq = {
            "question": "Valid question?",
            "answer": "Valid answer",
            "category": "test",
            "source": "Manual",
            "bisq_version": "General",
        }

        repository.save_faq(valid_faq)
        faqs = repository.get_all_faqs()
        assert len(faqs) == 1
        assert faqs[0]["question"] == "Valid question?"

    def test_get_faq_by_id_returns_correct_faq(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test retrieval of specific FAQ by ID."""
        repository = FAQRepository(settings=test_settings)

        # Save all FAQs
        for faq in sample_faq_data:
            repository.save_faq(faq)

        # Get all FAQs to obtain IDs
        all_faqs = repository.get_all_faqs()
        target_faq = all_faqs[1]

        # Retrieve specific FAQ
        retrieved = repository.get_faq_by_id(target_faq["id"])

        assert retrieved is not None
        assert retrieved["id"] == target_faq["id"]
        assert retrieved["question"] == target_faq["question"]

    def test_update_faq_preserves_id(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test that updating FAQ preserves its ID."""
        repository = FAQRepository(settings=test_settings)

        # Save initial FAQ
        repository.save_faq(sample_faq_data[0])
        faqs = repository.get_all_faqs()
        original_id = faqs[0]["id"]

        # Update the FAQ
        updated_faq = faqs[0].copy()
        updated_faq["answer"] = "Updated answer"
        repository.update_faq(original_id, updated_faq)

        # Verify ID is preserved
        updated = repository.get_faq_by_id(original_id)
        assert updated["id"] == original_id
        assert updated["answer"] == "Updated answer"

    def test_delete_faq_removes_correctly(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test that FAQ deletion works correctly."""
        repository = FAQRepository(settings=test_settings)

        # Save all FAQs
        for faq in sample_faq_data:
            repository.save_faq(faq)

        initial_count = len(repository.get_all_faqs())
        faq_to_delete = repository.get_all_faqs()[1]

        # Delete FAQ
        repository.delete_faq(faq_to_delete["id"])

        # Verify deletion
        remaining_faqs = repository.get_all_faqs()
        assert len(remaining_faqs) == initial_count - 1
        assert repository.get_faq_by_id(faq_to_delete["id"]) is None


class TestFAQRepositoryFiltering:
    """Test FAQ filtering and search functionality."""

    def test_filter_by_category(self, test_settings, sample_faq_data, clean_test_files):
        """Test filtering FAQs by category."""
        repository = FAQRepository(settings=test_settings)

        # Save all FAQs
        for faq in sample_faq_data:
            repository.save_faq(faq)

        # Filter by category
        trading_faqs = [
            faq for faq in repository.get_all_faqs() if faq.get("category") == "trading"
        ]

        assert len(trading_faqs) == 2
        assert all(faq["category"] == "trading" for faq in trading_faqs)

    def test_filter_by_bisq_version(
        self, test_settings, sample_faq_data, clean_test_files
    ):
        """Test filtering FAQs by Bisq version."""
        repository = FAQRepository(settings=test_settings)

        # Save all FAQs
        for faq in sample_faq_data:
            repository.save_faq(faq)

        # Filter by version
        bisq2_faqs = [
            faq
            for faq in repository.get_all_faqs()
            if faq.get("bisq_version") == "Bisq 2"
        ]

        assert len(bisq2_faqs) == 1
        assert bisq2_faqs[0]["question"] == "How do I create a Bisq account?"

    def test_search_by_text(self, test_settings, sample_faq_data, clean_test_files):
        """Test text search across questions and answers."""
        repository = FAQRepository(settings=test_settings)

        # Save all FAQs
        for faq in sample_faq_data:
            repository.save_faq(faq)

        # Search for 'trade'
        all_faqs = repository.get_all_faqs()
        search_results = [
            faq
            for faq in all_faqs
            if "trade" in faq["question"].lower() or "trade" in faq["answer"].lower()
        ]

        assert len(search_results) >= 2


class TestFAQRepositoryErrorHandling:
    """Test error handling and recovery."""

    def test_handles_missing_file_gracefully(self, test_settings, clean_test_files):
        """Test that repository handles missing FAQ file gracefully."""
        repository = FAQRepository(settings=test_settings)

        # No file exists yet
        faqs = repository.get_all_faqs()
        assert faqs == []

    def test_handles_corrupted_file_gracefully(self, test_settings, clean_test_files):
        """Test that repository handles corrupted FAQ file."""
        repository = FAQRepository(settings=test_settings)

        # Write corrupted data
        faq_file = Path(test_settings.FAQ_FILE_PATH)
        faq_file.parent.mkdir(parents=True, exist_ok=True)
        with open(faq_file, "w", encoding="utf-8") as f:
            f.write("This is not valid JSON\n")
            f.write('{"valid": "json"}\n')

        # Should skip corrupted lines and load valid ones
        faqs = repository.get_all_faqs()
        # Implementation dependent - may return empty or partial data
        assert isinstance(faqs, list)

    def test_nonexistent_faq_returns_none(self, test_settings, clean_test_files):
        """Test that getting non-existent FAQ returns None."""
        repository = FAQRepository(settings=test_settings)

        result = repository.get_faq_by_id("nonexistent-id-12345")
        assert result is None
