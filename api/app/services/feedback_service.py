"""
Feedback management service for Bisq 2 Support Assistant.

This service handles all feedback-related functionality:
- Storing and loading user feedback
- Analyzing feedback for patterns
- Generating FAQs from feedback
- Using feedback to improve RAG responses
"""

import json
import logging
import os
import re
import shutil
import asyncio
import portalocker
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

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
            logger.info("Feedback service initialized")

            # Source weights to be applied to different content types
            # These are influenced by feedback but used by RAG
            self.source_weights = {
                "faq": 1.2,  # Prioritize FAQ content
                "wiki": 1.0,  # Standard weight for wiki content
            }

            # Prompting guidance based on feedback
            self.prompt_guidance = []

    def load_feedback(self) -> List[Dict[str, Any]]:
        """Load feedback data from month-based JSONL files.

        Loads feedback data from the standardized format: feedback_YYYY-MM.jsonl
        stored in the DATA_DIR/feedback directory.

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

        all_feedback = []

        # Load from the feedback directory (standard location)
        feedback_dir = self.settings.FEEDBACK_DIR_PATH

        # Check if the directory exists and is accessible
        if not os.path.exists(feedback_dir):
            logger.info(f"Feedback directory does not exist: {feedback_dir}")
            return all_feedback

        if not os.path.isdir(feedback_dir):
            logger.info(f"Feedback path exists but is not a directory: {feedback_dir}")
            return all_feedback

        try:
            # Process month-based files (current convention)
            month_pattern = re.compile(r"feedback_\d{4}-\d{2}\.jsonl$")
            month_files = [
                os.path.join(feedback_dir, f)
                for f in os.listdir(feedback_dir)
                if month_pattern.match(f)
            ]

            # Sort files chronologically (newest first) to prioritize recent feedback
            month_files.sort(reverse=True)

            for file_path in month_files:
                try:
                    with open(file_path, "r") as f:
                        file_feedback = [json.loads(line) for line in f]
                        all_feedback.extend(file_feedback)
                        logger.info(
                            f"Loaded {len(file_feedback)} feedback entries from {os.path.basename(file_path)}"
                        )
                except Exception as e:
                    logger.error(f"Error loading feedback from {file_path}: {str(e)}")

            logger.info(f"Loaded a total of {len(all_feedback)} feedback entries")

            # Cache the loaded feedback
            self._feedback_cache = all_feedback
            self._last_load_time = current_time

        except Exception as e:
            logger.error(f"Error loading feedback data: {str(e)}")

        return all_feedback

    async def store_feedback(self, feedback_data: Dict[str, Any]) -> bool:
        """Store user feedback in the feedback file.

        Args:
            feedback_data: The feedback data to store

        Returns:
            bool: True if the operation was successful
        """
        # Create feedback directory if it doesn't exist
        feedback_dir = self.settings.FEEDBACK_DIR_PATH
        os.makedirs(feedback_dir, exist_ok=True)

        # Use current month for filename following the established convention
        current_month = datetime.now().strftime("%Y-%m")
        feedback_file = os.path.join(feedback_dir, f"feedback_{current_month}.jsonl")

        # Add timestamp if not already present
        if "timestamp" not in feedback_data:
            feedback_data["timestamp"] = datetime.now().isoformat()

        # Write to the feedback file
        with open(feedback_file, "a") as f:
            f.write(json.dumps(feedback_data) + "\n")

        logger.info(f"Stored feedback in {os.path.basename(feedback_file)}")

        # Apply feedback weights to improve future responses
        await self.apply_feedback_weights_async(feedback_data)

        return True

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
        """Update an existing feedback entry in a month-based feedback file.

        This method is concurrency-safe for intra-process calls due to an asyncio.Lock.
        It reads a feedback file, updates the entry if found, and writes to a temporary
        file before replacing the original.

        Args:
            message_id: The unique ID of the message to update.
            updated_entry: The full updated feedback entry. If provided and explanation/issues
                           are None, this will be used to replace the entire entry.
            explanation: The explanation text to add/update in the entry's metadata.
            issues: The list of issues to add/extend in the entry's metadata.

        Returns:
            bool: True if the entry was found and an update was made (or attempted with data),
                  False if the entry was not found, or if no update data (explanation, issues,
                  or updated_entry) was provided for a found entry, resulting in no change.
        """
        if self._update_lock is None:
            logger.error("FeedbackService update_lock is not initialized!")
            self._update_lock = asyncio.Lock()

        async with self._update_lock:
            feedback_dir = self.settings.FEEDBACK_DIR_PATH
            if not os.path.exists(feedback_dir) or not os.path.isdir(feedback_dir):
                logger.warning(f"Feedback directory not found: {feedback_dir}")
                return False

            month_pattern = re.compile(r"feedback_\d{4}-\d{2}\.jsonl$")
            feedback_files = [
                os.path.join(feedback_dir, f)
                for f in os.listdir(feedback_dir)
                if month_pattern.match(f)
            ]
            feedback_files.sort(reverse=True)

            current_month = datetime.now().strftime("%Y-%m")
            current_month_file = os.path.join(
                feedback_dir, f"feedback_{current_month}.jsonl"
            )

            # Ensure current month file is processed first if it exists, then others
            ordered_files_to_check = []
            if os.path.exists(current_month_file):
                ordered_files_to_check.append(current_month_file)
            for f_path in feedback_files:
                if f_path != current_month_file:
                    ordered_files_to_check.append(f_path)

            if not ordered_files_to_check and not os.path.exists(current_month_file):
                # Attempt to create current month file if no files exist and an update is requested.
                # This handles the case where the first feedback interaction might be an update call.
                try:
                    # The outer condition already ensures current_month_file does not exist here.
                    open(current_month_file, "a").close()  # Create if not exists
                    logger.info(
                        f"Created empty feedback file for current month: {current_month_file}"
                    )
                    # Explicitly check again after creation attempt before appending
                    if os.path.exists(current_month_file):
                        ordered_files_to_check.append(current_month_file)
                except IOError as e:
                    logger.error(
                        f"Could not create feedback file {current_month_file}: {e}"
                    )

            overall_updated_made = False

            for file_path in ordered_files_to_check:
                if not os.path.exists(file_path):
                    continue

                temp_path = file_path + ".tmp"
                file_updated_locally = False
                entry_found_in_file = False

                try:
                    # Acquire an exclusive cross-process lock on the file
                    with portalocker.Lock(
                        file_path, mode="r+", timeout=10
                    ) as locked_file_handle:
                        # Note: portalocker.Lock opens the file, so we use its handle or reopen carefully.
                        # For simplicity and to maintain existing open logic, we will re-open
                        # after lock acquisition, ensuring portalocker primarily handles the lock file mechanism.
                        # A more integrated approach would use locked_file_handle directly if its mode matches.
                        # However, the temp file pattern means we mostly need the lock for the duration of this block.
                        # Re-opening inside the lock context after portalocker creates/validates the lock file:
                        with open(file_path, "r") as original, open(
                            temp_path, "w"
                        ) as temp:
                            for line in original:
                                try:
                                    entry = json.loads(line.strip())
                                except json.JSONDecodeError:
                                    temp.write(line)  # Write invalid line as is
                                    continue

                                if entry.get("message_id") == message_id:
                                    entry_found_in_file = True
                                    if explanation is not None or issues is not None:
                                        entry = self._apply_partial_update(
                                            entry,
                                            explanation=explanation,
                                            issues=issues,
                                        )
                                        temp.write(json.dumps(entry) + "\n")
                                        file_updated_locally = True
                                    elif updated_entry is not None:
                                        temp.write(json.dumps(updated_entry) + "\n")
                                        file_updated_locally = True
                                    else:
                                        # No update data for this specific entry, write original
                                        temp.write(line)
                                else:
                                    temp.write(line)

                    if file_updated_locally:
                        os.replace(temp_path, file_path)
                        logger.info(
                            f"Updated feedback entry in {os.path.basename(file_path)}"
                        )
                        overall_updated_made = True
                        # Invalidate cache since a file was changed
                        FeedbackService._feedback_cache = None
                        FeedbackService._last_load_time = None
                        return True  # Found and updated
                    else:
                        os.remove(
                            temp_path
                        )  # No changes made to this file, or entry not found with update data
                        if entry_found_in_file:
                            # Entry was found, but no data was provided to update it. This is not an error but not an update.
                            logger.info(
                                f"Feedback entry {message_id} found in {os.path.basename(file_path)} but no update data provided."
                            )
                            # Still, we consider the message_id handled, so return based on whether any change was made
                            return overall_updated_made  # Which would be False if this was the only file with the entry

                except IOError as e:
                    logger.error(f"IOError during feedback update for {file_path}: {e}")
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    # Potentially return False or re-raise depending on desired error handling
                    return False  # Stop processing if a file operation fails catastrophically

            if not overall_updated_made:
                logger.warning(
                    f"Could not find feedback entry with message_id: {message_id} in any feedback file, or no update was performed."
                )

            # Invalidate cache if any update might have occurred or if file structure changed
            if overall_updated_made:  # Invalidate only if an actual change was made
                FeedbackService._feedback_cache = None
                FeedbackService._last_load_time = None

            return overall_updated_made

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
            logger.error(f"Error applying feedback weights: {str(e)}", exc_info=True)
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
                logger.error(f"Error processing legacy file {file_path}: {str(e)}")

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
                logger.error(f"Error processing root feedback file: {str(e)}")

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
                logger.error(f"Error writing entry to month file: {str(e)}")

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


# Dependency function for FastAPI
def get_feedback_service(request: Request) -> FeedbackService:
    """Get the feedback service from the request state."""
    return request.app.state.feedback_service
