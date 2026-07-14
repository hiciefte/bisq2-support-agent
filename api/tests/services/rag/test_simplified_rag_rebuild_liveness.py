"""Liveness contracts for scheduled live-index rebuilds."""

import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from app.services.simplified_rag_service import SimplifiedRAGService


@pytest.mark.asyncio
async def test_live_index_rebuild_keeps_event_loop_responsive() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._setup_lock = asyncio.Lock()
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()

    @asynccontextmanager
    async def rebuild_guard() -> AsyncIterator[None]:
        yield

    service.faq_index_sync = SimpleNamespace(rebuild_guard=rebuild_guard)
    service.colbert_reranker = None
    service.settings = SimpleNamespace(COLBERT_TOP_N=4)
    service.embeddings = None
    outgoing_retriever = MagicMock()
    service.retriever = outgoing_retriever
    service.document_retriever = SimpleNamespace(retriever=outgoing_retriever)

    build_started = threading.Event()
    release_build = threading.Event()
    next_embeddings = object()
    next_retriever = object()

    def assert_new_state_is_live_before_close() -> None:
        assert service.embeddings is next_embeddings
        assert service.retriever is next_retriever
        assert service.document_retriever.retriever is next_retriever

    outgoing_retriever.close.side_effect = assert_new_state_is_live_before_close

    def blocking_build(*, force_rebuild: bool):
        assert force_rebuild is True
        build_started.set()
        release_build.wait(timeout=1)
        return next_embeddings, next_retriever

    service._build_live_index = blocking_build
    safety_release = threading.Timer(0.4, release_build.set)
    safety_release.start()

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    rebuild_task = asyncio.create_task(service.rebuild_live_index())
    while not build_started.is_set():
        await asyncio.sleep(0)
    await asyncio.sleep(0.02)
    heartbeat_elapsed = loop.time() - started_at

    release_build.set()
    assert await rebuild_task is True
    safety_release.cancel()

    assert heartbeat_elapsed < 0.2
    assert service.embeddings is next_embeddings
    assert service.retriever is next_retriever
    assert service.document_retriever.retriever is next_retriever
    outgoing_retriever.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_live_index_rebuild_keeps_new_state_when_old_close_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = object.__new__(SimplifiedRAGService)
    service._setup_lock = asyncio.Lock()
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()

    @asynccontextmanager
    async def rebuild_guard() -> AsyncIterator[None]:
        yield

    service.faq_index_sync = SimpleNamespace(rebuild_guard=rebuild_guard)
    service.colbert_reranker = None
    service.settings = SimpleNamespace(COLBERT_TOP_N=4)
    outgoing_retriever = MagicMock()
    outgoing_retriever.close.side_effect = RuntimeError("close failed")
    service.embeddings = object()
    service.retriever = outgoing_retriever
    service.document_retriever = SimpleNamespace(retriever=outgoing_retriever)
    next_embeddings = object()
    next_retriever = MagicMock()
    service._build_live_index = MagicMock(
        return_value=(next_embeddings, next_retriever)
    )

    with caplog.at_level("ERROR"):
        result = await service.rebuild_live_index()

    assert result is True
    assert service.embeddings is next_embeddings
    assert service.retriever is next_retriever
    assert service.document_retriever.retriever is next_retriever
    assert "Failed to close outgoing Qdrant retriever" in caplog.text


