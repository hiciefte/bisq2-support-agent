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
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import portalocker
from app.db.database import get_database
from app.db.repository import FeedbackRepository
from app.models.feedback import (
    FeedbackFilterRequest,
    FeedbackItem,
    FeedbackListResponse,
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

            # Initialize database and repository
            db_path = os.path.join(self.settings.DATA_DIR, "feedback.db")
            db = get_database()
            db.initialize(db_path)
            self.repository = FeedbackRepository()

            logger.info("Feedback service initialized with SQLite database")

            # Source weights to be applied to different content types
            # These are influenced by feedback but used by RAG
            self.source_weights = {
                "faq": 1.2,  # Prioritize FAQ content
                "wiki": 1.0,  # Standard weight for wiki content
            }

            # Prompting guidance based on feedback
            self.prompt_guidance = []

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

            # Add timestamp if not already present
            if timestamp is None:
                timestamp = datetime.now().isoformat()

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
                # For explanation updates, use repository's update method
                if explanation is not None:
                    success = self.repository.update_feedback_explanation(
                        message_id, explanation
                    )
                    if success:
                        logger.info(f"Updated explanation for feedback {message_id}")
                        # Invalidate cache
                        self._feedback_cache = None
                        self._last_load_time = None
                        return True
                    else:
                        logger.warning(
                            f"Could not find feedback entry with message_id: {message_id}"
                        )
                        return False

                # For issues, we need to update metadata
                # This requires getting the current entry, updating it, and storing it back
                # For now, log a warning as this functionality needs repository enhancement
                if issues is not None:
                    logger.warning(
                        "Issue updates not yet implemented in SQLite repository. "
                        "This requires adding issues to an existing feedback entry."
                    )
                    return False

                logger.warning(
                    f"No update data provided for feedback entry {message_id}"
                )
                return False

            except Exception as e:
                logger.error(f"Error updating feedback entry in database: {e!s}")
                return False

    async def analyze_feedback_text(self, explanation_text: str) -> List[str]:
        """Analyze feedback explanation text to identify common issues.

        This uses simple keyword matching for now but could be enhanced with
        NLP or LLM-based analysis in the future.

        Args:
            explanation_text: The text to analyze

        Returns:
            List of detected issues
        """
        detected_issues = []

        # Simple keyword-based issue detection
        if not explanation_text:
            return detected_issues

        explanation_lower = explanation_text.lower()

        # Dictionary of issues and their associated keywords
        issue_keywords = {
            "too_verbose": [
                "too long",
                "verbose",
                "wordy",
                "rambling",
                "shorter",
                "concise",
            ],
            "too_technical": [
                "technical",
                "complex",
                "complicated",
                "jargon",
                "simpler",
                "simplify",
            ],
            "not_specific": [
                "vague",
                "unclear",
                "generic",
                "specific",
                "details",
                "elaborate",
                "more info",
            ],
            "inaccurate": [
                "wrong",
                "incorrect",
                "false",
                "error",
                "mistake",
                "accurate",
                "accuracy",
            ],
            "outdated": ["outdated", "old", "not current", "update"],
            "not_helpful": [
                "useless",
                "unhelpful",
                "doesn't help",
                "didn't help",
                "not useful",
            ],
            "missing_context": ["context", "missing", "incomplete", "partial"],
            "confusing": ["confusing", "confused", "unclear", "hard to understand"],
        }

        # Check for each issue
        for issue, keywords in issue_keywords.items():
            for keyword in keywords:
                if keyword in explanation_lower:
                    detected_issues.append(issue)
                    break  # Found one match for this issue, no need to check other keywords

        return detected_issues

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

        if not feedback or len(feedback) < 20:  # Need sufficient data
            logger.info("Not enough feedback data to update prompt")
            return False

        # Analyze common issues in negative feedback
        common_issues = self._analyze_feedback_issues(feedback)

        # Generate additional prompt guidance
        prompt_guidance = []

        if common_issues.get("too_verbose", 0) > 5:
            prompt_guidance.append("Keep answers very concise and to the point.")

        if common_issues.get("too_technical", 0) > 5:
            prompt_guidance.append("Use simple terms and avoid technical jargon.")

        if common_issues.get("not_specific", 0) > 5:
            prompt_guidance.append(
                "Be specific and provide concrete examples when possible."
            )

        # Update the system template with new guidance
        if prompt_guidance:
            self.prompt_guidance = prompt_guidance
            logger.info(f"Updated prompt guidance based on feedback: {prompt_guidance}")
            return True

        return False

    def _analyze_feedback_issues(
        self, feedback: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Analyze feedback to identify common issues."""
        issues = defaultdict(int)

        for item in feedback:
            if not item.get("helpful", True):
                # Check for specific issue fields
                for issue_key in [
                    "too_verbose",
                    "too_technical",
                    "not_specific",
                    "inaccurate",
                ]:
                    if item.get(issue_key):
                        issues[issue_key] += 1

                # Also check issue list if present
                for issue in item.get("issues", []):
                    issues[issue] += 1

        return dict(issues)

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

        This private method contains the actual implementation logic for analyzing
        feedback data and adjusting source weights accordingly.

        Args:
            feedback_data: Optional specific feedback entry to process.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        try:
            # If specific feedback item was provided, we could do targeted processing
            # For now we'll process all feedback for simplicity
            feedback = self.load_feedback()

            if not feedback:
                logger.info("No feedback available for weight adjustment")
                return True

            # Count positive/negative responses by source type
            source_scores = defaultdict(
                lambda: {"positive": 0, "negative": 0, "total": 0}
            )

            for item in feedback:
                # Skip items without necessary data
                if "sources_used" not in item or "helpful" not in item:
                    continue

                helpful = item["helpful"]

                for source in item["sources_used"]:
                    source_type = source.get("type", "unknown")

                    if helpful:
                        source_scores[source_type]["positive"] += 1
                    else:
                        source_scores[source_type]["negative"] += 1

                    source_scores[source_type]["total"] += 1

            # Calculate new weights
            for source_type, scores in source_scores.items():
                if scores["total"] > 10:  # Only adjust if we have enough data
                    # Calculate success rate: positive / total
                    success_rate = scores["positive"] / scores["total"]

                    # Scale it between 0.5 and 1.5
                    new_weight = 0.5 + success_rate

                    # Update weight if this source type exists
                    if source_type in self.source_weights:
                        old_weight = self.source_weights[source_type]
                        # Apply gradual adjustment (70% old, 30% new)
                        self.source_weights[source_type] = (0.7 * old_weight) + (
                            0.3 * new_weight
                        )
                        logger.info(
                            f"Adjusted weight for {source_type}: {old_weight:.2f} → {self.source_weights[source_type]:.2f}"
                        )

            logger.info(
                f"Updated source weights based on feedback: {self.source_weights}"
            )
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
        migration_stats = {
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
        return self.prompt_guidance

    def get_source_weights(self) -> Dict[str, float]:
        """Get the current source weights based on feedback.

        Returns:
            Dictionary mapping source types to their weights
        """
        return self.source_weights

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

        # Apply filters
        filtered_items = self._apply_filters(feedback_items, filters)

        # Apply sorting
        sorted_items = self._apply_sorting(filtered_items, filters.sort_by)

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

    def _apply_filters(
        self, feedback_items: List[FeedbackItem], filters: FeedbackFilterRequest
    ) -> List[FeedbackItem]:
        """Apply various filters to feedback items."""
        filtered_items = feedback_items

        # Filter by rating
        if filters.rating == "positive":
            filtered_items = [item for item in filtered_items if item.is_positive]
        elif filters.rating == "negative":
            filtered_items = [item for item in filtered_items if item.is_negative]

        # Filter by date range
        if filters.date_from or filters.date_to:
            filtered_items = self._filter_by_date(
                filtered_items, filters.date_from, filters.date_to
            )

        # Filter by issues
        if filters.issues:
            filtered_items = [
                item
                for item in filtered_items
                if any(issue in item.issues for issue in filters.issues)
            ]

        # Filter by source types
        if filters.source_types:
            filtered_items = [
                item
                for item in filtered_items
                if self._has_source_type(item, filters.source_types)
            ]

        # Filter by search text
        if filters.search_text:
            filtered_items = self._filter_by_text_search(
                filtered_items, filters.search_text
            )

        # Filter for items that need FAQ creation
        if filters.needs_faq:
            filtered_items = [
                item
                for item in filtered_items
                if item.is_negative
                and (item.has_no_source_response or item.explanation)
            ]

        return filtered_items

    def _filter_by_date(
        self,
        items: List[FeedbackItem],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> List[FeedbackItem]:
        """Filter items by date range."""
        filtered = []
        for item in items:
            try:
                # Parse timestamp
                if "T" in item.timestamp:
                    item_date = datetime.fromisoformat(
                        item.timestamp.replace("Z", "+00:00")
                    )
                else:
                    item_date = datetime.fromisoformat(item.timestamp)

                # Check date bounds
                if date_from:
                    from_date = datetime.fromisoformat(date_from)
                    if item_date < from_date:
                        continue

                if date_to:
                    to_date = datetime.fromisoformat(date_to)
                    if item_date > to_date:
                        continue

                filtered.append(item)
            except Exception as e:
                logger.warning(f"Error parsing timestamp {item.timestamp}: {e}")
                # Include items with unparseable timestamps to avoid losing data
                filtered.append(item)

        return filtered

    def _has_source_type(self, item: FeedbackItem, source_types: List[str]) -> bool:
        """Check if item has any of the specified source types."""
        sources = (
            item.sources_used
            if item.sources_used
            else (item.sources if item.sources else [])
        )
        if not sources:
            return "unknown" in source_types

        for source in sources:
            if source.get("type", "unknown") in source_types:
                return True
        return False

    def _filter_by_text_search(
        self, items: List[FeedbackItem], search_text: str
    ) -> List[FeedbackItem]:
        """Filter items by text search in questions, answers, and explanations."""
        search_lower = search_text.lower()
        filtered = []

        for item in items:
            # Search in question
            if search_lower in item.question.lower():
                filtered.append(item)
                continue

            # Search in answer
            if search_lower in item.answer.lower():
                filtered.append(item)
                continue

            # Search in explanation if available
            if item.explanation and search_lower in item.explanation.lower():
                filtered.append(item)
                continue

        return filtered

    def _apply_sorting(
        self, items: List[FeedbackItem], sort_by: Optional[str]
    ) -> List[FeedbackItem]:
        """Apply sorting to feedback items."""
        if not sort_by or sort_by == "newest":
            return sorted(items, key=lambda x: x.timestamp, reverse=True)
        elif sort_by == "oldest":
            return sorted(items, key=lambda x: x.timestamp)
        elif sort_by == "rating_desc":
            return sorted(items, key=lambda x: x.rating, reverse=True)
        elif sort_by == "rating_asc":
            return sorted(items, key=lambda x: x.rating)
        else:
            return items

    def get_feedback_by_issues(self) -> Dict[str, List[FeedbackItem]]:
        """Get feedback grouped by issue types for analysis."""
        all_feedback = self.load_feedback()
        feedback_items = []

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
        issues_dict = defaultdict(list)
        for item in feedback_items:
            for issue in item.issues:
                issues_dict[issue].append(item)

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

    def get_feedback_stats_enhanced(self) -> Dict[str, Any]:
        """Get enhanced feedback statistics for admin dashboard."""
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

            if not feedback_items:
                return {
                    "total_feedback": basic_stats.get("total", 0),
                    "positive_count": basic_stats.get("positive", 0),
                    "negative_count": basic_stats.get("negative", 0),
                    "helpful_rate": basic_stats.get("positive_rate", 0),
                    "common_issues": {},
                    "recent_negative_count": 0,
                    "needs_faq_count": 0,
                    "source_effectiveness": {},
                    "feedback_by_month": {},
                }

            # Recent negative feedback (last 30 days)
            thirty_days_ago = datetime.now().replace(day=1).strftime("%Y-%m-01")
            recent_negative = [
                item
                for item in feedback_items
                if item.is_negative and item.timestamp >= thirty_days_ago
            ]

            # Feedback that needs FAQ creation
            needs_faq_items = [
                item
                for item in feedback_items
                if item.is_negative
                and (item.explanation or item.has_no_source_response)
            ]

            # Feedback by month
            monthly_counts = defaultdict(int)
            for item in feedback_items:
                try:
                    month_key = item.timestamp[:7]  # YYYY-MM
                    monthly_counts[month_key] += 1
                except (IndexError, TypeError, AttributeError):
                    # Handle cases where timestamp is None, empty, or malformed
                    monthly_counts["unknown"] += 1

            # Source effectiveness
            source_stats = defaultdict(lambda: {"total": 0, "positive": 0})
            for item in feedback_items:
                sources = (
                    item.sources_used
                    if item.sources_used
                    else (item.sources if item.sources else [])
                )
                for source in sources:
                    source_type = source.get("type", "unknown")
                    source_stats[source_type]["total"] += 1
                    if item.is_positive:
                        source_stats[source_type]["positive"] += 1

            # Add helpfulness rate to source stats
            for source_type in source_stats:
                stats = source_stats[source_type]
                stats["helpful_rate"] = (
                    stats["positive"] / stats["total"] if stats["total"] > 0 else 0
                )

            # Convert common_issues from repository format to dict[str, int]
            common_issues = {
                item["issue"]: item["count"]
                for item in basic_stats.get("common_issues", [])
            }

            return {
                "total_feedback": basic_stats["total"],
                "positive_count": basic_stats["positive"],
                "negative_count": basic_stats["negative"],
                "helpful_rate": basic_stats["positive_rate"],
                "common_issues": common_issues,
                "recent_negative_count": len(recent_negative),
                "needs_faq_count": len(needs_faq_items),
                "source_effectiveness": dict(source_stats),
                "feedback_by_month": dict(monthly_counts),
            }

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
                "source_effectiveness": {},
                "feedback_by_month": {},
            }


# Dependency function for FastAPI
def get_feedback_service(request: Request) -> FeedbackService:
    """Get the feedback service from the request state."""
    return request.app.state.feedback_service
