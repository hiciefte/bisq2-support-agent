"""
Tests for FAQService integration with SimilarFaqRepository (Phase 7.1.6).

This test suite validates that similar FAQs detected during extraction
are persisted to the review queue instead of just being logged.
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.faq import FAQItem
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from app.services.faq.similar_faq_repository import SimilarFaqRepository
from app.services.faq_service import FAQService


class MockSettings:
    """Mock settings for testing."""

    def __init__(self, data_dir: str, faq_db_path: str, similar_db_path: str):
        self.DATA_DIR = data_dir
        self.FAQ_DB_PATH = faq_db_path
        self.SIMILAR_FAQ_DB_PATH = similar_db_path
        self.SUPPORT_AGENT_NICKNAMES = ["support"]
        self.OPENAI_API_KEY = "test-key"
        self.ENABLE_PRIVACY_MODE = True  # Skip conversation persistence


@pytest.fixture
def temp_db_paths():
    """Create temporary database files for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield {
            "data_dir": temp_dir,
            "faq_db_path": os.path.join(temp_dir, "faqs.db"),
            "similar_db_path": os.path.join(temp_dir, "similar_faqs.db"),
        }


@pytest.fixture
def mock_settings(temp_db_paths):
    """Create mock settings for testing."""
    return MockSettings(
        data_dir=temp_db_paths["data_dir"],
        faq_db_path=temp_db_paths["faq_db_path"],
        similar_db_path=temp_db_paths["similar_db_path"],
    )


@pytest.fixture
def faq_repository(temp_db_paths):
    """Create FAQ repository for testing."""
    repo = FAQRepositorySQLite(temp_db_paths["faq_db_path"])
    # Add a sample FAQ to reference in similar FAQ candidates
    repo.add_faq(
        FAQItem(
            question="How do I buy Bitcoin on Bisq?",
            answer="Use Bisq Easy to buy Bitcoin safely.",
            category="Trading",
            source="Manual",
            verified=True,
            protocol="bisq_easy",
        )
    )
    yield repo
    repo.close()


@pytest.fixture
def similar_faq_repository(temp_db_paths, faq_repository):
    """Create SimilarFaqRepository for testing.

    Note: SimilarFaqRepository uses denormalized data (matched_* fields stored
    directly in candidates table), so no faqs table is needed in this database.
    """
    repo = SimilarFaqRepository(temp_db_paths["similar_db_path"])
    yield repo
    repo.close()


