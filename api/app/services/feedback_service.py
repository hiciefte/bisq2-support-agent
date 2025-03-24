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
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from fastapi import Request

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeedbackService:
    """Service responsible for handling all feedback-related operations."""

    def __init__(self, settings=None):
        """Initialize the feedback service.

        Args:
            settings: Application settings
        """
        self.settings = settings
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
            month_files = [os.path.join(feedback_dir, f) for f in
                           os.listdir(feedback_dir)
                           if month_pattern.match(f)]

            # Sort files chronologically (newest first) to prioritize recent feedback
            month_files.sort(reverse=True)

            for file_path in month_files:
                try:
                    with open(file_path, "r") as f:
                        file_feedback = [json.loads(line) for line in f]
                        all_feedback.extend(file_feedback)
                        logger.info(
                            f"Loaded {len(file_feedback)} feedback entries from {os.path.basename(file_path)}")
                except Exception as e:
                    logger.error(f"Error loading feedback from {file_path}: {str(e)}")

            logger.info(f"Loaded a total of {len(all_feedback)} feedback entries")
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
        if 'timestamp' not in feedback_data:
            feedback_data['timestamp'] = datetime.now().isoformat()

        # Write to the feedback file
        with open(feedback_file, 'a') as f:
            f.write(json.dumps(feedback_data) + '\n')

        logger.info(f"Stored feedback in {os.path.basename(feedback_file)}")

        # Apply feedback weights to improve future responses
        await self.apply_feedback_weights_async(feedback_data)

        return True

    async def update_feedback_entry(self, message_id: str,
                                    updated_entry: Dict[str, Any]) -> bool:
        """Update an existing feedback entry in a month-based feedback file.

        Args:
            message_id: The unique ID of the message to update
            updated_entry: The updated feedback entry

        Returns:
            Boolean indicating whether the update was successful
        """
        feedback_dir = self.settings.FEEDBACK_DIR_PATH
        if not os.path.exists(feedback_dir) or not os.path.isdir(feedback_dir):
            logger.warning(f"Feedback directory not found: {feedback_dir}")
            return False

        # Get all month-based files in the feedback directory
        month_pattern = re.compile(r"feedback_\d{4}-\d{2}\.jsonl$")
        feedback_files = [os.path.join(feedback_dir, f) for f in
                          os.listdir(feedback_dir)
                          if month_pattern.match(f)]

        # Sort files chronologically (newest first) to prioritize recent files
        feedback_files.sort(reverse=True)

        # First check current month's file as it's most likely to contain recent entries
        current_month = datetime.now().strftime("%Y-%m")
        current_month_file = os.path.join(feedback_dir,
                                          f"feedback_{current_month}.jsonl")

        if os.path.exists(current_month_file):
            # Try to update in current month's file first
            temp_path = current_month_file + '.tmp'
            updated = False

            with open(current_month_file, 'r') as original, open(temp_path,
                                                                 'w') as temp:
                for line in original:
                    entry = json.loads(line.strip())
                    if entry.get('message_id') == message_id:
                        # Update the entry
                        temp.write(json.dumps(updated_entry) + '\n')
                        updated = True
                    else:
                        # Keep the original entry
                        temp.write(line)

            # Replace the original file if updated
            if updated:
                os.replace(temp_path, current_month_file)
                logger.info(
                    f"Updated feedback entry in current month's file {os.path.basename(current_month_file)}")
                return True
            else:
                os.remove(temp_path)
                # Continue checking other files

        # If not found in current month, check all other month-based files
        for file_path in [f for f in feedback_files if f != current_month_file]:
            temp_path = file_path + '.tmp'
            updated = False

            with open(file_path, 'r') as original, open(temp_path, 'w') as temp:
                for line in original:
                    entry = json.loads(line.strip())
                    if entry.get('message_id') == message_id:
                        # Update the entry
                        temp.write(json.dumps(updated_entry) + '\n')
                        updated = True
                    else:
                        # Keep the original entry
                        temp.write(line)

            # Replace the original file if updated
            if updated:
                os.replace(temp_path, file_path)
                logger.info(f"Updated feedback entry in {os.path.basename(file_path)}")
                return True
            else:
                os.remove(temp_path)

        # If we got here, the entry wasn't found
        logger.warning(f"Could not find feedback entry with message_id: {message_id}")
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
            "too_verbose": ["too long", "verbose", "wordy", "rambling", "shorter",
                            "concise"],
            "too_technical": ["technical", "complex", "complicated", "jargon",
                              "simpler", "simplify"],
            "not_specific": ["vague", "unclear", "generic", "specific", "details",
                             "elaborate", "more info"],
            "inaccurate": ["wrong", "incorrect", "false", "error", "mistake",
                           "accurate", "accuracy"],
            "outdated": ["outdated", "old", "not current", "update"],
            "not_helpful": ["useless", "unhelpful", "doesn't help", "didn't help",
                            "not useful"],
            "missing_context": ["context", "missing", "incomplete", "partial"],
            "confusing": ["confusing", "confused", "unclear", "hard to understand"]
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
            None,  # Use default executor
            self._update_prompt_based_on_feedback
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

        if common_issues.get('too_verbose', 0) > 5:
            prompt_guidance.append("Keep answers very concise and to the point.")

        if common_issues.get('too_technical', 0) > 5:
            prompt_guidance.append("Use simple terms and avoid technical jargon.")

        if common_issues.get('not_specific', 0) > 5:
            prompt_guidance.append(
                "Be specific and provide concrete examples when possible.")

        # Update the system template with new guidance
        if prompt_guidance:
            self.prompt_guidance = prompt_guidance
            logger.info(f"Updated prompt guidance based on feedback: {prompt_guidance}")
            return True

        return False

    def _analyze_feedback_issues(self, feedback: List[Dict[str, Any]]) -> Dict[
        str, int]:
        """Analyze feedback to identify common issues."""
        issues = defaultdict(int)

        for item in feedback:
            if not item.get('helpful', True):
                # Check for specific issue fields
                for issue_key in ['too_verbose', 'too_technical', 'not_specific',
                                  'inaccurate']:
                    if item.get(issue_key):
                        issues[issue_key] += 1

                # Also check issue list if present
                for issue in item.get('issues', []):
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
            None,  # Use default executor
            self._apply_feedback_weights,
            feedback_data
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
                lambda: {'positive': 0, 'negative': 0, 'total': 0})

            for item in feedback:
                # Skip items without necessary data
                if 'sources_used' not in item or 'helpful' not in item:
                    continue

                helpful = item['helpful']

                for source in item['sources_used']:
                    source_type = source.get('type', 'unknown')

                    if helpful:
                        source_scores[source_type]['positive'] += 1
                    else:
                        source_scores[source_type]['negative'] += 1

                    source_scores[source_type]['total'] += 1

            # Calculate new weights
            for source_type, scores in source_scores.items():
                if scores['total'] > 10:  # Only adjust if we have enough data
                    # Calculate success rate: positive / total
                    success_rate = scores['positive'] / scores['total']

                    # Scale it between 0.5 and 1.5
                    new_weight = 0.5 + success_rate

                    # Update weight if this source type exists
                    if source_type in self.source_weights:
                        old_weight = self.source_weights[source_type]
                        # Apply gradual adjustment (70% old, 30% new)
                        self.source_weights[source_type] = (0.7 * old_weight) + (
                            0.3 * new_weight)
                        logger.info(
                            f"Adjusted weight for {source_type}: {old_weight:.2f} → {self.source_weights[source_type]:.2f}")

            logger.info(
                f"Updated source weights based on feedback: {self.source_weights}")
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
            "backed_up_files": []
        }

        feedback_dir = self.settings.FEEDBACK_DIR_PATH
        os.makedirs(feedback_dir, exist_ok=True)

        # Setup backup directory
        backup_dir = os.path.join(feedback_dir, 'legacy_backup')
        os.makedirs(backup_dir, exist_ok=True)

        # Collect entries from legacy files
        legacy_entries = []

        # 1. Check day-based files
        day_pattern = re.compile(r"feedback_\d{8}\.jsonl$")
        day_files = [os.path.join(feedback_dir, f) for f in os.listdir(feedback_dir)
                     if day_pattern.match(f)]

        for file_path in day_files:
            try:
                with open(file_path, 'r') as f:
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
        root_feedback = os.path.join(self.settings.DATA_DIR, 'feedback.jsonl')
        if os.path.exists(root_feedback):
            try:
                with open(root_feedback, 'r') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        legacy_entries.append(entry)

                # Back up the file
                backup_path = os.path.join(backup_dir, 'feedback.jsonl')
                shutil.copy2(root_feedback, backup_path)
                migration_stats["backed_up_files"].append('feedback.jsonl')
                migration_stats["legacy_files_processed"] += 1
            except Exception as e:
                logger.error(f"Error processing root feedback file: {str(e)}")

        # Sort entries by timestamp where available
        for entry in legacy_entries:
            if 'timestamp' not in entry:
                # Add a placeholder timestamp for entries without one
                entry['timestamp'] = '2025-01-01T00:00:00'

        legacy_entries.sort(key=lambda e: e.get('timestamp', ''))
        migration_stats["total_entries_migrated"] = len(legacy_entries)

        # Group by month and write to appropriate files
        for entry in legacy_entries:
            try:
                # Extract month from timestamp
                timestamp = entry.get('timestamp', '')
                month = timestamp[:7] if timestamp else '2025-01'  # YYYY-MM format

                # Ensure month is in proper format
                if not re.match(r'^\d{4}-\d{2}$', month):
                    month = '2025-01'  # Default if format is invalid

                # Update stats
                if month not in migration_stats["entries_by_month"]:
                    migration_stats["entries_by_month"][month] = 0
                migration_stats["entries_by_month"][month] += 1

                # Write to month-based file
                month_file = os.path.join(feedback_dir, f"feedback_{month}.jsonl")
                with open(month_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
            except Exception as e:
                logger.error(f"Error writing entry to month file: {str(e)}")

        logger.info(
            f"Migration completed: {migration_stats['total_entries_migrated']} entries "
            f"from {migration_stats['legacy_files_processed']} files")

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
