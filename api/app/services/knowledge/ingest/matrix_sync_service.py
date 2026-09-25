"""Matrix history sync service for knowledge intake.

Orchestrates Matrix room polling and LLM-based knowledge extraction, processing
messages through the knowledge intake pipeline for review candidates.

Uses KnowledgeExtractor for single-pass LLM extraction instead of
pattern-based reply matching.
"""

import asyncio
import logging
import time as time_module
from typing import Any, Dict, List, Optional, Set

try:
    from nio import (
        AsyncClient,
        MessageDirection,
        RoomContextResponse,
        RoomMessagesResponse,
    )

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    MessageDirection = None
    RoomContextResponse = None
    RoomMessagesResponse = None

from app.channels.plugins.matrix.client.polling_state import PollingStateManager
from app.metrics.training_metrics import (
    sync_duration_seconds,
    sync_last_status,
    sync_last_success_timestamp,
    sync_pairs_processed,
    training_errors,
)
from app.services.knowledge.knowledge_extractor import is_matrix_text_message

logger = logging.getLogger(__name__)
MAX_BOUNDARY_CONTEXT_READS = 10


class IncompleteKnowledgeContextError(RuntimeError):
    """A source boundary needs a durable no-extraction disposition."""

    def __init__(self, message: str, reason: str = "context_unavailable"):
        super().__init__(message)
        self.reason = reason


