"""Matrix Shadow Mode Integration for support channel monitoring."""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from app.services.shadow_mode.repository import ShadowModeRepository
    from app.services.shadow_mode_processor import ShadowModeProcessor

try:
    from nio import AsyncClient, RoomMessagesError  # type: ignore[import-not-found]

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    RoomMessagesError = None

from app.integrations.matrix import ConnectionManager, ErrorHandler, SessionManager
from app.integrations.matrix.polling_state import PollingStateManager
from app.services.llm_extraction.metrics import (
    extraction_confidence_score,
    questions_extracted_total,
    questions_rejected_total,
)
from app.services.matrix_metrics import (
    matrix_poll_duration_seconds,
    matrix_polls_total,
    matrix_questions_detected,
    matrix_questions_processed,
)

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

    def _extract_reply_to(self, event) -> Optional[str]:
        """Extract reply reference from Matrix event.

        Args:
            event: Matrix RoomMessageText event

        Returns:
            Event ID of replied-to message, or None if not a reply
        """
        try:
            relates_to = event.source["content"].get("m.relates_to")
            if relates_to and "m.in_reply_to" in relates_to:
                return relates_to["m.in_reply_to"]["event_id"]
        except (KeyError, AttributeError, TypeError) as e:
            logger.debug(f"Failed to extract reply_to: {e}")
        return None

    def _extract_thread_id(self, event) -> Optional[str]:
        """Extract thread ID from Matrix event.

        Args:
            event: Matrix RoomMessageText event

        Returns:
            Event ID of thread root, or None if not in a thread
        """
        try:
            relates_to = event.source["content"].get("m.relates_to")
            if relates_to and relates_to.get("rel_type") == "m.thread":
                return relates_to.get("event_id")
        except (KeyError, AttributeError, TypeError) as e:
            logger.debug(f"Failed to extract thread_id: {e}")
        return None

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
                            "reply_to": self._extract_reply_to(event),
                            "thread_id": self._extract_thread_id(event),
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
        # Old classification loop removed - now handled by extract_questions_with_llm()
        # which uses UnifiedBatchProcessor for privacy-preserving extraction
        logger.info(
            "Old classification system removed. Use extract_questions_with_llm() instead."
        )
        return []

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

    async def extract_questions_with_llm(
        self, messages: List[Dict[str, Any]], settings: Any
    ) -> List[Dict[str, Any]]:
        """
        Extract user questions from messages using UnifiedBatchProcessor.

        This replaces the old multi-layer classification system with a single
        LLM call that:
        1. Receives ALL messages (users + staff)
        2. Uses privacy-preserving username anonymization
        3. Filters staff messages and extracts user questions
        4. Returns questions with real usernames for shadow mode queue

        Args:
            messages: List of ALL message dictionaries (including staff)
            settings: Application settings with LLM configuration

        Returns:
            List of messages identified as user questions with extraction metadata
        """
        try:
            # Import here to avoid circular dependencies
            import aisuite as ai  # type: ignore[import-untyped]
            from app.services.llm_extraction.unified_batch_processor import (
                UnifiedBatchProcessor,
            )

            # Initialize AISuite client and UnifiedBatchProcessor
            client = ai.Client()
            extractor = UnifiedBatchProcessor(
                ai_client=client,
                settings=settings,
            )

            # Extract user questions from ALL messages (single LLM call with anonymization)
            result = await extractor.extract_questions(
                messages=messages, room_id=self.room_id
            )

            # Convert extracted questions back to message format
            # ONLY include "initial_question" type for training (filter out follow-ups)
            questions = []
            filtered_count = 0

            for extracted_q in result.questions:
                # Record extraction metrics for all questions
                questions_extracted_total.labels(
                    question_type=extracted_q.question_type
                ).inc()
                extraction_confidence_score.observe(extracted_q.confidence)

                # Skip non-initial questions (follow-ups, acknowledgments, not_question)
                if extracted_q.question_type != "initial_question":
                    filtered_count += 1
                    logger.debug(
                        f"Filtered {extracted_q.question_type}: {extracted_q.question_text[:50]}..."
                    )
                    continue

                # Skip low-confidence initial questions
                if extracted_q.confidence < settings.LLM_EXTRACTION_MIN_CONFIDENCE:
                    filtered_count += 1
                    questions_rejected_total.labels(reason="low_confidence").inc()
                    logger.info(
                        f"Filtered low-confidence ({extracted_q.confidence:.2f}): "
                        f"{extracted_q.question_text[:50]}..."
                    )
                    continue

                # Find original message by message_id
                original_msg = next(
                    (m for m in messages if m["event_id"] == extracted_q.message_id),
                    None,
                )

                if original_msg:
                    # Add extraction metadata to message (anonymized sender)
                    enriched_msg = original_msg.copy()
                    enriched_msg["_llm_extraction"] = {
                        "question_text": extracted_q.question_text,
                        "question_type": extracted_q.question_type,
                        "confidence": extracted_q.confidence,
                        "sender": extracted_q.sender,  # Anonymized (User_1, User_2, etc.)
                        "extraction_method": "unified_batch",
                        "conversation_count": len(result.conversations),
                    }
                    questions.append(enriched_msg)

            logger.info(
                f"Unified batch extraction: {len(questions)} initial questions from {result.total_messages} messages "
                f"({filtered_count} filtered by type/confidence) "
                f"in {len(result.conversations)} conversations (processing_time={result.processing_time_ms}ms)"
            )

            return questions

        except Exception as e:
            logger.error(f"Batch LLM extraction failed: {e}", exc_info=True)
            # Fallback: return empty list on error
            return []

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

        # Filter to support questions only
        if processor and processor.settings.ENABLE_LLM_EXTRACTION:
            # Use LLM-based extraction when enabled
            questions = await self.extract_questions_with_llm(
                messages, processor.settings
            )
            logger.info(
                f"LLM extraction enabled: extracted {len(questions)} questions from {len(messages)} messages"
            )
        elif processor:
            # Use rule-based classification when LLM disabled
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
                # Use Matrix sender (will be anonymized by shadow_mode_processor)
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
