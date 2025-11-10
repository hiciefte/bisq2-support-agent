"""
Vector store state tracking and manual rebuild coordination.
"""

import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class VectorStoreStateManager:
    """
    Tracks vector store synchronization state with source data.

    Responsibilities:
    - Track when vector store is out of sync with FAQ data
    - Record pending changes for UI display
    - Coordinate manual rebuild operations
    - Provide status information for API endpoints
    """

    def __init__(self):
        """Initialize state manager with clean state."""
        self._needs_rebuild: bool = False
        self._last_rebuild_time: Optional[float] = None
        self._pending_changes: List[Dict[str, Any]] = []
        self._rebuild_in_progress: bool = False

    def mark_change(
        self, operation: str, faq_id: str, metadata: Optional[Dict] = None
    ) -> None:
        """
        Record a change that requires vector store rebuild.

        Args:
            operation: Type of operation (add, update, delete)
            faq_id: ID of the FAQ that changed
            metadata: Optional additional context (question text, category, etc.)
        """
        self._needs_rebuild = True

        change_record = {
            "operation": operation,
            "faq_id": faq_id,
            "timestamp": time.time(),
            "timestamp_iso": datetime.utcnow().isoformat(),
        }

        if metadata:
            change_record["metadata"] = metadata

        self._pending_changes.append(change_record)

        logger.info(
            f"Marked change for rebuild: {operation} on FAQ {faq_id}. "
            f"Total pending: {len(self._pending_changes)}"
        )

    def needs_rebuild(self) -> bool:
        """Check if vector store needs rebuilding."""
        return self._needs_rebuild and not self._rebuild_in_progress

    def is_rebuilding(self) -> bool:
        """Check if rebuild is currently in progress."""
        return self._rebuild_in_progress

    def get_status(self) -> Dict[str, Any]:
        """
        Get detailed rebuild status for API/UI consumption.

        Returns:
            Dictionary with rebuild status, pending changes, and timestamps
        """
        return {
            "needs_rebuild": self._needs_rebuild,
            "rebuild_in_progress": self._rebuild_in_progress,
            "pending_changes_count": len(self._pending_changes),
            "last_rebuild_time": self._last_rebuild_time,
            "last_rebuild_iso": (
                datetime.fromtimestamp(self._last_rebuild_time).isoformat()
                if self._last_rebuild_time
                else None
            ),
            "pending_changes": self._pending_changes,
        }

    def get_summary_status(self) -> Dict[str, Any]:
        """
        Get lightweight status for frequent polling.

        Returns:
            Minimal status dictionary (excludes change details)
        """
        return {
            "needs_rebuild": self._needs_rebuild,
            "rebuild_in_progress": self._rebuild_in_progress,
            "pending_changes_count": len(self._pending_changes),
            "last_rebuild_time": self._last_rebuild_time,
        }

    async def execute_rebuild(self, rebuild_callback: Callable) -> Dict[str, Any]:
        """
        Execute vector store rebuild and reset state.

        Args:
            rebuild_callback: Async function that performs the actual rebuild

        Returns:
            Dictionary with rebuild results (success, duration, changes applied)
        """
        if self._rebuild_in_progress:
            return {
                "success": False,
                "error": "Rebuild already in progress",
            }

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
                f"Starting manual vector store rebuild ({initial_changes_count} changes)"
            )

            # Execute the actual rebuild
            await rebuild_callback()

            rebuild_duration = time.time() - start_time

            # Reset state on success, but preserve changes added mid-rebuild
            self._last_rebuild_time = time.time()
            if len(self._pending_changes) > initial_changes_count:
                # New changes arrived during rebuild - keep them
                self._pending_changes = self._pending_changes[initial_changes_count:]
                self._needs_rebuild = True
            else:
                # No new changes - clear everything
                self._pending_changes = []
                self._needs_rebuild = False

            logger.info(
                f"Vector store rebuild completed successfully in {rebuild_duration:.2f}s "
                f"({initial_changes_count} changes applied)"
            )

            result = {
                "success": True,
                "rebuild_time": rebuild_duration,
                "changes_applied": initial_changes_count,
                "timestamp": self._last_rebuild_time,
            }
            if self._needs_rebuild:
                result["pending_changes_count"] = len(self._pending_changes)
            return result

        except Exception as e:
            logger.error(f"Vector store rebuild failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "changes_pending": len(self._pending_changes),
            }

        finally:
            self._rebuild_in_progress = False

    def reset(self) -> None:
        """Reset state (for testing or emergency recovery)."""
        logger.warning("Resetting vector store state manager")
        self._needs_rebuild = False
        self._pending_changes = []
        self._rebuild_in_progress = False
