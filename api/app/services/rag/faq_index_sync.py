"""Incremental FAQ index synchronization for the RAG service."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)


class AsyncSharedExclusiveGate:
    """Coordinate concurrent readers with a writer-preferred exclusive section."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_readers = 0
        self._writer_active = False
        self._waiting_writers = 0

    @property
    def waiting_writers(self) -> int:
        """Return the number of writers waiting to enter the exclusive section."""
        return self._waiting_writers

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        """Enter a shared section while giving queued writers priority."""
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._writer_active and self._waiting_writers == 0
            )
            self._active_readers += 1

        try:
            yield
        finally:
            async with self._condition:
                self._active_readers -= 1
                if self._active_readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        """Enter an exclusive section after all active readers have left."""
        acquired = False
        async with self._condition:
            self._waiting_writers += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._writer_active and self._active_readers == 0
                )
                self._writer_active = True
                acquired = True
            finally:
                self._waiting_writers -= 1
                if not acquired:
                    self._condition.notify_all()

        try:
            yield
        finally:
            async with self._condition:
                self._writer_active = False
                self._condition.notify_all()


class FAQIndexSyncManager:
    """Apply FAQ changes to the live Qdrant index or mark rebuilds."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self._mutation_gate = AsyncSharedExclusiveGate()

    @asynccontextmanager
    async def rebuild_guard(self) -> AsyncIterator[None]:
        """Exclude incremental updates while a rebuild snapshots and swaps data."""
        async with self._mutation_gate.exclusive():
            yield

    def handle_update(
        self,
        rebuild: bool,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Handle FAQ updates with incremental indexing or full rebuild."""
        if rebuild:
            logger.info("Immediate index rebuild requested by FAQ update")
            rebuild_coro = self.service.setup(force_rebuild=True)
            try:
                task = asyncio.create_task(rebuild_coro)
            except RuntimeError:
                rebuild_coro.close()
                logger.warning(
                    "No running event loop for FAQ-triggered rebuild "
                    "(%s on %s); marking change for rebuild",
                    operation,
                    faq_id,
                )
                self.mark_change(operation, faq_id, metadata)
            else:
                self.service._background_tasks.add(task)

                def _on_done(done_task: asyncio.Task[Any]) -> None:
                    self.service._background_tasks.discard(done_task)
                    try:
                        done_task.result()
                    except Exception:
                        logger.exception("FAQ-triggered rebuild task failed")

                task.add_done_callback(_on_done)
            return

        if not self.can_apply_incremental_update(operation, faq_id):
            self.mark_change(operation, faq_id, metadata)
            return

        update_coro = self.apply_incremental_update(operation, faq_id, metadata)
        try:
            task = asyncio.create_task(update_coro)
        except RuntimeError:
            update_coro.close()
            logger.warning(
                "No running event loop for incremental index update "
                "(%s on %s); marking change for rebuild",
                operation,
                faq_id,
            )
            self.mark_change(operation, faq_id, metadata)
        else:
            self.service._background_tasks.add(task)
            task.add_done_callback(self.service._background_tasks.discard)

    async def ensure_embeddings_initialized(self) -> None:
        """Initialize embeddings once across concurrent incremental workers."""
        if self.service.embeddings is not None:
            return
        async with self.service._embeddings_init_lock:
            if self.service.embeddings is None:
                await asyncio.to_thread(self.service.initialize_embeddings)

    async def acquire_lock(self, faq_id: str) -> asyncio.Lock:
        async with self.service._faq_index_locks_guard:
            lock = self.service._faq_index_locks.get(faq_id)
            if lock is None:
                lock = asyncio.Lock()
                self.service._faq_index_locks[faq_id] = lock
            self.service._faq_index_lock_refs[faq_id] = (
                self.service._faq_index_lock_refs.get(faq_id, 0) + 1
            )
        try:
            await lock.acquire()
        except BaseException:
            await self._drop_lock_reference(faq_id, lock)
            raise
        return lock

    async def release_lock(self, faq_id: str, lock: asyncio.Lock) -> None:
        lock.release()
        await self._drop_lock_reference(faq_id, lock)

    async def _drop_lock_reference(self, faq_id: str, lock: asyncio.Lock) -> None:
        """Drop one waiter/holder reference and remove an unused per-ID lock."""
        async with self.service._faq_index_locks_guard:
            ref_count = self.service._faq_index_lock_refs.get(faq_id, 1) - 1
            if ref_count <= 0:
                if self.service._faq_index_locks.get(faq_id) is lock:
                    self.service._faq_index_locks.pop(faq_id, None)
                self.service._faq_index_lock_refs.pop(faq_id, None)
            else:
                self.service._faq_index_lock_refs[faq_id] = ref_count

    def can_apply_incremental_update(self, operation: str, faq_id: str) -> bool:
        """Return True when a change can be applied point-by-point."""
        return (
            operation in ("add", "update", "delete")
            and bool(faq_id)
            and self.service.faq_service is not None
        )

    def mark_change(
        self,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a FAQ change that requires a manual index rebuild."""
        logger.debug("Marking FAQ change for rebuild: %s on %s", operation, faq_id)
        self.service.state_manager.mark_change(
            operation=operation or "unknown",
            item_id=faq_id or "unknown",
            metadata=metadata,
        )

    async def apply_incremental_update(
        self,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Apply a single FAQ change to the live Qdrant index off-loop."""
        lock: asyncio.Lock | None = None
        try:
            # A full rebuild snapshots FAQ data before atomically swapping its alias.
            # Keep point updates outside that snapshot/swap window so an update cannot
            # land on the retired collection and disappear from the new active index.
            # Shared admission still lets unrelated FAQ IDs update concurrently.
            async with self._mutation_gate.shared():
                lock = await self.acquire_lock(faq_id)
                try:
                    if operation != "delete":
                        await self.ensure_embeddings_initialized()
                    worker = asyncio.create_task(
                        asyncio.to_thread(self.service._sync_faq_in_index, faq_id)
                    )
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        # Cancelling the await does not stop a thread. Keep both the
                        # shared gate and per-ID lock until the mutation really ends,
                        # otherwise a rebuild could overlap the orphaned write.
                        try:
                            await worker
                        except Exception:
                            logger.exception(
                                "Incremental index worker failed while cancellation "
                                "was pending for FAQ %s (%s)",
                                faq_id,
                                operation,
                            )
                            self.mark_change(operation, faq_id, metadata)
                        raise
                finally:
                    await self.release_lock(faq_id, lock)
            logger.info("Applied incremental index update: %s on %s", operation, faq_id)
        except Exception:
            logger.exception(
                "Incremental index update failed for FAQ %s (%s); "
                "marking change for manual rebuild",
                faq_id,
                operation,
            )
            self.mark_change(operation, faq_id, metadata)

    def sync_faq_in_index(self, faq_id: str) -> None:
        """Blocking worker: reconcile one FAQ's points in the Qdrant index."""
        faq_docs = [
            doc
            for doc in self.service.faq_service.load_faq_data()
            if (doc.metadata or {}).get("id") == faq_id
        ]

        if not faq_docs:
            self.service.index_manager.delete_faq_points(faq_id)
            return

        splits = self.service.document_processor.split_documents(faq_docs)
        if self.service.embeddings is None:
            raise RuntimeError("Embeddings must be initialized before FAQ index sync")
        self.service.index_manager.upsert_faq_documents(
            faq_id=faq_id,
            documents=splits,
            embeddings=self.service.embeddings,
        )
