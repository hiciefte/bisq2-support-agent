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
            prompt_guidance.append(
                "Keep answers tight: answer first, then only the minimum necessary detail."
            )

        if common_issues.get("too_technical", 0) > 5:
            prompt_guidance.append(
                "Use plain language first and introduce technical terms only when they help."
            )

        if common_issues.get("not_specific", 0) > 5:
            prompt_guidance.append(
                "Be specific, concrete, and action-oriented. Prefer exact steps over general advice."
            )

        if common_issues.get("wrong_version", 0) > 3:
            prompt_guidance.append(
                "Do not mix Bisq 1 and Bisq 2 guidance. If version is unclear, ask a short clarifying question."
            )

        if common_issues.get("bad_tone", 0) > 3:
            prompt_guidance.append(
                "Sound like a calm human support teammate. Avoid robotic, corporate, or overly performative language."
            )

        if common_issues.get("bad_formatting", 0) > 3:
            prompt_guidance.append(
                "Keep formatting chat-friendly: short paragraphs, short lists, and no markdown headings."
            )

        if common_issues.get("partially_inaccurate", 0) > 3:
            prompt_guidance.append(
                "Avoid stretching beyond evidence. If one detail is uncertain, state the uncertainty instead of guessing."
            )

        # Update the system template with new guidance
        if prompt_guidance:
            self.prompt_guidance = list(dict.fromkeys(prompt_guidance))
            logger.info(f"Updated prompt guidance based on feedback: {prompt_guidance}")
            return True

        return False

    def get_prompt_guidance(self) -> List[str]:
        """Get the current prompt guidance based on feedback.

        Returns:
            List of guidance strings to incorporate into prompts
        """
        return self.prompt_guidance
