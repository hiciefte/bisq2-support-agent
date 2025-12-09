"""
Hybrid classifier combining pattern matching with OpenAI classification.

Implements tiered classification strategy:
1. Pattern matching (fast, free, high confidence cases)
2. OpenAI API (slower, paid, uncertain cases only)
3. Fallback to pattern result
"""

import logging
from typing import List, Optional, Tuple

from .classifiers import SpeakerRoleClassifier
from .openai_classifier import OpenAIMessageClassifier

logger = logging.getLogger(__name__)


class HybridSpeakerClassifier:
    """
    Hybrid classifier using pattern matching + OpenAI fallback.

    Decision Flow:
    1. Check pattern confidence >= 0.85 → return pattern result (FAST PATH)
    2. If confidence < 0.85 AND OpenAI enabled → query OpenAI
    3. If OpenAI confidence >= 0.75 → return OpenAI result
    4. Otherwise → return pattern result (conservative fallback)
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        enable_openai: bool = False,
        pattern_confidence_threshold: float = 0.85,
        openai_confidence_threshold: float = 0.75,
        known_staff: Optional[List[str]] = None,
        **openai_kwargs,
    ):
        """
        Initialize hybrid classifier.

        Args:
            openai_api_key: OpenAI API key (required if enable_openai=True)
            enable_openai: Whether to enable OpenAI fallback classification
            pattern_confidence_threshold: Min confidence to skip OpenAI (0-1.0)
            openai_confidence_threshold: Min OpenAI confidence to use (0-100)
            known_staff: List of known support staff identifiers
            **openai_kwargs: Additional arguments for OpenAIMessageClassifier
        """
        self.enable_openai = enable_openai
        self.pattern_threshold = pattern_confidence_threshold
        self.openai_threshold = openai_confidence_threshold
        self.known_staff = known_staff or []

        # Initialize OpenAI classifier if enabled
        self.openai_classifier = None
        if enable_openai:
            if not openai_api_key:
                raise ValueError("openai_api_key required when enable_openai=True")

            self.openai_classifier = OpenAIMessageClassifier(
                api_key=openai_api_key, **openai_kwargs
            )
            logger.info(
                "OpenAI classification enabled (pattern threshold: %.2f, OpenAI threshold: %.0f)",
                pattern_confidence_threshold,
                openai_confidence_threshold,
            )

        # Classification statistics
        self.stats = {
            "total_classifications": 0,
            "pattern_only": 0,
            "openai_invoked": 0,
            "openai_used": 0,
            "pattern_fallback": 0,
        }

    async def classify_speaker_role(
        self,
        message: str,
        sender: str = "",
    ) -> Tuple[str, float, str]:
        """
        Classify speaker role using hybrid strategy.

        Args:
            message: Message text to classify
            sender: Sender ID (used for known_staff lookup)

        Returns:
            Tuple of (role, confidence, reasoning)
            - role: "staff" or "user" (normalized to lowercase)
            - confidence: 0.0-1.0 float
            - reasoning: Explanation of classification decision
        """
        self.stats["total_classifications"] += 1

        # Stage 1: Pattern matching (always run first)
        pattern_role, pattern_confidence = SpeakerRoleClassifier.classify_speaker_role(
            message, sender, self.known_staff
        )

        # Normalize role to lowercase for consistency
        pattern_role = pattern_role.lower()

        # High confidence pattern match - skip OpenAI
        if pattern_confidence >= self.pattern_threshold:
            self.stats["pattern_only"] += 1
            reasoning = f"Pattern match (confidence: {pattern_confidence:.2f})"
            logger.debug(
                f"High confidence pattern: {pattern_role} ({pattern_confidence:.2f})"
            )
            return (pattern_role, pattern_confidence, reasoning)

        # Stage 2: OpenAI classification for uncertain cases
        if self.enable_openai and self.openai_classifier:
            self.stats["openai_invoked"] += 1

            try:
                openai_role, openai_confidence, openai_reasoning = (
                    await self.openai_classifier.classify_message(
                        message, use_few_shot=True
                    )
                )

                # Normalize OpenAI role to lowercase
                openai_role = openai_role.lower()

                # Normalize OpenAI confidence to 0-1 scale (API returns 0-100)
                openai_confidence_normalized = openai_confidence / 100.0

                # Use OpenAI result if confidence threshold met
                if openai_confidence >= self.openai_threshold:
                    self.stats["openai_used"] += 1
                    reasoning = f"OpenAI classification (confidence: {openai_confidence:.0f}): {openai_reasoning}"
                    logger.debug(
                        f"OpenAI classification: {openai_role} ({openai_confidence:.0f}) - {openai_reasoning}"
                    )
                    return (openai_role, openai_confidence_normalized, reasoning)

                # OpenAI confidence too low - log disagreement if roles differ
                if openai_role != pattern_role:
                    logger.warning(
                        f"Classification disagreement (pattern: {pattern_role} {pattern_confidence:.2f}, "
                        f"OpenAI: {openai_role} {openai_confidence:.0f}) - using pattern"
                    )

            except Exception as e:
                logger.error(
                    f"OpenAI classification failed: {e}, falling back to pattern matching"
                )
                # Continue to fallback

        # Stage 3: Fallback to pattern result
        self.stats["pattern_fallback"] += 1
        reasoning = f"Pattern fallback (confidence: {pattern_confidence:.2f})"
        logger.debug(
            f"Using pattern fallback: {pattern_role} ({pattern_confidence:.2f})"
        )
        return (pattern_role, pattern_confidence, reasoning)

    def get_classification_stats(self) -> dict:
        """
        Get classification statistics.

        Returns:
            Dict with classification metrics and OpenAI/cache stats
        """
        total = self.stats["total_classifications"]
        stats = {
            "total_classifications": total,
            "pattern_only": self.stats["pattern_only"],
            "pattern_only_percent": (
                (self.stats["pattern_only"] / total * 100) if total > 0 else 0
            ),
            "openai_invoked": self.stats["openai_invoked"],
            "openai_invoked_percent": (
                (self.stats["openai_invoked"] / total * 100) if total > 0 else 0
            ),
            "openai_used": self.stats["openai_used"],
            "openai_used_percent": (
                (self.stats["openai_used"] / total * 100) if total > 0 else 0
            ),
            "pattern_fallback": self.stats["pattern_fallback"],
            "pattern_fallback_percent": (
                (self.stats["pattern_fallback"] / total * 100) if total > 0 else 0
            ),
            "openai_enabled": self.enable_openai,
        }

        # Add OpenAI cost and cache stats if enabled
        if self.enable_openai and self.openai_classifier:
            stats["openai_costs"] = self.openai_classifier.get_cost_estimate()
            stats["cache_stats"] = self.openai_classifier.get_cache_stats()

        return stats

    def reset_stats(self):
        """Reset classification statistics."""
        self.stats = {
            "total_classifications": 0,
            "pattern_only": 0,
            "openai_invoked": 0,
            "openai_used": 0,
            "pattern_fallback": 0,
        }
        logger.info("Classification statistics reset")

    def clear_openai_cache(self):
        """Clear OpenAI classification cache."""
        if self.openai_classifier:
            self.openai_classifier.clear_cache()


# Convenience function for quick classification
async def classify_message_hybrid(
    message: str,
    sender: str = "",
    openai_api_key: Optional[str] = None,
    enable_openai: bool = False,
    known_staff: Optional[List[str]] = None,
) -> Tuple[str, float, str]:
    """
    Quick helper for hybrid classification without instantiating classifier.

    Args:
        message: Message text
        sender: Sender ID
        openai_api_key: OpenAI API key
        enable_openai: Whether to use OpenAI fallback
        known_staff: List of known staff identifiers

    Returns:
        Tuple of (role, confidence, reasoning)
    """
    classifier = HybridSpeakerClassifier(
        openai_api_key=openai_api_key,
        enable_openai=enable_openai,
        known_staff=known_staff,
    )
    return await classifier.classify_speaker_role(message, sender)
