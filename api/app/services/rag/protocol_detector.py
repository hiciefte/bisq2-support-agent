"""Detect Bisq protocol from user questions and context.

This module provides the ProtocolDetector class which detects the appropriate
Bisq protocol (bisq_easy, multisig_v1, etc.) from user questions and context.

Protocol enums: "bisq_easy", "multisig_v1", "musig", "all"
Legacy version strings: "Bisq 1", "Bisq 2", "Unknown" (for backwards compatibility)

Primary API uses protocol enums directly.
Legacy API uses version strings for backwards compatibility with RAG chatbot.
"""

import logging
from typing import Dict, List, Literal, Optional, Tuple, Union, overload

from app.services.rag.bisq_entities import BISQ1_STRONG_KEYWORDS, BISQ2_STRONG_KEYWORDS

logger = logging.getLogger(__name__)

# Protocol type alias
Protocol = Literal["multisig_v1", "bisq_easy", "musig", "all"]

# Source type alias (for FAQ candidate sources)
Source = Literal["bisq2", "matrix"]

# Source to default protocol mapping
# Bisq 2 Support API is primarily for Bisq Easy questions
SOURCE_DEFAULT_PROTOCOLS: Dict[str, Protocol] = {
    "bisq2": "bisq_easy",
    # "matrix" has no default - it serves both Bisq 1 and Bisq 2 users
}

# Confidence level for source-based defaults (moderate - can be overridden)
SOURCE_DEFAULT_CONFIDENCE = 0.6


