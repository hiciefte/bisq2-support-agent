"""
Feedback repository for SQLite database operations.

This module provides a clean interface for all feedback-related database
operations, abstracting away SQL queries from the service layer.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.database import get_database

logger = logging.getLogger(__name__)


class FeedbackRepository:
    """Repository for feedback database operations."""

    def __init__(self):
        """Initialize the feedback repository."""
        self.db = get_database()

    def store_feedback(
        self,
        message_id: str,
        question: str,
        answer: str,
        rating: int,
        explanation: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
        sources_used: Optional[List[Dict[str, Any]]] = None,
        channel: str = "web",
        feedback_method: str = "web_dialog",
        external_message_id: Optional[str] = None,
        reactor_identity_hash: Optional[str] = None,
        reaction_emoji: Optional[str] = None,
    ) -> int:
        """
        Store feedback entry in the database.

        Args:
            message_id: Unique message identifier
            question: User's question
            answer: Assistant's answer
            rating: 0 for negative, 1 for positive
            explanation: Optional user explanation
            conversation_history: Optional list of conversation messages
            metadata: Optional metadata dictionary
            timestamp: Optional ISO timestamp (defaults to now)
            sources: Optional list of source documents used in RAG response
            sources_used: Optional list of sources actually used (typically same as sources)
            channel: Source channel (e.g., "web", "matrix", "bisq2")
            feedback_method: Submission method (e.g., "web_dialog", "reaction")
            external_message_id: Channel-native message identifier for reactions
            reactor_identity_hash: Privacy-safe hashed reactor identity
            reaction_emoji: Raw reaction emoji/reaction key

        Returns:
            int: Feedback ID of the inserted entry

        Raises:
            sqlite3.IntegrityError: If message_id already exists
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        # Convert sources to JSON strings for storage
        sources_json = json.dumps(sources) if sources else None
        sources_used_json = json.dumps(sources_used) if sources_used else None

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Insert main feedback entry with sources and channel metadata
            cursor.execute(
                """
                INSERT INTO feedback (message_id, question, answer, rating, explanation,
                    sources, sources_used, timestamp, channel, feedback_method,
                    external_message_id, reactor_identity_hash, reaction_emoji)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    question,
                    answer,
                    rating,
                    explanation,
                    sources_json,
                    sources_used_json,
                    timestamp,
                    channel,
                    feedback_method,
                    external_message_id,
                    reactor_identity_hash,
                    reaction_emoji,
                ),
            )
            feedback_id = cursor.lastrowid

            # Insert conversation history
            if conversation_history:
                for position, message in enumerate(conversation_history):
                    cursor.execute(
                        """
                        INSERT INTO conversation_messages (feedback_id, role, content, position)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            feedback_id,
                            message.get("role", "user"),
                            message.get("content", ""),
                            position,
                        ),
                    )

            # Insert metadata
            if metadata and isinstance(metadata, dict):
                for key, value in metadata.items():
                    # Convert complex values to JSON strings
                    if not isinstance(value, str):
                        value = json.dumps(value)

                    cursor.execute(
                        """
                        INSERT INTO feedback_metadata (feedback_id, key, value)
                        VALUES (?, ?, ?)
                        """,
                        (feedback_id, key, value),
                    )

                # Extract and store issues from metadata
                issues = metadata.get("issues", [])
                if isinstance(issues, list):
                    for issue in issues:
                        if issue:  # Skip empty strings
                            cursor.execute(
                                """
                                INSERT INTO feedback_issues (feedback_id, issue_type)
                                VALUES (?, ?)
                                """,
                                (feedback_id, issue),
                            )

            conn.commit()
            logger.info(f"Stored feedback with ID: {feedback_id}")
            return feedback_id

    def get_feedback_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get feedback entry by message ID.

        Args:
            message_id: Message identifier

        Returns:
            Dictionary with feedback data or None if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Get main feedback entry
            cursor.execute(
                """
                SELECT id, message_id, question, answer, rating, explanation,
                       sources, sources_used, timestamp, created_at, processed,
                       processed_at, faq_id, channel, feedback_method,
                       external_message_id, reactor_identity_hash, reaction_emoji
                FROM feedback
                WHERE message_id = ?
                """,
                (message_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            feedback = dict(row)
            feedback_id = feedback["id"]

            # Deserialize sources from JSON strings
            if feedback.get("sources"):
                try:
                    feedback["sources"] = json.loads(feedback["sources"])
                except (json.JSONDecodeError, TypeError):
                    feedback["sources"] = None

            if feedback.get("sources_used"):
                try:
                    feedback["sources_used"] = json.loads(feedback["sources_used"])
                except (json.JSONDecodeError, TypeError):
                    feedback["sources_used"] = None

            # Get conversation history
            cursor.execute(
                """
                SELECT role, content, position
                FROM conversation_messages
                WHERE feedback_id = ?
                ORDER BY position
                """,
                (feedback_id,),
            )
            conversation_history = [
                {"role": row["role"], "content": row["content"]}
                for row in cursor.fetchall()
            ]
            feedback["conversation_history"] = conversation_history

            # Get metadata
            cursor.execute(
                """
                SELECT key, value
                FROM feedback_metadata
                WHERE feedback_id = ?
                """,
                (feedback_id,),
            )
            metadata = {}
            for row in cursor.fetchall():
                key = row["key"]
                value = row["value"]
                # Try to parse JSON values
                try:
                    metadata[key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    metadata[key] = value

            # Get issues
            cursor.execute(
                """
                SELECT issue_type
                FROM feedback_issues
                WHERE feedback_id = ?
                """,
                (feedback_id,),
            )
            issues = [row["issue_type"] for row in cursor.fetchall()]
            metadata["issues"] = issues

            # Keep explanation in metadata for FeedbackItem compatibility.
            if feedback.get("explanation"):
                metadata["explanation"] = feedback["explanation"]

            feedback["metadata"] = metadata

            return feedback

    def get_all_feedback(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        rating: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all feedback entries with optional filtering.

        Args:
            limit: Maximum number of entries to return
            offset: Number of entries to skip
            rating: Filter by rating (0 or 1)

        Returns:
            List of feedback dictionaries
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            query = (
                "SELECT id, message_id, question, answer, rating, explanation, "
                "sources, sources_used, timestamp, processed, processed_at, faq_id, "
                "channel, feedback_method, external_message_id, "
                "reactor_identity_hash, reaction_emoji "
                "FROM feedback"
            )
            params = []

            if rating is not None:
                query += " WHERE rating = ?"
                params.append(rating)

            query += " ORDER BY timestamp DESC"

            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)

            if offset > 0:
                query += " OFFSET ?"
                params.append(offset)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            feedback_ids = [row["id"] for row in rows]

            # Batch-fetch metadata and issues for all feedback entries
            metadata_map: Dict[int, Dict[str, Any]] = defaultdict(dict)
            issues_map: Dict[int, List[str]] = defaultdict(list)

            if feedback_ids:
                placeholders = ",".join("?" for _ in feedback_ids)

                # Fetch metadata
                cursor.execute(
                    f"""
                    SELECT feedback_id, key, value
                    FROM feedback_metadata
                    WHERE feedback_id IN ({placeholders})
                    """,
                    feedback_ids,
                )
                for meta_row in cursor.fetchall():
                    value = meta_row["value"]
                    try:
                        value = json.loads(value)
                    except (TypeError, json.JSONDecodeError):
                        pass
                    metadata_map[meta_row["feedback_id"]][meta_row["key"]] = value

                # Fetch issues
                cursor.execute(
                    f"""
                    SELECT feedback_id, issue_type
                    FROM feedback_issues
                    WHERE feedback_id IN ({placeholders})
                    """,
                    feedback_ids,
                )
                for issue_row in cursor.fetchall():
                    issues_map[issue_row["feedback_id"]].append(issue_row["issue_type"])

            feedback_list = []
            for row in rows:
                feedback = dict(row)
                feedback_id = feedback["id"]

                # Get conversation history count (not full content for performance)
                cursor.execute(
                    "SELECT COUNT(*) as count FROM conversation_messages WHERE feedback_id = ?",
                    (feedback_id,),
                )
                feedback["conversation_message_count"] = cursor.fetchone()["count"]

                # Attach metadata and issues
                metadata = metadata_map.get(feedback_id, {}).copy()

                # Add explanation from feedback table to metadata for FeedbackItem compatibility
                # The FeedbackItem model expects explanation in metadata.explanation
                if row["explanation"]:
                    metadata["explanation"] = row["explanation"]

                if issues_map[feedback_id]:
                    metadata["issues"] = issues_map[feedback_id]

                if metadata:
                    feedback["metadata"] = metadata

                # Deserialize sources from JSON strings
                if feedback.get("sources"):
                    try:
                        feedback["sources"] = json.loads(feedback["sources"])
                    except (json.JSONDecodeError, TypeError):
                        feedback["sources"] = None

                if feedback.get("sources_used"):
                    try:
                        feedback["sources_used"] = json.loads(feedback["sources_used"])
                    except (json.JSONDecodeError, TypeError):
                        feedback["sources_used"] = None

                feedback_list.append(feedback)

            return feedback_list

    def get_feedback_count(self, rating: Optional[int] = None) -> int:
        """
        Get total count of feedback entries.

        Args:
            rating: Optional filter by rating

        Returns:
            Total count
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if rating is not None:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM feedback WHERE rating = ?",
                    (rating,),
                )
            else:
                cursor.execute("SELECT COUNT(*) as count FROM feedback")

            return cursor.fetchone()["count"]

    def get_feedback_by_issue(self, issue_type: str) -> List[Dict[str, Any]]:
        """
        Get all feedback entries with a specific issue type.

        Args:
            issue_type: Issue type to filter by

        Returns:
            List of feedback dictionaries
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT DISTINCT f.id, f.message_id, f.question, f.answer, f.rating,
                       f.explanation, f.timestamp, f.processed, f.processed_at, f.faq_id
                FROM feedback f
                INNER JOIN feedback_issues fi ON f.id = fi.feedback_id
                WHERE fi.issue_type = ?
                ORDER BY f.timestamp DESC
                """,
                (issue_type,),
            )

            return [dict(row) for row in cursor.fetchall()]

    def update_feedback_rating(self, feedback_id: int, rating: int) -> bool:
        """Update the rating for a feedback entry by ID.

        Args:
            feedback_id: Internal feedback row ID.
            rating: New rating value (0=negative, 1=positive).

        Returns:
            True if updated, False if not found.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE feedback SET rating = ? WHERE id = ?",
                (rating, feedback_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_feedback_by_id(self, feedback_id: int) -> bool:
        """Delete feedback entry by internal feedback ID.

        Returns:
            True if deleted, False if not found.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update_feedback_explanation(self, message_id: str, explanation: str) -> bool:
        """
        Update the explanation for an existing feedback entry.

        Args:
            message_id: Message identifier
            explanation: New explanation text

        Returns:
            True if updated, False if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "UPDATE feedback SET explanation = ? WHERE message_id = ?",
                (explanation, message_id),
            )
            conn.commit()

            return cursor.rowcount > 0

    def update_feedback_issues(self, message_id: str, issues: List[str]) -> bool:
        """
        Update the issues for an existing feedback entry.

        This method adds new issues to the feedback entry without removing
        existing ones, ensuring all identified issues are captured.

        Args:
            message_id: Message identifier
            issues: List of issue types to add

        Returns:
            True if feedback entry exists and issues were added, False if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # First, get the feedback_id for this message_id
            cursor.execute(
                "SELECT id FROM feedback WHERE message_id = ?",
                (message_id,),
            )
            row = cursor.fetchone()

            if not row:
                logger.warning(f"Feedback entry not found for message_id: {message_id}")
                return False

            feedback_id = row["id"]

            # Add each issue to the feedback_issues table
            # Skip duplicates by checking if issue already exists
            for issue in issues:
                if not issue:  # Skip empty strings
                    continue

                # Check if this issue already exists for this feedback
                cursor.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM feedback_issues
                    WHERE feedback_id = ? AND issue_type = ?
                    """,
                    (feedback_id, issue),
                )
                count = cursor.fetchone()["count"]

                if count == 0:
                    # Insert the new issue
                    cursor.execute(
                        """
                        INSERT INTO feedback_issues (feedback_id, issue_type)
                        VALUES (?, ?)
                        """,
                        (feedback_id, issue),
                    )
                    logger.info(
                        f"Added issue '{issue}' to feedback {message_id} (ID: {feedback_id})"
                    )

            conn.commit()
            return True

    def set_feedback_metadata_value(
        self,
        message_id: str,
        key: str,
        value: Any,
    ) -> bool:
        """Upsert a feedback metadata key for the feedback row identified by message_id."""
        if not key or not key.strip():
            raise ValueError("metadata key must not be empty")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM feedback WHERE message_id = ?",
                (message_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            feedback_id = int(row["id"])
            value_as_text = value if isinstance(value, str) else json.dumps(value)
            cursor.execute(
                """
                INSERT INTO feedback_metadata (feedback_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(feedback_id, key)
                DO UPDATE SET value = excluded.value
                """,
                (feedback_id, key.strip(), value_as_text),
            )
            conn.commit()
            return True

    def get_feedback_metadata_value(
        self,
        message_id: str,
        key: str,
    ) -> Optional[Any]:
        """Get a single metadata value for feedback identified by message_id."""
        if not key or not key.strip():
            return None

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT fm.value
                FROM feedback_metadata fm
                JOIN feedback f ON f.id = fm.feedback_id
                WHERE f.message_id = ? AND fm.key = ?
                LIMIT 1
                """,
                (message_id, key.strip()),
            )
            row = cursor.fetchone()
            if not row:
                return None

            raw = row["value"]
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw

    def delete_feedback(self, message_id: str) -> bool:
        """
        Delete feedback entry and all related data.

        Args:
            message_id: Message identifier

        Returns:
            True if deleted, False if not found
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM feedback WHERE message_id = ?", (message_id,))
            conn.commit()

            return cursor.rowcount > 0

    def mark_feedback_as_processed(
        self, message_id: str, faq_id: str, processed_at: Optional[str] = None
    ) -> bool:
        """
        Mark feedback entry as processed into a FAQ with atomic conditional update.

        Uses an atomic UPDATE with WHERE clause to ensure only unprocessed feedback
        can be marked as processed, preventing race conditions where concurrent
        requests might both try to process the same feedback.

        Args:
            message_id: Message identifier
            faq_id: ID of the created FAQ
            processed_at: Optional UTC timestamp (defaults to now in UTC)

        Returns:
            True if updated (feedback was unprocessed), False if not updated
            (feedback not found or already processed by another request)
        """
        from datetime import timezone

        if processed_at is None:
            processed_at = datetime.now(timezone.utc).isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Atomic conditional update - only succeeds if feedback exists AND is unprocessed
            cursor.execute(
                """
                UPDATE feedback
                SET processed = 1, processed_at = ?, faq_id = ?
                WHERE message_id = ? AND processed = 0
                """,
                (processed_at, faq_id, message_id),
            )
            conn.commit()

            success = cursor.rowcount > 0
            if success:
                logger.info(
                    f"Marked feedback {message_id} as processed (FAQ ID: {faq_id})"
                )
            else:
                logger.warning(
                    f"Feedback {message_id} not updated - either not found or already processed"
                )

            return success

    def get_feedback_stats(self) -> Dict[str, Any]:
        """
        Get overall feedback statistics.

        Returns:
            Dictionary with statistics
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Total feedback
            cursor.execute("SELECT COUNT(*) as total FROM feedback")
            total = cursor.fetchone()["total"]

            # Positive feedback
            cursor.execute("SELECT COUNT(*) as positive FROM feedback WHERE rating = 1")
            positive = cursor.fetchone()["positive"]

            # Negative feedback
            cursor.execute("SELECT COUNT(*) as negative FROM feedback WHERE rating = 0")
            negative = cursor.fetchone()["negative"]

            # Processed feedback
            cursor.execute(
                "SELECT COUNT(*) as processed FROM feedback WHERE processed = 1"
            )
            processed = cursor.fetchone()["processed"]

            # Unprocessed negative feedback (potential FAQs)
            cursor.execute(
                "SELECT COUNT(*) as unprocessed FROM feedback WHERE rating = 0 AND processed = 0"
            )
            unprocessed_negative = cursor.fetchone()["unprocessed"]

            # Most common issues
            cursor.execute("""
                SELECT issue_type, COUNT(*) as count
                FROM feedback_issues
                GROUP BY issue_type
                ORDER BY count DESC
                LIMIT 10
                """)
            common_issues = [
                {"issue": row["issue_type"], "count": row["count"]}
                for row in cursor.fetchall()
            ]

            return {
                "total": total,
                "positive": positive,
                "negative": negative,
                "processed": processed,
                "unprocessed_negative": unprocessed_negative,
                "positive_rate": positive / total if total > 0 else 0,
                "common_issues": common_issues,
            }

    def get_feedback_stats_for_period(
        self, start_time: str, end_time: str
    ) -> Dict[str, Any]:
        """
        Get feedback statistics for a specific time period.

        Args:
            start_time: ISO timestamp for period start (expects UTC timezone)
            end_time: ISO timestamp for period end (expects UTC timezone)

        Returns:
            Dictionary with statistics for the time period

        Note:
            - Timestamps should be normalized to UTC when storing and querying
              to avoid cross-host timezone drift
            - For optimal performance at scale, recommended database indexes:
              * CREATE INDEX IF NOT EXISTS idx_feedback_timestamp
                ON feedback(timestamp);
              * CREATE INDEX IF NOT EXISTS idx_feedback_rating_timestamp
                ON feedback(rating, timestamp);
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Total feedback in period
            cursor.execute(
                "SELECT COUNT(*) as total FROM feedback WHERE timestamp >= ? AND timestamp < ?",
                (start_time, end_time),
            )
            total = cursor.fetchone()["total"]

            # Positive feedback in period
            cursor.execute(
                "SELECT COUNT(*) as positive FROM feedback WHERE rating = 1 AND timestamp >= ? AND timestamp < ?",
                (start_time, end_time),
            )
            positive = cursor.fetchone()["positive"]

            # Negative feedback in period
            cursor.execute(
                "SELECT COUNT(*) as negative FROM feedback WHERE rating = 0 AND timestamp >= ? AND timestamp < ?",
                (start_time, end_time),
            )
            negative = cursor.fetchone()["negative"]

            return {
                "total": total,
                "positive": positive,
                "negative": negative,
                "helpful_rate": positive / total if total > 0 else 0,
            }

    # =========================================================================
    # Reaction tracking
    # =========================================================================

    def get_reaction_by_key(
        self,
        channel: str,
        external_message_id: str,
        reactor_identity_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """Look up a reaction by its uniqueness key.

        Returns dict with reaction fields or None if not found.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, channel, external_message_id, reactor_identity_hash,
                       reaction_emoji, feedback_id, created_at, last_updated_at, revoked_at
                FROM feedback_reactions
                WHERE channel = ? AND external_message_id = ? AND reactor_identity_hash = ?
                """,
                (channel, external_message_id, reactor_identity_hash),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_reaction_rating(
        self,
        channel: str,
        external_message_id: str,
        reactor_identity_hash: str,
    ) -> Optional[int]:
        """Return active reaction rating (0/1) for a reaction key.

        Returns None when reaction is not currently active.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT f.rating
                FROM feedback_reactions r
                JOIN feedback f ON f.id = r.feedback_id
                WHERE r.channel = ? AND r.external_message_id = ? AND r.reactor_identity_hash = ?
                  AND r.revoked_at IS NULL
                LIMIT 1
                """,
                (channel, external_message_id, reactor_identity_hash),
            )
            row = cursor.fetchone()
            return int(row["rating"]) if row and row["rating"] is not None else None

    def upsert_reaction_tracking(
        self,
        channel: str,
        external_message_id: str,
        reactor_identity_hash: str,
        reaction_emoji: str,
        feedback_id: int,
    ) -> None:
        """Insert or update a reaction tracking record.

        On conflict (same channel/ext_id/reactor), updates emoji and timestamp.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO feedback_reactions
                    (channel, external_message_id, reactor_identity_hash,
                     reaction_emoji, feedback_id, created_at, last_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, external_message_id, reactor_identity_hash)
                DO UPDATE SET
                    reaction_emoji = excluded.reaction_emoji,
                    last_updated_at = excluded.last_updated_at,
                    revoked_at = NULL
                """,
                (
                    channel,
                    external_message_id,
                    reactor_identity_hash,
                    reaction_emoji,
                    feedback_id,
                    now,
                    now,
                ),
            )
            conn.commit()

    def revoke_reaction_tracking(
        self,
        channel: str,
        external_message_id: str,
        reactor_identity_hash: str,
    ) -> bool:
        """Mark a reaction as revoked (soft delete).

        Returns True if a record was updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE feedback_reactions
                SET revoked_at = ?, last_updated_at = ?
                WHERE channel = ? AND external_message_id = ? AND reactor_identity_hash = ?
                  AND revoked_at IS NULL
                """,
                (now, now, channel, external_message_id, reactor_identity_hash),
            )
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # Channel statistics
    # =========================================================================

    def get_feedback_stats_by_channel(self) -> Dict[str, Dict[str, int]]:
        """Get feedback counts broken down by channel.

        Returns dict mapping channel -> {total, positive, negative}.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT channel,
                       COUNT(*) as total,
                       SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as positive,
                       SUM(CASE WHEN rating = 0 THEN 1 ELSE 0 END) as negative
                FROM feedback
                GROUP BY channel
            """)
            result = {}
            for row in cursor.fetchall():
                result[row["channel"]] = {
                    "total": row["total"],
                    "positive": row["positive"],
                    "negative": row["negative"],
                }
            return result

    def get_feedback_count_by_method(self) -> Dict[str, Dict[str, int]]:
        """Get feedback counts broken down by feedback method.

        Returns dict mapping method -> {total, positive, negative}.
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT feedback_method,
                       COUNT(*) as total,
                       SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as positive,
                       SUM(CASE WHEN rating = 0 THEN 1 ELSE 0 END) as negative
                FROM feedback
                GROUP BY feedback_method
            """)
            result = {}
            for row in cursor.fetchall():
                result[row["feedback_method"]] = {
                    "total": row["total"],
                    "positive": row["positive"],
                    "negative": row["negative"],
                }
            return result
