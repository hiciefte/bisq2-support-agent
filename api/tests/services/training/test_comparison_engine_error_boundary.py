"""Tests for comparison-engine error boundaries."""

import logging
from unittest.mock import AsyncMock

import pytest
from app.services.training.comparison_engine import AnswerComparisonEngine


@pytest.mark.asyncio
async def test_provider_failure_reasoning_is_generic(caplog):
    """Provider exception details must not be persisted as judge reasoning."""

    class MockClient:
        pass

    class MockEmbeddings:
        def embed_query(self, text):
            return [1.0, 0.0]

    engine = AnswerComparisonEngine(
        ai_client=MockClient(),
        embeddings_model=MockEmbeddings(),
    )
    internal_detail = "provider rejected credential marker"
    engine._call_llm_with_retry = AsyncMock(side_effect=RuntimeError(internal_detail))

    with caplog.at_level(
        logging.ERROR,
        logger="app.services.training.comparison_engine",
    ):
        result = await engine.compare(
            question_event_id="event-1",
            question_text="Question",
            staff_answer="Same answer",
            generated_answer="Same answer",
        )

    assert result.evaluation_status == "failed"
    assert result.llm_reasoning == "LLM evaluation failed"
    assert internal_detail not in result.llm_reasoning
    assert internal_detail in caplog.text
