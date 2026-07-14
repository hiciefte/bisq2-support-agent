"""Concurrency regressions for context-only RAG generation."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pytest
from app.prompts import error_messages


async def _wait_for_thread_event(event: Event) -> None:
    async def poll() -> None:
        while not event.is_set():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=1.0)


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
    assert response["routing_action"] == "needs_human"
    assert response["requires_human"] is True


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
    assert response["routing_action"] == "needs_human"
    assert response["requires_human"] is True


@pytest.mark.asyncio
async def test_context_fallback_does_not_occupy_default_executor(rag_service) -> None:
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-default")
    )
    rag_service.settings.CONTEXT_LLM_TIMEOUT_SECONDS = 1.0

    started = Event()
    release = Event()
    rag_service.llm = MagicMock()

    def blocking_invoke(*args, **kwargs) -> str:
        started.set()
        release.wait(timeout=1.0)
        return "context answer"

    rag_service.llm.invoke.side_effect = blocking_invoke
    context_task = asyncio.create_task(
        rag_service._answer_from_context(
            "What did we establish?",
            [{"role": "assistant", "content": "The answer is in this history."}],
        )
    )

    try:
        await _wait_for_thread_event(started)
        default_result = await asyncio.wait_for(
            asyncio.to_thread(lambda: "default executor available"),
            timeout=0.1,
        )
    finally:
        release.set()
        response = await asyncio.wait_for(context_task, timeout=1.0)

    assert default_result == "default executor available"
    assert response["answer"] == "context answer"


@pytest.mark.asyncio
async def test_cleanup_shuts_down_context_fallback_executor(rag_service) -> None:
    executor = rag_service._context_llm_executor

    await rag_service.cleanup()
    await rag_service.cleanup()

    with pytest.raises(RuntimeError, match="cannot schedule new futures"):
        executor.submit(lambda: None)
