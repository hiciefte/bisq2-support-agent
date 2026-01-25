"""
Unified FAQ Candidate Repository.

This module provides the repository layer for storing and managing
FAQ candidates from both Bisq 2 support chat and Matrix staff answers.

The repository handles:
- Candidate storage with source tracking (bisq2/matrix)
- Calibration state management
- Review queue operations (approve/reject/skip)
- Source-based filtering for the admin UI
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class UnifiedFAQCandidate:
    """A candidate FAQ entry pending review.

    Attributes:
        id: Database primary key
        source: Origin source ("bisq2" or "matrix")
        source_event_id: Unique identifier from source system
        source_timestamp: When the original message was created
        question_text: The user's question
        staff_answer: The staff member's answer
        generated_answer: RAG-generated answer for comparison
        staff_sender: Identifier of the staff member
        embedding_similarity: Cosine similarity between embeddings
        factual_alignment: LLM-judged factual alignment score
        contradiction_score: LLM-judged contradiction score
        completeness: LLM-judged completeness score
        hallucination_risk: LLM-judged hallucination risk
        final_score: Weighted combined score
        llm_reasoning: LLM explanation for the scores
        routing: Queue routing (AUTO_APPROVE/SPOT_CHECK/FULL_REVIEW)
        review_status: Current status (pending/approved/rejected)
        reviewed_by: Username of reviewer
        reviewed_at: Timestamp of review
        rejection_reason: Reason for rejection (if rejected)
        faq_id: ID of created FAQ (if approved)
        is_calibration_sample: Whether this is a calibration sample
        created_at: When the candidate was created
        updated_at: Last update timestamp
    """

    id: int
    source: Literal["bisq2", "matrix"]
    source_event_id: str
    source_timestamp: str
    question_text: str
    staff_answer: str
    generated_answer: Optional[str] = None
    staff_sender: Optional[str] = None
    embedding_similarity: Optional[float] = None
    factual_alignment: Optional[float] = None
    contradiction_score: Optional[float] = None
    completeness: Optional[float] = None
    hallucination_risk: Optional[float] = None
    final_score: Optional[float] = None
    llm_reasoning: Optional[str] = None
    routing: str = "FULL_REVIEW"
    review_status: str = "pending"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    faq_id: Optional[str] = None
    is_calibration_sample: bool = True
    created_at: str = ""
    updated_at: Optional[str] = None
    protocol: Optional[str] = None  # bisq_easy, multisig_v1, musig, all
    edited_staff_answer: Optional[str] = None  # User-edited version of staff answer
    category: Optional[str] = None  # FAQ category (e.g., Trading, Wallet, Installation)
    generated_answer_sources: Optional[str] = None  # JSON string of sources used
    original_user_question: Optional[str] = (
        None  # Original conversational user question before transformation
    )
    original_staff_answer: Optional[str] = (
        None  # Original conversational staff answer before transformation
    )
    generation_confidence: Optional[float] = (
        None  # RAG's own confidence in its generated answer
    )
    has_correction: bool = False  # Whether this candidate has been corrected by staff


@dataclass
class CalibrationStatus:
    """Calibration state for the training pipeline.

    Attributes:
        samples_collected: Number of samples reviewed during calibration
        samples_required: Total samples required for calibration (default 100)
        is_complete: Whether calibration is complete
        auto_approve_threshold: Score threshold for AUTO_APPROVE (default 0.90)
        spot_check_threshold: Score threshold for SPOT_CHECK (default 0.75)
    """

    samples_collected: int
    samples_required: int
    is_complete: bool
    auto_approve_threshold: float
    spot_check_threshold: float


@dataclass
class ConversationThread:
    """A conversation thread linking related messages.

    Thread State Machine
    --------------------
    The thread state machine tracks the lifecycle of Q&A extraction and FAQ creation.

    States:
        - pending_question: Initial state when thread created for a new question
        - has_staff_answer: Staff has replied to the question
        - candidate_created: FAQ candidate generated from the Q&A pair
        - has_correction: Staff has submitted a correction to the answer
        - closed: FAQ was approved and created from this thread
        - closed_updated: Post-approval correction was reviewed and resolved

    Transitions:
        pending_question ─────► has_staff_answer
                                  (staff replies)
                                      │
                                      ▼
                              candidate_created ◄────┐
                                      │              │
                        ┌─────────────┴──────────────┤
                        │                            │
                        ▼                            │
                 has_correction ─────────────────────┘
                    (staff sends correction)
                        │
                        └───► (re-processing continues)
                                      │
                        ┌─────────────┴───────────────┐
                        │                             │
                        ▼                             ▼
                     closed          closed ───► closed_updated
                  (approved)     (post-approval      (reviewed)
                                  correction)

    Attributes:
        id: Database primary key
        thread_key: Unique hash key for thread identification
        source: Origin source ("bisq2" or "matrix")
        room_id: Matrix room ID or Bisq channel (optional)
        first_question_id: Original question message ID
        state: Thread state machine value (see states above)
        created_at: When the thread was created
        updated_at: Last update timestamp
        candidate_id: Link to FAQ candidate when created (optional)
        faq_id: Link to FAQ after approval (optional)
        correction_reason: Reason for post-approval correction (optional)
    """

    id: int
    thread_key: str
    source: Literal["bisq2", "matrix"]
    room_id: Optional[str]
    first_question_id: str
    state: str = "pending_question"
    created_at: str = ""
    updated_at: Optional[str] = None
    candidate_id: Optional[int] = None
    faq_id: Optional[str] = None
    correction_reason: Optional[str] = None


@dataclass
class ThreadMessage:
    """A message within a conversation thread.

    Attributes:
        id: Database primary key
        thread_id: Foreign key to conversation_threads
        message_id: Original source message ID
        message_type: Type of message (question, staff_answer, correction, user_followup)
        sender_id: Identifier of the sender
        content: Message content
        timestamp: When the message was created
        is_processed: Whether this message has been processed
    """

    id: int
    thread_id: int
    message_id: str
    message_type: str
    sender_id: Optional[str]
    content: str
    timestamp: str
    is_processed: bool = False


class UnifiedFAQCandidateRepository:
    """Repository for managing unified FAQ candidates.

    This repository provides CRUD operations for FAQ candidates from
    both Bisq 2 support chat and Matrix staff answers, along with
    calibration state management.
    """

    def __init__(self, db_path: str):
        """Initialize the repository with database path.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path

        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database schema
        self._init_database()

    def _init_database(self) -> None:
        """Create database tables and indexes if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create unified_faq_candidates table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS unified_faq_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL CHECK (source IN ('bisq2', 'matrix')),
                source_event_id TEXT UNIQUE NOT NULL,
                source_timestamp TEXT NOT NULL,
                question_text TEXT NOT NULL,
                staff_answer TEXT NOT NULL,
                generated_answer TEXT,
                staff_sender TEXT,
                embedding_similarity REAL,
                factual_alignment REAL,
                contradiction_score REAL,
                completeness REAL,
                hallucination_risk REAL,
                final_score REAL,
                llm_reasoning TEXT,
                routing TEXT NOT NULL CHECK (routing IN ('AUTO_APPROVE', 'SPOT_CHECK', 'FULL_REVIEW')),
                review_status TEXT DEFAULT 'pending',
                reviewed_by TEXT,
                reviewed_at TEXT,
                rejection_reason TEXT,
                faq_id TEXT,
                is_calibration_sample BOOLEAN DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                skip_order INTEGER DEFAULT 0,
                protocol TEXT CHECK (protocol IN ('bisq_easy', 'multisig_v1', 'musig', 'all', NULL)),
                edited_staff_answer TEXT,
                category TEXT DEFAULT 'General'
            )
            """
        )

        # Create indexes for performance
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ufc_source ON unified_faq_candidates(source)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ufc_routing ON unified_faq_candidates(routing)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ufc_review_status ON unified_faq_candidates(review_status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_ufc_source_routing ON unified_faq_candidates(source, routing)"
        )

        # Create calibration_state table (singleton - only one row)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                samples_collected INTEGER DEFAULT 0,
                samples_required INTEGER DEFAULT 100,
                auto_approve_threshold REAL DEFAULT 0.90,
                spot_check_threshold REAL DEFAULT 0.75,
                calibration_complete BOOLEAN DEFAULT FALSE,
                last_updated TEXT
            )
            """
        )

        # Insert default calibration state if not exists
        cursor.execute(
            """
            INSERT OR IGNORE INTO calibration_state
            (id, samples_collected, samples_required, auto_approve_threshold, spot_check_threshold, calibration_complete)
            VALUES (1, 0, 100, 0.90, 0.75, FALSE)
            """
        )

        # Create learning_state table (for LearningEngine persistence)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                auto_send_threshold REAL DEFAULT 0.90,
                queue_high_threshold REAL DEFAULT 0.75,
                reject_threshold REAL DEFAULT 0.50,
                review_history TEXT,
                threshold_history TEXT,
                last_updated TEXT
            )
            """
        )

        # Insert default learning state if not exists
        cursor.execute(
            """
            INSERT OR IGNORE INTO learning_state
            (id, auto_send_threshold, queue_high_threshold, reject_threshold, review_history, threshold_history)
            VALUES (1, 0.90, 0.75, 0.50, '[]', '[]')
            """
        )

        # Create conversation_threads table for multi-poll conversation handling
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_key TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('bisq2', 'matrix')),
                room_id TEXT,
                first_question_id TEXT NOT NULL,
                state TEXT DEFAULT 'pending_question',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                candidate_id INTEGER,
                faq_id TEXT,
                correction_reason TEXT,
                FOREIGN KEY (candidate_id) REFERENCES unified_faq_candidates(id)
            )
            """
        )

        # Create thread_messages table for granular message tracking
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                sender_id TEXT,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                is_processed BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (thread_id) REFERENCES conversation_threads(id),
                UNIQUE(thread_id, message_id)
            )
            """
        )

        # Create conversation_state_transitions table for audit trail
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_state_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                trigger TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (thread_id) REFERENCES conversation_threads(id)
            )
            """
        )

        # Create indexes for thread tables
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_source ON conversation_threads(source)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_threads_state ON conversation_threads(state)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_id ON thread_messages(thread_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_thread_messages_message_id ON thread_messages(message_id)"
        )

        # Migrate existing tables: add protocol and edited_staff_answer columns if missing
        cursor.execute("PRAGMA table_info(unified_faq_candidates)")
        columns = [col[1] for col in cursor.fetchall()]

        if "protocol" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN protocol TEXT"
            )
            logger.info("Added 'protocol' column to unified_faq_candidates")

        if "edited_staff_answer" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN edited_staff_answer TEXT"
            )
            logger.info("Added 'edited_staff_answer' column to unified_faq_candidates")

        if "category" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN category TEXT DEFAULT 'General'"
            )
            logger.info("Added 'category' column to unified_faq_candidates")

        if "generated_answer_sources" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN generated_answer_sources TEXT"
            )
            logger.info(
                "Added 'generated_answer_sources' column to unified_faq_candidates"
            )

        if "original_user_question" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN original_user_question TEXT"
            )
            logger.info(
                "Added 'original_user_question' column to unified_faq_candidates"
            )

        if "original_staff_answer" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN original_staff_answer TEXT"
            )
            logger.info(
                "Added 'original_staff_answer' column to unified_faq_candidates"
            )

        if "generation_confidence" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN generation_confidence REAL"
            )
            logger.info(
                "Added 'generation_confidence' column to unified_faq_candidates"
            )

        if "has_correction" not in columns:
            cursor.execute(
                "ALTER TABLE unified_faq_candidates ADD COLUMN has_correction INTEGER DEFAULT 0"
            )
            logger.info("Added 'has_correction' column to unified_faq_candidates")

        # Add correction_reason column to conversation_threads (Cycle 17)
        cursor.execute("PRAGMA table_info(conversation_threads)")
        thread_columns = {row[1] for row in cursor.fetchall()}
        if "correction_reason" not in thread_columns:
            cursor.execute(
                "ALTER TABLE conversation_threads ADD COLUMN correction_reason TEXT"
            )
            logger.info("Added 'correction_reason' column to conversation_threads")

        conn.commit()
        conn.close()

    def create(
        self,
        source: Literal["bisq2", "matrix"],
        source_event_id: str,
        source_timestamp: str,
        question_text: str,
        staff_answer: str,
        routing: str = "FULL_REVIEW",
        generated_answer: Optional[str] = None,
        staff_sender: Optional[str] = None,
        embedding_similarity: Optional[float] = None,
        factual_alignment: Optional[float] = None,
        contradiction_score: Optional[float] = None,
        completeness: Optional[float] = None,
        hallucination_risk: Optional[float] = None,
        final_score: Optional[float] = None,
        llm_reasoning: Optional[str] = None,
        is_calibration_sample: bool = True,
        category: Optional[str] = None,
        protocol: Optional[str] = None,
        generated_answer_sources: Optional[str] = None,
        original_user_question: Optional[str] = None,
        original_staff_answer: Optional[str] = None,
        generation_confidence: Optional[float] = None,
    ) -> UnifiedFAQCandidate:
        """Create a new FAQ candidate.

        Args:
            source: Origin source ("bisq2" or "matrix")
            source_event_id: Unique identifier from source system
            source_timestamp: When the original message was created
            question_text: The user's question
            staff_answer: The staff member's answer
            routing: Queue routing (default FULL_REVIEW)
            generated_answer: RAG-generated answer for comparison
            staff_sender: Identifier of the staff member
            embedding_similarity: Cosine similarity score
            factual_alignment: LLM-judged alignment score
            contradiction_score: LLM-judged contradiction score
            completeness: LLM-judged completeness score
            hallucination_risk: LLM-judged hallucination risk
            final_score: Weighted combined score
            llm_reasoning: LLM explanation
            is_calibration_sample: Whether this is a calibration sample
            category: FAQ category (e.g., Trading, Wallet, Installation)
            protocol: Trade protocol (bisq_easy, multisig_v1, musig, all)
            generated_answer_sources: JSON string of sources used to generate the answer
            original_user_question: Original conversational user question before transformation
            original_staff_answer: Original conversational staff answer before transformation

        Returns:
            The created UnifiedFAQCandidate with assigned ID

        Raises:
            sqlite3.IntegrityError: If source_event_id already exists
        """
        created_at = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO unified_faq_candidates (
                source, source_event_id, source_timestamp, question_text, staff_answer,
                generated_answer, staff_sender, embedding_similarity, factual_alignment,
                contradiction_score, completeness, hallucination_risk, final_score,
                llm_reasoning, routing, is_calibration_sample, created_at, category, protocol,
                generated_answer_sources, original_user_question, original_staff_answer, generation_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                source_event_id,
                source_timestamp,
                question_text,
                staff_answer,
                generated_answer,
                staff_sender,
                embedding_similarity,
                factual_alignment,
                contradiction_score,
                completeness,
                hallucination_risk,
                final_score,
                llm_reasoning,
                routing,
                is_calibration_sample,
                created_at,
                category or "General",
                protocol,
                generated_answer_sources,
                original_user_question,
                original_staff_answer,
                generation_confidence,
            ),
        )

        candidate_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return UnifiedFAQCandidate(
            id=candidate_id,
            source=source,
            source_event_id=source_event_id,
            source_timestamp=source_timestamp,
            question_text=question_text,
            staff_answer=staff_answer,
            generated_answer=generated_answer,
            staff_sender=staff_sender,
            embedding_similarity=embedding_similarity,
            factual_alignment=factual_alignment,
            contradiction_score=contradiction_score,
            completeness=completeness,
            hallucination_risk=hallucination_risk,
            final_score=final_score,
            llm_reasoning=llm_reasoning,
            routing=routing,
            review_status="pending",
            is_calibration_sample=is_calibration_sample,
            created_at=created_at,
            category=category or "General",
            protocol=protocol,
            generated_answer_sources=generated_answer_sources,
            original_user_question=original_user_question,
            original_staff_answer=original_staff_answer,
            generation_confidence=generation_confidence,
        )

    def get_by_id(self, candidate_id: int) -> Optional[UnifiedFAQCandidate]:
        """Get a candidate by ID.

        Args:
            candidate_id: The candidate's database ID

        Returns:
            The candidate if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM unified_faq_candidates WHERE id = ?", (candidate_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_candidate(row)

    def exists_by_event_id(self, source_event_id: str) -> bool:
        """Check if a candidate with the given event ID exists.

        Args:
            source_event_id: The source system's event ID

        Returns:
            True if exists, False otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM unified_faq_candidates WHERE source_event_id = ?",
            (source_event_id,),
        )
        result = cursor.fetchone()
        conn.close()

        return result is not None

    def get_pending(
        self,
        source: Optional[Literal["bisq2", "matrix"]] = None,
        routing: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[UnifiedFAQCandidate]:
        """Get pending candidates, optionally filtered by source and routing.

        Args:
            source: Filter by source (None for all sources)
            routing: Filter by routing queue (None for all queues)
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns:
            List of pending candidates
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM unified_faq_candidates WHERE review_status = 'pending'"
        params: list = []

        if source:
            query += " AND source = ?"
            params.append(source)

        if routing:
            query += " AND routing = ?"
            params.append(routing)

        query += " ORDER BY skip_order ASC, created_at ASC"
        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_candidate(row) for row in rows]

    def get_current_item(
        self,
        routing: str,
        source: Optional[Literal["bisq2", "matrix"]] = None,
    ) -> Optional[UnifiedFAQCandidate]:
        """Get the next item to review from a queue.

        Args:
            routing: The routing queue (AUTO_APPROVE/SPOT_CHECK/FULL_REVIEW)
            source: Optional source filter

        Returns:
            The next candidate to review, or None if queue is empty
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = """
            SELECT * FROM unified_faq_candidates
            WHERE review_status = 'pending' AND routing = ?
        """
        params = [routing]

        if source:
            query += " AND source = ?"
            params.append(source)

        query += " ORDER BY skip_order ASC, created_at ASC LIMIT 1"

        cursor.execute(query, params)
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_candidate(row)

    def count_pending(
        self,
        source: Optional[Literal["bisq2", "matrix"]] = None,
        routing: Optional[str] = None,
    ) -> int:
        """Count pending candidates using efficient COUNT(*) query.

        Args:
            source: Filter by source (None for all sources)
            routing: Filter by routing queue (None for all queues)

        Returns:
            Total count of matching pending candidates
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT COUNT(*) FROM unified_faq_candidates WHERE review_status = 'pending'"
        params: list = []

        if source:
            query += " AND source = ?"
            params.append(source)

        if routing:
            query += " AND routing = ?"
            params.append(routing)

        cursor.execute(query, params)
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_queue_counts(
        self, source: Optional[Literal["bisq2", "matrix"]] = None
    ) -> Dict[str, int]:
        """Get counts of pending candidates per routing queue.

        Args:
            source: Optional source filter

        Returns:
            Dictionary mapping routing to count
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = """
            SELECT routing, COUNT(*) as count
            FROM unified_faq_candidates
            WHERE review_status = 'pending'
        """
        params = []

        if source:
            query += " AND source = ?"
            params.append(source)

        query += " GROUP BY routing"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        # Initialize with all routing types
        counts = {"AUTO_APPROVE": 0, "SPOT_CHECK": 0, "FULL_REVIEW": 0}

        for routing, count in rows:
            counts[routing] = count

        return counts

    def approve(self, candidate_id: int, reviewer: str, faq_id: str) -> None:
        """Approve a candidate and link to created FAQ.

        Args:
            candidate_id: The candidate's database ID
            reviewer: Username of the reviewer
            faq_id: ID of the created FAQ
        """
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE unified_faq_candidates
            SET review_status = 'approved',
                reviewed_by = ?,
                reviewed_at = ?,
                faq_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (reviewer, now, faq_id, now, candidate_id),
        )

        conn.commit()
        conn.close()

    def reject(self, candidate_id: int, reviewer: str, reason: str) -> None:
        """Reject a candidate with a reason.

        Args:
            candidate_id: The candidate's database ID
            reviewer: Username of the reviewer
            reason: Reason for rejection
        """
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE unified_faq_candidates
            SET review_status = 'rejected',
                reviewed_by = ?,
                reviewed_at = ?,
                rejection_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (reviewer, now, reason, now, candidate_id),
        )

        conn.commit()
        conn.close()

    def skip(self, candidate_id: int) -> None:
        """Skip a candidate, moving it to the end of the queue.

        Args:
            candidate_id: The candidate's database ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get the max skip_order and set this candidate's order to max + 1
        cursor.execute("SELECT MAX(skip_order) FROM unified_faq_candidates")
        max_order = cursor.fetchone()[0] or 0

        cursor.execute(
            """
            UPDATE unified_faq_candidates
            SET skip_order = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (max_order + 1, datetime.now(timezone.utc).isoformat(), candidate_id),
        )

        conn.commit()
        conn.close()

    def revert_to_pending(self, candidate_id: int) -> None:
        """Revert a candidate back to pending status.

        Used for undo operations. Clears review status, reviewer info,
        rejection reason, faq_id, and skip_order.

        Args:
            candidate_id: The candidate's database ID
        """
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE unified_faq_candidates
            SET review_status = 'pending',
                reviewed_by = NULL,
                reviewed_at = NULL,
                rejection_reason = NULL,
                faq_id = NULL,
                skip_order = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (now, candidate_id),
        )

        conn.commit()
        conn.close()

    def update_candidate(
        self,
        candidate_id: int,
        protocol: Optional[str] = None,
        edited_staff_answer: Optional[str] = None,
        generated_answer: Optional[str] = None,
        embedding_similarity: Optional[float] = None,
        factual_alignment: Optional[float] = None,
        contradiction_score: Optional[float] = None,
        completeness: Optional[float] = None,
        hallucination_risk: Optional[float] = None,
        final_score: Optional[float] = None,
        llm_reasoning: Optional[str] = None,
        routing: Optional[str] = None,
        category: Optional[str] = None,
        generated_answer_sources: Optional[str] = None,
        staff_answer: Optional[str] = None,
        has_correction: Optional[bool] = None,
        generation_confidence: Optional[float] = None,
    ) -> Optional[UnifiedFAQCandidate]:
        """Update a candidate with new values.

        Only non-None values will be updated. This allows partial updates
        for protocol selection, answer editing, and score regeneration.

        Args:
            candidate_id: The candidate's database ID
            protocol: Protocol type (bisq_easy, multisig_v1, musig, all)
            edited_staff_answer: User-edited version of the staff answer
            generated_answer: Regenerated RAG answer
            embedding_similarity: Updated embedding similarity score
            factual_alignment: Updated factual alignment score
            contradiction_score: Updated contradiction score
            completeness: Updated completeness score
            hallucination_risk: Updated hallucination risk score
            final_score: Updated final weighted score
            llm_reasoning: Updated LLM reasoning
            routing: Updated routing queue
            category: FAQ category (e.g., Trading, Wallet, Installation)
            generated_answer_sources: JSON string of sources used to generate the answer
            staff_answer: Updated staff answer (for corrections)
            has_correction: Whether this candidate has been corrected
            generation_confidence: RAG confidence score (0.0-1.0)

        Returns:
            The updated candidate, or None if not found
        """
        # Build dynamic UPDATE query with only provided fields
        updates: list[str] = []
        params: list[str | float | int | None] = []

        if protocol is not None:
            updates.append("protocol = ?")
            params.append(protocol)

        if edited_staff_answer is not None:
            updates.append("edited_staff_answer = ?")
            params.append(edited_staff_answer)

        if generated_answer is not None:
            updates.append("generated_answer = ?")
            params.append(generated_answer)

        if embedding_similarity is not None:
            updates.append("embedding_similarity = ?")
            params.append(embedding_similarity)

        if factual_alignment is not None:
            updates.append("factual_alignment = ?")
            params.append(factual_alignment)

        if contradiction_score is not None:
            updates.append("contradiction_score = ?")
            params.append(contradiction_score)

        if completeness is not None:
            updates.append("completeness = ?")
            params.append(completeness)

        if hallucination_risk is not None:
            updates.append("hallucination_risk = ?")
            params.append(hallucination_risk)

        if final_score is not None:
            updates.append("final_score = ?")
            params.append(final_score)

        if llm_reasoning is not None:
            updates.append("llm_reasoning = ?")
            params.append(llm_reasoning)

        if routing is not None:
            updates.append("routing = ?")
            params.append(routing)

        if category is not None:
            updates.append("category = ?")
            params.append(category)

        if generated_answer_sources is not None:
            updates.append("generated_answer_sources = ?")
            params.append(generated_answer_sources)

        if staff_answer is not None:
            updates.append("staff_answer = ?")
            params.append(staff_answer)

        if has_correction is not None:
            updates.append("has_correction = ?")
            params.append(1 if has_correction else 0)

        if generation_confidence is not None:
            updates.append("generation_confidence = ?")
            params.append(generation_confidence)

        if not updates:
            # Nothing to update, return current candidate
            return self.get_by_id(candidate_id)

        # Always update updated_at
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())

        # Add candidate_id to params
        params.append(candidate_id)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = f"""
            UPDATE unified_faq_candidates
            SET {', '.join(updates)}
            WHERE id = ?
        """

        cursor.execute(query, params)
        conn.commit()
        conn.close()

        return self.get_by_id(candidate_id)

    def is_calibration_mode(self) -> bool:
        """Check if the system is in calibration mode.

        Returns:
            True if calibration is active, False if complete
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT calibration_complete FROM calibration_state WHERE id = 1"
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return True  # Default to calibration mode

        return not row[0]  # Return True if NOT complete

    def increment_calibration_count(self) -> None:
        """Increment the calibration sample count.

        If the count reaches samples_required, marks calibration as complete.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get current state
        cursor.execute(
            "SELECT samples_collected, samples_required FROM calibration_state WHERE id = 1"
        )
        row = cursor.fetchone()

        if row is None:
            conn.close()
            return

        samples_collected, samples_required = row
        new_count = samples_collected + 1

        # Check if calibration should complete
        is_complete = new_count >= samples_required

        cursor.execute(
            """
            UPDATE calibration_state
            SET samples_collected = ?,
                calibration_complete = ?,
                last_updated = ?
            WHERE id = 1
            """,
            (new_count, is_complete, datetime.now(timezone.utc).isoformat()),
        )

        conn.commit()
        conn.close()

    def get_calibration_status(self) -> CalibrationStatus:
        """Get the current calibration status.

        Returns:
            CalibrationStatus dataclass with current state
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT samples_collected, samples_required, calibration_complete,
                   auto_approve_threshold, spot_check_threshold
            FROM calibration_state WHERE id = 1
            """
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            # Return defaults if no state exists
            return CalibrationStatus(
                samples_collected=0,
                samples_required=100,
                is_complete=False,
                auto_approve_threshold=0.90,
                spot_check_threshold=0.75,
            )

        return CalibrationStatus(
            samples_collected=row[0],
            samples_required=row[1],
            is_complete=bool(row[2]),
            auto_approve_threshold=row[3],
            spot_check_threshold=row[4],
        )

    def _row_to_candidate(self, row: sqlite3.Row) -> UnifiedFAQCandidate:
        """Convert a database row to a UnifiedFAQCandidate.

        Args:
            row: SQLite row object

        Returns:
            UnifiedFAQCandidate instance
        """
        # Handle columns that may not exist in older databases
        protocol = row["protocol"] if "protocol" in row.keys() else None
        edited_staff_answer = (
            row["edited_staff_answer"] if "edited_staff_answer" in row.keys() else None
        )
        category = row["category"] if "category" in row.keys() else "General"
        generated_answer_sources = (
            row["generated_answer_sources"]
            if "generated_answer_sources" in row.keys()
            else None
        )
        original_user_question = (
            row["original_user_question"]
            if "original_user_question" in row.keys()
            else None
        )
        original_staff_answer = (
            row["original_staff_answer"]
            if "original_staff_answer" in row.keys()
            else None
        )
        generation_confidence = (
            row["generation_confidence"]
            if "generation_confidence" in row.keys()
            else None
        )
        has_correction = (
            bool(row["has_correction"]) if "has_correction" in row.keys() else False
        )

        return UnifiedFAQCandidate(
            id=row["id"],
            source=row["source"],
            source_event_id=row["source_event_id"],
            source_timestamp=row["source_timestamp"],
            question_text=row["question_text"],
            staff_answer=row["staff_answer"],
            generated_answer=row["generated_answer"],
            staff_sender=row["staff_sender"],
            embedding_similarity=row["embedding_similarity"],
            factual_alignment=row["factual_alignment"],
            contradiction_score=row["contradiction_score"],
            completeness=row["completeness"],
            hallucination_risk=row["hallucination_risk"],
            final_score=row["final_score"],
            llm_reasoning=row["llm_reasoning"],
            routing=row["routing"],
            review_status=row["review_status"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            rejection_reason=row["rejection_reason"],
            faq_id=row["faq_id"],
            is_calibration_sample=bool(row["is_calibration_sample"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            protocol=protocol,
            edited_staff_answer=edited_staff_answer,
            category=category,
            generated_answer_sources=generated_answer_sources,
            original_user_question=original_user_question,
            original_staff_answer=original_staff_answer,
            generation_confidence=generation_confidence,
            has_correction=has_correction,
        )

    # =========================================================================
    # Learning State Persistence (for LearningEngine)
    # =========================================================================

    def get_learning_state(self) -> Optional[Dict]:
        """Get the saved learning engine state.

        Returns:
            Dictionary with learning state or None if not found
        """
        import json

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM learning_state WHERE id = 1")
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return {
            "auto_send_threshold": row["auto_send_threshold"],
            "queue_high_threshold": row["queue_high_threshold"],
            "reject_threshold": row["reject_threshold"],
            "review_history": json.loads(row["review_history"] or "[]"),
            "threshold_history": json.loads(row["threshold_history"] or "[]"),
            "last_updated": row["last_updated"],
        }

    def save_learning_state(
        self,
        auto_send_threshold: float,
        queue_high_threshold: float,
        reject_threshold: float,
        review_history: list,
        threshold_history: list,
    ) -> None:
        """Save learning engine state to database.

        Args:
            auto_send_threshold: Current auto-send threshold
            queue_high_threshold: Current queue high threshold
            reject_threshold: Current reject threshold
            review_history: List of review records
            threshold_history: List of threshold history records
        """
        import json

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Limit review history to last 1000 records to prevent unbounded growth
        limited_review_history = (
            review_history[-1000:] if len(review_history) > 1000 else review_history
        )

        cursor.execute(
            """
            UPDATE learning_state SET
                auto_send_threshold = ?,
                queue_high_threshold = ?,
                reject_threshold = ?,
                review_history = ?,
                threshold_history = ?,
                last_updated = ?
            WHERE id = 1
            """,
            (
                auto_send_threshold,
                queue_high_threshold,
                reject_threshold,
                json.dumps(limited_review_history),
                json.dumps(threshold_history),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        conn.commit()
        conn.close()
        logger.info("Learning state saved to database")

    # =========================================================================
    # Conversation Thread Management Methods
    # =========================================================================

    def _generate_thread_key(
        self, source: str, room_id: Optional[str], first_question_id: str
    ) -> str:
        """Generate a unique thread key from source, room, and question ID.

        Args:
            source: Origin source (bisq2 or matrix)
            room_id: Room or channel identifier
            first_question_id: Original question message ID

        Returns:
            Unique thread key string
        """
        import hashlib

        key_parts = f"{source}:{room_id or 'no_room'}:{first_question_id}"
        return hashlib.sha256(key_parts.encode()).hexdigest()[:32]

    def create_thread(
        self,
        source: Literal["bisq2", "matrix"],
        first_question_id: str,
        room_id: Optional[str] = None,
    ) -> ConversationThread:
        """Create a new conversation thread.

        Args:
            source: Origin source (bisq2 or matrix)
            first_question_id: Original question message ID
            room_id: Room or channel identifier (optional)

        Returns:
            Created ConversationThread
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        thread_key = self._generate_thread_key(source, room_id, first_question_id)
        now = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            INSERT INTO conversation_threads
            (thread_key, source, room_id, first_question_id, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending_question', ?, ?)
            """,
            (thread_key, source, room_id, first_question_id, now, now),
        )

        thread_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return ConversationThread(
            id=thread_id,
            thread_key=thread_key,
            source=source,
            room_id=room_id,
            first_question_id=first_question_id,
            state="pending_question",
            created_at=now,
            updated_at=now,
            candidate_id=None,
            faq_id=None,
        )

    def get_thread(self, thread_id: int) -> Optional[ConversationThread]:
        """Get a thread by ID.

        Args:
            thread_id: Thread database ID

        Returns:
            ConversationThread if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, thread_key, source, room_id, first_question_id, state,
                   created_at, updated_at, candidate_id, faq_id, correction_reason
            FROM conversation_threads
            WHERE id = ?
            """,
            (thread_id,),
        )

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return ConversationThread(
            id=row[0],
            thread_key=row[1],
            source=row[2],
            room_id=row[3],
            first_question_id=row[4],
            state=row[5],
            created_at=row[6],
            updated_at=row[7],
            candidate_id=row[8],
            faq_id=row[9],
            correction_reason=row[10] if len(row) > 10 else None,
        )

    def add_message_to_thread(
        self,
        thread_id: int,
        message_id: str,
        message_type: str,
        content: str,
        sender_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> ThreadMessage:
        """Add a message to a thread.

        Args:
            thread_id: Thread database ID
            message_id: Original source message ID
            message_type: Type of message (question, staff_answer, correction, user_followup)
            content: Message content
            sender_id: Identifier of the sender (optional)
            timestamp: Message timestamp (optional, defaults to now)

        Returns:
            Created ThreadMessage
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            INSERT INTO thread_messages
            (thread_id, message_id, message_type, sender_id, content, timestamp, is_processed)
            VALUES (?, ?, ?, ?, ?, ?, FALSE)
            """,
            (thread_id, message_id, message_type, sender_id, content, timestamp),
        )

        message_db_id = cursor.lastrowid

        # Update thread's updated_at timestamp
        cursor.execute(
            """
            UPDATE conversation_threads
            SET updated_at = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), thread_id),
        )

        conn.commit()
        conn.close()

        return ThreadMessage(
            id=message_db_id,
            thread_id=thread_id,
            message_id=message_id,
            message_type=message_type,
            sender_id=sender_id,
            content=content,
            timestamp=timestamp,
            is_processed=False,
        )

    def get_thread_messages(self, thread_id: int) -> List[ThreadMessage]:
        """Get all messages for a thread.

        Args:
            thread_id: Thread database ID

        Returns:
            List of ThreadMessage objects ordered by timestamp
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, thread_id, message_id, message_type, sender_id,
                   content, timestamp, is_processed
            FROM thread_messages
            WHERE thread_id = ?
            ORDER BY timestamp ASC
            """,
            (thread_id,),
        )

        rows = cursor.fetchall()
        conn.close()

        return [
            ThreadMessage(
                id=row[0],
                thread_id=row[1],
                message_id=row[2],
                message_type=row[3],
                sender_id=row[4],
                content=row[5],
                timestamp=row[6],
                is_processed=bool(row[7]),
            )
            for row in rows
        ]

    def find_thread_by_message(self, message_id: str) -> Optional[ConversationThread]:
        """Find a thread by any message ID within it.

        Args:
            message_id: Message ID to search for

        Returns:
            ConversationThread if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Join thread_messages to conversation_threads
        cursor.execute(
            """
            SELECT t.id, t.thread_key, t.source, t.room_id, t.first_question_id,
                   t.state, t.created_at, t.updated_at, t.candidate_id, t.faq_id,
                   t.correction_reason
            FROM conversation_threads t
            JOIN thread_messages m ON t.id = m.thread_id
            WHERE m.message_id = ?
            """,
            (message_id,),
        )

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return ConversationThread(
            id=row[0],
            thread_key=row[1],
            source=row[2],
            room_id=row[3],
            first_question_id=row[4],
            state=row[5],
            created_at=row[6],
            updated_at=row[7],
            candidate_id=row[8],
            faq_id=row[9],
            correction_reason=row[10] if len(row) > 10 else None,
        )

    def transition_thread_state(
        self,
        thread_id: int,
        to_state: str,
        trigger: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Transition a thread to a new state with audit trail.

        Args:
            thread_id: Thread database ID
            to_state: New state to transition to
            trigger: What caused this transition
            metadata: Optional additional metadata for the audit record
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get current state for audit
        cursor.execute(
            "SELECT state FROM conversation_threads WHERE id = ?",
            (thread_id,),
        )
        row = cursor.fetchone()
        from_state = row[0] if row else None

        now = datetime.now(timezone.utc).isoformat()

        # Update thread state
        cursor.execute(
            """
            UPDATE conversation_threads
            SET state = ?, updated_at = ?
            WHERE id = ?
            """,
            (to_state, now, thread_id),
        )

        # Create audit record
        import json

        metadata_json = json.dumps(metadata) if metadata else None
        cursor.execute(
            """
            INSERT INTO conversation_state_transitions
            (thread_id, from_state, to_state, trigger, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thread_id, from_state, to_state, trigger, metadata_json, now),
        )

        conn.commit()
        conn.close()

    def link_thread_to_candidate(
        self, thread_id: int, candidate_id: int, trigger: str = "candidate_created"
    ) -> None:
        """Link a conversation thread to a candidate and update state.

        Args:
            thread_id: Thread database ID
            candidate_id: Candidate database ID to link
            trigger: Trigger for state transition (default: candidate_created)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now(timezone.utc).isoformat()

        # Update thread with candidate link
        cursor.execute(
            """
            UPDATE conversation_threads
            SET candidate_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (candidate_id, now, thread_id),
        )

        conn.commit()
        conn.close()

        # Transition state to candidate_created
        self.transition_thread_state(
            thread_id=thread_id,
            to_state="candidate_created",
            trigger=trigger,
            metadata={"candidate_id": candidate_id},
        )

    def link_thread_to_faq(
        self, thread_id: int, faq_id: str, trigger: str = "faq_approved"
    ) -> None:
        """Link a conversation thread to an FAQ and close the thread.

        Args:
            thread_id: Thread database ID
            faq_id: FAQ ID to link
            trigger: Trigger for state transition (default: faq_approved)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now(timezone.utc).isoformat()

        # Update thread with FAQ link
        cursor.execute(
            """
            UPDATE conversation_threads
            SET faq_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (faq_id, now, thread_id),
        )

        conn.commit()
        conn.close()

        # Transition state to closed
        self.transition_thread_state(
            thread_id=thread_id,
            to_state="closed",
            trigger=trigger,
            metadata={"faq_id": faq_id},
        )

    def find_thread_by_candidate_id(
        self, candidate_id: int
    ) -> Optional[ConversationThread]:
        """Find a thread by its linked candidate ID.

        Args:
            candidate_id: Candidate database ID to search for

        Returns:
            ConversationThread if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, thread_key, source, room_id, first_question_id, state,
                   created_at, updated_at, candidate_id, faq_id, correction_reason
            FROM conversation_threads
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        )

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return ConversationThread(
            id=row[0],
            thread_key=row[1],
            source=row[2],
            room_id=row[3],
            first_question_id=row[4],
            state=row[5],
            created_at=row[6],
            updated_at=row[7],
            candidate_id=row[8],
            faq_id=row[9],
            correction_reason=row[10] if len(row) > 10 else None,
        )

    def get_thread_transitions(self, thread_id: int) -> List[Dict]:
        """Get state transition history for a thread.

        Args:
            thread_id: Thread database ID

        Returns:
            List of transition dictionaries with from_state, to_state, trigger, metadata
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, from_state, to_state, trigger, metadata, created_at
            FROM conversation_state_transitions
            WHERE thread_id = ?
            ORDER BY created_at ASC
            """,
            (thread_id,),
        )

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row[0],
                "from_state": row[1],
                "to_state": row[2],
                "trigger": row[3],
                "metadata": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

    def get_threads_by_state(self, state: str) -> List[ConversationThread]:
        """Get all threads with a specific state.

        Cycle 18: Used to find all threads flagged for review.

        Args:
            state: Thread state to filter by (e.g., "reopened_for_correction")

        Returns:
            List of ConversationThread objects with the specified state
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, thread_key, source, room_id, first_question_id, state,
                   created_at, updated_at, candidate_id, faq_id, correction_reason
            FROM conversation_threads
            WHERE state = ?
            ORDER BY updated_at DESC
            """,
            (state,),
        )

        rows = cursor.fetchall()
        conn.close()

        return [
            ConversationThread(
                id=row[0],
                thread_key=row[1],
                source=row[2],
                room_id=row[3],
                first_question_id=row[4],
                state=row[5],
                created_at=row[6],
                updated_at=row[7],
                candidate_id=row[8],
                faq_id=row[9],
                correction_reason=row[10],
            )
            for row in rows
        ]

    def reopen_thread_for_correction(
        self,
        thread_id: int,
        correction_reason: str,
        trigger: str = "staff_correction",
    ) -> None:
        """Reopen a closed thread for post-approval correction.

        This is used when a staff member corrects their answer after
        the FAQ has already been approved. The thread is reopened
        and the correction reason is stored.

        Args:
            thread_id: Thread database ID
            correction_reason: Reason/description of the correction
            trigger: Trigger for state transition (default: staff_correction)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now(timezone.utc).isoformat()

        # Update thread with correction reason and state
        cursor.execute(
            """
            UPDATE conversation_threads
            SET correction_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (correction_reason, now, thread_id),
        )

        conn.commit()
        conn.close()

        # Transition state to reopened_for_correction
        self.transition_thread_state(
            thread_id=thread_id,
            to_state="reopened_for_correction",
            trigger=trigger,
            metadata={"correction_reason": correction_reason},
        )
