"""
Index state tracking and manual rebuild coordination.

This is the Qdrant-only successor to the old Chroma "vectorstore" state manager.
It tracks whether the search index is out of sync with source data and
coordinates manual rebuild operations.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class IndexStateManager:
    """Tracks index synchronization state with source data."""

    def __init__(self) -> None:
        self._needs_rebuild: bool = False
        self._last_rebuild_time: Optional[float] = None
        self._pending_changes: List[Dict[str, Any]] = []
        self._rebuild_in_progress: bool = False

    def mark_change(
        self, operation: str, item_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record a change that requires an index rebuild."""
        self._needs_rebuild = True

        change_record: Dict[str, Any] = {
            "operation": operation,
            "item_id": item_id,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            change_record["metadata"] = metadata
        self._pending_changes.append(change_record)

        logger.info(
            f"Marked change for rebuild: {operation} on {item_id}. "
            f"Total pending: {len(self._pending_changes)}"
        )

    def needs_rebuild(self) -> bool:
        """Return True if a rebuild is needed and not currently running."""
        return self._needs_rebuild and not self._rebuild_in_progress

    def is_rebuilding(self) -> bool:
        return self._rebuild_in_progress

    def get_status(self) -> Dict[str, Any]:
        return {
            "needs_rebuild": self._needs_rebuild,
            "rebuild_in_progress": self._rebuild_in_progress,
            "pending_changes_count": len(self._pending_changes),
            "last_rebuild_time": self._last_rebuild_time,
            "last_rebuild_iso": (
                datetime.fromtimestamp(
                    self._last_rebuild_time, tz=timezone.utc
                ).isoformat()
                if self._last_rebuild_time
                else None
            ),
            "pending_changes": self._pending_changes,
        }

    def get_summary_status(self) -> Dict[str, Any]:
        return {
            "needs_rebuild": self._needs_rebuild,
            "rebuild_in_progress": self._rebuild_in_progress,
            "pending_changes_count": len(self._pending_changes),
            "last_rebuild_time": self._last_rebuild_time,
        }

    async def execute_rebuild(
        self, rebuild_callback: Callable[[], Awaitable[Any]]
    ) -> Dict[str, Any]:
        """Run rebuild_callback and update state based on success/failure."""
        if self._rebuild_in_progress:
            return {"success": False, "error": "Rebuild already in progress"}

        if not self._needs_rebuild:
            return {
                "success": True,
                "message": "No rebuild needed",
                "changes_applied": 0,
            }

        self._rebuild_in_progress = True
        start_time = time.time()
        initial_changes_count = len(self._pending_changes)

        try:
            logger.info(
                f"Starting manual index rebuild ({initial_changes_count} changes)"
            )
            await rebuild_callback()

            rebuild_duration = time.time() - start_time
            self._last_rebuild_time = time.time()

            # Preserve any changes recorded mid-rebuild.
            if len(self._pending_changes) > initial_changes_count:
                self._pending_changes = self._pending_changes[initial_changes_count:]
                self._needs_rebuild = True
            else:
                self._pending_changes = []
                self._needs_rebuild = False

            logger.info(
                f"Index rebuild completed successfully in {rebuild_duration:.2f}s "
                f"({initial_changes_count} changes applied)"
            )
            result: Dict[str, Any] = {
                "success": True,
                "rebuild_time": rebuild_duration,
                "changes_applied": initial_changes_count,
                "timestamp": self._last_rebuild_time,
            }
            if self._needs_rebuild:
                result["pending_changes_count"] = len(self._pending_changes)
            return result

        except Exception as e:
            logger.error(f"Index rebuild failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "changes_pending": len(self._pending_changes),
            }
        finally:
            self._rebuild_in_progress = False
