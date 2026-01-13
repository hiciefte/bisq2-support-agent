"""Shadow mode processor for Matrix support channel monitoring."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

from app.core.config import Settings
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.services.rag.version_detector import VersionDetector
from app.services.shadow_mode.repository import ShadowModeRepository

logger = logging.getLogger(__name__)


class ShadowModeProcessor:
    """Process Matrix questions through RAG pipeline without sending to users.

    Note: Question extraction is now handled by UnifiedBatchProcessor in matrix_shadow_mode.py.
    This class focuses on storing and managing shadow responses.
    """

    # Default support staff from https://bisq.wiki/Support_Agent
    # Can be overridden via KNOWN_SUPPORT_STAFF env var
    # Pre-lowercased frozenset for O(1) lookups without repeated list creation
    DEFAULT_SUPPORT_STAFF: ClassVar[frozenset[str]] = frozenset(
        {
            "darawhelan",  # @darawhelan:matrix.org
            "luis3672",  # @luis3672:matrix.org
            "mwithm",  # @mwithm:matrix.org (MnM)
            "pazza83",  # @pazza83:matrix.org
            "strayorigin",  # @strayorigin:matrix.org
            "suddenwhipvapor",  # @suddenwhipvapor:matrix.org
        }
    )

    def __init__(
        self,
        repository: Optional[ShadowModeRepository] = None,
        settings: Optional[Settings] = None,
    ):
        """
        Initialize shadow mode processor.

        Args:
            repository: SQLite repository for persistent storage (optional)
            settings: Application settings for LLM configuration (optional)
        """
        self.repository = repository
        self.settings = settings or Settings()
        self.version_detector = VersionDetector()

        self._responses: Dict[str, ShadowResponse] = {}
        self._question_hashes: set = set()
        self._max_question_hashes: int = 10000  # Prevent unbounded memory growth

    async def process_question(
        self,
        question: str,
        question_id: str,
        room_id: Optional[str] = None,
        sender: Optional[str] = None,
        timestamp: Optional[int] = None,
        context_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[ShadowResponse]:
        """
        Process a question through the RAG pipeline.

        Args:
            question: The user's question
            question_id: Unique identifier for tracking
            room_id: Matrix room ID (optional)
            sender: Real username from LLM extraction or Matrix sender ID (optional)
            timestamp: Original Matrix message timestamp in milliseconds (optional)
            context_messages: Previous messages for conversation context (optional)

        Returns:
            ShadowResponse with answer and confidence, or None on error
        """
        try:
            # Scrub PII from question
            sanitized_question = self._scrub_pii(question)

            # Detect version from question text using shared VersionDetector
            # This provides consistent detection with the RAG pipeline
            detected_version, version_confidence, clarifying_question = (
                await self.version_detector.detect_version(
                    sanitized_question, []  # No chat history for Matrix messages
                )
            )

            # Create shadow response using new two-phase workflow model
            now = datetime.now(timezone.utc)
            # Convert Matrix timestamp (milliseconds) to ISO format, or use now if not provided
            if timestamp and timestamp > 0:
                msg_timestamp = datetime.fromtimestamp(
                    timestamp / 1000, tz=timezone.utc
                ).isoformat()
            else:
                msg_timestamp = now.isoformat()

            # Convert detected version format: "Bisq 1" -> "bisq1", "Bisq 2" -> "bisq2"
            normalized_version = detected_version.lower().replace(" ", "")

            # Build aggregated messages with context
            aggregated_messages = []

            # Add context messages (bystander filtering applied)
            if context_messages:
                # Filter to same-user messages only (GDPR compliance)
                filtered_context = []
                # Pre-compute sender's anonymized ID outside loop for efficiency
                sender_anon_id = self._anonymize_sender(sender or "")
                for ctx_msg in context_messages:
                    ctx_sender = ctx_msg.get("sender", "")

                    # Skip bystander messages (not from the current sender)
                    if self._anonymize_sender(ctx_sender) != sender_anon_id:
                        logger.debug(
                            f"Skipping bystander context: message_id={ctx_msg.get('event_id', 'unknown')}"
                        )
                        continue

                    # Scrub PII from context message
                    ctx_body = ctx_msg.get("body", "")
                    sanitized_ctx = self._scrub_pii(ctx_body)

                    # Convert timestamp
                    ctx_timestamp = ctx_msg.get("timestamp", 0)
                    if ctx_timestamp and ctx_timestamp > 0:
                        ctx_ts_iso = datetime.fromtimestamp(
                            ctx_timestamp / 1000, tz=timezone.utc
                        ).isoformat()
                    else:
                        ctx_ts_iso = now.isoformat()

                    filtered_context.append(
                        {
                            "content": sanitized_ctx,
                            "is_context": True,
                            "message_id": ctx_msg.get("event_id", "unknown"),
                            "timestamp": ctx_ts_iso,
                            "sender_id": self._anonymize_sender(ctx_sender),
                        }
                    )

                # Add context messages in chronological order
                aggregated_messages.extend(filtered_context)

            # Add primary question (always last)
            aggregated_messages.append(
                {
                    "content": sanitized_question,
                    "is_primary_question": True,
                    "timestamp": msg_timestamp,
                    "sender_type": "user",
                    "message_id": question_id,
                    "schema_version": "1.0",
                }
            )

            response = ShadowResponse(
                id=question_id,
                channel_id=room_id or "unknown",
                user_id=(
                    self._anonymize_sender(sender) if sender else "anonymous"
                ),  # Anonymize for privacy
                messages=aggregated_messages,
                synthesized_question=sanitized_question,
                detected_version=normalized_version,
                version_confidence=version_confidence,
                clarifying_question=clarifying_question,  # Preserve version uncertainty
                requires_clarification=clarifying_question is not None,
                generated_response=None,  # RAG deferred until version confirmation
                sources=[],  # Empty until RAG is called
                status=ShadowStatus.PENDING_VERSION_REVIEW,
                created_at=now,
                updated_at=now,
            )

            # Persist to SQLite repository if available (transactional)
            if self.repository:
                success = self.repository.add_response(response)
                if success:
                    # Only update memory if database write succeeded
                    self._responses[question_id] = response
                    logger.debug(f"Saved response {question_id} to SQLite repository")
                else:
                    logger.error(
                        f"Failed to persist {question_id}, skipping memory update"
                    )
                    return None
            else:
                # No repository - store in memory only
                self._responses[question_id] = response

            # Track question hash for duplicate detection (with size limit)
            question_hash = self._hash_question(sanitized_question)
            if len(self._question_hashes) >= self._max_question_hashes:
                # Clear entire set - Python sets don't preserve insertion order
                # so selective removal isn't possible without additional tracking
                logger.warning(
                    f"Question hash cache reached limit ({self._max_question_hashes}), clearing"
                )
                self._question_hashes.clear()
            self._question_hashes.add(question_hash)

            logger.info(
                f"Processed question {question_id}: "
                f"detected_version={normalized_version}, confidence={version_confidence:.0%}, "
                f"context_messages={len(aggregated_messages) - 1}"
            )

            return response

        except Exception:
            logger.exception(f"Error processing question {question_id}")
            return None

    def get_response(self, question_id: str) -> Optional[ShadowResponse]:
        """
        Get a stored response by ID.

        Checks in-memory cache first, then falls back to repository if configured.
        This ensures responses are retrievable even after a process restart.

        Args:
            question_id: The question ID to retrieve

        Returns:
            ShadowResponse if found, None otherwise
        """
        # Check in-memory cache first
        response = self._responses.get(question_id)
        if response is not None:
            return response

        # Fall back to repository if configured
        if self.repository is not None:
            response = self.repository.get_response(question_id)
            if response is not None:
                # Cache in memory for future lookups
                self._responses[question_id] = response
            return response

        return None

    def get_pending_responses(self) -> List[ShadowResponse]:
        """
        Get all unprocessed responses awaiting review.

        Queries both in-memory cache and repository if configured.
        Merges results to ensure admin review queue is complete after restarts.

        Returns:
            List of unprocessed ShadowResponses
        """
        # Get in-memory pending responses
        pending = {
            r.id: r
            for r in self._responses.values()
            if r.status == ShadowStatus.PENDING_VERSION_REVIEW
        }

        # Merge with repository responses if configured
        if self.repository is not None:
            # Query repository for pending responses
            repo_pending = self.repository.get_responses(
                status=ShadowStatus.PENDING_VERSION_REVIEW.value, limit=1000
            )
            for response in repo_pending:
                if response.id not in pending:
                    pending[response.id] = response
                    # Also cache in memory for future lookups
                    self._responses[response.id] = response

        return list(pending.values())

    def mark_as_processed(self, question_id: str) -> None:
        """
        Mark a response as processed.

        Persists to repository first (if configured), then updates in-memory cache.
        This ensures memory and persistent state remain consistent.

        Args:
            question_id: The question ID to mark
        """
        # Persist status change to repository first if configured
        if self.repository is not None:
            try:
                self.repository.update_response(
                    question_id, {"status": ShadowStatus.APPROVED.value}
                )
            except Exception:
                logger.exception(f"Failed to persist APPROVED status for {question_id}")
                # Don't update in-memory cache if persistence failed
                return

        # Update in-memory cache only after successful persistence (or if no repo)
        if question_id in self._responses:
            self._responses[question_id].status = ShadowStatus.APPROVED

    @classmethod
    def is_support_staff(cls, sender: str, staff_list: list[str] | None = None) -> bool:
        """
        Check if sender is a support staff member using exact localpart matching.

        Args:
            sender: Matrix user ID (e.g., @username:server.com)
            staff_list: Optional list of staff usernames to check against.
                       If None, uses DEFAULT_SUPPORT_STAFF.

        Returns:
            True if sender is support staff
        """
        # Use pre-lowercased default or convert provided list to set for O(1) lookup
        if staff_list is None:
            staff_set = cls.DEFAULT_SUPPORT_STAFF
        else:
            staff_set = frozenset(s.lower() for s in staff_list)

        # Extract localpart from Matrix ID (e.g., "@luis3672:matrix.org" -> "luis3672")
        localpart = sender.lower()
        if localpart.startswith("@"):
            localpart = localpart[1:]  # Remove leading @
        if ":" in localpart:
            localpart = localpart.split(":")[0]  # Remove server part

        # Exact match against staff set (O(1) lookup)
        return localpart in staff_set

    @classmethod
    def is_support_question(
        cls, body: str, sender: str = "", staff_list: list[str] | None = None
    ) -> bool:
        """
        Check if a message is a support question that should be processed.

        A message is considered a support question if:
        1. The sender is NOT a support staff member
        2. The message content looks like a question/help request

        Args:
            body: Message body text
            sender: Matrix user ID (e.g., @username:server.com)
            staff_list: Optional list of staff usernames to check against.

        Returns:
            True if message should be treated as a support question
        """
        # Filter out staff messages
        if sender and cls.is_support_staff(sender, staff_list):
            return False

        # Skip empty messages
        if not body or not body.strip():
            return False

        body_lower = body.lower().strip()

        # Filter out URL-only messages
        if body_lower.startswith("http://") or body_lower.startswith("https://"):
            # Check if message is mostly just a URL
            words = body_lower.split()
            if len(words) <= 3:
                return False

        # Patterns indicating a question/help request
        question_indicators = [
            # Direct question markers
            "?",
            # Help-seeking phrases
            "how do i",
            "how can i",
            "how to",
            "can i",
            "can someone",
            "is there a way",
            "i'm getting",
            "i am getting",
            "i'm having",
            "i am having",
            "i can't",
            "i cannot",
            "i don't see",
            "i don't have",
            "doesn't work",
            "not working",
            "help me",
            "need help",
            "having trouble",
            "having issue",
            "having problem",
            "is it possible",
            "what should i",
            "what do i",
            "why is",
            "why does",
            "why can't",
            "where is",
            "where can",
            # Bisq-specific question patterns
            "wallet is",
            "bsq wallet",
            "my offer",
            "my trade",
            "error with",
            "issue with",
            "problem with",
            "i performed",
            "i moved",
            "resyncing",
            "restarting",
        ]

        # Patterns indicating NOT a question (statements, responses, advice)
        non_question_indicators = [
            # Staff-like response patterns
            "you can",
            "you should",
            "you need to",
            "try to",
            "make sure",
            "if there is an issue",
            "if the",
            "sometimes",
            "are seeing no",  # Staff asking clarifying question
            "scammers set up",  # Warning message
            "lesson learned",
            "no problem",
            "alrighty",
            "indeed",
            "it's ok",
            "was a small",
            "i don't have that problem",
            "check your logs",
            "can also check",
            "can prevent",
            "can appear",
        ]

        # Check for non-question patterns first
        for pattern in non_question_indicators:
            if pattern in body_lower:
                return False

        # Check for question indicators
        for pattern in question_indicators:
            if pattern in body_lower:
                return True

        # Default: not a question
        return False

    def _scrub_pii(self, text: str) -> str:
        """
        Remove personally identifiable information from text.

        Includes Bisq-specific PII patterns (Trade IDs, Offer IDs, Matrix mentions).

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text, or "[REDACTED_DUE_TO_ERROR]" if scrubbing fails
        """
        try:
            # Remove email addresses
            text = re.sub(
                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                "[EMAIL]",
                text,
            )

            # Remove phone numbers
            text = re.sub(
                r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
                "[PHONE]",
                text,
            )

            # Remove IP addresses
            text = re.sub(
                r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
                "[IP]",
                text,
            )

            # Remove potential Bitcoin addresses (legacy P2PKH/P2SH and SegWit/Taproot)
            # Legacy addresses: start with 1 or 3, base58 charset, 25-34 chars
            text = re.sub(
                r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b",
                "[BTC_ADDRESS]",
                text,
            )
            # Native SegWit (bc1q) and Taproot (bc1p) addresses: bech32/bech32m
            # bc1q: 42-62 chars total, bc1p: 62 chars total
            text = re.sub(
                r"\bbc1[qp][a-z0-9]{38,58}\b",
                "[BTC_ADDRESS]",
                text,
                flags=re.IGNORECASE,
            )

            # Bisq-specific PII patterns
            # Trade IDs (UUID format: f8a3c2e1-9b4d-4f3a-a1e2-8c9d3f4e5a6b)
            text = re.sub(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                "[TRADE_ID]",
                text,
                flags=re.IGNORECASE,
            )

            # Offer IDs (numeric with # prefix: #98590482)
            text = re.sub(r"#\d{8,}", "[OFFER_ID]", text)

            # Matrix user mentions (@username:homeserver) - generic pattern for any homeserver
            text = re.sub(
                r"@[^:\s]+:[^\s]+",
                "@[USER]:[HOMESERVER]",
                text,
            )

            return text

        except Exception:
            logger.exception("PII scrubbing failed")
            return "[REDACTED_DUE_TO_ERROR]"

    def _anonymize_sender(self, sender: str) -> str:
        """
        Anonymize sender identifier.

        Args:
            sender: Original sender ID

        Returns:
            Anonymized sender hash
        """
        return hashlib.sha256(sender.encode()).hexdigest()[:8]

    def _hash_question(self, question: str) -> str:
        """
        Create hash of question for duplicate detection.

        Args:
            question: Question text

        Returns:
            Hash string
        """
        # Normalize question for hashing
        normalized = question.lower().strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return hashlib.md5(normalized.encode()).hexdigest()

    def is_duplicate(self, question: str) -> bool:
        """
        Check if question is a duplicate.

        Args:
            question: Question text to check

        Returns:
            True if question has been processed before
        """
        question_hash = self._hash_question(question)
        return question_hash in self._question_hashes
