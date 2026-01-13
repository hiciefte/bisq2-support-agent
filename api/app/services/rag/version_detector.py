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
    ) -> Tuple[str, float, Optional[str]]:
        """
        Detect Bisq version from question and chat history.

        Returns:
            Tuple[str, float, Optional[str]]: (version, confidence, clarifying_question)
                - version: "Bisq 1" | "Bisq 2" | "Unknown"
                - confidence: 0.0-1.0
                - clarifying_question: Question to ask user if version unclear (None if confident)
        """
        question_lower = question.lower()

        # 1. Check for explicit version mentions (highest confidence)
        explicit_version = self._check_explicit_mentions(question_lower)
        if explicit_version:
            return (*explicit_version, None)  # No clarification needed

        # 2. Check for version-specific keywords
        keyword_version = self._check_keywords(question_lower)
        if keyword_version[1] > 0.6:  # High confidence threshold
            return (*keyword_version, None)  # No clarification needed

        # 3. Check chat history for context
        history_version = self._check_chat_history(chat_history)
        if history_version:
            return (*history_version, None)  # No clarification needed

        # 4. Low confidence - generate clarifying question
        clarifying_q = self._generate_clarifying_question(question)
        logger.debug("Low version confidence, requesting clarification")
        return ("Unknown", 0.30, clarifying_q)

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

    def _check_chat_history(self, chat_history: List) -> Optional[Tuple[str, float]]:
        """Check recent chat history for version context."""
        if not chat_history:
            return None
        for msg in reversed(chat_history[-5:]):  # Last 5 messages
            # Handle both dict and Pydantic ChatMessage objects
            if hasattr(msg, "content"):
                # Pydantic ChatMessage object
                content = msg.content.lower()
            elif isinstance(msg, dict):
                # Dict format
                content = msg.get("content", "").lower()
            else:
                content = str(msg).lower()

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

    def _generate_clarifying_question(self, question: str) -> str:
        """Generate context-aware clarifying question.

        Strategy:
        1. Use context-aware defaults based on question keywords
        2. Fall back to generic version question if no context matches
        """
        question_lower = question.lower()

        # Context-aware clarifying questions
        if any(kw in question_lower for kw in ["trade", "payment", "buy", "sell"]):
            return "Are you using Bisq 1 trading or Bisq Easy (Bisq 2)?"

        if any(kw in question_lower for kw in ["wallet", "bitcoin", "btc"]):
            return "Which Bisq version's wallet are you asking about?"

        if any(kw in question_lower for kw in ["reputation", "profile"]):
            return "Are you asking about Bisq 2's reputation system, or transferring Bisq 1 reputation?"

        if any(kw in question_lower for kw in ["dao", "bsq", "voting"]):
            return "This sounds like a Bisq 1 DAO question. Is that correct, or are you asking about Bisq 2?"

        # Generic fallback
        return (
            "I can help with both Bisq 1 and Bisq 2. "
            "Which version are you using?\n\n"
            "• **Bisq 1**: Desktop app with DAO and altcoin trading\n"
            "• **Bisq 2**: Newer version with Bisq Easy for simple BTC purchases"
        )

    def get_clarification_prompt(self, question: str) -> str:
        """Generate clarification prompt for ambiguous questions.

        Deprecated: Use _generate_clarifying_question() instead.
        Kept for backwards compatibility.
        """
        return self._generate_clarifying_question(question)