class MatrixSyncService:
    """Orchestrates Matrix room polling and LLM-based knowledge extraction.

    This service:
    - Polls configured Matrix rooms for new messages
    - Uses LLM to identify Q&A pairs from the message stream
    - Processes candidates through the knowledge intake pipeline

    Uses KnowledgeExtractor via pipeline_service.extract_faqs_batch() for
    single-pass LLM extraction instead of pattern-based reply matching.

    Attributes:
        settings: Application settings
        pipeline_service: KnowledgePipelineService for processing Q&A pairs
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
            pipeline_service: KnowledgePipelineService for Q&A processing
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
        self._client_lock = asyncio.Lock()
        self._sync_lock = asyncio.Lock()
        self._connection_manager: Optional[Any] = None
        self._session_manager: Optional[Any] = None
        self._error_handler: Optional[Any] = None
        self.last_deferred_count = 0
        self.last_deferred_scopes = 0

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
        """Serialize room sync with session-retention maintenance."""
        async with self._sync_lock:
            return await self._sync_rooms_locked()

    async def _sync_rooms_locked(self) -> int:
        """Poll all configured rooms and process Q&A pairs.

        Returns:
            Number of Q&A pairs successfully processed
        """
        self.last_deferred_count = 0
        self.last_deferred_scopes = 0
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

            had_room_errors = False
            for room_id in rooms:
                try:
                    processed = await self._sync_single_room(client, room_id)
                    total_processed += processed
                except Exception:
                    logger.exception(f"Failed to sync room {room_id}")
                    had_room_errors = True
                    # Continue with other rooms

            # Save state after all rooms processed
            self.polling_state.save_batch_processed()

            # Record sync success metrics
            sync_last_status.labels(source="matrix").set(0 if had_room_errors else 1)
            if not had_room_errors:
                sync_last_success_timestamp.labels(source="matrix").set(
                    time_module.time()
                )
            sync_pairs_processed.labels(source="matrix").inc(total_processed)

            if had_room_errors:
                raise IncompleteKnowledgeContextError(
                    "Matrix knowledge sync is incomplete; failed room inputs remain unprocessed"
                )

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
        async with self._client_lock:
            if self._client is not None:
                return self._client

            # Import here to avoid circular imports
            from app.channels.plugins.matrix.client.connection_manager import (
                ConnectionManager,
            )
            from app.channels.plugins.matrix.client.error_handler import ErrorHandler
            from app.channels.plugins.matrix.client.session_manager import (
                SessionManager,
            )

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
        """Sync a single Matrix room using LLM-based knowledge extraction.

        Args:
            client: Authenticated Matrix client
            room_id: Room ID to sync

        Returns:
            Number of knowledge candidates processed from this room
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
            direction=MessageDirection.front if since_token else MessageDirection.back,
            limit=100,
            method_name="room_messages",
        )

        if not isinstance(response, RoomMessagesResponse):
            raise IncompleteKnowledgeContextError(
                "Matrix source messages are unavailable"
            )

        # First observe a recent backward snapshot, then continue forward from
        # its head. Existing tokens are never reset: legacy backward cursors
        # catch up forward through the existing processed-ID deduplication.
        raw_messages = response.chunk
        next_token = response.end if since_token else response.start
        # Matrix may omit end for an empty forward page. Keep the established
        # cursor; an empty response is not evidence of a new position.
        if since_token and not raw_messages and not next_token:
            next_token = since_token
        if not isinstance(next_token, str) or not next_token:
            raise IncompleteKnowledgeContextError(
                "Matrix page has no continuation token"
            )

        logger.debug(f"Fetched {len(raw_messages)} messages from {room_id}")

        if not raw_messages:
            # Update per-room since token even if no messages
            self.polling_state.update_room_token(room_id, next_token)
            return 0

        # Convert matrix-nio events to dict format
        messages = [self._event_to_dict(msg) for msg in raw_messages]

        # The SQLite disposition commits before the separate source-state file.
        # Reconcile that crash window before context reads or paid extraction.
        deferred_ids = self.pipeline_service.repository.get_deferred_event_ids(
            source="matrix", source_scope=room_id
        )
        for msg in messages:
            if msg.get("event_id") in deferred_ids:
                self.polling_state.mark_processed(msg["event_id"])

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
            self.polling_state.update_room_token(room_id, next_token)
            return 0

        # Processed events remain eligible as context, never as new answers.
        eligible_ids = {msg.get("event_id", "") for msg in new_messages}
        try:
            messages = await self._with_boundary_context(
                client, room_id, messages, eligible_ids
            )
        except IncompleteKnowledgeContextError as exc:
            # Disposition the whole eligible page, never an invented Q&A pair.
            # A failed write or unresolved paid guard leaves this page pending.
            count = self.pipeline_service.repository.record_intake_disposition(
                source="matrix",
                source_scope=room_id,
                event_ids=sorted(eligible_ids),
                reason=exc.reason,
            )
            self.last_deferred_count += count
            self.last_deferred_scopes += 1
            results = []
        else:
            # Context may contain a deferred or previously processed answer.
            # It must not trigger a new paid call for a user-only current page.
            if any(
                msg.get("event_id") in eligible_ids
                and str(msg.get("sender", "")).lower() in self._staff_ids_lower
                and is_matrix_text_message(msg)
                for msg in messages
            ):
                results = await self.pipeline_service.extract_faqs_batch(
                    messages=messages,
                    source="matrix",
                    staff_identifiers=self.trusted_staff_ids,
                    source_scope=room_id,
                    eligible_answer_ids=eligible_ids,
                )
            else:
                self.pipeline_service.repository.ensure_knowledge_scope_not_held(
                    source="matrix", source_scope=room_id
                )
                results = []

        for msg in new_messages:
            event_id = msg.get("event_id", "")
            if event_id:
                self.polling_state.mark_processed(event_id)
        logger.debug(f"Marked {len(new_messages)} input messages as processed")

        # Count successful candidates
        for result in results:
            if result.candidate_id is not None:
                processed_count += 1
                logger.info(
                    f"Processed Matrix FAQ -> candidate {result.candidate_id} "
                    f"(routing: {result.routing})"
                )

        # Update per-room since token
        self.polling_state.update_room_token(room_id, next_token)

        return processed_count

    async def _with_boundary_context(
        self,
        client: "AsyncClient",
        room_id: str,
        messages: List[Dict[str, Any]],
        eligible_ids: Set[str],
    ) -> List[Dict[str, Any]]:
        """Resolve bounded page boundaries from Matrix, without a raw archive.

        An explicit reply outside the page, or a staff-only page, needs source
        context. Reads use the authenticated client and the exact source room.
        Cursor advancement remains the caller's responsibility after extraction.
        """
        if any(
            msg.get("event_id") in eligible_ids
            and msg.get("type") == "m.room.encrypted"
            for msg in messages
        ):
            raise IncompleteKnowledgeContextError(
                "Matrix page contains unreadable encrypted inputs"
            )
        readable = [
            msg
            for msg in messages
            if msg.get("event_id") and is_matrix_text_message(msg)
        ]
        by_id = {msg["event_id"]: msg for msg in readable}
        if len(by_id) != len(readable):
            raise IncompleteKnowledgeContextError(
                "Matrix source has duplicate event provenance", "provenance_conflict"
            )
        staff_messages = [
            msg
            for msg in by_id.values()
            if str(msg.get("sender", "")).lower() in self._staff_ids_lower
            and msg.get("event_id") in eligible_ids
        ]
        missing_targets = set()
        for msg in staff_messages:
            content = msg.get("content", {})
            relates = (
                content.get("m.relates_to", {}) if isinstance(content, dict) else {}
            )
            target = relates.get("m.in_reply_to", {}).get("event_id")
            if isinstance(target, str) and target not in by_id:
                missing_targets.add(target)

        def has_prior_user() -> bool:
            return any(
                str(msg.get("sender", "")).lower() not in self._staff_ids_lower
                and msg.get("origin_server_ts", 0) <= first_staff_timestamp
                for msg in by_id.values()
            )

        first_staff_timestamp = min(
            (msg.get("origin_server_ts", 0) for msg in staff_messages), default=0
        )
        needs_prior = bool(staff_messages) and not has_prior_user()
        if not missing_targets and not needs_prior:
            return sorted(
                by_id.values(), key=lambda msg: msg.get("origin_server_ts", 0)
            )
        anchors = (
            sorted(missing_targets)
            if missing_targets
            else [
                min(staff_messages, key=lambda msg: msg.get("origin_server_ts", 0))[
                    "event_id"
                ]
            ]
        )
        if len(anchors) > MAX_BOUNDARY_CONTEXT_READS:
            raise IncompleteKnowledgeContextError(
                "Matrix reply targets exceed the bounded context reads; inputs deferred",
                "context_limit",
            )
        for anchor in anchors:
            # An earlier response may already contain another required target.
            if anchor in by_id and anchor in missing_targets:
                continue
            try:
                response = await self._error_handler.call_with_retry(
                    client.room_context,
                    room_id,
                    anchor,
                    limit=20,
                    method_name="room_context",
                )
            except Exception as exc:
                raise IncompleteKnowledgeContextError(
                    "Matrix boundary context is unavailable"
                ) from exc
            if (
                not isinstance(response, RoomContextResponse)
                or response.room_id != room_id
                or response.event is None
                or getattr(response.event, "event_id", None) != anchor
            ):
                raise IncompleteKnowledgeContextError(
                    "Matrix boundary context is unavailable"
                )
            context_events = [
                *response.events_before,
                response.event,
                *response.events_after,
            ]
            if len(context_events) > 21:
                raise IncompleteKnowledgeContextError(
                    "Matrix boundary context exceeded its bound", "context_limit"
                )
            for event in context_events:
                msg = self._event_to_dict(event)
                if msg.get("room_id", room_id) != room_id:
                    raise IncompleteKnowledgeContextError(
                        "Matrix context has conflicting room provenance",
                        "provenance_conflict",
                    )
                event_id = msg.get("event_id")
                if not event_id:
                    continue
                # Transport metadata such as unsigned.age changes between reads.
                immutable_fields = ("sender", "type", "content", "origin_server_ts")
                if event_id in by_id and any(
                    by_id[event_id].get(field) != msg.get(field)
                    for field in immutable_fields
                ):
                    raise IncompleteKnowledgeContextError(
                        "Matrix context has conflicting event provenance",
                        "provenance_conflict",
                    )
                if is_matrix_text_message(msg):
                    by_id[event_id] = msg
        if not missing_targets.issubset(by_id):
            raise IncompleteKnowledgeContextError(
                "Matrix reply context remains incomplete", "missing_reply_target"
            )
        if staff_messages and not has_prior_user():
            raise IncompleteKnowledgeContextError(
                "Matrix prior question context remains incomplete; inputs deferred",
                "missing_prior_question",
            )
        return sorted(by_id.values(), key=lambda msg: msg.get("origin_server_ts", 0))

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
        async with self._sync_lock:
            if self._connection_manager:
                await self._connection_manager.disconnect()
            if self._client is not None:
                self._client.access_token = None
                self._client.device_id = None
            self._client = None
            self._connection_manager = None
            self._session_manager = None
            self._error_handler = None


__all__ = [
    "AsyncClient",
    "MatrixSyncService",
    "NIO_AVAILABLE",
    "RoomMessagesResponse",
]
