"""Matrix polling state persistence with atomic writes.

Manages pagination tokens and processed message IDs to enable
stateful polling across service restarts.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)


class PollingStateManager:
    """Manages Matrix polling state persistence.

    Provides atomic file writes to prevent corruption and secure
    permissions to protect pagination tokens.

    Attributes:
        state_file: Path to state persistence file
        since_token: Current pagination token
        processed_ids: Set of processed message event IDs
    """

    def __init__(self, state_file: str = "/data/matrix_polling_state.json"):
        """Initialize polling state manager.

        Args:
            state_file: Path to state persistence file
        """
        self.state_file = Path(state_file)
        self.since_token: Optional[str] = None
        self.processed_ids: Set[str] = set()

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

            # Load pagination token
            self.since_token = state.get("since_token")

            # Load processed IDs (limited to most recent to prevent unbounded growth)
            processed_list = state.get("processed_ids", [])
            # Keep only last 10,000 IDs in memory
            self.processed_ids = set(processed_list[-10000:])

            last_poll = state.get("last_poll", "unknown")
            logger.info(
                f"Polling state restored: since_token={self.since_token[:20] if self.since_token else None}..., "
                f"processed_ids={len(self.processed_ids)}, last_poll={last_poll}"
            )

            return True

        except (IOError, json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to load polling state from {self.state_file}: {e}")
            return False

    def save_state(self) -> None:
        """Atomically save polling state to disk.

        Uses atomic write pattern (temp file + rename) with secure
        permissions to prevent corruption and unauthorized access.

        Raises:
            Exception: If state save fails
        """
        state_data = {
            "since_token": self.since_token,
            "processed_ids": list(self.processed_ids)[-10000:],  # Keep last 10K only
            "last_poll": datetime.now(timezone.utc).isoformat(),
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
        self.since_token = token
        self.save_state()

    def mark_processed(self, event_id: str) -> None:
        """Mark message as processed.

        Args:
            event_id: Matrix event ID to mark as processed
        """
        self.processed_ids.add(event_id)
        # Don't save on every mark - save in batch after polling

    def is_processed(self, event_id: str) -> bool:
        """Check if message has been processed.

        Args:
            event_id: Matrix event ID to check

        Returns:
            True if already processed, False otherwise
        """
        return event_id in self.processed_ids

    def save_batch_processed(self) -> None:
        """Save state after batch processing messages."""
        self.save_state()
