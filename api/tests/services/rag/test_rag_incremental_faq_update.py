"""Tests for incremental FAQ index updates wired through _handle_faq_update.

Review finding F1: with rebuild=False the handler only recorded pending
changes in memory, so approved/added FAQs never reached the Qdrant index
until an admin triggered a manual rebuild. The handler must now apply the
change incrementally (upsert/delete points for the affected FAQ) and only
fall back to mark_change when the incremental path cannot run or fails.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.simplified_rag_service import SimplifiedRAGService
from langchain_core.documents import Document


def _faq_doc(faq_id: str, question: str, answer: str) -> Document:
    return Document(
        page_content=f"Question: {question}\nAnswer: {answer}",
        metadata={
            "source": "sqlite://faqs.db",
            "type": "faq",
            "id": faq_id,
            "question": question,
            "answer": answer,
            "protocol": "all",
            "verified": True,
            "source_weight": 1.2,
        },
    )


@pytest.fixture
def faq_service() -> MagicMock:
    service = MagicMock()
    service.load_faq_data.return_value = [
        _faq_doc("faq-1", "How do I trade?", "Use the trade wizard."),
        _faq_doc("faq-2", "What is a mediator?", "A dispute helper."),
    ]
    return service


@pytest.fixture
def rag_service(test_settings, faq_service) -> SimplifiedRAGService:
    service = SimplifiedRAGService(settings=test_settings, faq_service=faq_service)
    service.index_manager = MagicMock()
    cast(Any, service).embeddings = MagicMock()
    return service


async def _drain_background_tasks(service: SimplifiedRAGService) -> None:
    while service._background_tasks:
        await asyncio.gather(*list(service._background_tasks))


class TestIncrementalFAQUpdate:
    @pytest.mark.asyncio
    async def test_add_upserts_faq_points_without_rebuild(
        self, rag_service, faq_service
    ):
        rag_service._handle_faq_update(False, "add", "faq-1", {"question": "How"})
        await _drain_background_tasks(rag_service)

        rag_service.index_manager.upsert_faq_documents.assert_called_once()
        kwargs = rag_service.index_manager.upsert_faq_documents.call_args.kwargs
        assert kwargs["faq_id"] == "faq-1"
        assert kwargs["embeddings"] is rag_service.embeddings
        docs = kwargs["documents"]
        assert docs, "expected FAQ documents to be upserted"
        assert all(doc.metadata["id"] == "faq-1" for doc in docs)
        assert any("How do I trade?" in doc.page_content for doc in docs)

        # No full rebuild involved and no pending manual-rebuild flag.
        rag_service.index_manager.rebuild_index.assert_not_called()
        assert rag_service.state_manager.needs_rebuild() is False

    @pytest.mark.asyncio
    async def test_documents_reuse_faq_loader_output(self, rag_service, faq_service):
        rag_service._handle_faq_update(False, "add", "faq-2", None)
        await _drain_background_tasks(rag_service)

        faq_service.load_faq_data.assert_called_once()
        docs = rag_service.index_manager.upsert_faq_documents.call_args.kwargs[
            "documents"
        ]
        # Only the changed FAQ is upserted, not the whole corpus.
        assert {doc.metadata["id"] for doc in docs} == {"faq-2"}

    @pytest.mark.asyncio
    async def test_delete_removes_faq_points(self, rag_service, faq_service):
        # FAQ already removed from the database.
        faq_service.load_faq_data.return_value = [
            _faq_doc("faq-2", "What is a mediator?", "A dispute helper.")
        ]

        rag_service._handle_faq_update(False, "delete", "faq-1", None)
        await _drain_background_tasks(rag_service)

        rag_service.index_manager.delete_faq_points.assert_called_once_with("faq-1")
        rag_service.index_manager.upsert_faq_documents.assert_not_called()
        assert rag_service.state_manager.needs_rebuild() is False

    @pytest.mark.asyncio
    async def test_update_to_unverified_faq_removes_points(
        self, rag_service, faq_service
    ):
        # FAQ still exists but is no longer part of the verified corpus.
        faq_service.load_faq_data.return_value = [
            _faq_doc("faq-2", "What is a mediator?", "A dispute helper.")
        ]

        rag_service._handle_faq_update(False, "update", "faq-1", None)
        await _drain_background_tasks(rag_service)

        rag_service.index_manager.delete_faq_points.assert_called_once_with("faq-1")
        rag_service.index_manager.upsert_faq_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_incremental_failure_falls_back_to_mark_change(self, rag_service):
        rag_service.index_manager.upsert_faq_documents.side_effect = RuntimeError(
            "qdrant unavailable"
        )

        rag_service._handle_faq_update(False, "add", "faq-1", {"question": "How"})
        await _drain_background_tasks(rag_service)

        assert rag_service.state_manager.needs_rebuild() is True
        pending = rag_service.state_manager.get_status()["pending_changes"]
        assert [change["item_id"] for change in pending] == ["faq-1"]

    @pytest.mark.asyncio
    async def test_same_faq_incremental_updates_are_serialized(self, rag_service):
        active = 0
        max_active = 0
        calls = 0
        guard = threading.Lock()

        def slow_sync(faq_id: str) -> None:
            nonlocal active, max_active, calls
            with guard:
                active += 1
                calls += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with guard:
                active -= 1

        rag_service._sync_faq_in_index = slow_sync

        rag_service._handle_faq_update(False, "update", "faq-1", None)
        rag_service._handle_faq_update(False, "delete", "faq-1", None)
        await _drain_background_tasks(rag_service)

        assert calls == 2
        assert max_active == 1

    @pytest.mark.asyncio
    async def test_incremental_update_waits_for_full_rebuild(self, rag_service):
        sync_started = asyncio.Event()

        def record_sync(_faq_id: str) -> None:
            sync_started.set()

        rag_service._sync_faq_in_index = record_sync
        await rag_service._setup_lock.acquire()
        update_task = asyncio.create_task(
            rag_service.faq_index_sync.apply_incremental_update("update", "faq-1", None)
        )

        try:
            await asyncio.sleep(0)
            assert not sync_started.is_set()
        finally:
            rag_service._setup_lock.release()

        await update_task
        assert sync_started.is_set()

    @pytest.mark.asyncio
    async def test_embeddings_initialization_is_serialized(self, rag_service):
        init_calls = 0
        init_active = 0
        max_init_active = 0
        guard = threading.Lock()
        cast(Any, rag_service).embeddings = None

        def initialize_embeddings() -> None:
            nonlocal init_calls, init_active, max_init_active
            with guard:
                init_calls += 1
                init_active += 1
                max_init_active = max(max_init_active, init_active)
            time.sleep(0.02)
            cast(Any, rag_service).embeddings = MagicMock()
            with guard:
                init_active -= 1

        rag_service.initialize_embeddings = initialize_embeddings
        rag_service._sync_faq_in_index = lambda _faq_id: None

        rag_service._handle_faq_update(False, "update", "faq-1", None)
        rag_service._handle_faq_update(False, "update", "faq-2", None)
        await _drain_background_tasks(rag_service)

        assert init_calls == 1
        assert max_init_active == 1

    @pytest.mark.asyncio
    async def test_bulk_operations_fall_back_to_mark_change(self, rag_service):
        rag_service._handle_faq_update(False, "bulk_delete", "3_faqs", {"count": 3})
        await _drain_background_tasks(rag_service)

        rag_service.index_manager.upsert_faq_documents.assert_not_called()
        rag_service.index_manager.delete_faq_points.assert_not_called()
        assert rag_service.state_manager.needs_rebuild() is True

    def test_without_event_loop_falls_back_to_mark_change(self, rag_service):
        # Called from a plain sync context (no running loop).
        rag_service._handle_faq_update(False, "add", "faq-1", None)

        rag_service.index_manager.upsert_faq_documents.assert_not_called()
        assert rag_service.state_manager.needs_rebuild() is True

    @pytest.mark.asyncio
    async def test_force_rebuild_path_is_unchanged(self, rag_service):
        rag_service.setup = AsyncMock()

        rag_service._handle_faq_update(True, "add", "faq-1", None)
        await _drain_background_tasks(rag_service)

        rag_service.setup.assert_awaited_once_with(force_rebuild=True)
        rag_service.index_manager.upsert_faq_documents.assert_not_called()

    def test_force_rebuild_without_event_loop_marks_change(self, rag_service):
        rag_service.setup = AsyncMock()

        rag_service._handle_faq_update(True, "add", "faq-1", {"question": "How"})

        rag_service.setup.assert_called_once_with(force_rebuild=True)
        assert rag_service.setup.await_count == 0
        assert rag_service._background_tasks == set()
        assert rag_service.state_manager.needs_rebuild() is True
