"""
Prompt Optimizer for feedback-based prompt improvement.

This module handles:
- Generating prompt guidance from feedback patterns
- Analyzing common issues in negative feedback
- Dynamic prompt adjustment based on user feedback
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PromptOptimizer:
    """Optimizer for RAG prompts based on feedback patterns.

    This class handles:
    - Analyzing feedback for common issues
    - Generating prompt guidance
    - Dynamically adjusting prompts to address user concerns
    """

    def __init__(self):
        """Initialize the prompt optimizer."""
        # Prompting guidance based on feedback
        self.prompt_guidance = []

        logger.info("Prompt optimizer initialized")

    def update_prompt_guidance(
        self, feedback_data: List[Dict[str, Any]], analyzer
    ) -> bool:
        """Dynamically adjust the system prompt based on feedback patterns.

        Args:
            feedback_data: List of feedback entries
            analyzer: FeedbackAnalyzer instance for issue analysis

        Returns:
            bool: True if the prompt was updated
        """
        if not feedback_data or len(feedback_data) < 20:  # Need sufficient data
            logger.info("Not enough feedback data to update prompt")
            return False

        # Analyze common issues in negative feedback
        common_issues = analyzer.analyze_feedback_issues(feedback_data)

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

    def get_prompt_guidance(self) -> List[str]:
        """Get the current prompt guidance based on feedback.

        Returns:
            List of guidance strings to incorporate into prompts
        """
        return self.prompt_guidance
