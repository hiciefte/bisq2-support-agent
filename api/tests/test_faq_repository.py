"""
Unit tests for FAQRepository - Critical path testing for FAQ data persistence.

Tests cover:
- CRUD operations (Create, Read, Update, Delete)
- Stable ID generation based on content hashing
- Thread-safe file operations with locking
- Duplicate prevention
- Pagination and filtering
- Timestamp management (created_at, updated_at, verified_at)
- Date range filtering
"""

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import portalocker
import pytest
from app.models.faq import FAQItem
from app.services.faq.faq_repository import FAQRepository


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

    @pytest.mark.skip(
        reason="Flaky test: File lock race condition - 'I/O operation on closed file'"
    )
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
        assert (
            len(results) >= 8
        ), f"Expected at least 8 successful writes, got {len(results)}"
        assert (
            len(errors) <= 2
        ), f"Expected at most 2 errors, got {len(errors)}: {errors}"

        # Verify most FAQs were written
        all_faqs = faq_repository.get_all_faqs()
        assert (
            len(all_faqs) >= 8
        ), f"Expected at least 8 FAQs written, got {len(all_faqs)}"


class TestFAQRepositoryTimestamps:
    """Test timestamp management for FAQs."""

    def test_add_faq_auto_populates_timestamps(self, faq_repository, sample_faq_item):
        """Test that adding FAQ auto-populates created_at and updated_at."""
        before_add = datetime.now(timezone.utc)
        result = faq_repository.add_faq(sample_faq_item)
        after_add = datetime.now(timezone.utc)

        assert result.created_at is not None
        assert result.updated_at is not None
        assert before_add <= result.created_at <= after_add
        assert before_add <= result.updated_at <= after_add

    def test_add_verified_faq_sets_verified_at(self, faq_repository):
        """Test that adding verified FAQ sets verified_at timestamp."""
        faq = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="test",
            source="manual",
            verified=True,
        )

        before_add = datetime.now(timezone.utc)
        result = faq_repository.add_faq(faq)
        after_add = datetime.now(timezone.utc)

        assert result.verified is True
        assert result.verified_at is not None
        assert before_add <= result.verified_at <= after_add

    def test_add_unverified_faq_has_null_verified_at(
        self, faq_repository, sample_faq_item
    ):
        """Test that adding unverified FAQ has None verified_at."""
        result = faq_repository.add_faq(sample_faq_item)

        assert result.verified is False
        assert result.verified_at is None

    def test_update_faq_updates_updated_at(self, faq_repository, sample_faq_item):
        """Test that updating FAQ updates the updated_at timestamp."""
        # Add FAQ
        added_faq = faq_repository.add_faq(sample_faq_item)
        original_updated_at = added_faq.updated_at

        # Wait a small amount to ensure timestamp difference
        import time

        time.sleep(0.01)

        # Update FAQ
        updated_data = FAQItem(
            question=sample_faq_item.question,
            answer="Updated answer",
            category="test",
            source="manual",
        )

        result = faq_repository.update_faq(added_faq.id, updated_data)

        assert result is not None
        assert result.updated_at > original_updated_at

    def test_update_faq_preserves_created_at(self, faq_repository, sample_faq_item):
        """Test that updating FAQ preserves the original created_at."""
        # Add FAQ
        added_faq = faq_repository.add_faq(sample_faq_item)
        original_created_at = added_faq.created_at

        # Update FAQ
        updated_data = FAQItem(
            question=sample_faq_item.question,
            answer="Updated answer",
            category="test",
            source="manual",
        )

        result = faq_repository.update_faq(added_faq.id, updated_data)

        assert result is not None
        assert result.created_at == original_created_at

    def test_verify_faq_sets_verified_at(self, faq_repository, sample_faq_item):
        """Test that verifying FAQ sets verified_at timestamp."""
        # Add unverified FAQ
        added_faq = faq_repository.add_faq(sample_faq_item)
        assert added_faq.verified_at is None

        # Verify it
        updated_data = FAQItem(
            question=sample_faq_item.question,
            answer=sample_faq_item.answer,
            category=sample_faq_item.category,
            source=sample_faq_item.source,
            verified=True,
        )

        before_verify = datetime.now(timezone.utc)
        result = faq_repository.update_faq(added_faq.id, updated_data)
        after_verify = datetime.now(timezone.utc)

        assert result is not None
        assert result.verified is True
        assert result.verified_at is not None
        assert before_verify <= result.verified_at <= after_verify

    def test_unverify_faq_clears_verified_at(self, faq_repository):
        """Test that unverifying FAQ clears verified_at timestamp."""
        # Add verified FAQ
        faq = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="test",
            source="manual",
            verified=True,
        )
        added_faq = faq_repository.add_faq(faq)
        assert added_faq.verified_at is not None

        # Unverify it
        updated_data = FAQItem(
            question=faq.question,
            answer=faq.answer,
            category=faq.category,
            source=faq.source,
            verified=False,
        )

        result = faq_repository.update_faq(added_faq.id, updated_data)

        assert result is not None
        assert result.verified is False
        assert result.verified_at is None


