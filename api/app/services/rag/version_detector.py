"""Detect Bisq version from user questions and context."""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class VersionDetector:
    """Detect Bisq version from user questions and context."""

    BISQ1_KEYWORDS = [
        "dao",
        "bsq",
        "burningman",
        "burning man",
        "arbitration",
        "arbitrator",
        "mediator",
        "altcoin",
        "security deposit",
        "multisig",
        "2-of-2",
        "delayed payout",
        "refund agent",
        "dao voting",
    ]

    BISQ2_KEYWORDS = [
        "bisq easy",
        "reputation",
        "bonded roles",
        "trade protocol",
        "multiple identities",
        "600 usd",
        "$600",
        "novice bitcoin",
        "bisq 2",
        "bisq2",
    ]

    async def detect_version(
        self, question: str, chat_history: List[Dict[str, str]]
    ) -> Tuple[str, float]:
        """
        Detect Bisq version from question and chat history.

        Returns:
            Tuple[str, float]: ("Bisq 1" | "Bisq 2" | "Unknown", confidence)
        """
        question_lower = question.lower()

        # 1. Check for explicit version mentions
        explicit_version = self._check_explicit_mentions(question_lower)
        if explicit_version:
            return explicit_version

        # 2. Check for version-specific keywords
        keyword_version = self._check_keywords(question_lower)
        if keyword_version[1] > 0.6:  # Confidence threshold
            return keyword_version

        # 3. Check chat history for context
        history_version = self._check_chat_history(chat_history)
        if history_version:
            return history_version

        # 4. Default to Bisq 2 (current version) with low confidence
        logger.debug("No version detected, defaulting to Bisq 2")
        return ("Bisq 2", 0.50)

    def _check_explicit_mentions(self, text: str) -> Optional[Tuple[str, float]]:
        """Check for explicit version mentions."""
        if "bisq 1" in text or "bisq1" in text:
            return ("Bisq 1", 0.95)
        if "bisq 2" in text or "bisq2" in text:
            return ("Bisq 2", 0.95)
        return None

    def _check_keywords(self, text: str) -> Tuple[str, float]:
        """Score based on version-specific keywords."""
        bisq1_score = sum(1 for kw in self.BISQ1_KEYWORDS if kw in text)
        bisq2_score = sum(1 for kw in self.BISQ2_KEYWORDS if kw in text)

        if bisq1_score > bisq2_score and bisq1_score > 0:
            confidence = min(0.7 + (bisq1_score * 0.1), 0.95)
            return ("Bisq 1", confidence)

        if bisq2_score > bisq1_score and bisq2_score > 0:
            confidence = min(0.7 + (bisq2_score * 0.1), 0.95)
            return ("Bisq 2", confidence)

        return ("Unknown", 0.0)

    def _check_chat_history(
        self, chat_history: List[Dict[str, str]]
    ) -> Optional[Tuple[str, float]]:
        """Check recent chat history for version context."""
        for msg in reversed(chat_history[-5:]):  # Last 5 messages
            content = msg.get("content", "").lower()

            if "bisq 1" in content or "bisq1" in content:
                return ("Bisq 1", 0.80)
            if "bisq 2" in content or "bisq2" in content:
                return ("Bisq 2", 0.80)

            # Check for keyword patterns in history
            bisq1_found = any(kw in content for kw in self.BISQ1_KEYWORDS[:5])
            bisq2_found = any(kw in content for kw in self.BISQ2_KEYWORDS[:5])

            if bisq1_found and not bisq2_found:
                return ("Bisq 1", 0.70)
            if bisq2_found and not bisq1_found:
                return ("Bisq 2", 0.70)

        return None

    def get_clarification_prompt(self, question: str) -> str:
        """Generate clarification prompt for ambiguous questions."""
        return (
            "I'd be happy to help! To give you the most accurate answer, "
            "could you please clarify which version of Bisq you're using?\n\n"
            "- **Bisq 1**: The original desktop application with DAO and altcoin trading\n"
            "- **Bisq 2**: The newer version with Bisq Easy for simple BTC purchases"
        )
