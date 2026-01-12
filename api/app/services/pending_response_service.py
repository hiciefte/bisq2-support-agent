"""Pending Response Service for moderator review queue.

This service manages responses that are queued for moderator review
before being sent to users, based on confidence thresholds.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import Settings

logger = logging.getLogger(__name__)


class PendingResponseService:
    """Service for managing pending responses awaiting moderator review."""

    def __init__(self, settings: Settings):
        """Initialize the pending response service.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.data_dir = Path(settings.FEEDBACK_DIR_PATH).parent
        self.pending_file = self.data_dir / "pending_responses.jsonl"

        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

    async def queue_response(
        self,
        question: str,
        answer: str,
        confidence: float,
        routing_action: str,
        sources: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        channel: str = "web",
    ) -> str:
        """Queue a response for moderator review.

        Args:
            question: The user's question
            answer: The generated answer
            confidence: Confidence score (0-1)
            routing_action: Routing decision (queue_medium, queue_low)
            sources: List of source documents used
            metadata: Additional metadata (version, emotion, etc.)
            channel: Source channel (web, matrix, telegram)

        Returns:
            The ID of the queued response
        """
        response_id = str(uuid.uuid4())

        pending_entry = {
            "id": response_id,
            "question": question,
            "answer": answer,
            "confidence": confidence,
            "routing_action": routing_action,
            "sources": sources,
            "metadata": metadata or {},
            "channel": channel,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_at": None,
            "reviewed_by": None,
            "modified_answer": None,
            "review_notes": None,
        }

        # Append to JSONL file
        try:
            with open(self.pending_file, "a") as f:
                f.write(json.dumps(pending_entry) + "\n")

            logger.info(
                f"Queued response {response_id} for review "
                f"(confidence={confidence:.2f}, action={routing_action})"
            )
            return response_id

        except Exception as e:
            logger.error(f"Failed to queue response: {e}", exc_info=True)
            raise

    async def get_pending_responses(
        self,
        status: str = "pending",
        priority: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get pending responses with filtering and pagination.

        Args:
            status: Filter by status (pending, approved, rejected, modified)
            priority: Filter by priority (high, normal)
            limit: Maximum number of responses to return
            offset: Number of responses to skip

        Returns:
            Dict with responses list and pagination info
        """
        responses = []

        if not self.pending_file.exists():
            return {
                "responses": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }

        try:
            with open(self.pending_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())

                        # Apply filters
                        if status and entry.get("status") != status:
                            continue

                        if priority:
                            # High priority = queue_low (needs human expertise)
                            if (
                                priority == "high"
                                and entry.get("routing_action") != "queue_low"
                            ):
                                continue
                            if (
                                priority == "normal"
                                and entry.get("routing_action") != "queue_medium"
                            ):
                                continue

                        responses.append(entry)

                    except json.JSONDecodeError:
                        continue

            # Sort by created_at descending (newest first)
            responses.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            total = len(responses)
            paginated = responses[offset : offset + limit]

            return {
                "responses": paginated,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

        except Exception as e:
            logger.error(f"Failed to get pending responses: {e}", exc_info=True)
            return {
                "responses": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }

    async def get_response_by_id(self, response_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific pending response by ID.

        Args:
            response_id: The response ID

        Returns:
            The response entry or None if not found
        """
        if not self.pending_file.exists():
            return None

        try:
            with open(self.pending_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("id") == response_id:
                            return entry
                    except json.JSONDecodeError:
                        continue

            return None

        except Exception as e:
            logger.error(f"Failed to get response {response_id}: {e}", exc_info=True)
            return None

    async def update_response(
        self,
        response_id: str,
        status: str,
        reviewed_by: Optional[str] = None,
        modified_answer: Optional[str] = None,
        review_notes: Optional[str] = None,
    ) -> bool:
        """Update a pending response after moderator review.

        Args:
            response_id: The response ID
            status: New status (approved, rejected, modified)
            reviewed_by: Moderator identifier
            modified_answer: Modified answer text (if status is modified)
            review_notes: Notes from the reviewer

        Returns:
            True if updated successfully, False otherwise
        """
        if not self.pending_file.exists():
            return False

        try:
            # Read all entries
            entries = []
            updated = False

            with open(self.pending_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())

                        if entry.get("id") == response_id:
                            entry["status"] = status
                            entry["reviewed_at"] = datetime.now(
                                timezone.utc
                            ).isoformat()
                            entry["reviewed_by"] = reviewed_by
                            if modified_answer:
                                entry["modified_answer"] = modified_answer
                            if review_notes:
                                entry["review_notes"] = review_notes
                            updated = True

                        entries.append(entry)

                    except json.JSONDecodeError:
                        continue

            if not updated:
                return False

            # Write back all entries
            with open(self.pending_file, "w") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")

            logger.info(f"Updated response {response_id} to status={status}")
            return True

        except Exception as e:
            logger.error(f"Failed to update response {response_id}: {e}", exc_info=True)
            return False

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get statistics about the pending response queue.

        Returns:
            Dict with queue statistics
        """
        stats = {
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "modified": 0,
            "high_priority": 0,
            "normal_priority": 0,
            "avg_confidence": 0.0,
        }

        if not self.pending_file.exists():
            return stats

        try:
            total_confidence = 0.0
            pending_count = 0

            with open(self.pending_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        status = entry.get("status", "pending")

                        if status == "pending":
                            stats["pending"] += 1
                            pending_count += 1
                            total_confidence += entry.get("confidence", 0.0)

                            if entry.get("routing_action") == "queue_low":
                                stats["high_priority"] += 1
                            else:
                                stats["normal_priority"] += 1
                        elif status == "approved":
                            stats["approved"] += 1
                        elif status == "rejected":
                            stats["rejected"] += 1
                        elif status == "modified":
                            stats["modified"] += 1

                    except json.JSONDecodeError:
                        continue

            if pending_count > 0:
                stats["avg_confidence"] = total_confidence / pending_count

            return stats

        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}", exc_info=True)
            return stats

    async def delete_response(self, response_id: str) -> bool:
        """Delete a pending response.

        Args:
            response_id: The response ID to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        if not self.pending_file.exists():
            return False

        try:
            entries = []
            deleted = False

            with open(self.pending_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("id") == response_id:
                            deleted = True
                        else:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue

            if not deleted:
                return False

            with open(self.pending_file, "w") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")

            logger.info(f"Deleted response {response_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete response {response_id}: {e}", exc_info=True)
            return False
