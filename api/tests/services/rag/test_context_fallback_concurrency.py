"""Concurrency regressions for context-only RAG generation."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from app.prompts import error_messages


@pytest.mark.asyncio
async def test_context_fallback_does_not_block_event_loop(rag_service) -> None:
    rag_service.settings.CONTEXT_LLM_TIMEOUT_SECONDS = 1.0
    rag_service.llm = MagicMock()
    rag_service.llm.invoke.side_effect = lambda *args, **kwargs: (
        time.sleep(0.2) or "context answer"
    )

    tick_elapsed = None
    started = time.monotonic()

    async def tick() -> None:
        nonlocal tick_elapsed
        await asyncio.sleep(0.01)
        tick_elapsed = time.monotonic() - started

    response, _ = await asyncio.gather(
        rag_service._answer_from_context(
            "What did we establish?",
            [{"role": "assistant", "content": "The answer is in this history."}],
        ),
        tick(),
    )

    assert tick_elapsed is not None
    assert tick_elapsed < 0.1
    assert response["answer"] == "context answer"


@pytest.mark.asyncio
async def test_context_fallback_times_out_to_insufficient_information(
    rag_service,
) -> None:
    rag_service.settings.CONTEXT_LLM_TIMEOUT_SECONDS = 0.01
    rag_service.llm = MagicMock()
    rag_service.llm.invoke.side_effect = lambda *args, **kwargs: (
        time.sleep(0.2) or "late answer"
    )

    started = time.monotonic()
    response = await rag_service._answer_from_context(
        "What did we establish?",
        [{"role": "assistant", "content": "The answer is in this history."}],
    )

    assert time.monotonic() - started < 0.1
    assert response["answer"] == error_messages.INSUFFICIENT_INFO
    assert response["context_fallback_failed"] is True