class TestFAQServiceSimilarFaqIntegration:
    """Tests for FAQService integration with SimilarFaqRepository."""

    def test_faq_service_accepts_similar_faq_repository(
        self, mock_settings, faq_repository, similar_faq_repository
    ):
        """Test that FAQService can be initialized with SimilarFaqRepository."""
        # Reset singleton for testing
        FAQService._instance = None

        with patch("app.services.faq_service.ai.Client"):
            service = FAQService(mock_settings)
            service.repository = faq_repository

            # Set similar FAQ repository
            service.similar_faq_repository = similar_faq_repository

            assert service.similar_faq_repository is not None
            assert isinstance(service.similar_faq_repository, SimilarFaqRepository)

    @pytest.mark.asyncio
    async def test_extract_and_save_faqs_persists_similar_faqs(
        self, mock_settings, faq_repository, similar_faq_repository
    ):
        """Test that similar FAQs are persisted to review queue during extraction."""
        # Reset singleton for testing
        FAQService._instance = None

        with patch("app.services.faq_service.ai.Client"):
            service = FAQService(mock_settings)
            service.repository = faq_repository
            service.similar_faq_repository = similar_faq_repository

            # Mock the extraction and semantic check methods
            mock_new_faqs = []  # No truly new FAQs
            mock_similar_faqs = [
                {
                    "question": "How can I purchase BTC?",
                    "answer": "Bisq Easy is the way.",
                    "category": "Trading",
                    "similar_to": {
                        "id": 1,
                        "question": "How do I buy Bitcoin on Bisq?",
                        "similarity": 0.92,
                    },
                }
            ]

            # Mock conversation processing
            service.processed_msg_ids = set()
            service.conversation_processor = MagicMock()
            service.faq_extractor = MagicMock()

            # Mock faq_extractor methods
            service.faq_extractor.extract_faqs_with_openai.return_value = (
                mock_similar_faqs
            )
            service.faq_extractor.check_semantic_duplicates = AsyncMock(
                return_value=(mock_new_faqs, mock_similar_faqs)
            )
            service.faq_extractor.seed_duplicate_tracker = MagicMock()

            # Mock RAG service with vectorstore
            mock_rag_service = MagicMock()
            mock_rag_service.vectorstore = MagicMock()

            # Mock fetch_and_merge_messages and load_messages
            service.fetch_and_merge_messages = AsyncMock()
            service.load_messages = MagicMock()
            service.group_conversations = MagicMock(
                return_value=[
                    {
                        "id": "conv1",
                        "messages": [{"msg_id": "msg1", "text": "test"}],
                    }
                ]
            )

            # Execute extraction
            await service.extract_and_save_faqs(
                bisq_api=None, rag_service=mock_rag_service
            )

            # Verify similar FAQs were persisted to review queue
            pending = similar_faq_repository.get_pending_candidates()
            assert pending.total == 1
            assert pending.items[0].extracted_question == "How can I purchase BTC?"
            assert pending.items[0].similarity == 0.92
            assert pending.items[0].matched_faq_id == 1

    @pytest.mark.asyncio
    async def test_extract_skips_persistence_without_similar_faq_repository(
        self, mock_settings, faq_repository
    ):
        """Test that extraction works without SimilarFaqRepository (graceful degradation)."""
        # Reset singleton for testing
        FAQService._instance = None

        with patch("app.services.faq_service.ai.Client"):
            service = FAQService(mock_settings)
            service.repository = faq_repository
            # Don't set similar_faq_repository

            # Mock everything
            service.processed_msg_ids = set()
            service.conversation_processor = MagicMock()
            service.faq_extractor = MagicMock()

            mock_similar_faqs = [
                {
                    "question": "How can I purchase BTC?",
                    "answer": "Bisq Easy is the way.",
                    "category": "Trading",
                    "similar_to": {
                        "id": 1,
                        "question": "How do I buy Bitcoin on Bisq?",
                        "similarity": 0.92,
                    },
                }
            ]

            service.faq_extractor.extract_faqs_with_openai.return_value = (
                mock_similar_faqs
            )
            service.faq_extractor.check_semantic_duplicates = AsyncMock(
                return_value=([], mock_similar_faqs)
            )
            service.faq_extractor.seed_duplicate_tracker = MagicMock()

            mock_rag_service = MagicMock()
            mock_rag_service.vectorstore = MagicMock()

            service.fetch_and_merge_messages = AsyncMock()
            service.load_messages = MagicMock()
            service.group_conversations = MagicMock(
                return_value=[
                    {
                        "id": "conv1",
                        "messages": [{"msg_id": "msg1", "text": "test"}],
                    }
                ]
            )

            # Execute - should not raise even without similar_faq_repository
            result = await service.extract_and_save_faqs(
                bisq_api=None, rag_service=mock_rag_service
            )

            # Should complete without error
            assert result == []

    @pytest.mark.asyncio
    async def test_extract_logs_persistence_failure(
        self, mock_settings, faq_repository, similar_faq_repository, caplog
    ):
        """Test that persistence failures are logged but don't crash extraction."""
        # Reset singleton for testing
        FAQService._instance = None

        with patch("app.services.faq_service.ai.Client"):
            service = FAQService(mock_settings)
            service.repository = faq_repository
            service.similar_faq_repository = similar_faq_repository

            # Mock to make add_candidate fail
            service.similar_faq_repository.add_candidate = MagicMock(
                side_effect=Exception("Database error")
            )

            # Mock everything else
            service.processed_msg_ids = set()
            service.conversation_processor = MagicMock()
            service.faq_extractor = MagicMock()

            mock_similar_faqs = [
                {
                    "question": "How can I purchase BTC?",
                    "answer": "Bisq Easy is the way.",
                    "category": "Trading",
                    "similar_to": {
                        "id": 1,
                        "question": "How do I buy Bitcoin on Bisq?",
                        "similarity": 0.92,
                    },
                }
            ]

            service.faq_extractor.extract_faqs_with_openai.return_value = (
                mock_similar_faqs
            )
            service.faq_extractor.check_semantic_duplicates = AsyncMock(
                return_value=([], mock_similar_faqs)
            )
            service.faq_extractor.seed_duplicate_tracker = MagicMock()

            mock_rag_service = MagicMock()
            mock_rag_service.vectorstore = MagicMock()

            service.fetch_and_merge_messages = AsyncMock()
            service.load_messages = MagicMock()
            service.group_conversations = MagicMock(
                return_value=[
                    {
                        "id": "conv1",
                        "messages": [{"msg_id": "msg1", "text": "test"}],
                    }
                ]
            )

            # Execute - should not crash
            import logging

            with caplog.at_level(logging.WARNING):
                result = await service.extract_and_save_faqs(
                    bisq_api=None, rag_service=mock_rag_service
                )

            # Should complete without error
            assert result == []
            # Should log the error
            assert any(
                "Failed to persist similar FAQ" in record.message
                for record in caplog.records
            )
