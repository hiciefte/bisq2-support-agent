"""Matrix polling state persistence with atomic writes.

Manages pagination tokens and processed message IDs to enable
stateful polling across service restarts.
"""

import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class PollingStateManager:
    """Manages Matrix polling state persistence.

    Provides atomic file writes to prevent corruption and secure
    permissions to protect pagination tokens.

    Attributes:
        state_file: Path to state persistence file
        since_token: Current pagination token (deprecated, use per-room tokens)
        room_tokens: Per-room pagination tokens
        processed_ids: Set of processed message event IDs
    """

    def __init__(
        self,
        state_file: str = "/data/matrix_polling_state.json",
        retention_days: int = 30,
    ):
        """Initialize polling state manager.

        Args:
            state_file: Path to state persistence file
        """
        self.state_file = Path(state_file)
        self.retention_days = max(1, int(retention_days))
        self.since_token: Optional[str] = None  # Kept for backward compatibility
        self.room_tokens: Dict[str, str] = {}  # Per-room pagination tokens
        self.processed_ids: Set[str] = set()
        self._processed_at: Dict[str, datetime] = {}
        self._pending_expired_ids: Set[str] = set()
        self.last_poll: Optional[datetime] = None
        self._state_lock = threading.RLock()

        # Load existing state if available
        self._load_state()

    def _load_state(self) -> bool:
        """Load polling state from disk if exists.

        Returns:
            True if state loaded successfully, False otherwise
        """
        if not self.state_file.exists():
            logger.debug(f"Polling state file not found: {self.state_file}")
            return False

        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)

            if not isinstance(state, dict):
                raise ValueError("Polling state root must be an object")

            # Load legacy pagination token (for backward compatibility)
            self.since_token = state.get("since_token")

            # Load per-room tokens
            self.room_tokens = state.get("room_tokens", {})

            # Load processed IDs (limited to most recent to prevent unbounded growth)
            processed_list = state.get("processed_ids", [])
            if not isinstance(processed_list, list):
                processed_list = []
            ordered_ids = list(
                dict.fromkeys(
                    str(event_id)
                    for event_id in processed_list
                    if str(event_id).strip()
                )
            )

            raw_timestamps = state.get("processed_id_timestamps", {})
            if not isinstance(raw_timestamps, dict):
                raw_timestamps = {}
            parsed_timestamps = {
                event_id: self._parse_optional_timestamp(raw_timestamps.get(event_id))
                for event_id in ordered_ids
            }
            valid_ids = [
                event_id
                for event_id in ordered_ids
                if parsed_timestamps[event_id] is not None
            ]
            retained_ids = valid_ids[-10000:]
            self._pending_expired_ids = set(ordered_ids) - set(retained_ids)
            self.processed_ids = set(retained_ids)
            self._processed_at = {
                event_id: parsed_timestamp
                for event_id in retained_ids
                if (parsed_timestamp := parsed_timestamps[event_id]) is not None
            }

            last_poll = state.get("last_poll", "unknown")
            self.last_poll = self._parse_optional_timestamp(last_poll)
            logger.info(
                f"Polling state restored: rooms={len(self.room_tokens)}, "
                f"processed_ids={len(self.processed_ids)}, last_poll={last_poll}"
            )

            return True

        except (IOError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(f"Failed to load polling state from {self.state_file}: {e}")
            return False

    @staticmethod
    def _parse_optional_timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or not value or value == "unknown":
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )

    def save_state(self, *, prune_expired: bool = True) -> None:
        """Serialize one in-memory snapshot under the manager lock."""
        with self._state_lock:
            self._save_state_locked(prune_expired=prune_expired)

    def _save_state_locked(self, *, prune_expired: bool) -> None:
        """Atomically save polling state to disk.

        Uses atomic write pattern (temp file + rename) with secure
        permissions to prevent corruption and unauthorized access.

        Raises:
            Exception: If state save fails
        """
        now = datetime.now(UTC)
        if prune_expired:
            self._prune_expired(now)
        self.last_poll = now
        retained_ids = sorted(
            self.processed_ids,
            key=lambda event_id: (self._processed_at[event_id], event_id),
        )[-10000:]
        retained_set = set(retained_ids)
        self.processed_ids = retained_set
        self._processed_at = {
            event_id: self._processed_at[event_id] for event_id in retained_ids
        }
        state_data = {
            "since_token": self.since_token,  # Kept for backward compatibility
            "room_tokens": self.room_tokens,
            "processed_ids": retained_ids,
            "processed_id_timestamps": {
                event_id: self._processed_at[event_id].isoformat()
                for event_id in retained_ids
            },
            "last_poll": now.isoformat(),
        }

        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Set secure umask before creating temp file
        old_umask = os.umask(0o077)
        try:
            # Atomic write: write to temp file, then rename
            fd, temp_path = tempfile.mkstemp(
                dir=self.state_file.parent,
                prefix=".tmp_polling_state_",
                suffix=".json",
            )

            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(state_data, f, indent=2)

                # Atomic rename (prevents corruption if crash during write)
                os.rename(temp_path, self.state_file)

                # Defensive: Explicitly set 0o600 permissions
                # (temp file already has these from umask 0o077, but this ensures
                # correctness even if umask handling changes in the future)
                os.chmod(self.state_file, 0o600)
                self._pending_expired_ids.clear()

                logger.debug(
                    f"Polling state saved to {self.state_file}: "
                    f"since_token={self.since_token[:20] if self.since_token else None}..., "
                    f"processed_ids={len(self.processed_ids)}"
                )

            except Exception:
                # Clean up temp file on error
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        finally:
            # Restore original umask
            os.umask(old_umask)

    def update_since_token(self, token: str) -> None:
        """Update pagination token and save state.

        Args:
            token: New pagination token from Matrix API
        """
        with self._state_lock:
            self.since_token = token
            self.save_state()

    def mark_processed(
        self,
        event_id: str,
        *,
        processed_at: datetime | None = None,
    ) -> None:
        """Mark message as processed.

        Args:
            event_id: Matrix event ID to mark as processed
        """
        with self._state_lock:
            self.processed_ids.add(event_id)
            timestamp = processed_at or datetime.now(UTC)
            self._processed_at[event_id] = (
                timestamp.replace(tzinfo=UTC)
                if timestamp.tzinfo is None
                else timestamp.astimezone(UTC)
            )
        # Don't save on every mark - save in batch after polling

    def is_processed(self, event_id: str) -> bool:
        """Check if message has been processed.

        Args:
            event_id: Matrix event ID to check

        Returns:
            True if already processed, False otherwise
        """
        with self._state_lock:
            return event_id in self.processed_ids

    def save_batch_processed(self) -> None:
        """Save state after batch processing messages."""
        self.save_state()

    def get_room_token(self, room_id: str) -> Optional[str]:
        """Get pagination token for a specific room.

        Args:
            room_id: Matrix room ID

        Returns:
            Room-specific token, or None if not set
        """
        with self._state_lock:
            return self.room_tokens.get(room_id)

    def update_room_token(self, room_id: str, token: str) -> None:
        """Update pagination token for a specific room.

        Args:
            room_id: Matrix room ID
            token: New pagination token from Matrix API
        """
        with self._state_lock:
            self.room_tokens[room_id] = token
            # Also update legacy token for backward compatibility
            self.since_token = token
            self.save_state()

    def _prune_expired(self, now: datetime) -> int:
        cutoff = now.astimezone(UTC) - timedelta(days=self.retention_days)
        expired = {
            event_id
            for event_id, processed_at in self._processed_at.items()
            if processed_at < cutoff
        }
        self.processed_ids.difference_update(expired)
        for event_id in expired:
            self._processed_at.pop(event_id, None)
        return len(expired)

    def prune_before(self, cutoff: datetime, *, dry_run: bool = False) -> int:
        """Remove processed IDs before a cutoff while preserving sync cursors."""
        effective_cutoff = (
            cutoff.replace(tzinfo=UTC)
            if cutoff.tzinfo is None
            else cutoff.astimezone(UTC)
        )
        with self._state_lock:
            expired = self._pending_expired_ids | {
                event_id
                for event_id, processed_at in self._processed_at.items()
                if processed_at < effective_cutoff
            }
            deleted = len(expired)
            if dry_run or deleted == 0:
                return deleted
            self.processed_ids.difference_update(expired)
            for event_id in expired:
                self._processed_at.pop(event_id, None)
            self.save_state(prune_expired=False)
            return deleted

    def oldest_processed_at(self) -> datetime | None:
        """Return the oldest retained processed-ID timestamp."""
        with self._state_lock:
            return min(self._processed_at.values(), default=None)
