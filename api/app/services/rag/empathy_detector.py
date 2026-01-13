"""Detect emotional signals in user messages."""

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)


class EmpathyDetector:
    """Detect emotional signals in user messages."""

    FRUSTRATION_PATTERNS = [
        r"doesn't work",
        r"not working",
        r"broken",
        r"stuck",
        r"can't figure out",
        r"frustrated",
        r"annoyed",
        r"don't understand",
        r"makes no sense",
        r"waste of time",
        r"!{2,}",  # Multiple exclamation marks
        r"\?{2,}",  # Multiple question marks
    ]

    CONFUSION_PATTERNS = [
        r"what does .* mean",
        r"i don't get",
        r"confused about",
        r"not sure what",
        r"\blost\b",
        r"help me understand",
        r"can you explain",
    ]

    POSITIVE_PATTERNS = [
        r"thank",
        r"helpful",
        r"great",
        r"awesome",
        r"perfect",
        r"works",
        r"got it",
        r"understand now",
    ]

    async def detect_emotion(self, message: str) -> Tuple[str, float]:
        """
        Detect emotional state from message.

        Returns:
            Tuple[str, float]: (emotion, intensity)
            - emotion: "frustrated", "confused", "positive", "neutral"
            - intensity: 0.0-1.0
        """
        message_lower = message.lower()

        # Count pattern matches
        frustration_count = sum(
            1 for p in self.FRUSTRATION_PATTERNS if re.search(p, message_lower)
        )
        confusion_count = sum(
            1 for p in self.CONFUSION_PATTERNS if re.search(p, message_lower)
        )
        positive_count = sum(
            1 for p in self.POSITIVE_PATTERNS if re.search(p, message_lower)
        )

        # Determine primary emotion
        if frustration_count >= 2:
            intensity = min(frustration_count * 0.3, 1.0)
            return ("frustrated", intensity)

        if confusion_count >= 1:
            intensity = min(confusion_count * 0.4, 1.0)
            return ("confused", intensity)

        if positive_count >= 1:
            intensity = min(positive_count * 0.4, 1.0)
            return ("positive", intensity)

        return ("neutral", 0.0)

    def get_response_modifier(self, emotion: str, intensity: float) -> str:
        """Get tone modifier for response generation."""
        if emotion == "frustrated" and intensity > 0.5:
            return (
                "The user seems frustrated. Respond with empathy and "
                "acknowledge their difficulty. Provide clear, step-by-step "
                "guidance. Avoid technical jargon."
            )

        if emotion == "confused" and intensity > 0.3:
            return (
                "The user seems confused. Start with a simple explanation, "
                "then provide more details. Use analogies if helpful."
            )

        if emotion == "positive":
            return (
                "The user is expressing positivity. Match their energy "
                "and provide any additional helpful information."
            )

        return ""  # Neutral - no modification
