"""Tests for shared FAQ duplicate guard helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.faq.duplicate_guard import (
    ANSWER_PREVIEW_CHARS,
    build_duplicate_faq_detail,
    find_similar_faqs,
)


@pytest.mark.asyncio
async def test_find_similar_faqs_returns_empty_when_rag_service_missing() -> None:
    result = await find_similar_faqs(None, question="What is Bisq Easy?")
    assert result == []


@pytest.mark.asyncio
async def test_find_similar_faqs_calls_rag_similarity_search() -> None:
    rag_service = MagicMock()
    rag_service.search_faq_similarity = AsyncMock(return_value=[{"id": 1}])

    result = await find_similar_faqs(
        rag_service,
        question="What is Bisq Easy?",
        threshold=0.85,
        limit=3,
    )

    assert result == [{"id": 1}]
    rag_service.search_faq_similarity.assert_awaited_once_with(
        question="What is Bisq Easy?",
        threshold=0.85,
        limit=3,
        exclude_id=None,
    )


def test_build_duplicate_faq_detail_truncates_answer_and_includes_context() -> None:
    long_answer = "a" * (ANSWER_PREVIEW_CHARS + 10)
    detail = build_duplicate_faq_detail(
        message="Cannot create FAQ: duplicate",
        similar_faqs=[
            {
                "id": 42,
                "question": "How do I trade?",
                "answer": long_answer,
                "similarity": 0.91,
                "category": "Trading",
                "protocol": "bisq_easy",
            }
        ],
        context={"escalation_id": 7},
    )

    assert detail["error"] == "duplicate_faq"
    assert detail["message"] == "Cannot create FAQ: duplicate"
    assert detail["escalation_id"] == 7
    assert detail["similar_faqs"][0]["id"] == 42
    assert detail["similar_faqs"][0]["answer"].endswith("...")
