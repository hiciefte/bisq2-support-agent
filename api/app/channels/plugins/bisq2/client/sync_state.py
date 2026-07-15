"""Bisq sync state management with persistent storage.

This module provides state tracking for Bisq 2 API synchronization,
including last sync timestamp and processed message deduplication.
"""

import json
import logging
import os
import tempfile
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Deque, Dict, Optional, Set

logger = logging.getLogger(__name__)


class BisqSyncStateManager:
    """Manages synchronization state for Bisq 2 API data fetching.

    Provides:
    - Last sync timestamp tracking for incremental fetches
    - Processed message ID tracking for deduplication
    - Atomic file persistence with crash recovery

    Attributes:
        state_file: Path to JSON state persistence file
        last_sync_timestamp: Timestamp of last successful sync
        processed_message_ids: Set of already processed message IDs
        max_processed_ids: Maximum number of processed IDs to retain (prevents unbounded growth)
    """

    MAX_PROCESSED_IDS = 10000  # Keep only last 10K IDs

    def __init__(
        self,
        state_file: str = "/data/bisq_sync_state.json",
        retention_days: int = 30,
    ):
        """Initialize state manager with persistence file.

        Args:
            state_file: Path to JSON file for state persistence
        """
        self.state_file = Path(state_file)
        self.retention_days = max(1, int(retention_days))
        self._state_lock = threading.RLock()
        self.last_sync_timestamp: Optional[datetime] = None
        self.processed_message_ids: Set[str] = set()
        self._processed_message_order: Deque[str] = deque()
        self._processed_at: Dict[str, datetime] = {}
        self._pending_expired_ids: Set[str] = set()
        self._prune_listeners: list[Callable[[set[str]], None]] = []
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk if exists.

        Handles corrupted or missing files gracefully by starting fresh.
        """
        with self._state_lock:
            if not self.state_file.exists():
                logger.debug(f"State file not found: {self.state_file}")
                return

            try:
                with self.state_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("Sync state root must be a JSON object")

                # Restore timestamp
                last_sync = data.get("last_sync_timestamp")
                if last_sync:
                    self.last_sync_timestamp = datetime.fromisoformat(last_sync)

                # Restore processed IDs (limit to most recent to prevent unbounded growth)
                processed_list = data.get("processed_message_ids", [])
                if not isinstance(processed_list, list):
                    processed_list = []
                ordered_ids = list(
                    dict.fromkeys(
                        str(message_id)
                        for message_id in processed_list
                        if str(message_id).strip()
                    )
                )
                raw_timestamps = data.get("processed_message_timestamps", {})
                if not isinstance(raw_timestamps, dict):
                    raw_timestamps = {}
                parsed_timestamps = {
                    message_id: self._parse_processed_at(raw_timestamps.get(message_id))
                    for message_id in ordered_ids
                }
                valid_ids = [
                    message_id
                    for message_id in ordered_ids
                    if parsed_timestamps[message_id] is not None
                ]
                retained_ids = valid_ids[-self.MAX_PROCESSED_IDS :]
                self._pending_expired_ids = set(ordered_ids) - set(retained_ids)
                self._processed_message_order = deque(retained_ids)
                self.processed_message_ids = set(retained_ids)
                self._processed_at = {
                    message_id: parsed_timestamp
                    for message_id in retained_ids
                    if (parsed_timestamp := parsed_timestamps[message_id]) is not None
                }

                logger.info(
                    f"Loaded sync state: timestamp={self.last_sync_timestamp}, "
                    f"processed_ids={len(self.processed_message_ids)}"
                )

            except (OSError, UnicodeError, ValueError, TypeError):
                self.last_sync_timestamp = None
                self.processed_message_ids = set()
                self._processed_message_order = deque()
                self._processed_at = {}
                self._pending_expired_ids = set()
                logger.exception(f"Failed to load sync state from {self.state_file}")

    @staticmethod
    def _parse_processed_at(value: object) -> datetime | None:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return (
                    parsed.replace(tzinfo=UTC)
                    if parsed.tzinfo is None
                    else parsed.astimezone(UTC)
                )
            except ValueError:
                pass
        return None

    def save_state(self, *, prune_expired: bool = True) -> None:
        """Atomically save state to disk.

        Uses temp file + rename pattern to prevent corruption if
        process crashes during write.

        Raises:
            Exception: If state save fails
        """
        temp_file: Optional[Path] = None
        with self._state_lock:
            # Serialize snapshot + replace so an older snapshot cannot win after a
            # newer one. A unique temp file also avoids cross-instance collisions.
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._reconcile_and_prune_processed_ids()
                if prune_expired:
                    self._prune_expired(datetime.now(UTC))
                processed_list = list(self._processed_message_order)
                data = {
                    "last_sync_timestamp": (
                        self.last_sync_timestamp.isoformat()
                        if self.last_sync_timestamp
                        else None
                    ),
                    "processed_message_ids": processed_list,
                    "processed_message_timestamps": {
                        message_id: self._processed_at[message_id].isoformat()
                        for message_id in processed_list
                    },
                }

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.state_file.parent,
                    prefix=f".{self.state_file.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temp_file = Path(handle.name)
                    json.dump(data, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())

                temp_file.replace(self.state_file)
                self._pending_expired_ids.clear()

                logger.info(
                    f"Saved sync state: timestamp={self.last_sync_timestamp}, "
                    f"processed_ids={len(self.processed_message_ids)}"
                )

            except Exception:
                logger.exception(f"Failed to save sync state to {self.state_file}")
                if temp_file is not None and temp_file.exists():
                    temp_file.unlink()
                raise

    def is_processed(self, message_id: str) -> bool:
        """Check if a message has already been processed.

        Args:
            message_id: The Bisq message ID to check

        Returns:
            True if already processed, False otherwise
        """
        with self._state_lock:
            return message_id in self.processed_message_ids

    def register_prune_listener(self, listener: Callable[[set[str]], None]) -> None:
        """Register a callback that evicts IDs from a live consumer cache."""
        with self._state_lock:
            if listener not in self._prune_listeners:
                self._prune_listeners.append(listener)

    def get_processed_ids_in_order(self) -> list[str]:
        """Return retained message IDs from oldest to newest."""
        with self._state_lock:
            return list(self._processed_message_order)

    def mark_processed(
        self,
        message_id: str,
        *,
        processed_at: datetime | None = None,
    ) -> None:
        """Mark a message as processed.

        Args:
            message_id: The Bisq message ID to mark as processed
        """
        with self._state_lock:
            if message_id in self.processed_message_ids:
                return
            self.processed_message_ids.add(message_id)
            self._processed_message_order.append(message_id)
            timestamp = processed_at or datetime.now(UTC)
            self._processed_at[message_id] = (
                timestamp.replace(tzinfo=UTC)
                if timestamp.tzinfo is None
                else timestamp.astimezone(UTC)
            )
            self._prune_processed_ids()

    def _reconcile_and_prune_processed_ids(self) -> None:
        """Keep legacy direct set mutations deterministic and bounded."""
        ordered = [
            message_id
            for message_id in self._processed_message_order
            if message_id in self.processed_message_ids
        ]
        ordered_set = set(ordered)
        ordered.extend(sorted(self.processed_message_ids - ordered_set))
        self._processed_message_order = deque(ordered)
        now = datetime.now(UTC)
        for message_id in ordered:
            self._processed_at.setdefault(message_id, now)
        self._prune_processed_ids()

    def _prune_processed_ids(self) -> None:
        while len(self._processed_message_order) > self.MAX_PROCESSED_IDS:
            oldest = self._processed_message_order.popleft()
            self.processed_message_ids.discard(oldest)
            self._processed_at.pop(oldest, None)

    def _prune_expired(self, now: datetime) -> int:
        cutoff = now.astimezone(UTC) - timedelta(days=self.retention_days)
        expired = [
            message_id
            for message_id, processed_at in self._processed_at.items()
            if processed_at < cutoff
        ]
        if not expired:
            return 0
        expired_set = set(expired)
        self._processed_message_order = deque(
            message_id
            for message_id in self._processed_message_order
            if message_id not in expired_set
        )
        self.processed_message_ids.difference_update(expired_set)
        for message_id in expired_set:
            self._processed_at.pop(message_id, None)
        return len(expired_set)

    def prune_before(self, cutoff: datetime, *, dry_run: bool = False) -> int:
        """Remove processed IDs older than a UTC cutoff."""
        effective_cutoff = (
            cutoff.replace(tzinfo=UTC)
            if cutoff.tzinfo is None
            else cutoff.astimezone(UTC)
        )
        with self._state_lock:
            expired = self._pending_expired_ids | {
                message_id
                for message_id, processed_at in self._processed_at.items()
                if processed_at < effective_cutoff
            }
            if dry_run or not expired:
                return len(expired)
            self._processed_message_order = deque(
                message_id
                for message_id in self._processed_message_order
                if message_id not in expired
            )
            self.processed_message_ids.difference_update(expired)
            for message_id in expired:
                self._processed_at.pop(message_id, None)
            self.save_state(prune_expired=False)
            listeners = tuple(self._prune_listeners)
        for listener in listeners:
            listener(set(expired))
        return len(expired)

    def oldest_processed_at(self) -> datetime | None:
        """Return the oldest retained processed-ID timestamp."""
        with self._state_lock:
            return min(self._processed_at.values(), default=None)

    def update_last_sync(self, timestamp: datetime) -> None:
        """Update the last sync timestamp.

        Args:
            timestamp: Timestamp of the completed sync
        """
        with self._state_lock:
            self.last_sync_timestamp = timestamp
