"""
Feedback management service for Bisq 2 Support Assistant.

This service handles all feedback-related functionality:
- Storing and loading user feedback
- Analyzing feedback for patterns
- Generating FAQs from feedback
- Using feedback to improve RAG responses
"""

import asyncio
import json
import logging
import math
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.database import get_database
from app.db.repository import FeedbackRepository
from app.models.feedback import (
    FeedbackFilterRequest,
    FeedbackItem,
    FeedbackListResponse,
)
from app.services.feedback import (
    FeedbackAnalyzer,
    FeedbackFilters,
    FeedbackWeightManager,
    PromptOptimizer,
)
from fastapi import Request

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeedbackService:
    """Service responsible for handling all feedback-related operations."""

    _instance = None
    _feedback_cache = None
    _last_load_time = None
    _cache_ttl = 300  # 5 minutes cache TTL
    _update_lock = None

    def __new__(cls, settings=None):
        if cls._instance is None:
            cls._instance = super(FeedbackService, cls).__new__(cls)
            cls._update_lock = asyncio.Lock()
        return cls._instance

    def __init__(self, settings=None):
        """Initialize the feedback service.

        Args:
            settings: Application settings
        """
        if not hasattr(self, "initialized"):
            self.settings = settings
            self.initialized = True
            if self._update_lock is None:
                self._update_lock = asyncio.Lock()

            # Guard against missing DATA_DIR setting
            if not hasattr(self.settings, "DATA_DIR") or not self.settings.DATA_DIR:
                raise ValueError(
                    "DATA_DIR setting is required but not configured in settings"
                )

            # Ensure DATA_DIR exists before initializing database
            os.makedirs(self.settings.DATA_DIR, exist_ok=True)

            # Initialize database and repository
            db_path = os.path.join(self.settings.DATA_DIR, "feedback.db")
            db = get_database()
            db.initialize(db_path)
            self.repository = FeedbackRepository()

            logger.info("Feedback service initialized with SQLite database")

            # Initialize modular components
            self.analyzer = FeedbackAnalyzer()
            self.filters = FeedbackFilters()
            self.weight_manager = FeedbackWeightManager()
            self.prompt_optimizer = PromptOptimizer()

    def _is_valid_feedback_item(self, item: Dict[str, Any]) -> bool:
        """Check if a feedback item has required fields.

        Args:
            item: The feedback dictionary to validate

        Returns:
            bool: True if item has message_id and rating
        """
        if "message_id" not in item or "rating" not in item:
            logger.debug(
                f"Skipping item missing required fields (message_id/rating): "
                f"{item.get('feedback_type', 'unknown')}"
            )
            return False
        return True

    def load_feedback(self) -> List[Dict[str, Any]]:
        """Load feedback data from SQLite database.

        Returns:
            List of feedback entries as dictionaries
        """
        # Check if we have valid cached data
        current_time = datetime.now().timestamp()
        if (
            self._feedback_cache is not None
            and self._last_load_time is not None
            and current_time - self._last_load_time < self._cache_ttl
        ):
            return self._feedback_cache

        try:
            # Load all feedback from database
            all_feedback = self.repository.get_all_feedback()
            logger.info(f"Loaded {len(all_feedback)} feedback entries from database")

            # Cache the loaded feedback
            self._feedback_cache = all_feedback
            self._last_load_time = current_time

            return all_feedback

        except Exception as e:
            logger.error(f"Error loading feedback data from database: {e!s}")
            return []

    async def store_feedback(self, feedback_data: Dict[str, Any]) -> bool:
        """Store user feedback in the SQLite database.

        Args:
            feedback_data: The feedback data to store

        Returns:
            bool: True if the operation was successful
        """
        try:
            # Extract required fields
            message_id = feedback_data.get("message_id")
            question = feedback_data.get("question", "")
            answer = feedback_data.get("answer", "")
            rating = feedback_data.get("rating", 0)
            explanation = feedback_data.get("explanation")
            conversation_history = feedback_data.get("conversation_history")
            metadata = feedback_data.get("metadata", {})
            timestamp = feedback_data.get("timestamp")
            sources = feedback_data.get("sources")
            sources_used = feedback_data.get("sources_used")

            # Add timestamp if not already present
            if timestamp is None:
                timestamp = datetime.now(timezone.utc).isoformat()

            # Store in database using repository
            feedback_id = self.repository.store_feedback(
                message_id=message_id,
                question=question,
                answer=answer,
                rating=rating,
                explanation=explanation,
                conversation_history=conversation_history,
                metadata=metadata,
                timestamp=timestamp,
                sources=sources,
                sources_used=sources_used,
            )

            # Log conversation history details
            conversation_count = (
                len(conversation_history) if conversation_history else 0
            )
            logger.info(
                f"Stored feedback with ID {feedback_id} "
                f"with {conversation_count} conversation messages"
            )

            # Invalidate cache
            self._feedback_cache = None
            self._last_load_time = None

            # Apply feedback weights to improve future responses
            await self.apply_feedback_weights_async(feedback_data)

            return True

        except Exception as e:
            logger.error(f"Error storing feedback in database: {e!s}")
            return False

    def _apply_partial_update(
        self,
        entry: Dict[str, Any],
        explanation: Optional[str] = None,
        issues: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Helper to apply explanation and issues to a feedback entry's metadata."""
        if explanation is None and issues is None:
            return entry  # No partial update to apply

        entry.setdefault("metadata", {})
        if explanation is not None:
            entry["metadata"]["explanation"] = explanation
        if issues is not None:
            entry["metadata"].setdefault("issues", [])
            for issue in issues:
                if issue not in entry["metadata"]["issues"]:
                    entry["metadata"]["issues"].append(issue)
        return entry

    async def update_feedback_entry(
        self,
        message_id: str,
        updated_entry: Optional[Dict[str, Any]] = None,
        explanation: Optional[str] = None,
        issues: Optional[List[str]] = None,
    ) -> bool:
        """Update an existing feedback entry in the SQLite database.

        Args:
            message_id: The unique ID of the message to update.
            updated_entry: The full updated feedback entry (not currently used with SQLite).
            explanation: The explanation text to add/update.
            issues: The list of issues to add/extend in the entry's metadata.

        Returns:
            bool: True if the entry was found and updated, False otherwise.
        """
        if self._update_lock is None:
            logger.error("FeedbackService update_lock is not initialized!")
            self._update_lock = asyncio.Lock()

        async with self._update_lock:
            try:
                updated = False

                # Update explanation if provided
                if explanation is not None:
                    success = self.repository.update_feedback_explanation(
                        message_id, explanation
                    )
                    if success:
                        logger.info(f"Updated explanation for feedback {message_id}")
                        updated = True
                    else:
                        logger.warning(
                            f"Could not find feedback entry with message_id: {message_id}"
                        )
                        return False

                # Update issues if provided
                if issues is not None:
                    success = self.repository.update_feedback_issues(message_id, issues)
                    if success:
                        logger.info(
                            f"Updated {len(issues)} issues for feedback {message_id}"
                        )
                        updated = True
                    else:
                        logger.warning(
                            f"Could not find feedback entry with message_id: {message_id}"
                        )
                        return False

                # Invalidate cache if any update was successful
                if updated:
                    self._feedback_cache = None
                    self._last_load_time = None
                    return True

                logger.warning(
                    f"No update data provided for feedback entry {message_id}"
                )
                return False

            except Exception as e:
                logger.error(f"Error updating feedback entry in database: {e!s}")
                return False

    async def analyze_feedback_text(self, explanation_text: str) -> List[str]:
        """Analyze feedback explanation text to identify common issues.

        Delegates to FeedbackAnalyzer for issue detection.

        Args:
            explanation_text: The text to analyze

        Returns:
            List of detected issues
        """
        return self.analyzer.analyze_feedback_text(explanation_text)

    def update_prompt_based_on_feedback(self) -> bool:
        """Update system prompts based on feedback patterns.

        This method enhances prompt guidance using patterns identified in
        user feedback, improving response quality by addressing common issues.

        Returns:
            bool: True if the prompt was updated
        """
        return self._update_prompt_based_on_feedback()

    async def update_prompt_based_on_feedback_async(self) -> bool:
        """Update system prompts based on feedback patterns (asynchronous version).

        This is the async-compatible version of update_prompt_based_on_feedback.
        It properly handles the potentially I/O-bound prompt update in an async context.

        Returns:
            The result of the prompt update process
        """
        import asyncio

        # Use run_in_executor to move the I/O-bound task to a thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._update_prompt_based_on_feedback  # Use default executor
        )

    def _update_prompt_based_on_feedback(self) -> bool:
        """Dynamically adjust the system prompt based on feedback patterns."""
        feedback = self.load_feedback()
        return self.prompt_optimizer.update_prompt_guidance(feedback, self.analyzer)

    def _analyze_feedback_issues(
        self, feedback: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Analyze feedback to identify common issues. Delegates to analyzer."""
        return self.analyzer.analyze_feedback_issues(feedback)

    def apply_feedback_weights(self, feedback_data=None) -> bool:
        """Update source weights based on feedback data (synchronous version).

        This public method applies feedback-derived adjustments to the source weights,
        prioritizing more helpful content sources based on user feedback ratings.

        Args:
            feedback_data: Optional specific feedback entry to use for adjustment.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        return self._apply_feedback_weights(feedback_data)

    async def apply_feedback_weights_async(self, feedback_data=None) -> bool:
        """Update source weights based on feedback data (asynchronous version).

        This is the async-compatible version of apply_feedback_weights.
        It properly handles the CPU-bound weight calculation in an async context.

        Args:
            feedback_data: Optional specific feedback entry to use for adjustment.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        import asyncio

        # Use run_in_executor to move the CPU-bound task to a thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._apply_feedback_weights, feedback_data  # Use default executor
        )

    def _apply_feedback_weights(self, feedback_data=None) -> bool:
        """Core implementation for applying feedback weight adjustments.

        Delegates to FeedbackWeightManager for weight calculations.

        Args:
            feedback_data: Optional specific feedback entry to process.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        try:
            feedback = self.load_feedback()
            if not feedback:
                logger.info("No feedback available for weight adjustment")
                return True

            # Delegate to weight manager
            self.weight_manager.apply_feedback_weights(feedback)
            return True

        except Exception as e:
            logger.error(f"Error applying feedback weights: {e!s}", exc_info=True)
            return False

    def migrate_legacy_feedback(self) -> Dict[str, Any]:
        """Migrate legacy feedback files to the current month-based convention.

        Note: This function has been used to migrate existing legacy feedback files,
        but is kept for historical purposes and in case additional legacy files are
        discovered in the future. Under normal operation, this should not be needed
        as all feedback now uses the standardized month-based naming convention.

        This function:
        1. Reads all feedback from legacy files (day-based and root feedback.jsonl)
        2. Sorts them by timestamp
        3. Writes them to appropriate month-based files
        4. Backs up original files
        5. Returns statistics about the migration

        Returns:
            Dict with migration statistics
        """
        # Explicitly type the dictionary values to help mypy
        migration_stats: Dict[str, Any] = {
            "total_entries_migrated": 0,
            "legacy_files_processed": 0,
            "entries_by_month": {},
            "backed_up_files": [],
        }

        feedback_dir = self.settings.FEEDBACK_DIR_PATH
        os.makedirs(feedback_dir, exist_ok=True)

        # Setup backup directory
        backup_dir = os.path.join(feedback_dir, "legacy_backup")
        os.makedirs(backup_dir, exist_ok=True)

        # Collect entries from legacy files
        legacy_entries = []

        # 1. Check day-based files
        day_pattern = re.compile(r"feedback_\d{8}\.jsonl$")
        day_files = [
            os.path.join(feedback_dir, f)
            for f in os.listdir(feedback_dir)
            if day_pattern.match(f)
        ]

        for file_path in day_files:
            try:
                with open(file_path, "r") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        legacy_entries.append(entry)

                # Back up the file
                backup_path = os.path.join(backup_dir, os.path.basename(file_path))
                shutil.copy2(file_path, backup_path)
                migration_stats["backed_up_files"].append(os.path.basename(file_path))
                migration_stats["legacy_files_processed"] += 1
            except Exception as e:
                logger.error(f"Error processing legacy file {file_path}: {e!s}")

        # 2. Check root feedback.jsonl
        root_feedback = os.path.join(self.settings.DATA_DIR, "feedback.jsonl")
        if os.path.exists(root_feedback):
            try:
                with open(root_feedback, "r") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        legacy_entries.append(entry)

                # Back up the file
                backup_path = os.path.join(backup_dir, "feedback.jsonl")
                shutil.copy2(root_feedback, backup_path)
                migration_stats["backed_up_files"].append("feedback.jsonl")
                migration_stats["legacy_files_processed"] += 1
            except Exception as e:
                logger.error(f"Error processing root feedback file: {e!s}")

        # Sort entries by timestamp where available
        for entry in legacy_entries:
            if "timestamp" not in entry:
                # Add a placeholder timestamp for entries without one
                entry["timestamp"] = "2025-01-01T00:00:00"

        legacy_entries.sort(key=lambda e: e.get("timestamp", ""))
        migration_stats["total_entries_migrated"] = len(legacy_entries)

        # Group by month and write to appropriate files
        for entry in legacy_entries:
            try:
                # Extract month from timestamp
                timestamp = entry.get("timestamp", "")
                month = timestamp[:7] if timestamp else "2025-01"  # YYYY-MM format

                # Ensure month is in proper format
                if not re.match(r"^\d{4}-\d{2}$", month):
                    month = "2025-01"  # Default if format is invalid

                # Update stats
                if month not in migration_stats["entries_by_month"]:
                    migration_stats["entries_by_month"][month] = 0
                migration_stats["entries_by_month"][month] += 1

                # Write to month-based file
                month_file = os.path.join(feedback_dir, f"feedback_{month}.jsonl")
                with open(month_file, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                logger.error(f"Error writing entry to month file: {e!s}")

        logger.info(
            f"Migration completed: {migration_stats['total_entries_migrated']} entries "
            f"from {migration_stats['legacy_files_processed']} files"
        )

        return migration_stats

    def get_prompt_guidance(self) -> List[str]:
        """Get the current prompt guidance based on feedback.

        Returns:
            List of guidance strings to incorporate into prompts
        """
        return self.prompt_optimizer.get_prompt_guidance()

    def get_source_weights(self) -> Dict[str, float]:
        """Get the current source weights based on feedback.

        Returns:
            Dictionary mapping source types to their weights
        """
        return self.weight_manager.get_source_weights()

    def get_feedback_with_filters(
        self, filters: FeedbackFilterRequest
    ) -> FeedbackListResponse:
        """Get filtered and paginated feedback data.

        Args:
            filters: Filtering and pagination parameters

        Returns:
            FeedbackListResponse with filtered feedback items
        """
        all_feedback = self.load_feedback()

        # Convert dict items to FeedbackItem objects
        feedback_items = []
        for item in all_feedback:
            try:
                if not self._is_valid_feedback_item(item):
                    continue

                feedback_item = FeedbackItem(**item)
                feedback_items.append(feedback_item)
            except Exception as e:
                logger.warning(f"Error parsing feedback item: {e}")
                continue

        # Apply filters using filters module
        filtered_items = self.filters.apply_filters(feedback_items, filters)

        # Apply sorting using filters module
        sorted_items = self.filters.apply_sorting(filtered_items, filters.sort_by)

        # Apply pagination
        total_count = len(sorted_items)
        total_pages = (
            math.ceil(total_count / filters.page_size) if total_count > 0 else 0
        )

        start_idx = (filters.page - 1) * filters.page_size
        end_idx = start_idx + filters.page_size
        paginated_items = sorted_items[start_idx:end_idx]

        return FeedbackListResponse(
            feedback_items=paginated_items,
            total_count=total_count,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=total_pages,
            filters_applied={
                "rating": filters.rating,
                "date_from": filters.date_from,
                "date_to": filters.date_to,
                "issues": filters.issues,
                "source_types": filters.source_types,
                "search_text": filters.search_text,
                "needs_faq": filters.needs_faq,
                "sort_by": filters.sort_by,
            },
        )

    def get_feedback_by_issues(self) -> Dict[str, List[FeedbackItem]]:
        """Get feedback grouped by issue types for analysis."""
        all_feedback = self.load_feedback()
        feedback_items: List[FeedbackItem] = []

        for item in all_feedback:
            try:
                if not self._is_valid_feedback_item(item):
                    continue

                feedback_item = FeedbackItem(**item)
                if feedback_item.is_negative and feedback_item.issues:
                    feedback_items.append(feedback_item)
            except Exception as e:
                logger.warning(f"Error parsing feedback item: {e}")
                continue

        # Group by issues
        issues_dict: Dict[str, List[FeedbackItem]] = defaultdict(list)
        # Type checker doesn't recognize Pydantic @computed_field properties
        for item in feedback_items:  # type: ignore[assignment]
            for issue in item.issues:  # type: ignore[attr-defined]
                issues_dict[issue].append(item)  # type: ignore[arg-type]

        return dict(issues_dict)

    def get_negative_feedback_for_faq_creation(self) -> List[FeedbackItem]:
        """Get negative feedback that would benefit from FAQ creation."""
        all_feedback = self.load_feedback()
        feedback_items = []

        for item in all_feedback:
            try:
                if not self._is_valid_feedback_item(item):
                    continue

                feedback_item = FeedbackItem(**item)
                # Include negative feedback with explanations or "no source" responses
                if feedback_item.is_negative and (
                    feedback_item.explanation or feedback_item.has_no_source_response
                ):
                    feedback_items.append(feedback_item)
            except Exception as e:
                logger.warning(f"Error parsing feedback item: {e}")
                continue

        # Sort by newest first
        return sorted(feedback_items, key=lambda x: x.timestamp, reverse=True)

    def mark_feedback_as_processed(
        self, message_id: str, faq_id: str, processed_at: Optional[str] = None
    ) -> bool:
        """
        Mark feedback entry as processed into a FAQ.

        Args:
            message_id: Message identifier
            faq_id: ID of the created FAQ
            processed_at: Optional timestamp (defaults to now)

        Returns:
            True if updated successfully
        """
        success = self.repository.mark_feedback_as_processed(
            message_id, faq_id, processed_at
        )

        if success:
            # Invalidate cache to reflect the change
            self._feedback_cache = None
            self._last_load_time = None
            logger.info(
                f"Successfully marked feedback {message_id} as processed (FAQ: {faq_id})"
            )
        else:
            logger.warning(f"Failed to mark feedback {message_id} as processed")

        return success

    def delete_feedback(self, message_id: str) -> bool:
        """
        Delete feedback entry and all related data.

        Args:
            message_id: Message identifier

        Returns:
            True if deleted, False if not found
        """
        success = self.repository.delete_feedback(message_id)

        if success:
            # Invalidate cache to reflect the deletion
            self._feedback_cache = None
            self._last_load_time = None
            logger.info(f"Successfully deleted feedback {message_id}")
        else:
            logger.warning(f"Failed to delete feedback {message_id} - not found")

        return success

    def get_total_feedback_count(self) -> int:
        """Get total feedback count using constant-time database query.

        This is an O(1) operation that only queries the count, unlike
        get_feedback_stats_enhanced() which is O(n) and loads all feedback.

        Returns:
            Total number of feedback entries
        """
        try:
            return self.repository.get_feedback_count()
        except Exception:
            logger.exception("Error getting feedback count")
            return 0

    def get_feedback_stats_enhanced(self) -> Dict[str, Any]:
        """Get enhanced feedback statistics for admin dashboard.

        Delegates complex calculations to FeedbackAnalyzer.
        """
        try:
            # Get basic stats from repository
            basic_stats = self.repository.get_feedback_stats()

            # Load all feedback for additional calculations
            all_feedback = self.load_feedback()
            feedback_items = []

            for item in all_feedback:
                try:
                    if not self._is_valid_feedback_item(item):
                        continue

                    feedback_item = FeedbackItem(**item)
                    feedback_items.append(feedback_item)
                except Exception as e:
                    logger.warning(f"Error parsing feedback item: {e}")
                    continue

            # Delegate to analyzer for enhanced statistics
            return self.analyzer.calculate_enhanced_stats(feedback_items, basic_stats)

        except Exception as e:
            logger.error(f"Error getting feedback stats: {e!s}")
            return {
                "total_feedback": 0,
                "positive_count": 0,
                "negative_count": 0,
                "helpful_rate": 0,
                "common_issues": {},
                "recent_negative_count": 0,
                "needs_faq_count": 0,
                "processed_count": 0,
                "unprocessed_negative_count": 0,
                "source_effectiveness": {},
                "feedback_by_month": {},
            }


# Dependency function for FastAPI
def get_feedback_service(request: Request) -> FeedbackService:
    """Get the feedback service from the request state."""
    return request.app.state.feedback_service
