"""Shadow mode processor for Matrix support channel monitoring."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.services.rag.version_detector import VersionDetector
from app.services.shadow_mode.classifiers import MultiLayerClassifier
from app.services.shadow_mode.repository import ShadowModeRepository

logger = logging.getLogger(__name__)


class ShadowModeProcessor:
    """Process Matrix questions through RAG pipeline without sending to users."""

    # Question detection patterns - expanded to catch more support requests
    QUESTION_PATTERNS = [
        r"\?",  # Contains question mark anywhere
        r"^(?:what|how|why|where|when|who|which|can|could|would|should|is|are|do|does)\s",
        r"^(?:hi|hello|hey)[\s,.]",  # Starts with greeting (common for support)
        r"(?:help|please help|can.+help|need help|need.+help)",
        r"(?:i'm stuck|my .+ stuck|problem with|issue with|error|failing)",
        r"(?:not able|unable|can't|cannot|couldn't|won't|doesn't|don't|hasn't|haven't)",
        r"(?:not confirmed|not syncing|not working|not showing|not received)",
        r"(?:opened a trade|open trade|trade.+resolved|trade.+back)",
        r"(?:arbitration|mediator|arbitrator|refund|dispute)",
        r"(?:transaction.+confirmed|btc.+confirmed|funds)",
        r"(?:wallet|bsq|offer|seed)",
    ]

    # Official support staff from https://bisq.wiki/Support_Agent
    SUPPORT_STAFF = [
        "darawhelan",  # @darawhelan:matrix.org
        "luis3672",  # @luis3672:matrix.org
        "mwithm",  # @mwithm:matrix.org (MnM)
        "pazza83",  # @pazza83:matrix.org
        "strayorigin",  # @strayorigin:matrix.org
        "suddenwhipvapor",  # @suddenwhipvapor:matrix.org
    ]

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

        # Initialize pattern-based classifier (used as fallback when LLM extraction disabled)
        # Note: LLM-based question extraction (UnifiedBatchProcessor) is now the primary method
        self.classifier = MultiLayerClassifier(
            known_staff=self.SUPPORT_STAFF,
            llm_classifier=None,  # LLM classification removed (replaced by UnifiedBatchProcessor)
            enable_llm=False,  # Disabled - UnifiedBatchProcessor handles LLM now
            llm_threshold=self.settings.LLM_PATTERN_CONFIDENCE_THRESHOLD,
        )

        self._responses: Dict[str, ShadowResponse] = {}
        self._question_hashes: set = set()

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
            sender: Anonymized sender ID (optional)
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
                for ctx_msg in context_messages:
                    ctx_sender = ctx_msg.get("sender", "")

                    # Skip bystander messages (not from the current sender)
                    if self._anonymize_sender(ctx_sender) != self._anonymize_sender(
                        sender
                    ):
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
                user_id=self._anonymize_sender(sender) if sender else "anonymous",
                messages=aggregated_messages,
                synthesized_question=sanitized_question,
                detected_version=normalized_version,
                version_confidence=version_confidence,
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

            # Track question hash for duplicate detection
            question_hash = self._hash_question(sanitized_question)
            self._question_hashes.add(question_hash)

            logger.info(
                f"Processed question {question_id}: "
                f"detected_version={normalized_version}, confidence={version_confidence:.0%}, "
                f"context_messages={len(aggregated_messages) - 1}"
            )

            return response

        except Exception as e:
            logger.error(f"Error processing question {question_id}: {e}")
            return None

    def get_response(self, question_id: str) -> Optional[ShadowResponse]:
        """
        Get a stored response by ID.

        Args:
            question_id: The question ID to retrieve

        Returns:
            ShadowResponse if found, None otherwise
        """
        return self._responses.get(question_id)

    def get_pending_responses(self) -> List[ShadowResponse]:
        """
        Get all unprocessed responses awaiting review.

        Returns:
            List of unprocessed ShadowResponses
        """
        return [
            r
            for r in self._responses.values()
            if r.status == ShadowStatus.PENDING_VERSION_REVIEW
        ]

    def mark_as_processed(self, question_id: str) -> None:
        """
        Mark a response as processed.

        Args:
            question_id: The question ID to mark
        """
        if question_id in self._responses:
            self._responses[question_id].status = ShadowStatus.APPROVED

    async def is_support_question(
        self,
        text: str,
        sender: str = "",
        prev_messages: Optional[List[str]] = None,
    ) -> bool:
        """
        Detect if text is a support question using multi-layer classification.

        Args:
            text: Text to analyze
            sender: Sender ID (e.g., @username:matrix.org) for staff detection
            prev_messages: Previous messages in conversation for context analysis

        Returns:
            True if text appears to be a genuine user support question
        """
        # Run multi-layer classification using instance classifier (supports LLM fallback)
        result = await self.classifier.classify_message(
            text, sender, prev_messages or []
        )

        # Log classification details for monitoring
        if not result["is_question"]:
            logger.debug(
                f"Filtered message: reason={result['reason']}, "
                f"speaker={result['speaker_role']}, intent={result['intent']}, "
                f"confidence={result['confidence']:.2f}"
            )

        return result["is_question"]

    @staticmethod
    def is_support_staff(sender: str) -> bool:
        """
        Check if sender is a support staff member.

        Args:
            sender: Matrix user ID (e.g., @username:server.com)

        Returns:
            True if sender is support staff
        """
        sender_lower = sender.lower()
        for staff in ShadowModeProcessor.SUPPORT_STAFF:
            if staff.lower() in sender_lower:
                return True
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

            # Remove potential Bitcoin addresses
            text = re.sub(
                r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b",
                "[BTC_ADDRESS]",
                text,
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

            # Matrix user mentions (@username:matrix.org)
            text = re.sub(
                r"@[^:]+:matrix\.org",
                "@[USER]:matrix.org",
                text,
            )

            return text

        except Exception as e:
            logger.error(f"PII scrubbing failed: {e}")
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
