"""
Tests for Similar FAQ search functionality in SimplifiedRAGService.

TDD Phase 2: Tests for search_faq_similarity() method.
"""

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document


class TestSearchFAQSimilarity:
    """Tests for SimplifiedRAGService.search_faq_similarity() method."""

    @pytest.fixture
    def mock_vectorstore(self):
        """Create a mock vectorstore with similarity_search_with_score."""
        mock = MagicMock()
        # Default: return empty results
        mock.similarity_search_with_score.return_value = []
        return mock

    @pytest.fixture
    def rag_service_with_vectorstore(self, rag_service, mock_vectorstore):
        """Create RAG service with a mock vectorstore."""
        rag_service.vectorstore = mock_vectorstore
        return rag_service

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_similar_faqs(
        self, rag_service_with_vectorstore
    ):
        """Test that empty list is returned when no similar FAQs exist."""
        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="How do I setup Bisq?"
        )

        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_similar_faqs_above_threshold(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that FAQs above threshold are returned."""
        # ChromaDB returns (Document, distance) tuples
        # Distance of 0.3 = similarity of 1 - (0.3/2) = 0.85
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="Q: How do I buy bitcoin?\nA: Use Bisq Easy.",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "How do I buy bitcoin?",
                        "answer": "Use Bisq Easy to buy bitcoin safely and privately.",
                        "category": "Trading",
                        "protocol": "bisq_easy",
                    },
                ),
                0.3,  # Distance = 0.3 -> Similarity = 0.85
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="How can I purchase BTC?",
            threshold=0.65,
        )

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["question"] == "How do I buy bitcoin?"
        assert result[0]["similarity"] == pytest.approx(0.85, rel=0.01)

    @pytest.mark.asyncio
    async def test_filters_out_faqs_below_threshold(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that FAQs below threshold are filtered out."""
        # Distance of 1.0 = similarity of 1 - (1.0/2) = 0.5
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="Q: How do I buy bitcoin?\nA: Use Bisq Easy.",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "How do I buy bitcoin?",
                        "answer": "Use Bisq Easy.",
                    },
                ),
                1.0,  # Distance = 1.0 -> Similarity = 0.5
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="How can I purchase BTC?",
            threshold=0.65,  # 0.5 < 0.65, so should be filtered out
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_uses_faq_type_filter(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that search filters by type='faq' to exclude wiki documents."""
        await rag_service_with_vectorstore.search_faq_similarity(
            question="Test question"
        )

        # Verify the filter was applied
        mock_vectorstore.similarity_search_with_score.assert_called_once()
        call_kwargs = mock_vectorstore.similarity_search_with_score.call_args[1]
        assert call_kwargs.get("filter") == {"type": "faq"}

    @pytest.mark.asyncio
    async def test_excludes_faq_by_id(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that exclude_id filters out the specified FAQ."""
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="Q: Question 1\nA: Answer 1",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "Question 1",
                        "answer": "Answer 1",
                    },
                ),
                0.2,  # Similarity = 0.9
            ),
            (
                Document(
                    page_content="Q: Question 2\nA: Answer 2",
                    metadata={
                        "type": "faq",
                        "id": 2,
                        "question": "Question 2",
                        "answer": "Answer 2",
                    },
                ),
                0.3,  # Similarity = 0.85
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test question",
            exclude_id=1,  # Exclude FAQ with id=1
        )

        # Only FAQ with id=2 should be returned
        assert len(result) == 1
        assert result[0]["id"] == 2

    @pytest.mark.asyncio
    async def test_respects_limit_parameter(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that limit parameter restricts number of results."""
        # Return 5 FAQs
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content=f"Q: Question {i}\nA: Answer {i}",
                    metadata={
                        "type": "faq",
                        "id": i,
                        "question": f"Question {i}",
                        "answer": f"Answer {i}",
                    },
                ),
                0.2,  # All have high similarity
            )
            for i in range(1, 6)
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test question",
            limit=3,  # Only want 3 results
        )

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_over_fetches_to_ensure_limit_after_filtering(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that search over-fetches by 2x to ensure enough results after filtering."""
        await rag_service_with_vectorstore.search_faq_similarity(
            question="Test question",
            limit=5,
        )

        # Should request 10 (2x limit) to ensure enough after filtering
        call_kwargs = mock_vectorstore.similarity_search_with_score.call_args[1]
        assert call_kwargs.get("k") == 10

    @pytest.mark.asyncio
    async def test_results_sorted_by_similarity_descending(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that results are sorted by similarity (highest first)."""
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="Q: Low sim\nA: Answer",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "Low sim",
                        "answer": "Answer",
                    },
                ),
                0.5,  # Similarity = 0.75
            ),
            (
                Document(
                    page_content="Q: High sim\nA: Answer",
                    metadata={
                        "type": "faq",
                        "id": 2,
                        "question": "High sim",
                        "answer": "Answer",
                    },
                ),
                0.1,  # Similarity = 0.95
            ),
            (
                Document(
                    page_content="Q: Med sim\nA: Answer",
                    metadata={
                        "type": "faq",
                        "id": 3,
                        "question": "Med sim",
                        "answer": "Answer",
                    },
                ),
                0.3,  # Similarity = 0.85
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test",
            threshold=0.65,
        )

        # Should be sorted highest first
        assert result[0]["similarity"] > result[1]["similarity"]
        assert result[1]["similarity"] > result[2]["similarity"]

    @pytest.mark.asyncio
    async def test_truncates_answer_to_200_chars(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that answer is truncated to 200 characters."""
        long_answer = "A" * 500  # 500 character answer

        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content=f"Q: Question\nA: {long_answer}",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "Question",
                        "answer": long_answer,
                    },
                ),
                0.2,
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test"
        )

        assert len(result[0]["answer"]) <= 200

    @pytest.mark.asyncio
    async def test_returns_empty_on_vectorstore_error(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that errors return empty list (graceful degradation)."""
        mock_vectorstore.similarity_search_with_score.side_effect = Exception(
            "Vector store error"
        )

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test question"
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_vectorstore_not_initialized(self, rag_service):
        """Test that empty list returned when vectorstore is None."""
        rag_service.vectorstore = None

        result = await rag_service.search_faq_similarity(question="Test question")

        assert result == []

    @pytest.mark.asyncio
    async def test_converts_chroma_distance_to_similarity(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test correct conversion from ChromaDB distance to similarity score."""
        # ChromaDB uses L2 distance where lower = more similar
        # Formula: similarity = 1 - (distance / 2)
        test_cases = [
            (0.0, 1.0),  # Distance 0 = 100% similar
            (0.2, 0.9),  # Distance 0.2 = 90% similar
            (0.5, 0.75),  # Distance 0.5 = 75% similar
            (1.0, 0.5),  # Distance 1.0 = 50% similar
            (2.0, 0.0),  # Distance 2.0 = 0% similar
        ]

        for distance, expected_similarity in test_cases:
            mock_vectorstore.similarity_search_with_score.return_value = [
                (
                    Document(
                        page_content="Q: Test\nA: Test",
                        metadata={
                            "type": "faq",
                            "id": 1,
                            "question": "Test",
                            "answer": "Test",
                        },
                    ),
                    distance,
                ),
            ]

            result = await rag_service_with_vectorstore.search_faq_similarity(
                question="Test",
                threshold=0.0,  # Accept all
            )

            if result:
                assert result[0]["similarity"] == pytest.approx(
                    expected_similarity, rel=0.01
                ), f"Distance {distance} should give similarity {expected_similarity}"

    @pytest.mark.asyncio
    async def test_includes_category_and_protocol_in_result(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that category and protocol metadata are included in results."""
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="Q: Question\nA: Answer",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "Question",
                        "answer": "Answer",
                        "category": "Trading",
                        "protocol": "bisq_easy",
                    },
                ),
                0.2,
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test"
        )

        assert result[0]["category"] == "Trading"
        assert result[0]["protocol"] == "bisq_easy"

    @pytest.mark.asyncio
    async def test_handles_missing_metadata_gracefully(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that missing metadata fields default to None."""
        mock_vectorstore.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="Q: Question\nA: Answer",
                    metadata={
                        "type": "faq",
                        "id": 1,
                        "question": "Question",
                        "answer": "Answer",
                        # No category or protocol
                    },
                ),
                0.2,
            ),
        ]

        result = await rag_service_with_vectorstore.search_faq_similarity(
            question="Test"
        )

        assert result[0]["category"] is None
        assert result[0]["protocol"] is None

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_list(
        self, rag_service_with_vectorstore, mock_vectorstore
    ):
        """Test that timeout results in empty list."""

        async def slow_search(*args, **kwargs):
            await asyncio.sleep(10)  # Simulate slow search
            return []

        # Mock to be slow
        mock_vectorstore.similarity_search_with_score = MagicMock(
            side_effect=lambda *args, **kwargs: []
        )

        # Patch asyncio.wait_for to simulate timeout
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await rag_service_with_vectorstore.search_faq_similarity(
                question="Test",
                timeout=0.1,
            )

        assert result == []
