"""
Integration tests for FAQ SQLite end-to-end flow.

This test suite validates the complete flow from admin CRUD operations
through to RAG document consistency, ensuring SQLite serves as the
single source of truth.
"""

from pathlib import Path

import pytest
from app.models.faq import FAQItem
from app.services.faq.faq_rag_loader import FAQRAGLoader
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from app.services.faq_service import FAQService
from langchain_core.documents import Document


@pytest.fixture
def integration_db(tmp_path):
    """Create a temporary database for integration testing."""
    db_path = tmp_path / "integration_faqs.db"
    repo = FAQRepositorySQLite(str(db_path))
    return repo


@pytest.fixture
def faq_service_e2e(test_settings, integration_db):
    """Create FAQService instance for end-to-end testing."""
    test_settings.DATA_DIR = str(Path(integration_db.db_path).parent)
    service = FAQService(settings=test_settings)
    service.repository = integration_db
    return service


@pytest.fixture
def rag_loader_e2e():
    """Create FAQRAGLoader instance for end-to-end testing."""
    return FAQRAGLoader()


class TestFAQSQLiteE2E:
    """Integration tests for FAQ SQLite end-to-end flow."""

    def test_admin_crud_to_rag_consistency(self, integration_db, rag_loader_e2e):
        """Test that admin CRUD operations are reflected in RAG document loading.

        This is the core integration test validating:
        1. FAQs added via admin API appear in RAG queries
        2. FAQs updated via admin API show changes in RAG
        3. FAQs deleted via admin API are removed from RAG
        """
        # Step 1: Add FAQ via admin API (simulated)
        new_faq = FAQItem(
            question="How do I create a trade?",
            answer="Use the Create Offer button in the trade view",
            category="Trading",
            source="Manual",
            verified=True,
            protocol="bisq_easy",
        )
        integration_db.add_faq(new_faq)

        # Verify it appears in RAG document loading
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )
        assert len(docs) == 1, "Should load the newly added FAQ"
        assert "How do I create a trade?" in docs[0].page_content
        assert "Create Offer button" in docs[0].page_content

        # Step 2: Update FAQ via admin API (simulated)
        all_faqs = integration_db.get_all_faqs()
        faq_to_update = all_faqs[0]
        faq_to_update.answer = "Navigate to Markets tab and click Create Offer"
        integration_db.update_faq(faq_to_update.id, faq_to_update)

        # Verify changes reflected in RAG
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )
        assert len(docs) == 1
        assert "Navigate to Markets tab" in docs[0].page_content
        assert "Create Offer button" not in docs[0].page_content

        # Step 3: Delete FAQ via admin API (simulated)
        integration_db.delete_faq(faq_to_update.id)

        # Verify it's removed from RAG
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )
        assert len(docs) == 0, "Deleted FAQ should not appear in RAG"

    def test_verified_filter_consistency(self, integration_db, rag_loader_e2e):
        """Test that verified filtering works consistently across admin and RAG."""
        # Setup: Add mix of verified and unverified FAQs
        verified_faq = FAQItem(
            question="Verified FAQ",
            answer="This is verified",
            verified=True,
        )
        unverified_faq = FAQItem(
            question="Unverified FAQ",
            answer="This is not verified",
            verified=False,
        )

        integration_db.add_faq(verified_faq)
        integration_db.add_faq(unverified_faq)

        # Action: Load with verified filter
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: Only verified FAQ should appear
        assert len(docs) == 1
        assert "Verified FAQ" in docs[0].page_content
        assert docs[0].metadata["verified"] is True

        # Action: Load without verified filter
        docs_all = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=False
        )

        # Assert: Both FAQs should appear
        assert len(docs_all) == 2

    def test_category_metadata_consistency(self, integration_db, rag_loader_e2e):
        """Test that category metadata is preserved from admin to RAG."""
        # Setup: Add FAQs with different categories
        categories = ["Trading", "Installation", "Security", "Technical"]
        for i, category in enumerate(categories):
            faq = FAQItem(
                question=f"Question {i}",
                answer=f"Answer {i}",
                category=category,
                verified=True,
            )
            integration_db.add_faq(faq)

        # Action: Load all FAQs
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: All categories preserved
        loaded_categories = {doc.metadata["category"] for doc in docs}
        assert loaded_categories == set(categories)

    def test_protocol_metadata_consistency(self, integration_db, rag_loader_e2e):
        """Test that protocol metadata is preserved from admin to RAG."""
        # Setup: Add FAQs with different protocol values
        protocols = ["multisig_v1", "bisq_easy", "all"]
        for i, protocol in enumerate(protocols):
            faq = FAQItem(
                question=f"Question {i}",
                answer=f"Answer {i}",
                protocol=protocol,
                verified=True,
            )
            integration_db.add_faq(faq)

        # Action: Load all FAQs
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: All protocols preserved
        loaded_protocols = {doc.metadata["protocol"] for doc in docs}
        assert loaded_protocols == set(protocols)

    def test_source_weight_application(self, integration_db, rag_loader_e2e):
        """Test that source weights are correctly applied to FAQ documents."""
        # Setup: Add FAQ
        faq = FAQItem(
            question="Test question",
            answer="Test answer",
            verified=True,
        )
        integration_db.add_faq(faq)

        # Action: Load FAQ
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: Source weight should be 1.2 (default FAQ weight)
        assert len(docs) == 1
        assert docs[0].metadata["source_weight"] == 1.2

    def test_document_format_consistency(self, integration_db, rag_loader_e2e):
        """Test that Document format is consistent for RAG system."""
        # Setup: Add FAQ with all metadata
        faq = FAQItem(
            question="How does reputation work?",
            answer="Reputation is based on verified transactions",
            category="Features",
            source="Manual",
            verified=True,
            protocol="bisq_easy",
        )
        integration_db.add_faq(faq)

        # Action: Load FAQ
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: Document structure is correct
        assert len(docs) == 1
        doc = docs[0]

        # Check content format
        assert doc.page_content.startswith("Question: ")
        assert "Answer: " in doc.page_content
        assert "How does reputation work?" in doc.page_content
        assert "based on verified transactions" in doc.page_content

        # Check all required metadata fields
        assert "source" in doc.metadata
        assert "sqlite" in doc.metadata["source"].lower()
        assert doc.metadata["title"] == "How does reputation work?"
        assert doc.metadata["type"] == "faq"
        assert doc.metadata["source_weight"] == 1.2
        assert doc.metadata["category"] == "Features"
        assert doc.metadata["protocol"] == "bisq_easy"
        assert doc.metadata["verified"] is True

    def test_empty_database_handling(self, integration_db, rag_loader_e2e):
        """Test that empty database returns empty document list."""
        # Action: Load from empty database
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: Should return empty list without errors
        assert docs == []
        assert isinstance(docs, list)

    def test_large_faq_set_performance(self, integration_db, rag_loader_e2e):
        """Test that large FAQ sets are handled efficiently."""
        # Setup: Add 100 FAQs
        for i in range(100):
            faq = FAQItem(
                question=f"Question {i}",
                answer=f"Answer {i}",
                category="Performance Test",
                verified=True,
            )
            integration_db.add_faq(faq)

        # Action: Load all FAQs
        docs = rag_loader_e2e.load_faq_data(
            repository=integration_db, only_verified=True
        )

        # Assert: All FAQs loaded correctly
        assert len(docs) == 100
        assert all(isinstance(doc, Document) for doc in docs)

    def test_faq_service_integration(self, faq_service_e2e):
        """Test FAQService end-to-end integration with RAG loading."""
        # Setup: Add FAQ via service
        faq = FAQItem(
            question="Integration test question",
            answer="Integration test answer",
            verified=True,
        )
        faq_service_e2e.repository.add_faq(faq)

        # Action: Load via FAQService
        docs = faq_service_e2e.load_faq_data()

        # Assert: FAQ loaded correctly through service
        assert len(docs) == 1
        assert "Integration test question" in docs[0].page_content
        assert docs[0].metadata["type"] == "faq"
