"""Liveness contracts for scheduled live-index rebuilds."""

import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
from app.services.simplified_rag_service import SimplifiedRAGService


@pytest.mark.asyncio
async def test_live_index_rebuild_keeps_event_loop_responsive() -> None:
    service = object.__new__(SimplifiedRAGService)
    service._setup_lock = asyncio.Lock()

    @asynccontextmanager
    async def rebuild_guard() -> AsyncIterator[None]:
        yield

    service.faq_index_sync = SimpleNamespace(rebuild_guard=rebuild_guard)
    service.colbert_reranker = None
    service.settings = SimpleNamespace(COLBERT_TOP_N=4)
    service.embeddings = None
    service.retriever = None
    service.document_retriever = None

    build_started = threading.Event()
    release_build = threading.Event()
    next_embeddings = object()
    next_retriever = object()

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
