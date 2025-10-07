"""
Feedback repository for SQLite database operations.

This module provides a clean interface for all feedback-related database
operations, abstracting away SQL queries from the service layer.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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

        Returns:
            int: Feedback ID of the inserted entry

        Raises:
            sqlite3.IntegrityError: If message_id already exists
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            # Insert main feedback entry
            cursor.execute(
                """
                INSERT INTO feedback (message_id, question, answer, rating, explanation, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, question, answer, rating, explanation, timestamp),
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
                SELECT id, message_id, question, answer, rating, explanation, timestamp, created_at
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

            query = "SELECT id, message_id, question, answer, rating, explanation, timestamp FROM feedback"
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
                if issues_map[feedback_id]:
                    metadata["issues"] = issues_map[feedback_id]
                if metadata:
                    feedback["metadata"] = metadata

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
                       f.explanation, f.timestamp
                FROM feedback f
                INNER JOIN feedback_issues fi ON f.id = fi.feedback_id
                WHERE fi.issue_type = ?
                ORDER BY f.timestamp DESC
                """,
                (issue_type,),
            )

            return [dict(row) for row in cursor.fetchall()]

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

            # Most common issues
            cursor.execute(
                """
                SELECT issue_type, COUNT(*) as count
                FROM feedback_issues
                GROUP BY issue_type
                ORDER BY count DESC
                LIMIT 10
                """
            )
            common_issues = [
                {"issue": row["issue_type"], "count": row["count"]}
                for row in cursor.fetchall()
            ]

            return {
                "total": total,
                "positive": positive,
                "negative": negative,
                "positive_rate": positive / total if total > 0 else 0,
                "common_issues": common_issues,
            }