@pytest.mark.asyncio
async def test_live_index_wrapper_failure_preserves_old_state() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._setup_lock = asyncio.Lock()
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()

    @asynccontextmanager
    async def rebuild_guard() -> AsyncIterator[None]:
        yield

    service.faq_index_sync = SimpleNamespace(rebuild_guard=rebuild_guard)
    service.colbert_reranker = None
    service.settings = SimpleNamespace(COLBERT_TOP_N=4)
    outgoing_embeddings = object()
    outgoing_retriever = MagicMock()
    outgoing_document_retriever = SimpleNamespace(retriever=outgoing_retriever)
    service.embeddings = outgoing_embeddings
    service.retriever = outgoing_retriever
    service.document_retriever = outgoing_document_retriever
    candidate_retriever = MagicMock()
    service._build_live_index = MagicMock(return_value=(object(), candidate_retriever))

    with patch(
        "app.services.simplified_rag_service.DocumentRetriever",
        side_effect=RuntimeError("wrapper failed"),
    ):
        with pytest.raises(RuntimeError, match="wrapper failed"):
            await service.rebuild_live_index()

    assert service.embeddings is outgoing_embeddings
    assert service.retriever is outgoing_retriever
    assert service.document_retriever is outgoing_document_retriever
    outgoing_retriever.close.assert_not_called()
    candidate_retriever.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_live_index_rebuild_drains_outgoing_retrieval_before_close() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._setup_lock = asyncio.Lock()
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()

    @asynccontextmanager
    async def rebuild_guard() -> AsyncIterator[None]:
        yield

    service.faq_index_sync = SimpleNamespace(rebuild_guard=rebuild_guard)
    service.colbert_reranker = None
    service.settings = SimpleNamespace(COLBERT_TOP_N=4)
    outgoing_retriever = MagicMock()
    service.embeddings = object()
    service.retriever = outgoing_retriever
    service.document_retriever = SimpleNamespace(retriever=outgoing_retriever)
    next_retriever = MagicMock()
    service._build_live_index = MagicMock(return_value=(object(), next_retriever))

    retrieval_started = threading.Event()
    release_retrieval = threading.Event()

    def blocking_retrieval() -> None:
        retrieval_started.set()
        release_retrieval.wait(timeout=1)

    retrieval_future = service._start_retriever_call(
        outgoing_retriever, blocking_retrieval
    )
    while not retrieval_started.is_set():
        await asyncio.sleep(0)

    rebuild_task = asyncio.create_task(service.rebuild_live_index())
    while service.retriever is outgoing_retriever:
        await asyncio.sleep(0)
    await asyncio.sleep(0.02)

    assert rebuild_task.done() is False
    outgoing_retriever.close.assert_not_called()

    release_retrieval.set()
    await retrieval_future
    assert await rebuild_task is True
    outgoing_retriever.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_timed_out_similarity_search_keeps_lease_until_worker_finishes() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()
    retriever = MagicMock()
    service.retriever = retriever

    retrieval_started = threading.Event()
    release_retrieval = threading.Event()

    def blocking_retrieval(*args: object, **kwargs: object) -> list[object]:
        retrieval_started.set()
        release_retrieval.wait(timeout=1)
        return []

    retriever.retrieve_semantic_with_scores.side_effect = blocking_retrieval

    result = await service.search_faq_similarity("test question", timeout=0.01)

    assert result == []
    assert retrieval_started.is_set()
    assert service._retriever_lease_counts[id(retriever)] == 1

    close_task = asyncio.create_task(service._close_retriever_when_idle(retriever))
    await asyncio.sleep(0.02)
    assert close_task.done() is False
    retriever.close.assert_not_called()

    release_retrieval.set()
    await close_task
    retriever.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_cancelled_rebuild_still_retires_outgoing_retriever() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._setup_lock = asyncio.Lock()
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()

    @asynccontextmanager
    async def rebuild_guard() -> AsyncIterator[None]:
        yield

    service.faq_index_sync = SimpleNamespace(rebuild_guard=rebuild_guard)
    service.colbert_reranker = None
    service.settings = SimpleNamespace(COLBERT_TOP_N=4)
    outgoing_retriever = MagicMock()
    service.embeddings = object()
    service.retriever = outgoing_retriever
    service.document_retriever = SimpleNamespace(retriever=outgoing_retriever)
    service._build_live_index = MagicMock(return_value=(object(), MagicMock()))

    retrieval_started = threading.Event()
    release_retrieval = threading.Event()

    def blocking_retrieval() -> None:
        retrieval_started.set()
        release_retrieval.wait(timeout=1)

    retrieval_future = service._start_retriever_call(
        outgoing_retriever, blocking_retrieval
    )
    while not retrieval_started.is_set():
        await asyncio.sleep(0)

    rebuild_task = asyncio.create_task(service.rebuild_live_index())
    while service.retriever is outgoing_retriever:
        await asyncio.sleep(0)
    rebuild_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await rebuild_task

    retirement_tasks = list(service._background_tasks)
    assert len(retirement_tasks) == 1
    outgoing_retriever.close.assert_not_called()

    release_retrieval.set()
    await retrieval_future
    await asyncio.gather(*retirement_tasks)
    outgoing_retriever.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_cancelled_retrieval_wait_does_not_strand_lease() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()
    retriever = MagicMock()
    retrieval_started = threading.Event()
    release_retrieval = threading.Event()

    def blocking_retrieval() -> None:
        retrieval_started.set()
        release_retrieval.wait(timeout=1)

    retrieval_task = asyncio.create_task(
        service._run_retriever_call(retriever, blocking_retrieval)
    )
    while not retrieval_started.is_set():
        await asyncio.sleep(0)

    retrieval_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await retrieval_task

    assert service._retriever_lease_counts[id(retriever)] == 1
    close_task = asyncio.create_task(service._close_retriever_when_idle(retriever))
    await asyncio.sleep(0.02)
    assert close_task.done() is False

    release_retrieval.set()
    await close_task
    assert id(retriever) not in service._retriever_lease_counts
    retriever.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_executor_submission_failure_releases_retriever_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(SimplifiedRAGService)
    service._retriever_lease_counts = {}
    service._retriever_idle_events = {}
    service._background_tasks = set()
    retriever = MagicMock()
    loop = MagicMock()
    loop.run_in_executor.side_effect = RuntimeError("executor unavailable")
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)

    with pytest.raises(RuntimeError, match="executor unavailable"):
        service._start_retriever_call(retriever, MagicMock())

    assert id(retriever) not in service._retriever_lease_counts
    assert service._retriever_idle_events[id(retriever)].is_set()
