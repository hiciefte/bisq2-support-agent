"""SQLite repository for Shadow Mode with two-phase workflow."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.shadow_response import ShadowResponse, ShadowStatus

logger = logging.getLogger(__name__)


class ShadowModeRepository:
    """SQLite repository for shadow mode responses."""

    # Column whitelist for SQL injection protection
    ALLOWED_FILTER_COLUMNS = {
        "id",
        "channel_id",
        "user_id",
        "detected_version",
        "confirmed_version",
        "training_protocol",
        "status",
        "source",
        "requires_clarification",
        "created_at",
        "updated_at",
        "version_confirmed_at",
        "response_generated_at",
    }

    ALLOWED_UPDATE_COLUMNS = {
        "messages",
        "synthesized_question",
        "detected_version",
        "version_confidence",
        "detection_signals",
        "confirmed_version",
        "version_change_reason",
        "training_protocol",
        "requires_clarification",
        "clarifying_question",
        "source",
        "clarification_answer",
        "preprocessed",
        "generated_response",
        "sources",
        "edited_response",
        "confidence",
        "routing_action",
        "status",
        "rag_error",
        "retry_count",
        "skip_reason",
        "updated_at",
        "version_confirmed_at",
        "response_generated_at",
    }

    def __init__(self, db_path: str):
        """Initialize repository with database path."""
        self.db_path = db_path
        self._create_tables()

    def _build_filter_clause(self, filters: Dict[str, Any]) -> tuple[str, List[Any]]:
        """Build SQL filter clause with SQL injection protection.

        Args:
            filters: Dictionary of column-value pairs to filter by

        Returns:
            Tuple of (WHERE clause string, parameter list)

        Raises:
            ValueError: If any filter column is not in whitelist
        """
        if not filters:
            return "", []

        conditions = []
        params = []

        for key, value in filters.items():
            # Validate column name (SQL injection prevention)
            if key not in self.ALLOWED_FILTER_COLUMNS:
                raise ValueError(
                    f"Invalid filter column: {key}. "
                    f"Allowed columns: {', '.join(sorted(self.ALLOWED_FILTER_COLUMNS))}"
                )

            conditions.append(f"{key} = ?")
            params.append(value)

        return " AND ".join(conditions), params

    def _create_tables(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_responses (
                id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                messages TEXT NOT NULL,
                synthesized_question TEXT,
                detected_version TEXT,
                version_confidence REAL DEFAULT 0.0,
                detection_signals TEXT,
                confirmed_version TEXT,
                version_change_reason TEXT,
                training_protocol TEXT,
                requires_clarification BOOLEAN DEFAULT FALSE,
                clarifying_question TEXT,
                source TEXT DEFAULT 'shadow_mode',
                clarification_answer TEXT,
                preprocessed TEXT,
                generated_response TEXT,
                sources TEXT,
                edited_response TEXT,
                confidence REAL,
                routing_action TEXT,
                status TEXT NOT NULL DEFAULT 'pending_version_review',
                rag_error TEXT,
                retry_count INTEGER DEFAULT 0,
                skip_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version_confirmed_at TEXT,
                response_generated_at TEXT
            )
        """
        )

        # Create indexes for common queries
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_status
            ON shadow_responses(status)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_created_at
            ON shadow_responses(created_at)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_channel_id
            ON shadow_responses(channel_id)
        """
        )

        # Unknown version enhancement indexes
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_responses_clarification
            ON shadow_responses(requires_clarification, training_protocol)
            WHERE requires_clarification = TRUE
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_responses_version_training
            ON shadow_responses(confirmed_version, training_protocol)
        """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_shadow_responses_source
            ON shadow_responses(source, created_at)
            WHERE source = 'rag_bot_clarification'
        """
        )

        conn.commit()
        conn.close()

    def get_response(self, response_id: str) -> Optional[ShadowResponse]:
        """Get a shadow response by ID."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM shadow_responses WHERE id = ?", (response_id,))
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_response(row)

    def get_by_question_id(self, question_id: str) -> Optional[ShadowResponse]:
        """Get a shadow response by question ID (Matrix event_id).

        This is an alias for get_response() since the response ID IS the question ID.
        Used for database duplicate checking during polling.

        Args:
            question_id: Matrix event ID

        Returns:
            ShadowResponse if found, None otherwise
        """
        return self.get_response(question_id)

    def get_responses(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ShadowResponse]:
        """Get shadow responses with optional filtering."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if status:
            cursor.execute(
                """
                SELECT * FROM shadow_responses
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """,
                (status, limit, offset),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM shadow_responses
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """,
                (limit, offset),
            )

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_response(row) for row in rows]

    def update_response(self, response_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields of a shadow response.

        Args:
            response_id: The response ID to update
            updates: Dictionary of column-value pairs to update

        Returns:
            True if response was updated, False otherwise

        Raises:
            ValueError: If any update column is not in whitelist
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Build dynamic update query with SQL injection protection
        set_clauses = []
        values = []

        for key, value in updates.items():
            # Validate column name (SQL injection prevention)
            if key not in self.ALLOWED_UPDATE_COLUMNS:
                conn.close()
                raise ValueError(
                    f"Invalid update column: {key}. "
                    f"Allowed columns: {', '.join(sorted(self.ALLOWED_UPDATE_COLUMNS))}"
                )

            set_clauses.append(f"{key} = ?")
            # Serialize JSON fields
            if key in ["messages", "detection_signals", "preprocessed", "sources"]:
                values.append(json.dumps(value) if value else None)
            elif key in [
                "created_at",
                "updated_at",
                "version_confirmed_at",
                "response_generated_at",
            ]:
                if isinstance(value, datetime):
                    values.append(value.isoformat())
                else:
                    values.append(value)
            else:
                values.append(value)

        # Always update updated_at
        if "updated_at" not in updates:
            set_clauses.append("updated_at = ?")
            values.append(datetime.now(timezone.utc).isoformat())

        values.append(response_id)

        query = f"UPDATE shadow_responses SET {', '.join(set_clauses)} WHERE id = ?"

        cursor.execute(query, values)
        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if updated:
            logger.debug(f"Updated shadow response: {response_id}")

        return updated

    def delete_response(self, response_id: str) -> bool:
        """Delete a shadow response by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM shadow_responses WHERE id = ?", (response_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if deleted:
            logger.debug(f"Deleted shadow response: {response_id}")

        return deleted

    def delete_all_responses(self) -> int:
        """Delete all shadow responses. Returns count deleted."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM shadow_responses")
        count = cursor.fetchone()[0]

        cursor.execute("DELETE FROM shadow_responses")
        conn.commit()
        conn.close()

        logger.info(f"Deleted all {count} shadow responses")
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about shadow responses."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get counts by status
        cursor.execute(
            """
            SELECT status, COUNT(*) as count
            FROM shadow_responses
            GROUP BY status
        """
        )
        status_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Get total
        cursor.execute("SELECT COUNT(*) FROM shadow_responses")
        total = cursor.fetchone()[0]

        # Get average confidence
        cursor.execute(
            """
            SELECT AVG(version_confidence)
            FROM shadow_responses
            WHERE version_confidence > 0
        """
        )
        avg_confidence = cursor.fetchone()[0] or 0.0

        conn.close()

        return {
            "total": total,
            "pending_version_review": status_counts.get("pending_version_review", 0),
            "pending_response_review": status_counts.get("pending_response_review", 0),
            "rag_failed": status_counts.get("rag_failed", 0),
            "approved": status_counts.get("approved", 0),
            "edited": status_counts.get("edited", 0),
            "rejected": status_counts.get("rejected", 0),
            "skipped": status_counts.get("skipped", 0),
            "avg_confidence": round(avg_confidence, 2),
        }

    def confirm_version(
        self,
        response_id: str,
        confirmed_version: str,
        change_reason: Optional[str] = None,
        training_protocol: Optional[str] = None,
        requires_clarification: bool = False,
        clarifying_question: Optional[str] = None,
    ) -> bool:
        """Confirm version and move to pending_response_review status.

        Args:
            response_id: The response ID
            confirmed_version: The confirmed version (bisq1, bisq2, unknown)
            change_reason: Optional reason if version was changed
            training_protocol: Optional training version for Unknown cases
            requires_clarification: Flag if question needs clarification
            clarifying_question: Optional custom clarifying question

        Returns:
            True if updated successfully

        Raises:
            ValueError: If response is not in pending_version_review status
        """
        # Get current response to validate status
        response = self.get_response(response_id)
        if response is None:
            return False

        if response.status != ShadowStatus.PENDING_VERSION_REVIEW:
            raise ValueError(
                f"Cannot confirm version: response {response_id} is in "
                f"{response.status.value} status, expected pending_version_review"
            )

        now = datetime.now(timezone.utc)
        updates = {
            "confirmed_version": confirmed_version,
            "version_change_reason": change_reason,
            "training_protocol": training_protocol,
            "requires_clarification": requires_clarification,
            "clarifying_question": clarifying_question,
            "status": ShadowStatus.PENDING_RESPONSE_REVIEW.value,
            "version_confirmed_at": now,
            "updated_at": now,
        }

        return self.update_response(response_id, updates)

    def skip_response(self, response_id: str) -> bool:
        """Skip a response (mark as skipped).

        Args:
            response_id: The response ID

        Returns:
            True if updated successfully
        """
        return self.update_response(
            response_id,
            {
                "status": ShadowStatus.SKIPPED.value,
                "updated_at": datetime.now(timezone.utc),
            },
        )

    def update_rag_result(
        self,
        response_id: str,
        generated_response: Optional[str],
        sources: List[Dict[str, Any]],
        rag_error: Optional[str],
    ) -> bool:
        """Update response with RAG result (success or failure).

        Args:
            response_id: The response ID
            generated_response: The generated response text (None if failed)
            sources: List of source documents used
            rag_error: Error message if RAG failed (None if success)

        Returns:
            True if updated successfully
        """
        response = self.get_response(response_id)
        if response is None:
            return False

        now = datetime.now(timezone.utc)
        new_retry_count = response.retry_count + 1

        if rag_error:
            # RAG failed
            updates = {
                "status": ShadowStatus.RAG_FAILED.value,
                "rag_error": rag_error,
                "retry_count": new_retry_count,
                "updated_at": now,
            }
        else:
            # RAG succeeded
            updates = {
                "status": ShadowStatus.PENDING_RESPONSE_REVIEW.value,
                "generated_response": generated_response,
                "sources": sources,
                "rag_error": None,
                "retry_count": new_retry_count,
                "response_generated_at": now,
                "updated_at": now,
            }

        return self.update_response(response_id, updates)

    def get_version_changes(self) -> List[Dict[str, Any]]:
        """Get all responses where version was changed from detected.

        Returns:
            List of version change events for training data collection
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, messages, synthesized_question, detected_version,
                   version_confidence, detection_signals, confirmed_version,
                   version_change_reason, training_protocol, requires_clarification,
                   clarifying_question, source, clarification_answer, version_confirmed_at
            FROM shadow_responses
            WHERE confirmed_version IS NOT NULL
              AND confirmed_version != detected_version
            ORDER BY version_confirmed_at DESC
        """
        )

        rows = cursor.fetchall()
        conn.close()

        changes = []
        for row in rows:
            changes.append(
                {
                    "id": row["id"],
                    "messages": (
                        json.loads(row["messages"]) if row["messages"] else []
                    ),
                    "synthesized_question": row["synthesized_question"],
                    "detected_version": row["detected_version"],
                    "version_confidence": row["version_confidence"],
                    "detection_signals": (
                        json.loads(row["detection_signals"])
                        if row["detection_signals"]
                        else {}
                    ),
                    "confirmed_version": row["confirmed_version"],
                    "version_change_reason": row["version_change_reason"],
                    "training_protocol": row["training_protocol"],
                    "requires_clarification": row["requires_clarification"],
                    "clarifying_question": row["clarifying_question"],
                    "source": row["source"],
                    "clarification_answer": row["clarification_answer"],
                    "version_confirmed_at": row["version_confirmed_at"],
                }
            )

        return changes

    def get_skip_patterns(self) -> List[Dict[str, Any]]:
        """Get all skipped responses with reasons for ML training.

        Returns:
            List of skipped entries for question detection training
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, messages, synthesized_question, skip_reason, updated_at,
                   requires_clarification, version_confidence
            FROM shadow_responses
            WHERE status = 'skipped'
            ORDER BY updated_at DESC
        """
        )

        rows = cursor.fetchall()
        conn.close()

        patterns = []
        for row in rows:
            patterns.append(
                {
                    "id": row["id"],
                    "messages": (
                        json.loads(row["messages"]) if row["messages"] else []
                    ),
                    "synthesized_question": row["synthesized_question"],
                    "skip_reason": row["skip_reason"],
                    "skipped_at": row["updated_at"],
                    "requires_clarification": bool(row["requires_clarification"]),
                    "version_confidence": row["version_confidence"],
                }
            )

        return patterns

    def get_recent_messages(
        self,
        channel_id: str,
        limit: int = 10,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent messages for cross-poll context.

        Args:
            channel_id: Matrix channel ID to fetch messages from
            limit: Maximum number of messages to return
            before: ISO timestamp - only return messages before this time

        Returns:
            List of message dictionaries with content, sender, timestamp
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build query based on whether 'before' timestamp is provided
        if before:
            cursor.execute(
                """
                SELECT messages, created_at
                FROM shadow_responses
                WHERE channel_id = ?
                  AND created_at < ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (channel_id, before, limit),
            )
        else:
            cursor.execute(
                """
                SELECT messages, created_at
                FROM shadow_responses
                WHERE channel_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (channel_id, limit),
            )

        rows = cursor.fetchall()
        conn.close()

        # Extract all messages from each response
        all_messages = []
        for row in rows:
            messages_json = row["messages"]
            if messages_json:
                messages = json.loads(messages_json)
                # Messages can be a list or dict - normalize to list
                if isinstance(messages, list):
                    all_messages.extend(messages)
                elif isinstance(messages, dict):
                    all_messages.append(messages)

        # Return most recent messages up to limit
        return all_messages[:limit]

    def add_response(self, response: ShadowResponse) -> bool:
        """Add a new shadow response to the database.

        Returns:
            True if response was added, False if it already exists (idempotent)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO shadow_responses (
                    id, channel_id, user_id, messages, synthesized_question,
                    detected_version, version_confidence, detection_signals,
                    confirmed_version, version_change_reason, training_protocol,
                    requires_clarification, clarifying_question, source, clarification_answer,
                    preprocessed, generated_response, sources, edited_response, confidence,
                    routing_action, status, rag_error, retry_count, skip_reason,
                    created_at, updated_at, version_confirmed_at, response_generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    response.id,
                    response.channel_id,
                    response.user_id,
                    json.dumps(response.messages),
                    response.synthesized_question,
                    response.detected_version,
                    response.version_confidence,
                    (
                        json.dumps(response.detection_signals)
                        if response.detection_signals
                        else None
                    ),
                    response.confirmed_version,
                    response.version_change_reason,
                    response.training_protocol,
                    response.requires_clarification,
                    response.clarifying_question,
                    response.source,
                    response.clarification_answer,
                    (
                        json.dumps(response.preprocessed)
                        if response.preprocessed
                        else None
                    ),
                    response.generated_response,
                    json.dumps(response.sources) if response.sources else None,
                    response.edited_response,
                    response.confidence,
                    response.routing_action,
                    (
                        response.status.value
                        if isinstance(response.status, ShadowStatus)
                        else response.status
                    ),
                    response.rag_error,
                    response.retry_count,
                    response.skip_reason,
                    (
                        response.created_at.isoformat()
                        if response.created_at
                        else datetime.now(timezone.utc).isoformat()
                    ),
                    (
                        response.updated_at.isoformat()
                        if response.updated_at
                        else datetime.now(timezone.utc).isoformat()
                    ),
                    (
                        response.version_confirmed_at.isoformat()
                        if response.version_confirmed_at
                        else None
                    ),
                    (
                        response.response_generated_at.isoformat()
                        if response.response_generated_at
                        else None
                    ),
                ),
            )

            conn.commit()
            logger.debug(f"Added shadow response: {response.id}")
            return True

        except sqlite3.IntegrityError:
            logger.info(f"Response {response.id} already exists (idempotent)")
            return False
        finally:
            conn.close()

    def _row_to_response(self, row: sqlite3.Row) -> ShadowResponse:
        """Convert database row to ShadowResponse object."""
        # Parse JSON fields
        messages = json.loads(row["messages"]) if row["messages"] else []
        detection_signals = (
            json.loads(row["detection_signals"]) if row["detection_signals"] else {}
        )
        preprocessed = json.loads(row["preprocessed"]) if row["preprocessed"] else None
        sources = json.loads(row["sources"]) if row["sources"] else []

        # Parse timestamps
        created_at = (
            datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
        )
        updated_at = (
            datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
        )
        version_confirmed_at = (
            datetime.fromisoformat(row["version_confirmed_at"])
            if row["version_confirmed_at"]
            else None
        )
        response_generated_at = (
            datetime.fromisoformat(row["response_generated_at"])
            if row["response_generated_at"]
            else None
        )

        # Parse status
        status = ShadowStatus(row["status"])

        return ShadowResponse(
            id=row["id"],
            channel_id=row["channel_id"],
            user_id=row["user_id"],
            messages=messages,
            synthesized_question=row["synthesized_question"],
            detected_version=row["detected_version"],
            version_confidence=row["version_confidence"] or 0.0,
            detection_signals=detection_signals,
            confirmed_version=row["confirmed_version"],
            version_change_reason=row["version_change_reason"],
            training_protocol=(
                row["training_protocol"] if "training_protocol" in row.keys() else None
            ),
            requires_clarification=(
                row["requires_clarification"]
                if "requires_clarification" in row.keys()
                else False
            ),
            clarifying_question=(
                row["clarifying_question"]
                if "clarifying_question" in row.keys()
                else None
            ),
            source=row["source"] if "source" in row.keys() else "shadow_mode",
            clarification_answer=(
                row["clarification_answer"]
                if "clarification_answer" in row.keys()
                else None
            ),
            preprocessed=preprocessed,
            generated_response=row["generated_response"],
            sources=sources,
            edited_response=row["edited_response"],
            confidence=row["confidence"] if "confidence" in row.keys() else None,
            routing_action=(
                row["routing_action"] if "routing_action" in row.keys() else None
            ),
            status=status,
            rag_error=row["rag_error"],
            retry_count=row["retry_count"] or 0,
            skip_reason=row["skip_reason"] if "skip_reason" in row.keys() else None,
            created_at=created_at,
            updated_at=updated_at,
            version_confirmed_at=version_confirmed_at,
            response_generated_at=response_generated_at,
        )
