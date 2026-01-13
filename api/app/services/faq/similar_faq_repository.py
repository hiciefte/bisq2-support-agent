"""
SQLite-based Similar FAQ Candidate repository with security hardening.

Security features implemented:
- SQL injection prevention via parameterized queries (CRITICAL)
- Race condition prevention via write locks (CRITICAL)
- WAL mode for concurrent reads during writes
- Persistent connection with connection pooling
- Transaction isolation for data integrity

Following patterns from faq_repository_sqlite.py
"""

import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.similar_faq_candidate import (
    SimilarFaqCandidate,
    SimilarFaqCandidateListResponse,
)

logger = logging.getLogger(__name__)

# Retry configuration for database lock handling
MAX_RETRIES = 5
INITIAL_BACKOFF_MS = 100
MAX_BACKOFF_MS = 5000


class SimilarFaqRepository:
    """
    SQLite-based repository for Similar FAQ Candidates.

    Security mitigations:
    1. SQL Injection: All queries use parameterized statements
    2. Race Conditions: Write lock for concurrent modification
    3. Concurrent Access: WAL mode + persistent connection
    """

    def __init__(self, db_path: str):
        """
        Initialize SQLite repository with security hardening.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._read_lock = threading.Lock()

        # Ensure parent directory exists
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        # Create database file if missing
        if not db_file.exists():
            try:
                db_file.touch(mode=0o600)
                logger.info("Created database file with mode 600: %s", db_path)
            except (OSError, PermissionError) as e:
                db_file.touch()
                logger.warning(
                    "Created database file with default permissions: %s - %s",
                    db_path,
                    e,
                )

        # Create writer connection
        self._writer_conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level="IMMEDIATE",
            timeout=10.0,
        )
        self._writer_conn.row_factory = sqlite3.Row

        # Create reader connection
        self._reader_conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level="DEFERRED",
            timeout=10.0,
        )
        self._reader_conn.row_factory = sqlite3.Row

        # Configure connections with WAL mode
        for conn in [self._writer_conn, self._reader_conn]:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")

        # Initialize schema
        self._initialize_schema()

        logger.info(f"Similar FAQ repository initialized: {db_path}")

    def _initialize_schema(self):
        """Create database schema if it doesn't exist."""
        with self._writer_conn:
            # Create similar FAQ candidates table
            # Note: matched_faq_* columns store denormalized data because
            # FAQs are in a separate database (faqs.db), not this database
            self._writer_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS similar_faq_candidates (
                    id TEXT PRIMARY KEY,
                    extracted_question TEXT NOT NULL,
                    extracted_answer TEXT NOT NULL,
                    extracted_category TEXT,
                    matched_faq_id INTEGER NOT NULL,
                    matched_question TEXT,
                    matched_answer TEXT,
                    matched_category TEXT,
                    similarity REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    extracted_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    dismiss_reason TEXT,
                    merge_mode TEXT
                )
            """
            )

            # Create indexes for performance
            self._writer_conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_similar_faq_status
                ON similar_faq_candidates(status)
            """
            )

            self._writer_conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_similar_faq_matched_id
                ON similar_faq_candidates(matched_faq_id)
            """
            )

    def _execute_with_retry(self, operation, *args, **kwargs):
        """
        Execute database operation with exponential backoff retry on lock errors.
        """
        last_error = None
        backoff_ms = INITIAL_BACKOFF_MS

        for attempt in range(MAX_RETRIES):
            try:
                return operation(*args, **kwargs)
            except sqlite3.OperationalError as e:
                error_msg = str(e).lower()
                if "locked" in error_msg or "busy" in error_msg:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        sleep_ms = min(backoff_ms, MAX_BACKOFF_MS)
                        time.sleep(sleep_ms / 1000.0)
                        backoff_ms *= 2
                        logger.warning(
                            f"Database locked, retry {attempt + 1}/{MAX_RETRIES}: {e}"
                        )
                    continue
                else:
                    raise
            except sqlite3.DatabaseError:
                logger.exception("Database error (not retrying)")
                raise

        logger.error("All %s retries exhausted", MAX_RETRIES)
        raise last_error

    def add_candidate(
        self,
        extracted_question: str,
        extracted_answer: str,
        matched_faq_id: int,
        similarity: float,
        extracted_category: Optional[str] = None,
        matched_question: Optional[str] = None,
        matched_answer: Optional[str] = None,
        matched_category: Optional[str] = None,
    ) -> SimilarFaqCandidate:
        """
        Add a new similar FAQ candidate.

        Args:
            extracted_question: Question extracted from support conversation
            extracted_answer: Answer extracted from support conversation
            matched_faq_id: ID of the existing FAQ that this matches
            similarity: Similarity score (0.0 - 1.0)
            extracted_category: Optional category for the extracted FAQ
            matched_question: Question text of the matched FAQ (denormalized)
            matched_answer: Answer text of the matched FAQ (denormalized)
            matched_category: Category of the matched FAQ (denormalized)

        Returns:
            Created SimilarFaqCandidate with generated ID
        """
        candidate_id = str(uuid.uuid4())
        extracted_at = datetime.now(timezone.utc)

        def _add_operation():
            with self._write_lock:
                with self._writer_conn:
                    self._writer_conn.execute(
                        """
                        INSERT INTO similar_faq_candidates (
                            id, extracted_question, extracted_answer, extracted_category,
                            matched_faq_id, matched_question, matched_answer, matched_category,
                            similarity, status, extracted_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (
                            candidate_id,
                            extracted_question,
                            extracted_answer,
                            extracted_category,
                            matched_faq_id,
                            matched_question,
                            matched_answer,
                            matched_category,
                            similarity,
                            extracted_at.isoformat(),
                        ),
                    )

        self._execute_with_retry(_add_operation)

        return SimilarFaqCandidate(
            id=candidate_id,
            extracted_question=extracted_question,
            extracted_answer=extracted_answer,
            extracted_category=extracted_category,
            matched_faq_id=matched_faq_id,
            similarity=similarity,
            status="pending",
            extracted_at=extracted_at,
            resolved_at=None,
            resolved_by=None,
            dismiss_reason=None,
            matched_question=matched_question or "",
            matched_answer=matched_answer or "",
            matched_category=matched_category,
        )

    def get_candidate_by_id(self, candidate_id: str) -> Optional[SimilarFaqCandidate]:
        """
        Get a candidate by ID.

        Args:
            candidate_id: UUID of the candidate

        Returns:
            SimilarFaqCandidate if found, None otherwise
        """
        with self._read_lock:
            cursor = self._reader_conn.execute(
                "SELECT * FROM similar_faq_candidates WHERE id = ?",
                (candidate_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_candidate(row)
            return None

    def get_pending_candidates(self) -> SimilarFaqCandidateListResponse:
        """
        Get all pending candidates with matched FAQ details.

        Returns:
            SimilarFaqCandidateListResponse with pending candidates
        """
        with self._read_lock:
            cursor = self._reader_conn.execute(
                """
                SELECT * FROM similar_faq_candidates
                WHERE status = 'pending'
                ORDER BY extracted_at DESC
                """
            )
            rows = cursor.fetchall()

            # Get total count
            count_cursor = self._reader_conn.execute(
                "SELECT COUNT(*) FROM similar_faq_candidates WHERE status = 'pending'"
            )
            total = count_cursor.fetchone()[0]

        items = [self._row_to_candidate(row) for row in rows]
        return SimilarFaqCandidateListResponse(items=items, total=total)

    def approve_candidate(self, candidate_id: str, resolved_by: str) -> bool:
        """
        Approve a candidate (mark as approved).

        Args:
            candidate_id: UUID of the candidate
            resolved_by: Admin who approved

        Returns:
            True if successful, False if candidate not found or already resolved
        """
        return self._resolve_candidate(candidate_id, "approved", resolved_by)

    def merge_candidate(self, candidate_id: str, resolved_by: str, mode: str) -> bool:
        """
        Merge a candidate into an existing FAQ.

        Args:
            candidate_id: UUID of the candidate
            resolved_by: Admin who merged
            mode: Merge mode ('replace' or 'append')

        Returns:
            True if successful, False if candidate not found or already resolved
        """
        resolved_at = datetime.now(timezone.utc).isoformat()

        def _merge_operation():
            with self._write_lock:
                with self._writer_conn:
                    # Only merge pending candidates
                    cursor = self._writer_conn.execute(
                        """
                        UPDATE similar_faq_candidates
                        SET status = 'merged', resolved_at = ?, resolved_by = ?,
                            merge_mode = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (resolved_at, resolved_by, mode, candidate_id),
                    )
                    return cursor.rowcount > 0

        return self._execute_with_retry(_merge_operation)

    def dismiss_candidate(
        self, candidate_id: str, resolved_by: str, reason: Optional[str] = None
    ) -> bool:
        """
        Dismiss a candidate.

        Args:
            candidate_id: UUID of the candidate
            resolved_by: Admin who dismissed
            reason: Optional reason for dismissal

        Returns:
            True if successful, False if candidate not found or already resolved
        """
        resolved_at = datetime.now(timezone.utc).isoformat()

        def _dismiss_operation():
            with self._write_lock:
                with self._writer_conn:
                    # Only dismiss pending candidates
                    cursor = self._writer_conn.execute(
                        """
                        UPDATE similar_faq_candidates
                        SET status = 'dismissed', resolved_at = ?, resolved_by = ?,
                            dismiss_reason = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (resolved_at, resolved_by, reason, candidate_id),
                    )
                    return cursor.rowcount > 0

        return self._execute_with_retry(_dismiss_operation)

    def _resolve_candidate(
        self, candidate_id: str, status: str, resolved_by: str
    ) -> bool:
        """
        Generic method to resolve a candidate (approve/merge/dismiss).

        Args:
            candidate_id: UUID of the candidate
            status: New status
            resolved_by: Admin who resolved

        Returns:
            True if successful, False if candidate not found or already resolved
        """
        resolved_at = datetime.now(timezone.utc).isoformat()

        def _resolve_operation():
            with self._write_lock:
                with self._writer_conn:
                    # Only resolve pending candidates
                    cursor = self._writer_conn.execute(
                        """
                        UPDATE similar_faq_candidates
                        SET status = ?, resolved_at = ?, resolved_by = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (status, resolved_at, resolved_by, candidate_id),
                    )
                    return cursor.rowcount > 0

        return self._execute_with_retry(_resolve_operation)

    def _row_to_candidate(self, row: sqlite3.Row) -> SimilarFaqCandidate:
        """Convert database row to SimilarFaqCandidate."""
        return SimilarFaqCandidate(
            id=row["id"],
            extracted_question=row["extracted_question"],
            extracted_answer=row["extracted_answer"],
            extracted_category=row["extracted_category"],
            matched_faq_id=row["matched_faq_id"],
            similarity=row["similarity"],
            status=row["status"],
            extracted_at=datetime.fromisoformat(row["extracted_at"]),
            resolved_at=(
                datetime.fromisoformat(row["resolved_at"])
                if row["resolved_at"]
                else None
            ),
            resolved_by=row["resolved_by"],
            dismiss_reason=row["dismiss_reason"],
            matched_question=row["matched_question"] or "",
            matched_answer=row["matched_answer"] or "",
            matched_category=row["matched_category"],
        )

    def close(self):
        """Close database connections."""
        if hasattr(self, "_writer_conn"):
            self._writer_conn.close()
        if hasattr(self, "_reader_conn"):
            self._reader_conn.close()
            logger.info("Similar FAQ repository connection closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
