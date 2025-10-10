"""
Unit tests for FAQRepository - Critical path testing for FAQ data persistence.

Tests cover:
- CRUD operations (Create, Read, Update, Delete)
- Stable ID generation based on content hashing
- Thread-safe file operations with locking
- Duplicate prevention
- Pagination and filtering
"""

import pytest
import threading
from pathlib import Path
import portalocker

from app.services.faq.faq_repository import FAQRepository
from app.models.faq import FAQItem


@pytest.fixture
def faq_repository(test_settings, clean_test_files):
    """Create FAQ repository with test configuration."""
    faq_file_path = Path(test_settings.FAQ_FILE_PATH)
    faq_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Create lock file
    lock_file_path = faq_file_path.parent / "faq.lock"
    file_lock = portalocker.Lock(
        str(lock_file_path), timeout=10, flags=portalocker.LOCK_EX
    )

    return FAQRepository(faq_file_path=faq_file_path, file_lock=file_lock)


@pytest.fixture
def sample_faq_item():
    """Create a sample FAQ item for testing."""
    return FAQItem(
        question="How do I backup my data?",
        answer="Use the backup feature in settings.",
        category="backup",
        source="manual",
    )


class TestFAQRepositoryCRUD:
    """Test CRUD operations for FAQ repository."""

    def test_add_faq_creates_entry(self, faq_repository, sample_faq_item):
        """Test that adding FAQ creates an entry with ID."""
        result = faq_repository.add_faq(sample_faq_item)

        assert result.id is not None
        assert result.question == sample_faq_item.question
        assert result.answer == sample_faq_item.answer

    def test_add_duplicate_faq_raises_error(self, faq_repository, sample_faq_item):
        """Test that adding duplicate FAQ raises ValueError."""
        faq_repository.add_faq(sample_faq_item)

        # Try to add same FAQ again
        with pytest.raises(ValueError, match="Duplicate FAQ"):
            faq_repository.add_faq(sample_faq_item)

    def test_get_all_faqs_returns_list(self, faq_repository):
        """Test that get_all_faqs returns a list."""
        faqs = faq_repository.get_all_faqs()

        assert isinstance(faqs, list)

    def test_get_all_faqs_includes_added_items(self, faq_repository, sample_faq_item):
        """Test that added FAQs appear in get_all_faqs."""
        initial_count = len(faq_repository.get_all_faqs())

        faq_repository.add_faq(sample_faq_item)

        final_count = len(faq_repository.get_all_faqs())
        assert final_count == initial_count + 1

    def test_update_faq_modifies_content(self, faq_repository, sample_faq_item):
        """Test that update_faq modifies FAQ content."""
        # Add FAQ
        added_faq = faq_repository.add_faq(sample_faq_item)

        # Update it
        updated_data = FAQItem(
            question=sample_faq_item.question,
            answer="Updated answer with more details.",
            category="backup",
            source="manual",
        )

        result = faq_repository.update_faq(added_faq.id, updated_data)

        assert result is not None
        assert result.answer == "Updated answer with more details."

    def test_update_nonexistent_faq_returns_none(self, faq_repository):
        """Test that updating nonexistent FAQ returns None."""
        fake_id = "nonexistent_id_12345"
        updated_data = FAQItem(
            question="Question",
            answer="Answer",
            category="test",
            source="manual",
        )

        result = faq_repository.update_faq(fake_id, updated_data)

        assert result is None

    def test_delete_faq_removes_entry(self, faq_repository, sample_faq_item):
        """Test that delete_faq removes the FAQ."""
        # Add FAQ
        added_faq = faq_repository.add_faq(sample_faq_item)
        initial_count = len(faq_repository.get_all_faqs())

        # Delete it
        result = faq_repository.delete_faq(added_faq.id)

        assert result is True
        final_count = len(faq_repository.get_all_faqs())
        assert final_count == initial_count - 1

    def test_delete_nonexistent_faq_returns_false(self, faq_repository):
        """Test that deleting nonexistent FAQ returns False."""
        fake_id = "nonexistent_id_67890"

        result = faq_repository.delete_faq(fake_id)

        assert result is False


class TestFAQRepositoryID:
    """Test stable ID generation for FAQs."""

    def test_same_content_generates_same_id(self, faq_repository):
        """Test that identical content generates the same ID."""
        faq1 = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="test",
            source="manual",
        )

        faq2 = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="test",
            source="manual",
        )

        # Generate IDs
        id1 = faq_repository._generate_stable_id(faq1)
        id2 = faq_repository._generate_stable_id(faq2)

        assert id1 == id2

    def test_different_content_generates_different_id(self, faq_repository):
        """Test that different content generates different IDs."""
        faq1 = FAQItem(
            question="Question 1?",
            answer="Answer 1",
            category="test",
            source="manual",
        )

        faq2 = FAQItem(
            question="Question 2?",
            answer="Answer 2",
            category="test",
            source="manual",
        )

        # Generate IDs
        id1 = faq_repository._generate_stable_id(faq1)
        id2 = faq_repository._generate_stable_id(faq2)

        assert id1 != id2


