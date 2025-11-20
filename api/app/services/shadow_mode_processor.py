"""Shadow mode processor for Matrix support channel monitoring."""

import hashlib
import logging
import re
from typing import Dict, List, Optional

from app.models.shadow_response import ShadowResponse
from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.confidence_scorer import ConfidenceScorer

logger = logging.getLogger(__name__)


class ShadowModeProcessor:
    """Process Matrix questions through RAG pipeline without sending to users."""

    # Question detection patterns
    QUESTION_PATTERNS = [
        r"\?$",  # Ends with question mark
        r"^(?:what|how|why|where|when|who|which|can|could|would|should|is|are|do|does)\s",
        r"^(?:help|please help|can.+help|need help)",  # Help at start of message
        r"(?:i'm stuck|my .+ stuck|problem with|issue with|error|failing)",
    ]

    def __init__(
        self,
        rag_service,
        confidence_scorer: ConfidenceScorer,
        router: AutoSendRouter,
    ):
        """
        Initialize shadow mode processor.

        Args:
            rag_service: RAG service for question answering
            confidence_scorer: Confidence scorer for answer validation
            router: Router for routing decisions
        """
        self.rag_service = rag_service
        self.confidence_scorer = confidence_scorer
        self.router = router
        self._responses: Dict[str, ShadowResponse] = {}
        self._question_hashes: set = set()

    async def process_question(
        self,
        question: str,
        question_id: str,
        room_id: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> Optional[ShadowResponse]:
        """
        Process a question through the RAG pipeline.

        Args:
            question: The user's question
            question_id: Unique identifier for tracking
            room_id: Matrix room ID (optional)
            sender: Anonymized sender ID (optional)

        Returns:
            ShadowResponse with answer and confidence, or None on error
        """
        try:
            # Scrub PII from question
            sanitized_question = self._scrub_pii(question)

            # Query RAG service
            result = await self.rag_service.query(sanitized_question)

            answer = result.get("answer", "")
            sources = result.get("sources", [])
            confidence = result.get("confidence", 0.0)

            # Get routing decision
            routing_action = await self.router.route_response(
                confidence=confidence,
                question=sanitized_question,
                answer=answer,
                sources=[],  # Simplified for now
            )

            # Create shadow response
            response = ShadowResponse(
                question_id=question_id,
                question=sanitized_question,
                answer=answer,
                confidence=confidence,
                sources=sources if isinstance(sources, list) else [sources],
                room_id=room_id,
                sender=self._anonymize_sender(sender) if sender else None,
                routing_action=routing_action.action,
            )

            # Store response
            self._responses[question_id] = response

            # Track question hash for duplicate detection
            question_hash = self._hash_question(sanitized_question)
            self._question_hashes.add(question_hash)

            logger.info(
                f"Processed question {question_id}: "
                f"confidence={confidence:.2f}, "
                f"routing={routing_action.action}"
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
        return [r for r in self._responses.values() if not r.processed]

    def mark_as_processed(self, question_id: str) -> None:
        """
        Mark a response as processed.

        Args:
            question_id: The question ID to mark
        """
        if question_id in self._responses:
            self._responses[question_id].processed = True

    @staticmethod
    def is_support_question(text: str) -> bool:
        """
        Detect if text is a support question.

        Args:
            text: Text to analyze

        Returns:
            True if text appears to be a support question
        """
        text_lower = text.lower().strip()

        for pattern in ShadowModeProcessor.QUESTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True

        return False

    def _scrub_pii(self, text: str) -> str:
        """
        Remove personally identifiable information from text.

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text
        """
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

        return text

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
