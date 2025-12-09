"""Matrix Shadow Mode Integration for support channel monitoring."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

try:
    from nio import AsyncClient, RoomMessagesError  # type: ignore[import-not-found]

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    RoomMessagesError = None

from app.integrations.matrix import ConnectionManager, ErrorHandler, SessionManager
from app.integrations.matrix.polling_state import PollingStateManager
from app.services.matrix_metrics import (
    matrix_poll_duration_seconds,
    matrix_polls_total,
    matrix_questions_detected,
    matrix_questions_processed,
)
from app.services.shadow_mode_processor import ShadowModeProcessor

logger = logging.getLogger(__name__)


class MatrixShadowModeService:
    """Monitor Matrix support channels without sending responses."""

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        room_id: str,
        access_token: Optional[str] = None,  # DEPRECATED: Use password instead
        password: Optional[str] = None,
        session_file: str = "/data/matrix_session.json",
        polling_state_file: str = "/data/matrix_polling_state.json",
    ):
        """
        Initialize Matrix shadow mode service.

        Args:
            homeserver: Matrix homeserver URL
            user_id: Bot user ID
            room_id: Support room to monitor
            access_token: DEPRECATED - Bot access token (use password instead)
            password: Bot password for automatic session management (recommended)
            session_file: Path to session persistence file (default: /data/matrix_session.json)
            polling_state_file: Path to polling state file (default: /data/matrix_polling_state.json)
        """
        if not NIO_AVAILABLE:
            raise ImportError(
                "matrix-nio is not installed. " "Install with: pip install matrix-nio"
            )

        self.homeserver = homeserver
        self.user_id = user_id
        self.room_id = room_id

        # Initialize Matrix client
        self.client = AsyncClient(homeserver, user_id)

        # Initialize polling state manager (Phase 1: Session Persistence)
        self.polling_state = PollingStateManager(polling_state_file)
        logger.info(
            f"Polling state initialized: since_token={self.polling_state.since_token[:20] if self.polling_state.since_token else None}..., "
            f"processed_ids={len(self.polling_state.processed_ids)}"
        )

        # Initialize managers if password provided (new approach)
        if password:
            logger.info(
                "Initializing Matrix with password-based authentication (recommended)"
            )
            self.session_manager = SessionManager(self.client, password, session_file)
            self.error_handler = ErrorHandler(self.session_manager)
            self.connection_manager = ConnectionManager(
                self.client, self.session_manager
            )
            self._use_password_auth = True
        elif access_token:
            # Legacy mode - direct token assignment (DEPRECATED)
            logger.warning(
                "Using direct token authentication (DEPRECATED). "
                "Switch to password-based authentication for automatic session management."
            )
            self.client.access_token = access_token
            self.session_manager = None
            self.error_handler = None
            self.connection_manager = None
            self._use_password_auth = False
        else:
            raise ValueError(
                "Either 'password' (recommended) or 'access_token' (deprecated) must be provided"
            )

        # Legacy in-memory tracking (DEPRECATED - use polling_state instead)
        self._processed_ids: Set[str] = set()
        self._since_token: Optional[str] = None

        logger.info(f"Matrix shadow mode initialized for room {room_id}")

    async def connect(self) -> None:
        """Connect to Matrix homeserver with automatic session restoration."""
        if self._use_password_auth:
            # New approach: automatic session management
            await self.connection_manager.connect()
        else:
            # Legacy approach: access token already set
            logger.info(f"Connected to {self.homeserver} (legacy token mode)")

    async def disconnect(self) -> None:
        """Disconnect from Matrix homeserver."""
        # Save polling state before disconnect (Phase 1: Session Persistence)
        self.polling_state.save_state()
        logger.info("Polling state saved on disconnect")

        if self._use_password_auth:
            # New approach: clean shutdown with session preservation
            await self.connection_manager.disconnect()
        else:
            # Legacy approach: simple close
            await self.client.close()
            logger.info("Disconnected from Matrix (legacy mode)")

    async def fetch_messages(
        self,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch messages from the support room with automatic error recovery.

        Args:
            limit: Maximum number of messages to fetch
            since: Pagination token

        Returns:
            List of message dictionaries
        """
        if self._use_password_auth:
            # New approach: wrap with error handler for automatic retry
            return await self.error_handler.call_with_retry(
                self._fetch_messages_impl, limit=limit, since=since
            )
        else:
            # Legacy approach: direct call without error handling
            return await self._fetch_messages_impl(limit=limit, since=since)

    async def _fetch_messages_impl(
        self,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Internal implementation of message fetching.

        Args:
            limit: Maximum number of messages to fetch
            since: Pagination token

        Returns:
            List of message dictionaries
        """
        try:
            # Log the fetch attempt
            logger.info(
                f"Fetching messages from room {self.room_id}, "
                f"start={since or self._since_token}, limit={limit}"
            )

            response = await self.client.room_messages(
                self.room_id,
                start=since or self.polling_state.since_token or self._since_token,
                limit=limit,
            )

            if isinstance(response, RoomMessagesError):
                logger.error(f"Error fetching messages: {response.message}")
                return []

            # Update pagination token (Phase 1: Session Persistence)
            if hasattr(response, "end"):
                self._since_token = response.end  # Legacy in-memory
                self.polling_state.update_since_token(response.end)  # Persistent

            # Convert to dictionaries
            messages = []
            for event in response.chunk:
                if hasattr(event, "body"):
                    messages.append(
                        {
                            "event_id": event.event_id,
                            "sender": event.sender,
                            "body": event.body,
                            "timestamp": getattr(event, "server_timestamp", 0),
                        }
                    )

            logger.info(
                f"Fetched {len(messages)} messages from Matrix room. "
                f"Total events in response: {len(response.chunk) if hasattr(response, 'chunk') else 0}"
            )

            return messages

        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            return []

    async def filter_support_questions(
        self, messages: List[Dict[str, Any]], processor: "ShadowModeProcessor"
    ) -> List[Dict[str, Any]]:
        """
        Filter messages to find support questions with cross-poll context.

        Args:
            messages: List of message dictionaries (sorted chronologically)
            processor: Shadow mode processor for classification

        Returns:
            List of messages that appear to be support questions (with context attached)
        """
        questions = []

        # Build conversation context (last N messages before current)
        # For follow-up detection, we only need a small window
        CONTEXT_WINDOW = 5

        # Fetch recent messages from database for cross-poll context
        all_messages = []
        if processor.repository and messages:
            try:
                # Get timestamp of first message in current poll
                first_msg_timestamp = messages[0].get("timestamp", 0)
                if first_msg_timestamp > 0:
                    first_msg_ts = datetime.fromtimestamp(
                        first_msg_timestamp / 1000, tz=timezone.utc
                    ).isoformat()

                    # Fetch recent messages from database (before this poll)
                    recent_db_messages = await asyncio.create_task(
                        asyncio.to_thread(
                            processor.repository.get_recent_messages,
                            channel_id=self.room_id,
                            limit=10,
                            before=first_msg_ts,
                        )
                    )

                    # Convert database messages to same format as Matrix messages
                    db_msgs_as_matrix = []
                    for db_msg in recent_db_messages:
                        # Database messages have format: {content, message_id, timestamp, ...}
                        db_msgs_as_matrix.append(
                            {
                                "event_id": db_msg.get("message_id", "unknown"),
                                "sender": db_msg.get("sender_id", ""),
                                "body": db_msg.get("content", ""),
                                "timestamp": (
                                    int(
                                        datetime.fromisoformat(
                                            db_msg.get("timestamp", "")
                                        ).timestamp()
                                        * 1000
                                    )
                                    if db_msg.get("timestamp")
                                    else 0
                                ),
                            }
                        )

                    # Combine database messages + current poll messages
                    all_messages = db_msgs_as_matrix + messages
                    logger.debug(
                        f"Cross-poll context: fetched {len(db_msgs_as_matrix)} messages from database"
                    )
                else:
                    all_messages = messages
            except Exception as e:
                logger.warning(f"Failed to fetch cross-poll context: {e}")
                all_messages = messages
        else:
            all_messages = messages

        for i, msg in enumerate(all_messages):
            sender = msg.get("sender", "")
            body = msg.get("body", "")

            # Only process messages from current poll (not historical ones)
            # Historical messages are only used for context
            if msg not in messages:
                continue

            # Log each message for debugging
            logger.debug(f"Evaluating message from {sender}: {body[:100]}...")

            # Skip reply messages (Matrix replies start with "> <@user:server>")
            # The classifier handles this, but we can skip early for efficiency
            if body.strip().startswith(">"):
                logger.debug(f"  → Skipped (reply message)")
                continue

            # Extract previous messages for conversation context
            # Look back up to CONTEXT_WINDOW messages
            prev_messages = []
            for j in range(max(0, i - CONTEXT_WINDOW), i):
                prev_body = all_messages[j].get("body", "")
                if prev_body:  # Only include messages with content
                    prev_messages.append(prev_body)

            # Use multi-layer classifier with conversation context
            if await processor.is_support_question(
                body, sender=sender, prev_messages=prev_messages
            ):
                logger.info(f"  ✓ Identified as support question from {sender}")

                # Attach context messages to question for storage
                context_msgs = []
                for j in range(max(0, i - CONTEXT_WINDOW), i):
                    context_msgs.append(all_messages[j])

                # Add context to message metadata
                msg["_context_messages"] = context_msgs
                questions.append(msg)
            else:
                logger.debug(f"  → Skipped (filtered by classifier): {body[:50]}")

        logger.info(
            f"Filtered {len(questions)} support questions from {len(messages)} messages"
        )
        return questions

    def mark_as_processed(self, event_id: str) -> None:
        """
        Mark a message as processed.

        Args:
            event_id: Matrix event ID
        """
        self._processed_ids.add(event_id)  # Legacy in-memory
        self.polling_state.mark_processed(event_id)  # Persistent (Phase 1)

    def is_processed(self, event_id: str) -> bool:
        """
        Check if a message has been processed.

        Args:
            event_id: Matrix event ID

        Returns:
            True if already processed
        """
        # Check persistent state first, fallback to in-memory (Phase 1)
        return (
            self.polling_state.is_processed(event_id) or event_id in self._processed_ids
        )

    async def poll_for_questions(
        self,
        repository: Optional["ShadowModeRepository"] = None,
        processor: Optional["ShadowModeProcessor"] = None,
    ) -> List[Dict[str, Any]]:
        """
        Poll for new support questions with optional database duplicate checking.

        Args:
            repository: Optional repository for database duplicate checking
            processor: Optional shadow mode processor for classification

        Returns:
            List of new support questions
        """
        # Fetch recent messages
        messages = await self.fetch_messages()

        # Filter to support questions only (requires processor for classification)
        if processor:
            questions = await self.filter_support_questions(messages, processor)
        else:
            # Fallback: return all messages if no processor provided
            questions = messages

        # Filter out already processed (Phase 1: Database Duplicate Check)
        new_questions = []
        for q in questions:
            event_id = q["event_id"]

            # Fast path: memory check (both in-memory and persistent state)
            if self.is_processed(event_id):
                logger.debug(f"Skipping {event_id}: already in memory cache")
                continue

            # Persistent path: database check if repository provided
            if repository:
                try:
                    existing = await asyncio.create_task(
                        asyncio.to_thread(repository.get_by_question_id, event_id)
                    )
                    if existing:
                        logger.debug(
                            f"Skipping {event_id}: found in database with status {existing.status}"
                        )
                        # Add to memory cache for future fast-path checks
                        self.polling_state.mark_processed(event_id)
                        self._processed_ids.add(event_id)
                        continue
                except Exception as e:
                    # Conservative approach: skip on error to avoid duplicate processing
                    logger.error(
                        f"Database check failed for {event_id}: {e}. Skipping to avoid duplicates."
                    )
                    continue

            new_questions.append(q)

        logger.info(
            f"Filtered to {len(new_questions)} new questions from {len(questions)} total support questions"
        )
        return new_questions

    async def process_with_shadow_mode(
        self,
        processor: "ShadowModeProcessor",
    ) -> int:
        """
        Process new questions through shadow mode with Prometheus metrics tracking.

        Args:
            processor: Shadow mode processor instance

        Returns:
            Number of questions processed
        """
        # Phase 3: Track polling duration
        import time

        start_time = time.time()

        try:
            # Pass processor for classification and repository for database duplicate checking
            questions = await self.poll_for_questions(
                repository=processor.repository, processor=processor
            )

            # Phase 3: Record questions detected
            matrix_questions_detected.labels(room_id=self.room_id).inc(len(questions))

            processed_count = 0

            for question in questions:
                event_id = question["event_id"]
                body = question["body"]
                sender = question["sender"]
                timestamp = question.get("timestamp", 0)
                context_messages = question.get("_context_messages", [])

                try:
                    # Process through shadow mode with context
                    response = await processor.process_question(
                        question=body,
                        question_id=event_id,
                        room_id=self.room_id,
                        sender=sender,
                        timestamp=timestamp,
                        context_messages=context_messages,
                    )

                    if response:
                        self.mark_as_processed(event_id)
                        processed_count += 1
                        logger.info(
                            f"Processed question {event_id}: "
                            f"detected_version={response.detected_version}, "
                            f"context_messages={len(context_messages)}"
                        )

                except Exception as e:
                    logger.error(f"Error processing {event_id}: {e}")

            # Phase 3: Record questions processed
            matrix_questions_processed.labels(room_id=self.room_id).inc(processed_count)

            # Save polling state after batch processing (Phase 1: Session Persistence)
            self.polling_state.save_batch_processed()
            logger.info(
                f"Batch processed {processed_count} questions, polling state saved"
            )

            # Phase 3: Record successful poll
            matrix_polls_total.labels(room_id=self.room_id, status="success").inc()

            return processed_count

        except Exception as e:
            # Phase 3: Record failed poll
            logger.error(f"Polling failed: {e}")
            matrix_polls_total.labels(room_id=self.room_id, status="failure").inc()
            raise

        finally:
            # Phase 3: Record poll duration
            duration = time.time() - start_time
            matrix_poll_duration_seconds.labels(room_id=self.room_id).observe(duration)
