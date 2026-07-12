"""
Prompt Optimizer for feedback-based prompt improvement.

This module handles:
- Generating prompt guidance from feedback patterns
- Analyzing common issues in negative feedback
- Dynamic prompt adjustment based on user feedback
- Durable persistence of guidance via the learning_state store, so
  guidance computed by the weekly cron script is visible to the live
  server and survives restarts
"""

import logging
from collections.abc import Mapping
from typing import Any, ClassVar, Dict, List, Optional

logger = logging.getLogger(__name__)

# Key under which guidance is persisted in the learning_state table
PROMPT_GUIDANCE_STATE_KEY = "prompt_guidance"


class PromptOptimizer:
    """Optimizer for RAG prompts based on feedback patterns.

    This class handles:
    - Analyzing feedback for common issues
    - Generating prompt guidance
    - Dynamically adjusting prompts to address user concerns
    - Persisting guidance through an optional repository (learning_state)
    """

    DIVERGENCE_GUIDANCE: ClassVar[Dict[str, str]] = {
        "answer_too_long": (
            "Keep answers tight: answer first, then only the minimum necessary detail."
        ),
        "leading_greeting": (
            "Start with the answer; do not add a greeting or restate the question."
        ),
        "scam_warning_missing": (
            "When a scam-safety trigger is present, lead with the static scam warning "
            "before any other guidance."
        ),
        "scam_warning_false_positive": (
            "Give the scam warning only when a defined scam-safety trigger is present; "
            "do not infer one from an unrelated support request."
        ),
        "wiki_link_missing": (
            "When Context provides a canonical fix, use that fix and preserve its "
            "exact canonical source instead of substituting a generic page."
        ),
        "diagnostic_question_missing": (
            "For troubleshooting with a high-value unknown, ask exactly one targeted "
            "diagnostic question instead of speculative steps."
        ),
        "remedy_term_missing": (
            "Use the specific recovery action supported by Context; do not replace it "
            "with generic restart, wait, or contact-support advice."
        ),
    }
    ALLOWED_DIVERGENCE_SIGNALS: ClassVar[frozenset[str]] = frozenset(
        DIVERGENCE_GUIDANCE
    )

    def __init__(self, repository: Optional[Any] = None):
        """Initialize the prompt optimizer.

        Args:
            repository: Optional FeedbackRepository used to persist and
                reload guidance. Without it the optimizer is in-memory only.
        """
        self.repository = repository
        # Prompting guidance based on feedback
        self.prompt_guidance: List[str] = []
        self.load_guidance()

        logger.info("Prompt optimizer initialized")

    def load_guidance(self) -> List[str]:
        """Reload persisted guidance from the learning_state store.

        No-op without a repository.

        Returns:
            The current prompt guidance after the reload attempt
        """
        if self.repository is None:
            return self.prompt_guidance

        try:
            stored = self.repository.get_learning_state(PROMPT_GUIDANCE_STATE_KEY)
        except Exception as e:
            logger.warning("Could not load persisted prompt guidance: %s", e)
            return self.prompt_guidance

        if isinstance(stored, list):
            self.prompt_guidance = [str(item) for item in stored]
            logger.debug(
                "Loaded %d persisted prompt guidance entries",
                len(self.prompt_guidance),
            )

        return self.prompt_guidance

    def _persist_guidance(self) -> None:
        """Persist current guidance to the learning_state store (best-effort)."""
        if self.repository is None:
            return
        try:
            self.repository.set_learning_state(
                PROMPT_GUIDANCE_STATE_KEY, self.prompt_guidance
            )
        except Exception as e:
            logger.warning("Could not persist prompt guidance: %s", e)

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
            self._persist_guidance()
            logger.info(f"Updated prompt guidance based on feedback: {prompt_guidance}")
            return True

        return False

    def get_prompt_guidance(
        self, divergence_counts: Optional[Mapping[str, int]] = None
    ) -> List[str]:
        """Get the current prompt guidance based on feedback.

        Stage-2 divergence counts select only deterministic, human-authored
        guidance from ``DIVERGENCE_GUIDANCE``. Report text is never copied into
        the prompt.

        Args:
            divergence_counts: Sanitized Stage-2 counters keyed by known signal ID.

        Returns:
            List of guidance strings to incorporate into prompts
        """
        divergence_guidance = [
            guidance
            for signal, guidance in self.DIVERGENCE_GUIDANCE.items()
            if divergence_counts
            and type(divergence_counts.get(signal)) is int
            and divergence_counts[signal] > 0
        ]
        return list(dict.fromkeys([*self.prompt_guidance, *divergence_guidance]))
