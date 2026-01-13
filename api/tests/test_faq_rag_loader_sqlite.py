"""
Tests for FAQRAGLoader with SQLite repository backend.

This test suite validates the migration from JSONL file-based FAQ loading
to SQLite database-based loading for the RAG system.
"""

import pytest
from app.models.faq import FAQItem
from app.services.faq.faq_rag_loader import FAQRAGLoader
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from langchain_core.documents import Document


@pytest.fixture
def sqlite_repo(tmp_path):
    """Create a temporary SQLite repository for testing."""
    db_path = tmp_path / "test_faqs.db"
    repo = FAQRepositorySQLite(str(db_path))
    return repo


@pytest.fixture
def rag_loader():
    """Create FAQRAGLoader instance with default source weights."""
    return FAQRAGLoader()


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
            protocol="bisq_easy",
        ),
        FAQItem(
            question="What is the minimum trade amount?",
            answer="0.01 BTC",
            category="Trading",
            source="Extracted",
            verified=True,
            protocol="bisq_easy",
        ),
        FAQItem(
            question="How to install Bisq?",
            answer="Download from bisq.network",
            category="Installation",
            source="Manual",
            verified=False,  # Unverified
            protocol="all",
        ),
    ]


class TestFAQRAGLoaderSQLite:
    """Test suite for SQLite-based FAQ loading in RAG system."""

    def test_load_faq_data_from_sqlite_repository(
        self, sqlite_repo, rag_loader, sample_faq_data
    ):
        """Test loading FAQ data from SQLite repository instead of JSONL file.

        This is the core test validating the migration from file-based to
        database-based FAQ loading.
        """
        # Setup: Add FAQs to SQLite repository
        for faq in sample_faq_data:
            sqlite_repo.add_faq(faq)

        # Action: Load FAQs via RAG loader (should query SQLite)
        docs = rag_loader.load_faq_data(repository=sqlite_repo, only_verified=True)

        # Assert: Should load 2 verified FAQs (excluding unverified one)
        assert len(docs) == 2, "Should load only verified FAQs"

        # Verify document content format
        assert isinstance(docs[0], Document), "Should return LangChain Document objects"

        # Verify both verified FAQs are present (order-independent)
        all_content = " ".join([doc.page_content for doc in docs])
        assert "How do I trade Bitcoin?" in all_content
        assert "Use the trade view" in all_content

    def test_only_verified_faqs_loaded(self, sqlite_repo, rag_loader, sample_faq_data):
        """Test that only verified FAQs are loaded when only_verified=True."""
        # Setup: Add mix of verified and unverified FAQs
        for faq in sample_faq_data:
            sqlite_repo.add_faq(faq)

        # Action: Load with verified filter
        docs = rag_loader.load_faq_data(repository=sqlite_repo, only_verified=True)

        # Assert: Only verified FAQs should be present
        assert len(docs) == 2, "Should filter out unverified FAQs"

        # Verify all loaded FAQs are verified
        for doc in docs:
            assert (
                doc.metadata["verified"] is True
            ), "All loaded FAQs should be verified"

        # Verify unverified FAQ is excluded
        doc_contents = [doc.page_content for doc in docs]
        assert not any(
            "How to install Bisq?" in content for content in doc_contents
        ), "Unverified FAQ should not be loaded"

    def test_all_faqs_loaded_when_verified_false(
        self, sqlite_repo, rag_loader, sample_faq_data
    ):
        """Test that all FAQs are loaded when only_verified=False."""
        # Setup: Add mix of verified and unverified FAQs
        for faq in sample_faq_data:
            sqlite_repo.add_faq(faq)

        # Action: Load without verified filter
        docs = rag_loader.load_faq_data(repository=sqlite_repo, only_verified=False)

        # Assert: All FAQs should be present
        assert len(docs) == 3, "Should load all FAQs regardless of verified status"

    def test_document_metadata_preservation(
        self, sqlite_repo, rag_loader, sample_faq_data
    ):
        """Test that Document metadata structure matches expected format.

        Ensures SQLite-loaded Documents have the same metadata as JSONL-loaded
        Documents for backward compatibility with the RAG system.
        """
        # Setup: Add FAQ with all metadata fields
        sqlite_repo.add_faq(sample_faq_data[0])

        # Action: Load FAQ
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: Verify complete metadata structure
        meta = docs[0].metadata
        assert "source" in meta, "Must have source field"
        assert "title" in meta, "Must have title field"
        assert meta["type"] == "faq", "Type must be 'faq'"
        assert meta["source_weight"] == 1.2, "Default FAQ source weight is 1.2"
        assert meta["category"] == "Trading", "Category must be preserved"
        assert meta["protocol"] == "bisq_easy", "Protocol must be preserved"
        assert meta["verified"] is True, "Verified status must be preserved"

        # Verify title truncation
        assert len(meta["title"]) <= 53, "Title should be truncated to 50 chars + '...'"

    def test_empty_repository_returns_empty_list(self, sqlite_repo, rag_loader):
        """Test edge case: empty repository returns empty document list."""
        # Action: Load from empty repository
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: Should return empty list without errors
        assert docs == [], "Empty repository should return empty list"
        assert isinstance(docs, list), "Should return list type"

    def test_source_weight_applied_correctly(self, sqlite_repo, rag_loader):
        """Test that source weight is correctly applied to document metadata."""
        # Setup: Add FAQ
        faq = FAQItem(
            question="Test question?",
            answer="Test answer",
            category="Test",
            verified=True,
        )
        sqlite_repo.add_faq(faq)

        # Action: Load FAQ
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: Source weight should be applied
        assert (
            docs[0].metadata["source_weight"] == 1.2
        ), "FAQ source weight should be 1.2"

    def test_document_content_format(self, sqlite_repo, rag_loader, sample_faq_data):
        """Test that document content follows 'Question: ... Answer: ...' format."""
        # Setup: Add FAQ
        sqlite_repo.add_faq(sample_faq_data[0])

        # Action: Load FAQ
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: Content should have specific format
        content = docs[0].page_content
        assert content.startswith(
            "Question: "
        ), "Content should start with 'Question: '"
        assert "Answer: " in content, "Content should contain 'Answer: '"
        assert "How do I trade Bitcoin?" in content
        assert "Use the trade view" in content

    def test_multiple_categories_preserved(self, sqlite_repo, rag_loader):
        """Test that different FAQ categories are preserved in metadata."""
        # Setup: Add FAQs from different categories
        faqs = [
            FAQItem(question="Q1", answer="A1", category="Trading", verified=True),
            FAQItem(
                question="Q2",
                answer="A2",
                category="Installation",
                verified=True,
            ),
            FAQItem(question="Q3", answer="A3", category="Security", verified=True),
        ]
        for faq in faqs:
            sqlite_repo.add_faq(faq)

        # Action: Load all FAQs
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: All categories should be preserved
        categories = {doc.metadata["category"] for doc in docs}
        assert categories == {
            "Trading",
            "Installation",
            "Security",
        }, "All categories should be preserved"

    def test_protocol_handling(self, sqlite_repo, rag_loader):
        """Test that protocol metadata is correctly handled."""
        # Setup: Add FAQs with different protocol values
        protocols = ["multisig_v1", "bisq_easy", "all"]
        for idx, protocol in enumerate(protocols):
            faq = FAQItem(
                question=f"Q{idx}",
                answer=f"A{idx}",
                verified=True,
                protocol=protocol,
            )
            sqlite_repo.add_faq(faq)

        # Action: Load FAQs
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: All protocols should be preserved
        loaded_protocols = {doc.metadata["protocol"] for doc in docs}
        assert loaded_protocols == {
            "multisig_v1",
            "bisq_easy",
            "all",
        }, "All protocol values should be preserved"

    def test_source_metadata_format(self, sqlite_repo, rag_loader, sample_faq_data):
        """Test that source metadata indicates SQLite origin."""
        # Setup: Add FAQ
        sqlite_repo.add_faq(sample_faq_data[0])

        # Action: Load FAQ
        docs = rag_loader.load_faq_data(repository=sqlite_repo)

        # Assert: Source should indicate SQLite database
        source = docs[0].metadata["source"]
        assert (
            "sqlite" in source.lower() or "faqs.db" in source.lower()
        ), "Source should indicate SQLite database origin"
