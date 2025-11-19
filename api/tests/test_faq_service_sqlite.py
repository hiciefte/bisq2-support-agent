"""
Tests for FAQService SQLite integration.

This test suite validates that FAQService correctly uses SQLite repository
for FAQ data loading in the RAG system.
"""

from pathlib import Path

import pytest
from app.models.faq import FAQItem
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from app.services.faq_service import FAQService
from langchain_core.documents import Document


@pytest.fixture
def sqlite_repo(tmp_path):
    """Create a temporary SQLite repository for testing."""
    db_path = tmp_path / "test_faqs.db"
    repo = FAQRepositorySQLite(str(db_path))
    return repo


@pytest.fixture
def faq_service(test_settings, sqlite_repo):
    """Create FAQService instance with SQLite repository."""
    # Override settings to use temporary database
    test_settings.DATA_DIR = str(Path(sqlite_repo.db_path).parent)
    service = FAQService(settings=test_settings)
    # Replace repository with test instance
    service.repository = sqlite_repo
    return service


@pytest.fixture
def sample_faq_data():
    """Sample FAQ data for testing."""
    return [
        FAQItem(
            question="How do I trade Bitcoin?",
            answer="Use the trade view to create offers",
            category="Trading",
            source="Manual",
            verified=True,
            bisq_version="Bisq 2",
        ),
        FAQItem(
            question="What is the minimum trade amount?",
            answer="0.01 BTC",
            category="Trading",
            source="Extracted",
            verified=True,
            bisq_version="Bisq 2",
        ),
        FAQItem(
            question="How to install Bisq?",
            answer="Download from bisq.network",
            category="Installation",
            source="Manual",
            verified=False,  # Unverified
            bisq_version="General",
        ),
    ]


class TestFAQServiceSQLiteIntegration:
    """Test suite for FAQService SQLite integration."""

    def test_load_faq_data_uses_repository(self, faq_service, sample_faq_data):
        """Test that FAQService.load_faq_data() uses SQLite repository, not JSONL file.

        This is the core test validating FAQService integration with SQLite-based
        RAG loading.
        """
        # Setup: Add FAQs to SQLite repository
        for faq in sample_faq_data:
            faq_service.repository.add_faq(faq)

        # Action: Load FAQs via FAQService (should query SQLite)
        docs = faq_service.load_faq_data()

        # Assert: Should load only verified FAQs by default
        assert len(docs) == 2, "Should load only verified FAQs"
        assert all(isinstance(doc, Document) for doc in docs)

        # Verify both verified FAQs are present (order-independent)
        all_content = " ".join([doc.page_content for doc in docs])
        assert "How do I trade Bitcoin?" in all_content
        assert "What is the minimum trade amount?" in all_content

    def test_load_faq_data_no_faq_file_parameter(self, faq_service, sample_faq_data):
        """Test that load_faq_data() no longer accepts faq_file parameter."""
        # Setup: Add FAQs
        for faq in sample_faq_data:
            faq_service.repository.add_faq(faq)

        # Action & Assert: Should work without faq_file parameter
        docs = faq_service.load_faq_data()
        assert len(docs) == 2

    def test_load_faq_data_returns_documents_with_sqlite_metadata(
        self, faq_service, sample_faq_data
    ):
        """Test that loaded documents have SQLite source metadata."""
        # Setup: Add FAQ
        faq_service.repository.add_faq(sample_faq_data[0])

        # Action: Load FAQs
        docs = faq_service.load_faq_data()

        # Assert: Source metadata should indicate SQLite
        assert len(docs) == 1
        source = docs[0].metadata["source"]
        assert "sqlite" in source.lower() or "faqs.db" in source.lower()

    def test_load_faq_data_empty_repository(self, faq_service):
        """Test that loading from empty repository returns empty list."""
        # Action: Load from empty repository
        docs = faq_service.load_faq_data()

        # Assert: Should return empty list without errors
        assert docs == []
        assert isinstance(docs, list)

    def test_load_faq_data_preserves_document_format(
        self, faq_service, sample_faq_data
    ):
        """Test that Document structure is preserved for RAG compatibility."""
        # Setup: Add FAQ
        faq_service.repository.add_faq(sample_faq_data[0])

        # Action: Load FAQs
        docs = faq_service.load_faq_data()

        # Assert: Document structure matches expected format
        assert len(docs) == 1
        doc = docs[0]

        # Check metadata fields
        assert "source" in doc.metadata
        assert "title" in doc.metadata
        assert doc.metadata["type"] == "faq"
        assert "source_weight" in doc.metadata
        assert "category" in doc.metadata
        assert "bisq_version" in doc.metadata
        assert "verified" in doc.metadata

        # Check content format
        assert doc.page_content.startswith("Question: ")
        assert "Answer: " in doc.page_content
