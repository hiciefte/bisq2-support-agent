"""
Unified Pipeline Service for FAQ Training.

This service orchestrates the processing of support conversations from both
Bisq 2 in-app chat and Matrix chat sources, managing the comparison workflow,
routing decisions, and review actions.

Architecture:
    - Processes conversations from both Bisq 2 API and Matrix sources
    - Uses RAG service to generate answers for comparison
    - Routes candidates based on comparison scores and calibration state
    - Manages review workflow (approve/reject/skip)
    - Creates verified FAQs with source preservation
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, cast

# Import sync services at module level for testability (mocking)
from app.channels.plugins.bisq2.client.api import Bisq2API
from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
from app.channels.plugins.bisq2.services.sync_service import Bisq2SyncService
from app.channels.plugins.matrix.client.polling_state import PollingStateManager

# Import shared threshold constants from config
from app.core.config import (
    PIPELINE_AUTO_APPROVE_THRESHOLD,
    PIPELINE_DUPLICATE_FAQ_THRESHOLD,
    PIPELINE_SPOT_CHECK_THRESHOLD,
)
from app.metrics.training_metrics import (
    record_duplicate_detection,
    training_auto_approvals,
    training_comparison_duration,
    training_correction_resolutions,
    training_faqs_created,
    training_final_scores,
    training_human_reviews,
    training_pairs_processed,
    training_post_approval_corrections,
    update_calibration_metrics,
    update_queue_metrics,
)
from app.models.faq import FAQItem
from app.services.rag.protocol_detector import ProtocolDetector, Source
from app.services.training.matrix_sync_service import MatrixSyncService
from app.services.training.unified_repository import (
    CalibrationStatus,
    UnifiedFAQCandidate,
    UnifiedFAQCandidateRepository,
)

logger = logging.getLogger(__name__)

# Re-export threshold constants for backward compatibility and convenience
# These reference the central config values to ensure consistency
AUTO_APPROVE_THRESHOLD = PIPELINE_AUTO_APPROVE_THRESHOLD
SPOT_CHECK_THRESHOLD = PIPELINE_SPOT_CHECK_THRESHOLD
DUPLICATE_FAQ_THRESHOLD = PIPELINE_DUPLICATE_FAQ_THRESHOLD

# Human-readable source names for FAQ display
# Maps internal source identifiers to user-friendly names
SOURCE_DISPLAY_NAMES: Dict[str, str] = {
    "bisq2": "Bisq Support Chat",
    "matrix": "Matrix Support",
}


def get_faq_source_display_name(source: str) -> str:
    """Get human-readable display name for a FAQ source.

    Args:
        source: Internal source identifier (e.g., "bisq2", "matrix")

    Returns:
        Human-readable source name for display
    """
    return SOURCE_DISPLAY_NAMES.get(source, f"Extracted:{source}")


@dataclass
class ComparisonResult:
    """Result of comparing staff answer with RAG-generated answer."""

    embedding_similarity: float
    factual_alignment: float
    contradiction_score: float
    completeness: float
    hallucination_risk: float
    final_score: float
    llm_reasoning: str


@dataclass
class ProcessingResult:
    """Result of processing a conversation or answer."""

    candidate_id: Optional[int]
    source: str
    source_event_id: str
    routing: str
    final_score: float
    is_calibration_sample: bool
    skipped_reason: Optional[str] = None


@dataclass
class PostApprovalCorrectionResult:
    """Result of processing a post-approval correction.

    When a staff member corrects their answer after the FAQ has already been
    approved and created, this result contains information about how the
    correction was handled.

    Attributes:
        thread_id: ID of the affected thread
        faq_id: ID of the FAQ that was flagged
        faq_flagged: Whether the FAQ was flagged for review
        correction_stored: Whether the correction content was stored
        correction_reason: Reason string stored in the thread
    """

    thread_id: int
    faq_id: str
    faq_flagged: bool
    correction_stored: bool
    correction_reason: str


class DuplicateFAQError(Exception):
    """Raised when approving a candidate that duplicates an existing FAQ.

    This error is raised during the approval process when a semantically similar
    FAQ already exists in the system (similarity > 0.85 threshold).

    Attributes:
        similar_faqs: List of similar FAQs found (id, question, answer, similarity)
        candidate_id: ID of the candidate that triggered the duplication check
    """

    def __init__(self, message: str, similar_faqs: list, candidate_id: int):
        super().__init__(message)
        self.similar_faqs = similar_faqs
        self.candidate_id = candidate_id


class UnifiedPipelineService:
    """
    Orchestrates the unified FAQ training pipeline.

    This service handles:
    - Processing Bisq 2 and Matrix conversations
    - Generating RAG answers for comparison
    - Calculating comparison scores
    - Routing based on calibration state and thresholds
    - Managing review actions (approve/reject/skip)
    - Creating verified FAQs with source preservation
    """

    def __init__(
        self,
        settings: Any = None,
        rag_service: Any = None,
        faq_service: Any = None,
        db_path: Optional[str] = None,
        comparison_engine: Optional[Any] = None,
        repository: Optional[UnifiedFAQCandidateRepository] = None,
        aisuite_client: Any = None,
        learning_engine: Any = None,
    ):
        """
        Initialize the pipeline service.

        Args:
            settings: Application settings (optional, for future use)
            rag_service: RAG service for generating answers
            faq_service: FAQ service for creating verified FAQs
            db_path: Path to SQLite database (used if repository not provided)
            comparison_engine: Optional comparison engine for scoring
            repository: Optional pre-configured repository (takes precedence over db_path)
            aisuite_client: AISuite client for LLM calls in FAQ extraction
            learning_engine: Optional LearningEngine for adaptive threshold tuning
        """
        self.settings = settings
        self.rag_service = rag_service
        self.faq_service = faq_service
        self.comparison_engine = comparison_engine
        self.aisuite_client = aisuite_client
        self.learning_engine = learning_engine

        # Protocol detector for direct protocol detection from text
        self.protocol_detector = ProtocolDetector()

        # Create repository from db_path or use provided repository
        if repository is not None:
            self.repository = repository
        elif db_path is not None:
            self.repository = UnifiedFAQCandidateRepository(db_path)
        else:
            raise ValueError("Either repository or db_path must be provided")

    def _detect_protocol_with_fallback(
        self,
        question_text: str,
        staff_answer: str,
        source: Optional[Source] = None,
    ) -> Optional[str]:
        """Detect Bisq protocol from question, with staff answer and source fallback.

        Detection priority:
        1. Question text with explicit protocol keywords -> detected protocol
        2. Staff answer with explicit protocol keywords -> detected protocol
        3. Source-based default (bisq2 -> bisq_easy) if no explicit detection
        4. None if no detection and no source default

        The source provides a default when content detection is ambiguous.
        For example, messages from bisq2 source default to bisq_easy,
        since the Bisq 2 Support API is primarily for Bisq Easy questions.
        However, if the content clearly indicates Bisq 1 (DAO, BSQ, etc.),
        the detection will override the source default.

        Args:
            question_text: The user's question
            staff_answer: The staff member's answer
            source: Message source ("bisq2", "matrix", or None)

        Returns:
            Protocol string ("bisq_easy", "multisig_v1") if detected with
            sufficient confidence or from source default, None otherwise.
        """
        # First try detecting from question content (without source default)
        # This ensures explicit protocol keywords in content take priority
        protocol, confidence = self.protocol_detector.detect_protocol_from_text(
            question_text
        )
        if protocol is not None and confidence >= 0.6:
            logger.debug(
                f"Protocol detected from question: {protocol} "
                f"(confidence: {confidence})"
            )
            return protocol

        # Fallback: try detecting from staff answer content (without source default)
        # Staff answers often contain protocol-specific terms like "DAO", "BSQ"
        protocol, confidence = self.protocol_detector.detect_protocol_from_text(
            staff_answer
        )
        if protocol is not None and confidence >= 0.6:
            logger.debug(
                f"Protocol detected from staff answer: {protocol} "
                f"(confidence: {confidence})"
            )
            return protocol

        # No explicit detection - apply source-based default if available
        # This is the fallback for truly ambiguous content
        protocol = self.protocol_detector.detect_protocol_with_source_default(
            text=question_text, source=source
        )
        if protocol is not None:
            logger.debug(f"Using source default protocol: {protocol}")
            return protocol

        return None

    async def process_matrix_answer(
        self,
        event_id: str,
        staff_answer: str,
        reply_to_event_id: str,
        question_text: str,
        staff_sender: str,
        source_timestamp: Optional[str] = None,
        room_id: Optional[str] = None,
        question_sender: Optional[str] = None,
    ) -> Optional[ProcessingResult]:
        """
        Process a Matrix staff answer.

        Args:
            event_id: Matrix event ID for the answer
            staff_answer: The staff's answer text
            reply_to_event_id: Event ID of the question being answered
            question_text: The original question text
            staff_sender: Matrix user ID of the staff member
            source_timestamp: Optional timestamp of the answer
            room_id: Optional Matrix room ID for thread tracking
            question_sender: Optional sender ID of the question

        Returns:
            ProcessingResult if candidate created, None if skipped
        """
        source_event_id = event_id

        # Check for duplicates
        if self.repository.exists_by_event_id(source_event_id):
            return ProcessingResult(
                candidate_id=None,
                source="matrix",
                source_event_id=source_event_id,
                routing="SKIPPED",
                final_score=0.0,
                is_calibration_sample=False,
                skipped_reason="duplicate",
            )

        if source_timestamp is None:
            source_timestamp = datetime.now(timezone.utc).isoformat()

        # ===== Thread Management (Cycle 12) =====
        # Check if thread exists for this question (may have been created in prior poll)
        thread = self.repository.find_thread_by_message(reply_to_event_id)
        if thread is None:
            # Create new thread for this Q&A
            thread = self.repository.create_thread(
                source="matrix",
                first_question_id=reply_to_event_id,
                room_id=room_id,
            )
            # Add question message to thread
            self.repository.add_message_to_thread(
                thread_id=thread.id,
                message_id=reply_to_event_id,
                message_type="question",
                content=question_text,
                sender_id=question_sender,
                timestamp=source_timestamp,
            )
            # Transition to has_staff_answer since we got both together
            self.repository.transition_thread_state(
                thread_id=thread.id,
                to_state="has_staff_answer",
                trigger="staff_answer_received",
                metadata={"answer_event_id": event_id},
            )
        else:
            # Thread exists, transition state if still pending
            if thread.state == "pending_question":
                self.repository.transition_thread_state(
                    thread_id=thread.id,
                    to_state="has_staff_answer",
                    trigger="staff_answer_received",
                    metadata={"answer_event_id": event_id},
                )

        # Add answer message to thread
        self.repository.add_message_to_thread(
            thread_id=thread.id,
            message_id=event_id,
            message_type="staff_answer",
            content=staff_answer,
            sender_id=staff_sender,
            timestamp=source_timestamp,
        )
        # ===== End Thread Management =====

        # Detect protocol directly from question, with staff answer as fallback
        # Pass source="matrix" for Matrix messages
        detected_protocol = self._detect_protocol_with_fallback(
            question_text, staff_answer, source="matrix"
        )

        # Convert protocol to version string for RAG service (backwards compat)
        override_version = self.protocol_detector._protocol_to_version(
            detected_protocol
        )

        # Generate RAG answer with detected version (if available)
        # NOTE: SimplifiedRAGService.query() returns {"answer": ..., "sources": ...}
        # The key is "answer", not "response"
        rag_response = await self.rag_service.query(
            question_text, chat_history=[], override_version=override_version
        )
        generated_answer = rag_response.get("answer", "")
        sources = rag_response.get("sources", [])
        sources_json = json.dumps(sources) if sources else None
        # Extract RAG's own confidence (distinct from comparison final_score)
        generation_confidence = rag_response.get("confidence")

        # Calculate comparison scores
        comparison = await self._compare_answers(
            source_event_id, question_text, staff_answer, generated_answer
        )

        # Determine routing
        routing, is_calibration = self._determine_routing(comparison.final_score)

        # Create candidate
        candidate = self.repository.create(
            source="matrix",
            source_event_id=source_event_id,
            source_timestamp=source_timestamp,
            question_text=question_text,
            staff_answer=staff_answer,
            generated_answer=generated_answer,
            staff_sender=staff_sender,
            embedding_similarity=comparison.embedding_similarity,
            factual_alignment=comparison.factual_alignment,
            contradiction_score=comparison.contradiction_score,
            completeness=comparison.completeness,
            hallucination_risk=comparison.hallucination_risk,
            final_score=comparison.final_score,
            llm_reasoning=comparison.llm_reasoning,
            routing=routing,
            is_calibration_sample=is_calibration,
            protocol=detected_protocol,
            generated_answer_sources=sources_json,
            generation_confidence=generation_confidence,
        )

        # Link thread to candidate (Cycle 12)
        self.repository.link_thread_to_candidate(
            thread_id=thread.id,
            candidate_id=candidate.id,
            trigger="candidate_created",
        )

        # Increment calibration count if in calibration mode
        if is_calibration:
            self.repository.increment_calibration_count()
            # Update calibration metrics
            update_calibration_metrics(self.repository.get_calibration_status())

        # Record metrics
        training_pairs_processed.labels(routing=routing).inc()
        training_final_scores.observe(comparison.final_score)
        if routing == "AUTO_APPROVE":
            training_auto_approvals.inc()

        # Update queue metrics
        update_queue_metrics(self.repository.get_queue_counts())

        return ProcessingResult(
            candidate_id=candidate.id,
            source="matrix",
            source_event_id=source_event_id,
            routing=routing,
            final_score=comparison.final_score,
            is_calibration_sample=is_calibration,
        )

    async def process_correction(
        self,
        event_id: str,
        correction_content: str,
        reply_to_event_id: str,
        staff_sender: str,
        source_timestamp: Optional[str] = None,
    ) -> ProcessingResult:
        """
        Process a staff correction message (Cycle 13: Pre-approval corrections).

        When a staff member sends a correction before the candidate is approved,
        this method updates the existing candidate rather than creating a new one.
        If the candidate is already approved or no thread exists, appropriate
        handling is applied.

        Args:
            event_id: Matrix event ID for the correction message
            correction_content: The corrected answer text
            reply_to_event_id: Event ID of the original question
            staff_sender: Matrix user ID of the staff member
            source_timestamp: Optional timestamp of the correction

        Returns:
            ProcessingResult indicating outcome of correction processing
        """
        if source_timestamp is None:
            source_timestamp = datetime.now(timezone.utc).isoformat()

        # Find thread by the original question message ID
        thread = self.repository.find_thread_by_message(reply_to_event_id)

        if thread is None:
            # No existing thread - correction to unknown question
            return ProcessingResult(
                candidate_id=None,
                source="matrix",
                source_event_id=event_id,
                routing="SKIPPED",
                final_score=0.0,
                is_calibration_sample=False,
                skipped_reason="no_existing_thread",
            )

        # Check if candidate exists and its status
        candidate = (
            self.repository.get_by_id(thread.candidate_id)
            if thread.candidate_id
            else None
        )

        if candidate is None:
            # Thread exists but no candidate yet (question but no staff answer processed)
            # This shouldn't normally happen, but treat as orphan correction
            return ProcessingResult(
                candidate_id=None,
                source="matrix",
                source_event_id=event_id,
                routing="SKIPPED",
                final_score=0.0,
                is_calibration_sample=False,
                skipped_reason="no_candidate_for_thread",
            )

        # Check if candidate is already approved
        if candidate.review_status == "approved":
            # Post-approval correction - handled by Cycle 17, not here
            return ProcessingResult(
                candidate_id=candidate.id,
                source="matrix",
                source_event_id=event_id,
                routing="SKIPPED",
                final_score=candidate.final_score or 0.0,
                is_calibration_sample=False,
                skipped_reason="candidate_already_approved",
            )

        # Add correction message to thread
        self.repository.add_message_to_thread(
            thread_id=thread.id,
            message_id=event_id,
            message_type="correction",
            content=correction_content,
            sender_id=staff_sender,
            timestamp=source_timestamp,
        )

        # Transition thread state to has_correction
        self.repository.transition_thread_state(
            thread_id=thread.id,
            to_state="has_correction",
            trigger="correction_received",
            metadata={
                "correction_event_id": event_id,
                "original_answer": candidate.staff_answer,
            },
        )

        # Re-run comparison with corrected answer
        comparison = await self._compare_answers(
            candidate.source_event_id,
            candidate.question_text,
            correction_content,
            candidate.generated_answer or "",
        )

        # Determine new routing
        routing, _ = self._determine_routing(comparison.final_score)

        # Update the candidate with corrected answer and new scores
        self.repository.update_candidate(
            candidate_id=candidate.id,
            staff_answer=correction_content,
            has_correction=True,
            embedding_similarity=comparison.embedding_similarity,
            factual_alignment=comparison.factual_alignment,
            contradiction_score=comparison.contradiction_score,
            completeness=comparison.completeness,
            hallucination_risk=comparison.hallucination_risk,
            final_score=comparison.final_score,
            llm_reasoning=comparison.llm_reasoning,
            routing=routing,
        )

        logger.info(
            f"Processed correction for candidate {candidate.id}: "
            f"score={comparison.final_score:.2f}, routing={routing}"
        )

        return ProcessingResult(
            candidate_id=candidate.id,
            source="matrix",
            source_event_id=event_id,
            routing=routing,
            final_score=comparison.final_score,
            is_calibration_sample=False,
        )

    async def process_bisq_conversation(
        self,
        conversation: Dict[str, Any],
    ) -> Optional[ProcessingResult]:
        """
        Process a Bisq 2 conversation and extract Q&A pairs.

        Identifies staff replies following user questions and processes them
        through the pipeline. Staff users are identified via settings.BISQ_STAFF_USERS.

        Args:
            conversation: Conversation dict with:
                - thread_id: Thread identifier
                - channel_id: Channel identifier (optional)
                - timestamp: Conversation timestamp (optional)
                - messages: List of message dicts with messageId, message, author, date

        Returns:
            ProcessingResult for the last processed Q&A pair, or None if no pairs found
        """
        messages = conversation.get("messages", [])
        if len(messages) < 2:
            return None

        # Get staff users from settings
        staff_users = getattr(self.settings, "BISQ_STAFF_USERS", [])
        if isinstance(staff_users, str):
            staff_users = [s.strip() for s in staff_users.split(",") if s.strip()]
        staff_users_lower = {s.lower() for s in staff_users}

        # Extract Q&A pairs: look for staff answer following non-staff question
        result = None
        last_user_message = None

        for msg in messages:
            # Check is_support field first (test fixture format), then fall back to author check
            if "is_support" in msg:
                is_staff = msg.get("is_support", False)
            else:
                author = msg.get("author", msg.get("sender", ""))
                is_staff = author.lower() in staff_users_lower if author else False

            if not is_staff:
                # Track the last non-staff message as potential question
                last_user_message = msg
            elif is_staff and last_user_message is not None:
                # Staff reply to a user message - this is a Q&A pair
                thread_id = conversation.get("thread_id", "")
                channel_id = conversation.get("channel_id")
                pair_result = await self.process_bisq_qa_pair(
                    question_msg=last_user_message,
                    answer_msg=msg,
                    thread_id=thread_id,
                    channel_id=channel_id,
                )
                if pair_result is not None:
                    result = pair_result
                # Reset to detect next pair
                last_user_message = None

        return result

    async def process_bisq_qa_pair(
        self,
        question_msg: Dict[str, Any],
        answer_msg: Dict[str, Any],
        thread_id: str = "",
        channel_id: Optional[str] = None,
    ) -> Optional[ProcessingResult]:
        """
        Process a Q&A pair from flat Bisq messages.

        Args:
            question_msg: The user's question message
            answer_msg: The staff's answer message
            thread_id: Thread/conversation ID for uniqueness
            channel_id: Optional channel ID for thread tracking

        Returns:
            ProcessingResult if candidate created, None if skipped
        """
        # Build source event ID from thread and message IDs
        # Support both 'messageId' (production) and 'msg_id' (test fixture) field names
        q_id = question_msg.get("messageId") or question_msg.get("msg_id", "")
        a_id = answer_msg.get("messageId") or answer_msg.get("msg_id", "")
        # Include thread_id if available for better uniqueness
        if thread_id:
            source_event_id = f"bisq2_{thread_id}_{a_id}"
        else:
            source_event_id = f"bisq2_{q_id}_{a_id}"

        # Check for duplicates
        if self.repository.exists_by_event_id(source_event_id):
            return ProcessingResult(
                candidate_id=None,
                source="bisq2",
                source_event_id=source_event_id,
                routing="SKIPPED",
                final_score=0.0,
                is_calibration_sample=False,
                skipped_reason="duplicate",
            )

        # Support both 'message' (production) and 'content' (test fixture) field names
        question_text = question_msg.get("message") or question_msg.get("content", "")
        staff_answer = answer_msg.get("message") or answer_msg.get("content", "")
        # Support both 'author' (production) and 'sender' (test fixture) field names
        staff_sender = answer_msg.get("author") or answer_msg.get("sender", "")
        question_sender = question_msg.get("author") or question_msg.get("sender", "")
        # Support both 'date' (production) and 'timestamp' (test fixture) field names
        source_timestamp = (
            answer_msg.get("date")
            or answer_msg.get("timestamp")
            or datetime.now(timezone.utc).isoformat()
        )
        question_timestamp = (
            question_msg.get("date")
            or question_msg.get("timestamp")
            or source_timestamp
        )

        # Skip if question or answer is too short
        if len(question_text.strip()) < 10 or len(staff_answer.strip()) < 10:
            return None

        # ===== Thread Management (Cycle 12) =====
        # Check if thread exists for this question
        conv_thread = self.repository.find_thread_by_message(q_id)
        if conv_thread is None:
            # Create new thread for this Q&A
            conv_thread = self.repository.create_thread(
                source="bisq2",
                first_question_id=q_id,
                room_id=channel_id,
            )
            # Add question message to thread
            self.repository.add_message_to_thread(
                thread_id=conv_thread.id,
                message_id=q_id,
                message_type="question",
                content=question_text,
                sender_id=question_sender,
                timestamp=question_timestamp,
            )
            # Transition to has_staff_answer since we got both together
            self.repository.transition_thread_state(
                thread_id=conv_thread.id,
                to_state="has_staff_answer",
                trigger="staff_answer_received",
                metadata={"answer_id": a_id},
            )
        else:
            # Thread exists, transition state if still pending
            if conv_thread.state == "pending_question":
                self.repository.transition_thread_state(
                    thread_id=conv_thread.id,
                    to_state="has_staff_answer",
                    trigger="staff_answer_received",
                    metadata={"answer_id": a_id},
                )

        # Add answer message to thread
        self.repository.add_message_to_thread(
            thread_id=conv_thread.id,
            message_id=a_id,
            message_type="staff_answer",
            content=staff_answer,
            sender_id=staff_sender,
            timestamp=source_timestamp,
        )
        # ===== End Thread Management =====

        # Detect protocol directly from question, with staff answer as fallback
        # Pass source="bisq2" for Bisq 2 Support API messages
        detected_protocol = self._detect_protocol_with_fallback(
            question_text, staff_answer, source="bisq2"
        )

        # Convert protocol to version string for RAG service (backwards compat)
        override_version = self.protocol_detector._protocol_to_version(
            detected_protocol
        )

        # Generate RAG answer with detected version (if available)
        rag_response = await self.rag_service.query(
            question_text, chat_history=[], override_version=override_version
        )
        generated_answer = rag_response.get("answer", "")
        sources = rag_response.get("sources", [])
        sources_json = json.dumps(sources) if sources else None
        # Extract RAG's own confidence (distinct from comparison final_score)
        generation_confidence = rag_response.get("confidence")

        # Calculate comparison scores
        comparison = await self._compare_answers(
            source_event_id, question_text, staff_answer, generated_answer
        )

        # Determine routing
        routing, is_calibration = self._determine_routing(comparison.final_score)

        # Create candidate
        candidate = self.repository.create(
            source="bisq2",
            source_event_id=source_event_id,
            source_timestamp=source_timestamp,
            question_text=question_text,
            staff_answer=staff_answer,
            generated_answer=generated_answer,
            staff_sender=staff_sender,
            embedding_similarity=comparison.embedding_similarity,
            factual_alignment=comparison.factual_alignment,
            contradiction_score=comparison.contradiction_score,
            completeness=comparison.completeness,
            hallucination_risk=comparison.hallucination_risk,
            final_score=comparison.final_score,
            llm_reasoning=comparison.llm_reasoning,
            routing=routing,
            is_calibration_sample=is_calibration,
            protocol=detected_protocol,
            generated_answer_sources=sources_json,
            generation_confidence=generation_confidence,
        )

        # Link thread to candidate (Cycle 12)
        self.repository.link_thread_to_candidate(
            thread_id=conv_thread.id,
            candidate_id=candidate.id,
            trigger="candidate_created",
        )

        # Increment calibration count if in calibration mode
        if is_calibration:
            self.repository.increment_calibration_count()
            update_calibration_metrics(self.repository.get_calibration_status())

        # Record metrics
        training_pairs_processed.labels(routing=routing).inc()
        training_final_scores.observe(comparison.final_score)
        if routing == "AUTO_APPROVE":
            training_auto_approvals.inc()

        # Update queue metrics
        update_queue_metrics(self.repository.get_queue_counts())

        return ProcessingResult(
            candidate_id=candidate.id,
            source="bisq2",
            source_event_id=source_event_id,
            routing=routing,
            final_score=comparison.final_score,
            is_calibration_sample=is_calibration,
        )

    async def _compare_answers(
        self,
        source_event_id: str,
        question: str,
        staff_answer: str,
        generated_answer: str,
    ) -> ComparisonResult:
        """
        Compare staff answer with RAG-generated answer.

        Uses comparison engine if available, otherwise returns mock scores.
        Handles empty generated answers by returning low scores with honest reasoning.

        Args:
            source_event_id: The source event ID for tracking
            question: The original question
            staff_answer: The staff's answer
            generated_answer: The RAG-generated answer

        Returns:
            ComparisonResult with all comparison metrics
        """
        import time

        start_time = time.time()

        try:
            # CRITICAL: Check for empty generated answer FIRST
            # Empty RAG response means we couldn't generate an answer
            if not generated_answer or not generated_answer.strip():
                return ComparisonResult(
                    embedding_similarity=0.0,
                    factual_alignment=0.0,
                    contradiction_score=0.0,
                    completeness=0.0,
                    hallucination_risk=0.0,
                    final_score=0.0,
                    llm_reasoning="RAG system returned empty response. Unable to compare with staff answer. Requires full human review.",
                )

            if self.comparison_engine is not None:
                # Use actual comparison engine
                # NOTE: compare() expects (question_event_id, question_text, staff_answer, generated_answer)
                result = await self.comparison_engine.compare(
                    source_event_id, question, staff_answer, generated_answer
                )
                return ComparisonResult(
                    embedding_similarity=result.embedding_similarity,
                    factual_alignment=result.factual_alignment,
                    contradiction_score=result.contradiction_score,
                    completeness=result.completeness,
                    hallucination_risk=result.hallucination_risk,
                    final_score=result.final_score,
                    llm_reasoning=result.llm_reasoning,
                )

            # Default mock comparison for testing (no comparison engine provided)
            # NOTE: These are MOCK scores for testing only, not real comparisons
            return ComparisonResult(
                embedding_similarity=0.50,
                factual_alignment=0.50,
                contradiction_score=0.50,
                completeness=0.50,
                hallucination_risk=0.50,
                final_score=0.50,
                llm_reasoning="Mock comparison (no comparison engine configured). Manual review recommended.",
            )
        finally:
            # Record comparison duration
            duration = time.time() - start_time
            training_comparison_duration.observe(duration)

    def _determine_routing(self, final_score: float) -> tuple[str, bool]:
        """
        Determine routing based on score and calibration state.

        During calibration mode, all candidates go to FULL_REVIEW
        to establish accurate baseline thresholds.

        After calibration, uses LearningEngine adaptive thresholds if available,
        otherwise falls back to hardcoded thresholds:
        - score >= 0.90: AUTO_APPROVE
        - score >= 0.75: SPOT_CHECK
        - score < 0.75: FULL_REVIEW

        Args:
            final_score: The final comparison score

        Returns:
            Tuple of (routing, is_calibration_sample)
        """
        is_calibration = self.repository.is_calibration_mode()

        if is_calibration:
            # During calibration, everything goes to FULL_REVIEW
            return "FULL_REVIEW", True

        # Post-calibration: Use LearningEngine if available for adaptive thresholds
        if self.learning_engine is not None:
            routing = self.learning_engine.get_routing_recommendation(final_score)
            return routing, False

        # Fallback to hardcoded thresholds if no learning_engine
        if final_score >= AUTO_APPROVE_THRESHOLD:
            return "AUTO_APPROVE", False
        elif final_score >= SPOT_CHECK_THRESHOLD:
            return "SPOT_CHECK", False
        else:
            return "FULL_REVIEW", False

    async def approve_candidate(
        self,
        candidate_id: int,
        reviewer: str,
    ) -> str:
        """
        Approve a candidate and create a verified FAQ.

        Creates the FAQ with source preservation (Extracted:bisq2 or Extracted:matrix)
        and marks it as verified since pipeline approval IS verification.

        Before creating the FAQ, checks for semantically similar FAQs that already
        exist in the system. If duplicates are found (similarity > 0.85), the
        approval is blocked.

        Args:
            candidate_id: ID of the candidate to approve
            reviewer: Username of the reviewer

        Returns:
            The created FAQ ID

        Raises:
            ValueError: If candidate not found
            DuplicateFAQError: If similar FAQ(s) already exist (similarity > 0.85)
        """
        candidate = self.repository.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Check for duplicate FAQs before creating
        # Use edited question if available (admin may have improved phrasing)
        question_to_check = candidate.edited_question_text or candidate.question_text
        if self.rag_service is not None:
            similar_faqs = await self.rag_service.search_faq_similarity(
                question=question_to_check,
                threshold=DUPLICATE_FAQ_THRESHOLD,
                limit=3,
            )
            if similar_faqs:
                # Record metrics for duplicate detection
                for faq in similar_faqs:
                    record_duplicate_detection(faq.get("similarity", 0.0))
                raise DuplicateFAQError(
                    f"Cannot approve: {len(similar_faqs)} similar FAQ(s) already exist",
                    similar_faqs=similar_faqs,
                    candidate_id=candidate_id,
                )

        # Use human-readable source name for FAQ display
        faq_source = get_faq_source_display_name(candidate.source)
        now = datetime.now(timezone.utc)

        # Use edited versions if available, otherwise use original values
        final_answer = candidate.edited_staff_answer or candidate.staff_answer
        final_question = candidate.edited_question_text or candidate.question_text

        # Create verified FAQ using FAQItem model
        faq_item = FAQItem(
            question=final_question,
            answer=final_answer,
            source=faq_source,
            verified=True,  # Pipeline approval = admin verification
            verified_at=now,
            created_at=now,
            protocol=cast(
                Literal["multisig_v1", "bisq_easy", "musig", "all"],
                candidate.protocol,
            ),  # Preserve protocol context from candidate
            category=candidate.category
            or "General",  # Preserve category from candidate
        )
        faq = self.faq_service.add_faq(faq_item)

        faq_id = faq.id if hasattr(faq, "id") else str(faq)

        # Update candidate status
        self.repository.approve(candidate_id, reviewer, faq_id)

        # Close the thread if one exists (Cycle 12)
        thread = self.repository.find_thread_by_candidate_id(candidate_id)
        if thread is not None:
            self.repository.link_thread_to_faq(
                thread_id=thread.id,
                faq_id=faq_id,
                trigger="faq_approved",
            )

        # Record metrics
        training_faqs_created.inc()
        training_human_reviews.labels(outcome="approved").inc()

        # Update queue metrics after approval
        update_queue_metrics(self.repository.get_queue_counts())

        return faq_id

    async def reject_candidate(
        self,
        candidate_id: int,
        reviewer: str,
        reason: str,
    ) -> bool:
        """
        Reject a candidate with a reason.

        Args:
            candidate_id: ID of the candidate to reject
            reviewer: Username of the reviewer
            reason: Reason for rejection

        Returns:
            True if rejection successful
        """
        candidate = self.repository.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        self.repository.reject(candidate_id, reviewer, reason)

        # Record metrics
        training_human_reviews.labels(outcome="rejected").inc()

        # Update queue metrics after rejection
        update_queue_metrics(self.repository.get_queue_counts())

        return True

    async def process_post_approval_correction(
        self,
        event_id: str,
        correction_content: str,
        reply_to_event_id: str,
        staff_sender: str,
    ) -> Optional[PostApprovalCorrectionResult]:
        """
        Process a correction that arrives after FAQ approval.

        This handles the scenario where a staff member corrects their answer after
        the candidate has been approved and an FAQ created. Instead of silently
        ignoring the correction or creating a duplicate, we flag the FAQ for
        admin review.

        Cycle 17: Post-approval correction detection.

        Args:
            event_id: Unique ID of the correction message
            correction_content: The correction text from the staff member
            reply_to_event_id: The message ID being replied to (should be in closed thread)
            staff_sender: ID of the staff member making the correction

        Returns:
            PostApprovalCorrectionResult if correction was processed, None otherwise
        """
        # Try to find a thread for the referenced message
        thread = self.repository.find_thread_by_message(reply_to_event_id)

        if thread is None:
            logger.debug(
                f"No thread found for message {reply_to_event_id}, "
                "cannot process as post-approval correction"
            )
            return None

        # Check if thread is closed (has an approved FAQ)
        if thread.state != "closed" or thread.faq_id is None:
            logger.debug(
                f"Thread {thread.id} is not closed or has no FAQ, "
                f"state={thread.state}, faq_id={thread.faq_id}"
            )
            return None

        # This is a post-approval correction - flag the FAQ for review
        correction_reason = f"staff_correction:{staff_sender}"

        # Store the correction in the thread
        self.repository.add_message_to_thread(
            thread_id=thread.id,
            message_id=event_id,
            message_type="post_approval_correction",
            content=correction_content,
            sender_id=staff_sender,
        )

        # Reopen the thread for correction
        self.repository.reopen_thread_for_correction(
            thread_id=thread.id,
            correction_reason=correction_reason,
            trigger="staff_correction",
        )

        logger.info(
            f"Post-approval correction detected for FAQ {thread.faq_id}. "
            f"Thread {thread.id} reopened for review."
        )

        # Record metrics for post-approval correction
        training_post_approval_corrections.inc()

        return PostApprovalCorrectionResult(
            thread_id=thread.id,
            faq_id=thread.faq_id,
            faq_flagged=True,
            correction_stored=True,
            correction_reason=correction_reason,
        )

    async def skip_candidate(self, candidate_id: int) -> bool:
        """
        Skip a candidate to review later.

        Args:
            candidate_id: ID of the candidate to skip

        Returns:
            True if skip successful
        """
        candidate = self.repository.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        self.repository.skip(candidate_id)

        # Record metrics
        training_human_reviews.labels(outcome="skipped").inc()

        return True

    async def undo_action(
        self,
        candidate_id: int,
        action_type: str,
        faq_id: Optional[str] = None,
        faq_service: Optional[Any] = None,
    ) -> bool:
        """
        Undo a recent action on a candidate.

        Reverts the candidate to pending status and, if the action was an approval,
        deletes the created FAQ.

        Args:
            candidate_id: ID of the candidate
            action_type: Type of action to undo ('approve', 'reject', 'skip')
            faq_id: ID of FAQ to delete (required for approve undo)
            faq_service: FAQService instance (required for approve undo)

        Returns:
            True if undo successful

        Raises:
            ValueError: If candidate not found or invalid action type
        """
        candidate = self.repository.get_by_id(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        # Verify the candidate is in the expected state
        if action_type == "approve" and candidate.review_status != "approved":
            raise ValueError(
                f"Cannot undo approve: candidate status is '{candidate.review_status}'"
            )
        if action_type == "reject" and candidate.review_status != "rejected":
            raise ValueError(
                f"Cannot undo reject: candidate status is '{candidate.review_status}'"
            )

        # For approve, delete the created FAQ
        if action_type == "approve":
            if faq_id and faq_service:
                try:
                    faq_service.delete_faq(faq_id)
                    logger.info(f"Deleted FAQ {faq_id} during undo")
                except (ValueError, sqlite3.Error, OSError) as e:
                    logger.warning(f"Failed to delete FAQ {faq_id} during undo: {e}")
                    # Continue with reverting the candidate anyway

        # Revert candidate to pending status
        self.repository.revert_to_pending(candidate_id)

        logger.info(
            f"Undid {action_type} for candidate {candidate_id}, reverted to pending"
        )

        # Update queue metrics after undo
        update_queue_metrics(self.repository.get_queue_counts())

        return True

    def get_flagged_faqs(self) -> List[Dict[str, Any]]:
        """
        Get all FAQs that have been flagged for review due to post-approval corrections.

        Cycle 18: Returns threads in 'reopened_for_correction' state with their
        associated correction details.

        Returns:
            List of flagged FAQ information dicts containing:
            - thread_id: ID of the thread
            - faq_id: ID of the associated FAQ
            - correction_reason: Why it was flagged
            - original_answer: The original staff answer
            - correction_content: The correction message content
            - state: Thread state (should be 'reopened_for_correction')
            - flagged_at: When the correction was detected
        """
        flagged_threads = self.repository.get_threads_by_state(
            "reopened_for_correction"
        )

        results = []
        for thread in flagged_threads:
            # Get the correction message from thread messages
            messages = self.repository.get_thread_messages(thread.id)
            correction_msg = None
            original_answer = None

            for msg in messages:
                if msg.message_type == "post_approval_correction":
                    correction_msg = msg
                elif msg.message_type == "staff_answer":
                    original_answer = msg.content

            results.append(
                {
                    "thread_id": thread.id,
                    "faq_id": thread.faq_id,
                    "correction_reason": thread.correction_reason,
                    "original_answer": original_answer,
                    "correction_content": (
                        correction_msg.content if correction_msg else None
                    ),
                    "state": thread.state,
                    "flagged_at": thread.updated_at,
                }
            )

        return results

    async def resolve_flagged_faq(
        self,
        thread_id: int,
        action: str,
        reviewer: str,
        new_answer: Optional[str] = None,
    ) -> bool:
        """
        Resolve a flagged FAQ by updating, confirming, or deleting it.

        Cycle 18: Handles post-approval correction resolution.

        Args:
            thread_id: ID of the thread to resolve
            action: Resolution action - "update", "confirm", or "delete"
            reviewer: Username of the admin resolving
            new_answer: New answer text (required for "update" action)

        Returns:
            True if resolution was successful

        Raises:
            ValueError: If thread not found or invalid action
        """
        thread = self.repository.get_thread(thread_id)
        if thread is None:
            raise ValueError(f"Thread {thread_id} not found")

        if thread.state != "reopened_for_correction":
            raise ValueError(
                f"Thread {thread_id} is not flagged for correction (state={thread.state})"
            )

        if thread.faq_id is None:
            raise ValueError(f"Thread {thread_id} has no associated FAQ")

        if action == "update":
            if not new_answer:
                raise ValueError("new_answer is required for update action")
            # Update the FAQ answer
            self.faq_service.update_faq_answer(thread.faq_id, new_answer)
            logger.info(f"FAQ {thread.faq_id} updated with new answer by {reviewer}")
        elif action == "confirm":
            # Keep existing answer - just log confirmation
            logger.info(f"FAQ {thread.faq_id} confirmed (no change) by {reviewer}")
        elif action == "delete":
            # Delete the FAQ
            self.faq_service.delete_faq(thread.faq_id)
            logger.info(f"FAQ {thread.faq_id} deleted by {reviewer}")
        else:
            raise ValueError(f"Invalid action: {action}")

        # Transition thread to closed_updated state
        self.repository.transition_thread_state(
            thread_id=thread_id,
            to_state="closed_updated",
            trigger=f"resolved_{action}",
            metadata={
                "reviewer": reviewer,
                "action": action,
            },
        )

        # Record metrics for correction resolution
        training_correction_resolutions.labels(action=action).inc()

        return True

    async def update_candidate(
        self,
        candidate_id: int,
        edited_staff_answer: Optional[str] = None,
        edited_question_text: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[UnifiedFAQCandidate]:
        """
        Update a candidate's editable fields.

        Currently supports editing the question, staff answer, and category before approval.
        The edited values will be used when creating the FAQ.
        When the staff answer is edited, comparison scores are recalculated
        to reflect how well the RAG answer matches the new staff answer.

        Args:
            candidate_id: ID of the candidate to update
            edited_staff_answer: User-edited version of the staff answer
            edited_question_text: User-edited version of the question
            category: FAQ category (e.g., Trading, Wallet, Installation)

        Returns:
            Updated candidate or None if not found
        """
        candidate = self.repository.get_by_id(candidate_id)
        if candidate is None:
            return None

        # If staff answer is being edited and we have a generated answer,
        # recalculate comparison scores
        if edited_staff_answer and candidate.generated_answer:
            comparison = await self._compare_answers(
                candidate.source_event_id,
                candidate.question_text,
                edited_staff_answer,  # Use the edited answer for comparison
                candidate.generated_answer,
            )

            # Determine new routing based on updated score
            routing, _ = self._determine_routing(comparison.final_score)

            return self.repository.update_candidate(
                candidate_id=candidate_id,
                edited_staff_answer=edited_staff_answer,
                edited_question_text=edited_question_text,
                embedding_similarity=comparison.embedding_similarity,
                factual_alignment=comparison.factual_alignment,
                contradiction_score=comparison.contradiction_score,
                completeness=comparison.completeness,
                hallucination_risk=comparison.hallucination_risk,
                final_score=comparison.final_score,
                llm_reasoning=comparison.llm_reasoning,
                routing=routing,
                category=category,
            )

        # Simple update without score recalculation
        return self.repository.update_candidate(
            candidate_id=candidate_id,
            edited_staff_answer=edited_staff_answer,
            edited_question_text=edited_question_text,
            category=category,
        )

    async def regenerate_candidate_answer(
        self,
        candidate_id: int,
        protocol: str,
    ) -> Optional[UnifiedFAQCandidate]:
        """
        Regenerate the RAG answer for a candidate with a specific protocol.

        This allows reviewers to select the correct protocol context
        (bisq_easy, multisig_v1, musig, or all) for the RAG system to use
        when generating the comparison answer. The scores will be recalculated.

        Args:
            candidate_id: ID of the candidate
            protocol: Protocol to use (bisq_easy, multisig_v1, musig, all)

        Returns:
            Updated candidate with new generated answer and scores, or None if not found
        """
        candidate = self.repository.get_by_id(candidate_id)
        if candidate is None:
            return None

        # Map protocol to bisq_version for RAG filtering
        # bisq_easy → Bisq 2, multisig_v1 → Bisq 1, musig → Bisq 2, all → no filter
        protocol_to_version = {
            "bisq_easy": "Bisq 2",
            "multisig_v1": "Bisq 1",
            "musig": "Bisq 2",
            "all": None,  # No filter - search all versions
        }
        bisq_version = protocol_to_version.get(protocol)

        # Generate new RAG answer with protocol-specific filtering
        rag_response = await self.rag_service.query(
            candidate.question_text,
            chat_history=[],
            override_version=bisq_version,
        )
        generated_answer = rag_response.get("answer", "")
        sources = rag_response.get("sources", [])
        sources_json = json.dumps(sources) if sources else None
        generation_confidence = rag_response.get("confidence")

        # Recalculate comparison scores
        comparison = await self._compare_answers(
            candidate.source_event_id,
            candidate.question_text,
            candidate.staff_answer,
            generated_answer,
        )

        # Determine new routing based on updated score
        routing, _ = self._determine_routing(comparison.final_score)

        # Update the candidate with all new values
        return self.repository.update_candidate(
            candidate_id=candidate_id,
            protocol=protocol,
            generated_answer=generated_answer,
            embedding_similarity=comparison.embedding_similarity,
            factual_alignment=comparison.factual_alignment,
            contradiction_score=comparison.contradiction_score,
            completeness=comparison.completeness,
            hallucination_risk=comparison.hallucination_risk,
            final_score=comparison.final_score,
            llm_reasoning=comparison.llm_reasoning,
            routing=routing,
            generated_answer_sources=sources_json,
            generation_confidence=generation_confidence,
        )

    def get_pending_reviews(
        self,
        source: Optional[Literal["bisq2", "matrix"]] = None,
        routing: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[UnifiedFAQCandidate]:
        """
        Get pending candidates for review.

        Args:
            source: Optional filter by source (bisq2/matrix)
            routing: Optional filter by routing category
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of pending candidates
        """
        return self.repository.get_pending(
            source=source,
            routing=routing,
            limit=limit,
            offset=offset,
        )

    def count_pending_reviews(
        self,
        source: Optional[Literal["bisq2", "matrix"]] = None,
        routing: Optional[str] = None,
    ) -> int:
        """
        Count pending candidates using efficient COUNT(*) query.

        Args:
            source: Optional filter by source (bisq2/matrix)
            routing: Optional filter by routing category

        Returns:
            Total count of matching pending candidates
        """
        return self.repository.count_pending(source=source, routing=routing)

    def get_current_item(
        self,
        routing: str,
        source: Optional[Literal["bisq2", "matrix"]] = None,
    ) -> Optional[UnifiedFAQCandidate]:
        """
        Get the current item to review for a routing category.

        Args:
            routing: Routing category (FULL_REVIEW, SPOT_CHECK, etc.)
            source: Optional filter by source

        Returns:
            The next candidate to review, or None if queue empty
        """
        candidates = self.repository.get_pending(
            source=source,
            routing=routing,
            limit=1,
            offset=0,
        )
        return candidates[0] if candidates else None

    def get_queue_counts(
        self,
        source: Optional[Literal["bisq2", "matrix"]] = None,
    ) -> Dict[str, int]:
        """
        Get counts of candidates in each routing queue.

        Args:
            source: Optional filter by source

        Returns:
            Dictionary with counts per routing category
        """
        return self.repository.get_queue_counts(source=source)

    def get_calibration_status(self) -> CalibrationStatus:
        """
        Get the current calibration status.

        Returns:
            CalibrationStatus with samples collected, required, and completion state
        """
        return self.repository.get_calibration_status()

    def is_calibration_mode(self) -> bool:
        """
        Check if the system is in calibration mode.

        Returns:
            True if still collecting calibration samples
        """
        return self.repository.is_calibration_mode()

    async def _process_extracted_faq(
        self,
        question_text: str,
        staff_answer: str,
        source: str,
        source_event_id: str,
        staff_sender: str = "",
        category: str = "General",
        original_user_question: Optional[str] = None,
        original_staff_answer: Optional[str] = None,
    ) -> ProcessingResult:
        """Process a single extracted FAQ through the pipeline.

        This internal method handles FAQs extracted by UnifiedFAQExtractor,
        running them through RAG comparison and creating candidates.

        Args:
            question_text: The user's question
            staff_answer: The staff's answer (may be LLM-transformed for clarity)
            source: Source identifier ("bisq2" or "matrix")
            source_event_id: Unique event identifier
            staff_sender: Staff member who answered
            category: FAQ category (e.g., Trading, Wallet, Installation)
            original_user_question: Original conversational user question before
                                    LLM transformation (enables "View Original" UI)
            original_staff_answer: Original conversational staff answer before
                                   LLM transformation (enables "View Original" UI)

        Returns:
            ProcessingResult with candidate info and routing
        """
        # Check for duplicates
        if self.repository.exists_by_event_id(source_event_id):
            return ProcessingResult(
                candidate_id=None,
                source=source,
                source_event_id=source_event_id,
                routing="SKIPPED",
                final_score=0.0,
                is_calibration_sample=False,
                skipped_reason="duplicate",
            )

        # Skip if question or answer is too short
        if len(question_text.strip()) < 10 or len(staff_answer.strip()) < 10:
            return ProcessingResult(
                candidate_id=None,
                source=source,
                source_event_id=source_event_id,
                routing="SKIPPED",
                final_score=0.0,
                is_calibration_sample=False,
                skipped_reason="too_short",
            )

        # Detect protocol directly from question, with staff answer as fallback
        # Pass the source parameter to enable source-based defaults
        # Cast source to Source type (it should always be "bisq2" or "matrix")
        detected_protocol = self._detect_protocol_with_fallback(
            question_text, staff_answer, source=cast(Optional[Source], source)
        )

        # Convert protocol to version string for RAG service (backwards compat)
        override_version = self.protocol_detector._protocol_to_version(
            detected_protocol
        )

        # Generate RAG answer with detected version (if available)
        rag_response = await self.rag_service.query(
            question_text, chat_history=[], override_version=override_version
        )
        generated_answer = rag_response.get("answer", "")
        sources = rag_response.get("sources", [])
        sources_json = json.dumps(sources) if sources else None
        # Extract RAG's own confidence (distinct from comparison final_score)
        generation_confidence = rag_response.get("confidence")

        # Calculate comparison scores
        comparison = await self._compare_answers(
            source_event_id, question_text, staff_answer, generated_answer
        )

        # Determine routing
        routing, is_calibration = self._determine_routing(comparison.final_score)

        # Create candidate with detected protocol
        source_timestamp = datetime.now(timezone.utc).isoformat()
        candidate = self.repository.create(
            source=cast(Literal["bisq2", "matrix"], source),
            source_event_id=source_event_id,
            source_timestamp=source_timestamp,
            question_text=question_text,
            staff_answer=staff_answer,
            generated_answer=generated_answer,
            staff_sender=staff_sender,  # Now passed from LLM extraction
            embedding_similarity=comparison.embedding_similarity,
            factual_alignment=comparison.factual_alignment,
            contradiction_score=comparison.contradiction_score,
            completeness=comparison.completeness,
            hallucination_risk=comparison.hallucination_risk,
            final_score=comparison.final_score,
            llm_reasoning=comparison.llm_reasoning,
            routing=routing,
            is_calibration_sample=is_calibration,
            category=category,
            protocol=detected_protocol,
            generated_answer_sources=sources_json,
            original_user_question=original_user_question,
            original_staff_answer=original_staff_answer,
            generation_confidence=generation_confidence,
        )

        # Update calibration count and metrics if calibration sample
        if is_calibration:
            self.repository.increment_calibration_count()
            update_calibration_metrics(self.repository.get_calibration_status())

        # Record metrics
        training_pairs_processed.labels(routing=routing).inc()
        training_final_scores.observe(comparison.final_score)
        if routing == "AUTO_APPROVE":
            training_auto_approvals.inc()

        # Update queue metrics
        update_queue_metrics(self.repository.get_queue_counts())

        return ProcessingResult(
            candidate_id=candidate.id,
            source=source,
            source_event_id=source_event_id,
            routing=routing,
            final_score=comparison.final_score,
            is_calibration_sample=is_calibration,
        )

    async def extract_faqs_batch(
        self,
        messages: List[Dict[str, Any]],
        source: str,
        staff_identifiers: Optional[List[str]] = None,
    ) -> List[ProcessingResult]:
        """Extract FAQ candidates from a batch of messages using single LLM call.

        This method provides a simplified alternative to processing individual Q&A pairs.
        It uses UnifiedFAQExtractor for single-pass LLM extraction, then processes each
        extracted FAQ through the standard pipeline for comparison and routing.

        Args:
            messages: List of chat messages (Bisq 2 or Matrix format)
            source: Source identifier ("bisq2" or "matrix")
            staff_identifiers: Optional list of staff usernames/IDs

        Returns:
            List of ProcessingResult for each extracted FAQ candidate
        """
        from app.services.training.unified_faq_extractor import UnifiedFAQExtractor

        # Create extractor with AISuite client and settings
        extractor = UnifiedFAQExtractor(
            aisuite_client=self.aisuite_client,
            settings=self.settings,
            staff_identifiers=staff_identifiers,
        )

        # Extract FAQs using single LLM call
        extraction_result = await extractor.extract_faqs(
            messages=messages,
            source=source,
        )

        # Handle extraction errors
        if extraction_result.error:
            logger.error(f"FAQ extraction error: {extraction_result.error}")
            return []

        # Process each extracted FAQ through the pipeline
        results: List[ProcessingResult] = []
        pipeline_data = extraction_result.to_pipeline_format()

        for faq_data in pipeline_data:
            try:
                result = await self._process_extracted_faq(
                    question_text=faq_data["question_text"],
                    staff_answer=faq_data["staff_answer"],
                    source=faq_data["source"],
                    source_event_id=faq_data["source_event_id"],
                    staff_sender=faq_data.get("staff_sender", ""),
                    category=faq_data.get("category", "General"),
                    original_user_question=faq_data.get("original_user_question"),
                    original_staff_answer=faq_data.get("original_staff_answer"),
                )
                results.append(result)
            except Exception:
                logger.exception("Failed to process extracted FAQ")
                continue

        logger.info(
            f"Batch extraction complete: {extraction_result.extracted_count} FAQs "
            f"extracted, {len(results)} processed successfully"
        )

        return results

    async def sync_bisq_conversations(
        self,
        bisq_api: Optional[Any] = None,
        state_manager: Optional[Any] = None,
        staff_users: Optional[List[str]] = None,
    ) -> int:
        """
        Sync conversations from Bisq 2 API and process through the pipeline.

        This method instantiates a Bisq2SyncService and delegates the sync
        operation to it. The sync service handles:
        - Fetching new messages from Bisq 2 API
        - Extracting Q&A pairs from staff citations
        - Processing pairs through this pipeline

        Args:
            bisq_api: Optional Bisq2API instance (for testing)
            state_manager: Optional BisqSyncStateManager instance (for testing)
            staff_users: Optional list of staff usernames (overrides settings)

        Returns:
            Number of Q&A pairs successfully processed
        """
        # Use provided or create dependencies
        if bisq_api is None:
            # Check if Bisq API is configured
            bisq_api_url = getattr(self.settings, "BISQ_API_URL", None)
            if not bisq_api_url:
                logger.debug("Bisq 2 API not configured, skipping sync")
                return 0
            bisq_api = Bisq2API(settings=self.settings)

        if state_manager is None:
            state_manager = BisqSyncStateManager()

        # Override staff users in settings if provided
        settings_to_use = self.settings
        if staff_users is not None:
            # Create a simple wrapper that overrides BISQ_STAFF_USERS
            # but delegates all other attribute access to original settings
            class SettingsOverride:
                def __init__(self, base_settings: Any, staff_override: List[str]):
                    self._base = base_settings
                    self._staff_users = staff_override

                def __getattr__(self, name: str) -> Any:
                    if name == "BISQ_STAFF_USERS":
                        return self._staff_users
                    return getattr(self._base, name)

            settings_to_use = SettingsOverride(self.settings, staff_users)

        # Create and run sync service
        sync_service = Bisq2SyncService(
            settings=settings_to_use,
            pipeline_service=self,
            bisq_api=bisq_api,
            state_manager=state_manager,
        )

        return await sync_service.sync_conversations()

    async def sync_matrix_conversations(self) -> int:
        """
        Sync conversations from Matrix rooms and process through the pipeline.

        This method instantiates a MatrixSyncService and delegates the sync
        operation to it. The sync service handles:
        - Connecting to configured Matrix rooms
        - Detecting staff replies to user questions
        - Processing Q&A pairs through this pipeline

        Returns:
            Number of Q&A pairs successfully processed
        """
        # Check if Matrix is configured
        homeserver = getattr(self.settings, "MATRIX_HOMESERVER_URL", None)
        rooms = getattr(self.settings, "MATRIX_ROOMS", None)
        if not homeserver or not rooms:
            logger.debug("Matrix not configured, skipping sync")
            return 0

        # Create polling state manager
        polling_state = PollingStateManager(
            state_file=self.settings.get_data_path("matrix_polling_state.json")
        )

        # Create and run sync service
        sync_service = MatrixSyncService(
            settings=self.settings,
            pipeline_service=self,
            polling_state=polling_state,
        )

        return await sync_service.sync_rooms()