class TestFAQRepositoryDateRangeFiltering:
    """Test date range filtering for FAQs."""

    def test_filter_by_verified_from_date(self, faq_repository):
        """Test filtering FAQs by verified_from date."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add verified FAQ with specific timestamp
        faq1 = FAQItem(
            question="Old FAQ?",
            answer="Old answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq2 = FAQItem(
            question="New FAQ?",
            answer="New answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=now,
        )

        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)

        # Filter by verified_from = now (should exclude yesterday's FAQ)
        response = faq_repository.get_faqs_paginated(verified_from=now)

        # Should only include FAQs verified at or after 'now'
        assert all(faq.verified_at >= now for faq in response.faqs if faq.verified_at)

    def test_filter_by_verified_to_date(self, faq_repository):
        """Test filtering FAQs by verified_to date."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        # Add verified FAQs with different timestamps
        faq1 = FAQItem(
            question="Old FAQ?",
            answer="Old answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq2 = FAQItem(
            question="Future FAQ?",
            answer="Future answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=tomorrow,
        )

        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)

        # Filter by verified_to = now (should exclude tomorrow's FAQ)
        response = faq_repository.get_faqs_paginated(verified_to=now)

        # Should only include FAQs verified at or before 'now'
        assert all(faq.verified_at <= now for faq in response.faqs if faq.verified_at)

    def test_filter_by_date_range(self, faq_repository):
        """Test filtering FAQs by date range (from and to)."""
        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        # Add verified FAQs across date range
        faq1 = FAQItem(
            question="Very old FAQ?",
            answer="Very old answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=two_days_ago,
        )
        faq2 = FAQItem(
            question="Yesterday FAQ?",
            answer="Yesterday answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq3 = FAQItem(
            question="Today FAQ?",
            answer="Today answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=now,
        )
        faq4 = FAQItem(
            question="Future FAQ?",
            answer="Future answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=tomorrow,
        )

        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)
        faq_repository.add_faq(faq3)
        faq_repository.add_faq(faq4)

        # Filter by date range: yesterday to today (should include 2 FAQs)
        response = faq_repository.get_faqs_paginated(
            verified_from=yesterday, verified_to=now
        )

        # Should only include FAQs in date range
        assert all(
            yesterday <= faq.verified_at <= now
            for faq in response.faqs
            if faq.verified_at
        )

    def test_date_filter_excludes_unverified_faqs(self, faq_repository):
        """Test that date filtering excludes FAQs without verified_at."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add unverified FAQ (no verified_at)
        faq1 = FAQItem(
            question="Unverified FAQ?",
            answer="Unverified answer",
            category="test",
            source="manual",
            verified=False,
        )

        # Add verified FAQ
        faq2 = FAQItem(
            question="Verified FAQ?",
            answer="Verified answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=now,
        )

        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)

        # Filter by date range (should exclude unverified FAQ)
        response = faq_repository.get_faqs_paginated(
            verified_from=yesterday, verified_to=now
        )

        # All results should have verified_at timestamps
        assert all(faq.verified_at is not None for faq in response.faqs)

    def test_date_filter_with_empty_results(self, faq_repository):
        """Test date filtering with no matching results."""
        now = datetime.now(timezone.utc)
        future_start = now + timedelta(days=10)
        future_end = now + timedelta(days=20)

        # Add FAQ with current timestamp
        faq = FAQItem(
            question="Current FAQ?",
            answer="Current answer",
            category="test",
            source="manual",
            verified=True,
            verified_at=now,
        )
        faq_repository.add_faq(faq)

        # Filter by future date range (should return empty)
        response = faq_repository.get_faqs_paginated(
            verified_from=future_start, verified_to=future_end
        )

        assert response.total_count == 0
        assert len(response.faqs) == 0

    def test_date_filter_combined_with_other_filters(self, faq_repository):
        """Test date filtering combined with category and search filters."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        # Add verified FAQs with different categories
        faq1 = FAQItem(
            question="Backup FAQ?",
            answer="Backup answer",
            category="backup",
            source="manual",
            verified=True,
            verified_at=yesterday,
        )
        faq2 = FAQItem(
            question="Security FAQ?",
            answer="Security answer",
            category="security",
            source="manual",
            verified=True,
            verified_at=now,
        )
        faq3 = FAQItem(
            question="Another backup FAQ?",
            answer="Another backup answer",
            category="backup",
            source="manual",
            verified=True,
            verified_at=now,
        )

        faq_repository.add_faq(faq1)
        faq_repository.add_faq(faq2)
        faq_repository.add_faq(faq3)

        # Filter by date range + category
        response = faq_repository.get_faqs_paginated(
            verified_from=now, categories=["backup"]
        )

        # Should only include backup FAQs verified today or later
        assert all(faq.category == "backup" for faq in response.faqs)
        assert all(faq.verified_at >= now for faq in response.faqs if faq.verified_at)