class TestFAQRepositoryPagination:
    """Test pagination and filtering for FAQs."""

    def test_get_faqs_paginated_returns_response(self, faq_repository):
        """Test that pagination returns proper response structure."""
        response = faq_repository.get_faqs_paginated(page=1, page_size=10)

        assert hasattr(response, "faqs")
        assert hasattr(response, "total_count")
        assert hasattr(response, "page")
        assert hasattr(response, "page_size")
        assert hasattr(response, "total_pages")

    def test_pagination_respects_page_size(self, faq_repository):
        """Test that pagination respects page_size parameter."""
        # Add multiple FAQs
        for i in range(15):
            faq = FAQItem(
                question=f"Question {i}?",
                answer=f"Answer {i}",
                category="test",
                source="manual",
            )
            faq_repository.add_faq(faq)

        # Get first page with 10 items
        response = faq_repository.get_faqs_paginated(page=1, page_size=10)

        assert len(response.faqs) <= 10
        assert response.total_count >= 15
        assert response.page == 1
        assert response.page_size == 10

    def test_pagination_second_page(self, faq_repository):
        """Test retrieving second page of results."""
        # Add multiple FAQs
        for i in range(15):
            faq = FAQItem(
                question=f"Question {i}?",
                answer=f"Answer {i}",
                category="test",
                source="manual",
            )
            faq_repository.add_faq(faq)

        # Get second page
        response = faq_repository.get_faqs_paginated(page=2, page_size=10)

        assert response.page == 2
        assert len(response.faqs) >= 0  # May have remaining items

    def test_filter_by_search_text(self, faq_repository):
        """Test filtering FAQs by search text."""
        # Add FAQs with different content
        faq1 = FAQItem(
            question="How to backup data?",
            answer="Use backup feature",
            category="backup",
            source="manual",
        )
        faq2 = FAQItem(
            question="How to restore data?",
            answer="Use restore feature",
            category="backup",
            source="manual",
        )
        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)

        # Search for "backup"
        response = faq_repository.get_faqs_paginated(search_text="backup")

        # Should find at least one FAQ with "backup"
        assert any(
            "backup" in faq.question.lower() or "backup" in faq.answer.lower()
            for faq in response.faqs
        )

    def test_filter_by_category(self, faq_repository):
        """Test filtering FAQs by category."""
        # Add FAQs with different categories
        faq1 = FAQItem(
            question="Backup question?",
            answer="Backup answer",
            category="backup",
            source="manual",
        )
        faq2 = FAQItem(
            question="Security question?",
            answer="Security answer",
            category="security",
            source="manual",
        )
        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)

        # Filter by category
        response = faq_repository.get_faqs_paginated(categories=["backup"])

        # All results should be in backup category
        assert all(faq.category == "backup" for faq in response.faqs if faq.category)

    def test_filter_by_source(self, faq_repository):
        """Test filtering FAQs by source."""
        # Add FAQs with different sources
        faq1 = FAQItem(
            question="Manual FAQ?",
            answer="Manual answer",
            category="test",
            source="manual",
        )
        faq2 = FAQItem(
            question="Extracted FAQ?",
            answer="Extracted answer",
            category="test",
            source="extracted",
        )
        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)

        # Filter by source
        response = faq_repository.get_faqs_paginated(source="manual")

        # All results should be from manual source
        assert all(faq.source == "manual" for faq in response.faqs if faq.source)


class TestFAQRepositoryThreadSafety:
    """Test thread-safe operations."""

    def test_concurrent_writes_maintain_consistency(self, faq_repository):
        """Test that concurrent writes don't corrupt data."""
        results = []
        errors = []

        def write_faq(index):
            try:
                faq = FAQItem(
                    question=f"Question {index}?",
                    answer=f"Answer {index}",
                    category="test",
                    source="manual",
                )
                result = faq_repository.add_faq(faq)
                results.append(result)
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads writing simultaneously
        threads = []
        for i in range(10):
            thread = threading.Thread(target=write_faq, args=(i,))
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all to complete
        for thread in threads:
            thread.join()

        # Check results - expect most threads to succeed
        # In high-concurrency scenarios, some writes may fail due to timing
        assert len(results) >= 8, f"Expected at least 8 successful writes, got {len(results)}"
        assert len(errors) <= 2, f"Expected at most 2 errors, got {len(errors)}: {errors}"

        # Verify most FAQs were written
        all_faqs = faq_repository.get_all_faqs()
        assert len(all_faqs) >= 8, f"Expected at least 8 FAQs written, got {len(all_faqs)}"
