"""Matrix live polling service for unified training pipeline.

Orchestrates Matrix room polling and LLM-based FAQ extraction, processing
messages through the unified training pipeline for FAQ candidate generation.

Uses UnifiedFAQExtractor for single-pass LLM extraction instead of
pattern-based reply matching.
"""

import logging
import time as time_module
from typing import Any, Dict, List, Optional, Set

try:
    from nio import AsyncClient, RoomMessagesResponse

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    RoomMessagesResponse = None

from app.channels.plugins.matrix.client.polling_state import PollingStateManager
from app.metrics.training_metrics import (
    sync_duration_seconds,
    sync_last_status,
    sync_last_success_timestamp,
    sync_pairs_processed,
    training_errors,
)

logger = logging.getLogger(__name__)


class MatrixSyncService:
    """Orchestrates Matrix room polling and LLM-based FAQ extraction.

    This service:
    - Polls configured Matrix rooms for new messages
    - Uses LLM to identify Q&A pairs from the message stream
    - Processes candidates through the unified training pipeline

    Uses UnifiedFAQExtractor via pipeline_service.extract_faqs_batch() for
    single-pass LLM extraction instead of pattern-based reply matching.

    Attributes:
        settings: Application settings
        pipeline_service: UnifiedPipelineService for processing Q&A pairs
        polling_state: PollingStateManager for tracking sync state
        trusted_staff_ids: Set of trusted staff Matrix IDs
    """

    def __init__(
        self,
        settings: Any,
        pipeline_service: Any,
        polling_state: PollingStateManager,
    ):
        """Initialize Matrix sync service.

        Args:
            settings: Application settings with Matrix configuration
            pipeline_service: UnifiedPipelineService for Q&A processing
            polling_state: PollingStateManager for state tracking
        """
        self.settings = settings
        self.pipeline_service = pipeline_service
        self.polling_state = polling_state

        # Build trusted staff IDs set from settings
        staff_ids = getattr(settings, "TRUSTED_STAFF_IDS", [])
        if isinstance(staff_ids, str):
            staff_ids = [s.strip() for s in staff_ids.split(",") if s.strip()]
        self.trusted_staff_ids: List[str] = list(set(staff_ids))

        # Also add lowercase versions for case-insensitive matching
        self._staff_ids_lower: Set[str] = {s.lower() for s in self.trusted_staff_ids}

        # Matrix client (created lazily)
        self._client: Optional["AsyncClient"] = None
        self._connection_manager: Optional[Any] = None
        self._session_manager: Optional[Any] = None
        self._error_handler: Optional[Any] = None

    @staticmethod
    def _get_sync_rooms(settings: Any) -> List[str]:
        """Resolve Matrix sync rooms from MATRIX_SYNC_ROOMS."""
        rooms = getattr(settings, "MATRIX_SYNC_ROOMS", None)
        if isinstance(rooms, str):
            return [room.strip() for room in rooms.split(",") if room.strip()]
        if isinstance(rooms, list):
            return [
                room.strip() for room in rooms if isinstance(room, str) and room.strip()
            ]
        return []

    @staticmethod
    def _get_sync_session_path(settings: Any) -> str:
        """Resolve Matrix sync session path from MATRIX_SYNC_SESSION_PATH."""
        session_path = getattr(settings, "MATRIX_SYNC_SESSION_PATH", None)
        if isinstance(session_path, str) and session_path.strip():
            return session_path
        return "/data/matrix_session.json"

    @classmethod
    def _get_sync_user(cls, settings: Any) -> str:
        resolved = getattr(settings, "MATRIX_SYNC_USER_RESOLVED", None)
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
        value = getattr(settings, "MATRIX_SYNC_USER", None)
        return value.strip() if isinstance(value, str) else ""

    @classmethod
    def _get_sync_password(cls, settings: Any) -> str:
        resolved = getattr(settings, "MATRIX_SYNC_PASSWORD_RESOLVED", None)
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
        value = getattr(settings, "MATRIX_SYNC_PASSWORD", None)
        return value.strip() if isinstance(value, str) else ""

    def is_configured(self) -> bool:
        """Check if Matrix integration is configured.

        Returns:
            True if Matrix homeserver and rooms are configured
        """
        homeserver_value = getattr(self.settings, "MATRIX_HOMESERVER_URL", "")
        homeserver = (
            homeserver_value.strip() if isinstance(homeserver_value, str) else ""
        )
        rooms = self._get_sync_rooms(self.settings)
        return bool(homeserver) and bool(rooms)

    async def sync_rooms(self) -> int:
        """Poll all configured rooms and process Q&A pairs.

        Returns:
            Number of Q&A pairs successfully processed
        """
        if not self.is_configured():
            logger.debug("Matrix not configured, skipping sync")
            return 0

        if not NIO_AVAILABLE:
            logger.warning("matrix-nio not installed, skipping Matrix sync")
            return 0

        total_processed = 0
        rooms = self._get_sync_rooms(self.settings)
        sync_start_time = time_module.time()

        logger.info(f"Starting Matrix sync for {len(rooms)} room(s)")

        try:
            client = await self._get_client()

            for room_id in rooms:
                try:
                    processed = await self._sync_single_room(client, room_id)
                    total_processed += processed
                except Exception:
                    logger.exception(f"Failed to sync room {room_id}")
                    # Continue with other rooms

            # Save state after all rooms processed
            self.polling_state.save_batch_processed()

            # Record sync success metrics
            sync_last_status.labels(source="matrix").set(1)
            sync_last_success_timestamp.labels(source="matrix").set(time_module.time())
            sync_pairs_processed.labels(source="matrix").inc(total_processed)

            logger.info(f"Matrix sync complete: processed {total_processed} Q&A pairs")
            return total_processed

        except Exception:
            logger.exception("Matrix sync failed")
            training_errors.labels(stage="poll").inc()
            # Record sync failure metric
            sync_last_status.labels(source="matrix").set(0)
            raise

        finally:
            # Always record sync duration
            sync_duration_seconds.labels(source="matrix").observe(
                time_module.time() - sync_start_time
            )

    async def _get_client(self) -> "AsyncClient":
        """Get or create authenticated Matrix client.

        Returns:
            Authenticated AsyncClient instance
        """
        if self._client is not None:
            return self._client

        # Import here to avoid circular imports
        from app.channels.plugins.matrix.client.connection_manager import (
            ConnectionManager,
        )
        from app.channels.plugins.matrix.client.error_handler import ErrorHandler
        from app.channels.plugins.matrix.client.session_manager import SessionManager

        homeserver = self.settings.MATRIX_HOMESERVER_URL
        user_id = self._get_sync_user(self.settings)
        password = self._get_sync_password(self.settings)
        session_path = self._get_sync_session_path(self.settings)

        # Create client
        self._client = AsyncClient(homeserver, user_id)

        # Create session manager
        self._session_manager = SessionManager(
            client=self._client,
            password=password,
            session_file=session_path,
        )

        # Create connection manager
        self._connection_manager = ConnectionManager(
            client=self._client,
            session_manager=self._session_manager,
        )

        # Create error handler for retry logic
        self._error_handler = ErrorHandler(
            session_manager=self._session_manager,
            max_retries=3,
        )

        # Connect
        await self._connection_manager.connect()

        return self._client

    async def _sync_single_room(self, client: "AsyncClient", room_id: str) -> int:
        """Sync a single Matrix room using LLM-based FAQ extraction.

        Args:
            client: Authenticated Matrix client
            room_id: Room ID to sync

        Returns:
            Number of FAQ candidates processed from this room
        """
        logger.debug(f"Syncing room {room_id}")
        processed_count = 0

        # Fetch messages using per-room since_token if available
        since_token = self.polling_state.get_room_token(room_id)

        # Use error handler for retry logic
        response = await self._error_handler.call_with_retry(
            client.room_messages,
            room_id,
            start=since_token,
            limit=100,
            method_name="room_messages",
        )

        if not isinstance(response, RoomMessagesResponse):
            logger.error(f"Failed to fetch messages from {room_id}: {response}")
            return 0

        raw_messages = response.chunk
        logger.debug(f"Fetched {len(raw_messages)} messages from {room_id}")

        if not raw_messages:
            # Update per-room since token even if no messages
            if hasattr(response, "end") and response.end:
                self.polling_state.update_room_token(room_id, response.end)
            return 0

        # Convert matrix-nio events to dict format
        messages = [self._event_to_dict(msg) for msg in raw_messages]

        # Filter out already-processed messages
        new_messages = [
            msg
            for msg in messages
            if not self.polling_state.is_processed(msg.get("event_id", ""))
        ]
        logger.debug(
            f"After deduplication: {len(new_messages)} new messages to process"
        )

        if not new_messages:
            # Update per-room since token even if no new messages
            if hasattr(response, "end") and response.end:
                self.polling_state.update_room_token(room_id, response.end)
            return 0

        # Mark ALL input messages as processed BEFORE sending to LLM
        # This prevents duplicate processing on subsequent polls, regardless
        # of whether the LLM extracts any FAQs from them
        for msg in new_messages:
            event_id = msg.get("event_id", "")
            if event_id:
                self.polling_state.mark_processed(event_id)

        logger.debug(f"Marked {len(new_messages)} input messages as processed")

        # Use LLM-based extraction via pipeline service
        # This sends all messages to UnifiedFAQExtractor for single-pass extraction
        results = await self.pipeline_service.extract_faqs_batch(
            messages=new_messages,
            source="matrix",
            staff_identifiers=self.trusted_staff_ids,
        )

        # Count successful candidates
        for result in results:
            if result.candidate_id is not None:
                processed_count += 1
                logger.info(
                    f"Processed Matrix FAQ -> candidate {result.candidate_id} "
                    f"(routing: {result.routing})"
                )

        # Update per-room since token
        if hasattr(response, "end") and response.end:
            self.polling_state.update_room_token(room_id, response.end)

        return processed_count

    def _event_to_dict(self, event: Any) -> Dict[str, Any]:
        """Convert matrix-nio event to dictionary.

        Args:
            event: matrix-nio event object

        Returns:
            Dictionary representation of the event
        """
        content = {}
        if hasattr(event, "body"):
            content["body"] = event.body
            content["msgtype"] = getattr(event, "msgtype", "m.text")

        # Handle source dict if available (nio stores raw event)
        if hasattr(event, "source"):
            return event.source

        return {
            "event_id": getattr(event, "event_id", ""),
            "type": "m.room.message",
            "sender": getattr(event, "sender", ""),
            "origin_server_ts": getattr(event, "server_timestamp", 0),
            "content": content,
        }

    async def close(self) -> None:
        """Close Matrix client connection."""
        if self._connection_manager:
            await self._connection_manager.disconnect()
        self._client = None


__all__ = [
    "AsyncClient",
    "MatrixSyncService",
    "NIO_AVAILABLE",
    "RoomMessagesResponse",
]
