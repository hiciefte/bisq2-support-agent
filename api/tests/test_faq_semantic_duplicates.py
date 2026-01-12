"""
Tests for semantic duplicate detection in FAQ extraction pipeline.

Phase 6: Auto-extraction Integration - Tests for check_semantic_duplicates()
method that prevents semantically similar FAQs from being auto-extracted.
"""

from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.faq.faq_extractor import FAQExtractor


class TestCheckSemanticDuplicates:
    """Tests for FAQExtractor.check_semantic_duplicates() method."""

    @pytest.fixture
    def faq_extractor(self, test_settings):
        """Create a FAQExtractor instance for testing."""
        mock_client = MagicMock()
        return FAQExtractor(mock_client, test_settings)

    @pytest.fixture
    def mock_rag_service(self):
        """Create a mock RAG service with configurable similarity search."""
        mock = MagicMock()
        mock.search_faq_similarity = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def sample_extracted_faqs(self) -> List[Dict]:
        """Sample FAQs that might be extracted from conversations."""
        return [
            {
                "question": "How do I buy bitcoin on Bisq?",
                "answer": "Use Bisq Easy to purchase bitcoin safely.",
                "category": "Trading",
                "source": "Bisq Support Chat",
            },
            {
                "question": "What is the minimum trade amount?",
                "answer": "The minimum trade amount depends on the offer.",
                "category": "Trading",
                "source": "Bisq Support Chat",
            },
            {
                "question": "How do I restore my wallet?",
                "answer": "Go to Account > Restore and follow the instructions.",
                "category": "Technical",
                "source": "Bisq Support Chat",
            },
        ]

    @pytest.mark.asyncio
    async def test_returns_all_faqs_when_no_similar_exist(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that all FAQs are returned as unique when no similar FAQs exist."""
        mock_rag_service.search_faq_similarity = AsyncMock(return_value=[])

        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs,
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        assert len(unique_faqs) == 3
        assert len(similar_faqs) == 0
        assert unique_faqs == sample_extracted_faqs

    @pytest.mark.asyncio
    async def test_filters_semantically_similar_faqs(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that FAQs similar to existing ones are filtered out."""
        # First FAQ is similar to an existing one
        mock_rag_service.search_faq_similarity = AsyncMock(
            side_effect=[
                [  # First FAQ has a similar match
                    {
                        "id": 42,
                        "question": "How can I purchase BTC?",
                        "answer": "Use Bisq Easy for safe purchases.",
                        "similarity": 0.92,
                        "category": "Trading",
                    }
                ],
                [],  # Second FAQ has no similar match
                [],  # Third FAQ has no similar match
            ]
        )

        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs,
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        assert len(unique_faqs) == 2
        assert len(similar_faqs) == 1
        assert similar_faqs[0]["question"] == "How do I buy bitcoin on Bisq?"
        assert "similar_to" in similar_faqs[0]
        assert similar_faqs[0]["similar_to"]["id"] == 42

    @pytest.mark.asyncio
    async def test_uses_85_percent_threshold_by_default(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that the default threshold is 85% for auto-extraction."""
        # Return similarity just below 85% - should NOT be filtered
        mock_rag_service.search_faq_similarity = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "question": "Similar question",
                    "answer": "Similar answer",
                    "similarity": 0.84,  # Below 85% threshold
                }
            ]
        )

        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs[:1],  # Just first FAQ
            rag_service=mock_rag_service,
            # threshold defaults to 0.85
        )

        # 84% similarity is below 85% threshold, so it's unique
        assert len(unique_faqs) == 1
        assert len(similar_faqs) == 0

    @pytest.mark.asyncio
    async def test_filters_faqs_at_threshold(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that FAQs at exactly the threshold are filtered."""
        mock_rag_service.search_faq_similarity = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "question": "Similar question",
                    "answer": "Similar answer",
                    "similarity": 0.85,  # Exactly at threshold
                }
            ]
        )

        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs[:1],
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        # 85% is at threshold, so should be filtered
        assert len(unique_faqs) == 0
        assert len(similar_faqs) == 1

    @pytest.mark.asyncio
    async def test_handles_empty_input(self, faq_extractor, mock_rag_service):
        """Test that empty input returns empty results."""
        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=[],
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        assert unique_faqs == []
        assert similar_faqs == []
        mock_rag_service.search_faq_similarity.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_rag_service_none_gracefully(
        self, faq_extractor, sample_extracted_faqs
    ):
        """Test graceful degradation when RAG service is not available."""
        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs,
            rag_service=None,  # No RAG service available
            threshold=0.85,
        )

        # Without RAG service, all FAQs should be returned as unique
        assert len(unique_faqs) == 3
        assert len(similar_faqs) == 0

    @pytest.mark.asyncio
    async def test_handles_rag_service_error_gracefully(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test graceful degradation when RAG service raises an error."""
        mock_rag_service.search_faq_similarity = AsyncMock(
            side_effect=Exception("Vector store error")
        )

        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs,
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        # On error, treat as no similar FAQs (keep all unique)
        assert len(unique_faqs) == 3
        assert len(similar_faqs) == 0

    @pytest.mark.asyncio
    async def test_preserves_original_faq_data_in_similar_list(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that original FAQ data is preserved when marked as similar."""
        similar_match = {
            "id": 99,
            "question": "Existing similar question",
            "answer": "Existing answer",
            "similarity": 0.95,
        }
        mock_rag_service.search_faq_similarity = AsyncMock(
            side_effect=[[similar_match], [], []]
        )

        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs,
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        # The similar FAQ should preserve original question/answer/category/source
        assert similar_faqs[0]["question"] == sample_extracted_faqs[0]["question"]
        assert similar_faqs[0]["answer"] == sample_extracted_faqs[0]["answer"]
        assert similar_faqs[0]["category"] == sample_extracted_faqs[0]["category"]
        assert similar_faqs[0]["source"] == sample_extracted_faqs[0]["source"]
        # And also have the similar_to field
        assert similar_faqs[0]["similar_to"] == similar_match

    @pytest.mark.asyncio
    async def test_calls_search_with_correct_parameters(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that search_faq_similarity is called with correct parameters."""
        mock_rag_service.search_faq_similarity = AsyncMock(return_value=[])

        await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs[:1],
            rag_service=mock_rag_service,
            threshold=0.85,
        )

        mock_rag_service.search_faq_similarity.assert_called_once_with(
            question=sample_extracted_faqs[0]["question"],
            threshold=0.85,
            limit=1,  # Only need to know if ANY similar exists
        )

    @pytest.mark.asyncio
    async def test_custom_threshold(
        self, faq_extractor, mock_rag_service, sample_extracted_faqs
    ):
        """Test that custom threshold is respected."""
        # 70% similarity - would be filtered at 0.65 but not at 0.85
        mock_rag_service.search_faq_similarity = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "question": "Similar",
                    "answer": "Similar",
                    "similarity": 0.70,
                }
            ]
        )

        # With 0.65 threshold, this should be filtered
        unique_faqs, similar_faqs = await faq_extractor.check_semantic_duplicates(
            extracted_faqs=sample_extracted_faqs[:1],
            rag_service=mock_rag_service,
            threshold=0.65,
        )

        assert len(unique_faqs) == 0
        assert len(similar_faqs) == 1


class TestExtractAndSaveFaqsIntegration:
    """Integration tests for semantic duplicate check in extract_and_save_faqs flow."""

    @pytest.fixture
    def faq_service_with_mocked_rag(self, faq_service, rag_service):
        """Create an FAQ service with a mocked RAG service for testing."""
        # Set up the RAG service reference
        faq_service._rag_service = rag_service
        return faq_service

    @pytest.mark.asyncio
    async def test_skips_semantically_similar_faqs_during_extraction(
        self, faq_service, test_settings
    ):
        """Test that semantically similar FAQs are not saved during extraction."""
        # This is a higher-level integration test that verifies the full flow
        # It requires more complex setup - implementing as a placeholder for now
        # The actual integration will be tested after implementing the method
