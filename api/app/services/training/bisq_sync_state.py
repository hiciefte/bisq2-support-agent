"""Bisq sync state management with persistent storage.

This module provides state tracking for Bisq 2 API synchronization,
including last sync timestamp and processed message deduplication.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

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

    def __init__(self, state_file: str = "/data/bisq_sync_state.json"):
        """Initialize state manager with persistence file.

        Args:
            state_file: Path to JSON file for state persistence
        """
        self.state_file = Path(state_file)
        self.last_sync_timestamp: Optional[datetime] = None
        self.processed_message_ids: Set[str] = set()
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk if exists.

        Handles corrupted or missing files gracefully by starting fresh.
        """
        if not self.state_file.exists():
            logger.debug(f"State file not found: {self.state_file}")
            return

        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)

            # Restore timestamp
            if "last_sync_timestamp" in data and data["last_sync_timestamp"]:
                self.last_sync_timestamp = datetime.fromisoformat(
                    data["last_sync_timestamp"]
                )

            # Restore processed IDs (limit to most recent to prevent unbounded growth)
            processed_list = data.get("processed_message_ids", [])
            self.processed_message_ids = set(processed_list[-self.MAX_PROCESSED_IDS :])

            logger.info(
                f"Loaded sync state: timestamp={self.last_sync_timestamp}, "
                f"processed_ids={len(self.processed_message_ids)}"
            )

        except (IOError, json.JSONDecodeError) as e:
            logger.exception(f"Failed to load sync state from {self.state_file}: {e}")

    def save_state(self) -> None:
        """Atomically save state to disk.

        Uses temp file + rename pattern to prevent corruption if
        process crashes during write.

        Raises:
            Exception: If state save fails
        """
        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file, then rename
        temp_file = self.state_file.with_suffix(".tmp")
        try:
            # Prune to max size before saving
            processed_list = list(self.processed_message_ids)[-self.MAX_PROCESSED_IDS :]
            data = {
                "last_sync_timestamp": (
                    self.last_sync_timestamp.isoformat()
                    if self.last_sync_timestamp
                    else None
                ),
                "processed_message_ids": processed_list,
            }

            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2)

            # Atomic rename (prevents corruption if crash during write)
            temp_file.replace(self.state_file)

            logger.info(
                f"Saved sync state: timestamp={self.last_sync_timestamp}, "
                f"processed_ids={len(self.processed_message_ids)}"
            )

        except Exception:
            logger.exception(f"Failed to save sync state to {self.state_file}")
            if temp_file.exists():
                temp_file.unlink()
            raise

    def is_processed(self, message_id: str) -> bool:
        """Check if a message has already been processed.

        Args:
            message_id: The Bisq message ID to check

        Returns:
            True if already processed, False otherwise
        """
        return message_id in self.processed_message_ids

    def mark_processed(self, message_id: str) -> None:
        """Mark a message as processed.

        Args:
            message_id: The Bisq message ID to mark as processed
        """
        self.processed_message_ids.add(message_id)

    def update_last_sync(self, timestamp: datetime) -> None:
        """Update the last sync timestamp.

        Args:
            timestamp: Timestamp of the completed sync
        """
        self.last_sync_timestamp = timestamp