class ProtocolDetector:
    """Detect Bisq protocol from user questions and context.

    Primary API uses protocol enums (bisq_easy, multisig_v1, etc.).
    Legacy API uses version strings (Bisq 1, Bisq 2) for backwards compatibility.
    """

    # Keywords imported from shared bisq_entities module (single source of truth)
    BISQ1_KEYWORDS = BISQ1_STRONG_KEYWORDS

    BISQ2_KEYWORDS = BISQ2_STRONG_KEYWORDS

    # =========================================================================
    # PRIMARY API (protocol-first)
    # =========================================================================

    def detect_protocol_from_text(self, text: str) -> Tuple[Optional[Protocol], float]:
        """Detect protocol directly from text content.

        This is the primary method for protocol detection, returning
        protocol enums directly without version string conversion.

        Args:
            text: Any text to analyze for protocol indicators

        Returns:
            Tuple[Optional[Protocol], float]: (protocol, confidence)
                - protocol: "multisig_v1" | "bisq_easy" | None
                - confidence: 0.0-1.0
        """
        version, confidence = self.detect_version_from_text(text)
        return self._version_to_protocol(version), confidence

    async def detect_protocol(
        self, question: str, chat_history: List[Dict[str, str]]
    ) -> Tuple[Optional[Protocol], float, Optional[str]]:
        """Detect protocol from question and chat history.

        Async protocol detection with clarifying question support.

        Args:
            question: The user's question
            chat_history: Previous messages in the conversation

        Returns:
            Tuple[Optional[Protocol], float, Optional[str]]:
                (protocol, confidence, clarifying_question)
                - protocol: "multisig_v1" | "bisq_easy" | None
                - confidence: 0.0-1.0
                - clarifying_question: Question to ask if version unclear
        """
        version, confidence, clarifying = await self.detect_version(
            question, chat_history
        )
        return self._version_to_protocol(version), confidence, clarifying

    @overload
    def detect_protocol_with_source_default(
        self,
        text: str,
        source: Optional[Source] = None,
        *,
        return_confidence: Literal[False] = False,
    ) -> Optional[Protocol]: ...

    @overload
    def detect_protocol_with_source_default(
        self,
        text: str,
        source: Optional[Source] = None,
        *,
        return_confidence: Literal[True],
    ) -> Tuple[Optional[Protocol], float]: ...

    def detect_protocol_with_source_default(
        self,
        text: str,
        source: Optional[Source] = None,
        *,
        return_confidence: bool = False,
    ) -> Union[Optional[Protocol], Tuple[Optional[Protocol], float]]:
        """Detect protocol with source-based defaults.

        This method combines content-based detection with source-based defaults.
        The source provides a default protocol when content detection is ambiguous.

        For example, messages from the Bisq 2 Support API ("bisq2" source) default
        to "bisq_easy" protocol, since that's the primary use case. However, if
        the content clearly indicates Bisq 1 (e.g., DAO, BSQ, arbitration keywords),
        the detection will override the source default.

        Args:
            text: Text content to analyze for protocol indicators
            source: Message source ("bisq2", "matrix", or None)
            return_confidence: If True, return (protocol, confidence) tuple

        Returns:
            If return_confidence=False: Protocol enum or None
            If return_confidence=True: Tuple[Protocol, confidence]

        Examples:
            # Bisq2 source defaults to bisq_easy for ambiguous questions
            >>> detector.detect_protocol_with_source_default(
            ...     "How do I complete my trade?", source="bisq2"
            ... )
            "bisq_easy"

            # But Bisq 1 keywords override the source default
            >>> detector.detect_protocol_with_source_default(
            ...     "How does DAO voting work?", source="bisq2"
            ... )
            "multisig_v1"

            # Matrix has no default - ambiguous returns None
            >>> detector.detect_protocol_with_source_default(
            ...     "How do I complete my trade?", source="matrix"
            ... )
            None
        """
        # First, try content-based detection
        detected_protocol, detected_confidence = self.detect_protocol_from_text(text)

        # If detection found something with sufficient confidence, use it
        if detected_protocol is not None and detected_confidence >= 0.6:
            logger.debug(
                f"Protocol detected from content: {detected_protocol} "
                f"(confidence: {detected_confidence})"
            )
            if return_confidence:
                return detected_protocol, detected_confidence
            return detected_protocol

        # Fall back to source default if available
        if source is not None and source in SOURCE_DEFAULT_PROTOCOLS:
            default_protocol = SOURCE_DEFAULT_PROTOCOLS[source]
            logger.debug(
                f"Using source default: {default_protocol} for source={source}"
            )
            if return_confidence:
                return default_protocol, SOURCE_DEFAULT_CONFIDENCE
            return default_protocol

        # No detection and no source default
        if return_confidence:
            return None, 0.0
        return None

    # =========================================================================
    # CONVERSION HELPERS
    # =========================================================================

    def _version_to_protocol(self, version: Optional[str]) -> Optional[Protocol]:
        """Convert version string to protocol enum.

        Args:
            version: "Bisq 1", "Bisq 2", "Unknown", or None

        Returns:
            Protocol enum or None
        """
        if version == "Bisq 2":
            return "bisq_easy"
        elif version == "Bisq 1":
            return "multisig_v1"
        return None

    def _protocol_to_version(self, protocol: Optional[str]) -> Optional[str]:
        """Convert protocol enum to version string.

        Args:
            protocol: "bisq_easy", "multisig_v1", "musig", "all", or None

        Returns:
            Version string or None
        """
        if protocol is None:
            return None
        mapping = {
            "multisig_v1": "Bisq 1",
            "bisq_easy": "Bisq 2",
            "musig": "Bisq 2",
        }
        return mapping.get(protocol)

    @staticmethod
    def protocol_to_display_name(protocol: Optional[str]) -> str:
        """Convert protocol enum to user-friendly display name.

        Args:
            protocol: "bisq_easy", "multisig_v1", "musig", "all", or None

        Returns:
            Display name string
        """
        if protocol is None:
            return "Unknown"
        mapping = {
            "multisig_v1": "Bisq 1",
            "bisq_easy": "Bisq 2",
            "musig": "MuSig",
            "all": "General",
        }
        return mapping.get(protocol, "Unknown")

    # =========================================================================
    # LEGACY API (for backwards compatibility with RAG chatbot)
    # =========================================================================

    async def detect_version(
        self, question: str, chat_history: List[Dict[str, str]]
    ) -> Tuple[str, float, Optional[str]]:
        """
        Detect Bisq version from question and chat history.

        LEGACY: Use detect_protocol() for new code.

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

    def detect_version_from_text(self, text: str) -> Tuple[str, float]:
        """Detect Bisq version from any text (question, answer, or context).

        LEGACY: Use detect_protocol_from_text() for new code.

        This is a simpler version of detect_version() that only analyzes
        text content without chat history. Useful for fallback detection
        when the question alone doesn't reveal the version.

        Args:
            text: Any text to analyze for version indicators

        Returns:
            Tuple[str, float]: (version, confidence)
                - version: "Bisq 1" | "Bisq 2" | "Unknown"
                - confidence: 0.0-1.0
        """
        text_lower = text.lower()

        # Check for explicit mentions first
        explicit = self._check_explicit_mentions(text_lower)
        if explicit:
            return explicit

        # Check for version-specific keywords
        return self._check_keywords(text_lower)

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

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

        if any(kw in question_lower for kw in ["mediator", "mediation", "dispute"]):
            return "Are you asking about mediation in Bisq 1, or Bisq Easy (Bisq 2)? Both versions have mediators."

        # Generic fallback
        return (
            "I can help with both Bisq 1 and Bisq 2. "
            "Which version are you using?\n\n"
            "- **Bisq 1**: Desktop app with DAO and altcoin trading\n"
            "- **Bisq 2**: Newer version with Bisq Easy for simple BTC purchases"
        )

    def get_clarification_prompt(self, question: str) -> str:
        """Generate clarification prompt for ambiguous questions.

        Deprecated: Use _generate_clarifying_question() instead.
        Kept for backwards compatibility.
        """
        return self._generate_clarifying_question(question)


# Backwards compatibility alias
VersionDetector = ProtocolDetector
