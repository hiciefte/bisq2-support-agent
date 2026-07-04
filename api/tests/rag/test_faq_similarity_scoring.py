"""Tests for absolute score semantics in FAQ similarity search (finding G1).

search_faq_similarity() and the duplicate guard compare scores against
absolute thresholds (0.65 / 0.85), so they must consume calibrated semantic
similarity (raw cosine), not min-max normalized fusion scores where the best
hit is always 1.0.
"""

from unittest.mock import MagicMock

import pytest
from app.services.faq.duplicate_guard import find_similar_faqs
from app.services.rag.interfaces import RetrievedDocument


def _faq_doc(faq_id: int, score: float, question: str = "How do I trade?"):
    return RetrievedDocument(
        content=question,
        metadata={
            "id": faq_id,
            "question": question,
            "answer": f"Answer for FAQ {faq_id}",
            "category": "trading",
            "protocol": "bisq_easy",
            "type": "faq",
        },
        score=score,
        id=f"doc-{faq_id}",
    )


@pytest.fixture
def semantic_retriever():
    """Retriever mock exposing both scored search paths."""
    retriever = MagicMock()
    retriever.retrieve_semantic_with_scores.return_value = []
    retriever.retrieve_with_scores.return_value = []
    return retriever


class TestSearchFaqSimilarityScoreSemantics:
    """search_faq_similarity must use the semantic (absolute) score path."""

    @pytest.mark.asyncio
    async def test_uses_semantic_path_not_fused_ranking_path(
        self, rag_service, semantic_retriever
    ):
        semantic_retriever.retrieve_semantic_with_scores.return_value = [
            _faq_doc(1, 0.95)
        ]
        rag_service.retriever = semantic_retriever

        results = await rag_service.search_faq_similarity("test?", threshold=0.85)

        assert [faq["id"] for faq in results] == [1]
        semantic_retriever.retrieve_semantic_with_scores.assert_called_once()
        # The fused/min-max ranking path must NOT feed absolute thresholds
        semantic_retriever.retrieve_with_scores.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_low_relevance_faq_rejected_by_threshold(
        self, rag_service, semantic_retriever
    ):
        """A lone barely-related FAQ (cosine ~0.3) must not pass 0.65/0.85."""
        semantic_retriever.retrieve_semantic_with_scores.return_value = [
            _faq_doc(1, 0.3)
        ]
        rag_service.retriever = semantic_retriever

        assert await rag_service.search_faq_similarity("test?", threshold=0.65) == []
        assert await rag_service.search_faq_similarity("test?", threshold=0.85) == []

    @pytest.mark.asyncio
    async def test_true_near_duplicate_passes_threshold(
        self, rag_service, semantic_retriever
    ):
        semantic_retriever.retrieve_semantic_with_scores.return_value = [
            _faq_doc(7, 0.95, question="How do I buy bitcoin?"),
            _faq_doc(8, 0.3, question="What is the DAO?"),
        ]
        rag_service.retriever = semantic_retriever

        results = await rag_service.search_faq_similarity("test?", threshold=0.85)

        assert [faq["id"] for faq in results] == [7]
        assert results[0]["similarity"] == pytest.approx(0.95)


class TestDuplicateGuardScoreSemantics:
    """Duplicate guard (0.85 default threshold) via search_faq_similarity."""

    @pytest.mark.asyncio
    async def test_low_relevance_faq_not_flagged_as_duplicate(
        self, rag_service, semantic_retriever
    ):
        semantic_retriever.retrieve_semantic_with_scores.return_value = [
            _faq_doc(1, 0.3)
        ]
        rag_service.retriever = semantic_retriever

        assert await find_similar_faqs(rag_service, question="test?") == []

    @pytest.mark.asyncio
    async def test_near_duplicate_faq_flagged(self, rag_service, semantic_retriever):
        semantic_retriever.retrieve_semantic_with_scores.return_value = [
            _faq_doc(2, 0.95)
        ]
        rag_service.retriever = semantic_retriever

        results = await find_similar_faqs(rag_service, question="test?")

        assert [faq["id"] for faq in results] == [2]
        assert results[0]["similarity"] == pytest.approx(0.95)
