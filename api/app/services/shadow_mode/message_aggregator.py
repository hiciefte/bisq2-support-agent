"""Message aggregation and version confidence scoring for Shadow Mode V2."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple


class MessageAggregator:
    """Aggregate messages within time window and synthesize questions."""

    def __init__(self, window_minutes: int = 2):
        """Initialize with aggregation window."""
        self.window_minutes = window_minutes

    def aggregate_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        Group messages into conversation windows.

        Args:
            messages: List of messages with timestamp, content, sender_id, sender_type

        Returns:
            List of message groups, each group within window_minutes of each other
        """
        if not messages:
            return []

        # Sort by timestamp
        sorted_msgs = sorted(messages, key=lambda m: m.get("timestamp", ""))

        groups: List[List[Dict[str, Any]]] = []
        current_group: List[Dict[str, Any]] = []
        last_timestamp = None

        for msg in sorted_msgs:
            timestamp_str = msg.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.now(timezone.utc)

            if last_timestamp is None:
                current_group = [msg]
                last_timestamp = timestamp
            elif timestamp - last_timestamp <= timedelta(minutes=self.window_minutes):
                current_group.append(msg)
                last_timestamp = timestamp
            else:
                # Start new group
                if current_group:
                    groups.append(current_group)
                current_group = [msg]
                last_timestamp = timestamp

        # Add final group
        if current_group:
            groups.append(current_group)

        return groups

    def synthesize_question(self, messages: List[Dict[str, Any]]) -> str:
        """
        Combine messages into a single synthesized question.

        Args:
            messages: List of messages to combine

        Returns:
            Combined question text
        """
        # Filter to user messages only for the question
        user_messages = [m for m in messages if m.get("sender_type", "user") == "user"]

        if not user_messages:
            # Fall back to all messages if no user messages
            user_messages = messages

        # Combine content
        contents = [m.get("content", "").strip() for m in user_messages]
        combined = " ".join(contents)

        # Clean up whitespace
        combined = re.sub(r"\s+", " ", combined).strip()

        return combined


class VersionConfidenceScorer:
    """Calculate version confidence scores using multi-signal algorithm."""

    # Explicit version mentions
    BISQ2_EXPLICIT = [
        "bisq 2",
        "bisq2",
        "bisq easy",
        "bisq-easy",
    ]

    BISQ1_EXPLICIT = [
        "bisq 1",
        "bisq1",
        "desktop app",
        "bisq desktop",
    ]

    # Feature-specific patterns
    BISQ2_FEATURES = [
        "reputation",
        "no deposit",
        "no security deposit",
        "600 usd",
        "$600",
        "trade chat",
        "bisq easy",
        "mobile",
        "reputation score",
        "bonded role",
        "multiple identities",
    ]

    BISQ1_FEATURES = [
        "multisig",
        "2-of-2 multisig",
        "arbitration",
        "arbitrator",
        "security deposit",
        "security deposits",
        "time-locked",
        "delayed payout",
        "mediation",
        "mediator",
        "dao",
        "dao voting",
        "bsq",
        "bsq burning",
        "refund agent",
        "dispute resolution",
    ]

    # Terminology patterns
    BISQ2_TERMINOLOGY = [
        "offer book",
        "offerbook",
        "reputation-based",
        "no collateral",
        "trade limits",
        "easy",
    ]

    BISQ1_TERMINOLOGY = [
        "maker fee",
        "taker fee",
        "trade fee",
        "locked funds",
        "altcoin",
        "altcoins",
    ]

    def calculate_confidence(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate version detection confidence.

        Args:
            messages: List of messages to analyze

        Returns:
            Dict with detected_version, confidence, and signals
        """
        # Combine all message content
        combined_text = " ".join(m.get("content", "").lower() for m in messages)

        # Initialize signals
        signals = {
            "explicit_mention": 0.0,
            "feature_patterns": 0.0,
            "terminology": 0.0,
            "context_clues": 0.0,
        }

        # Track version scores
        bisq2_score = 0.0
        bisq1_score = 0.0

        # Signal 1: Explicit version mentions (40% weight)
        bisq2_explicit_count = sum(
            1 for pattern in self.BISQ2_EXPLICIT if pattern in combined_text
        )
        bisq1_explicit_count = sum(
            1 for pattern in self.BISQ1_EXPLICIT if pattern in combined_text
        )

        if bisq2_explicit_count > 0:
            signals["explicit_mention"] = 1.0
            bisq2_score += bisq2_explicit_count * 2.0
        if bisq1_explicit_count > 0:
            if bisq2_explicit_count == 0:
                signals["explicit_mention"] = 1.0
            bisq1_score += bisq1_explicit_count * 2.0

        # Signal 2: Feature-specific patterns (30% weight)
        bisq2_feature_count = sum(
            1 for pattern in self.BISQ2_FEATURES if pattern in combined_text
        )
        bisq1_feature_count = sum(
            1 for pattern in self.BISQ1_FEATURES if pattern in combined_text
        )

        total_features = bisq2_feature_count + bisq1_feature_count
        if total_features > 0:
            signals["feature_patterns"] = min(1.0, total_features / 3)
            bisq2_score += bisq2_feature_count
            bisq1_score += bisq1_feature_count

        # Signal 3: Terminology (20% weight)
        bisq2_term_count = sum(
            1 for pattern in self.BISQ2_TERMINOLOGY if pattern in combined_text
        )
        bisq1_term_count = sum(
            1 for pattern in self.BISQ1_TERMINOLOGY if pattern in combined_text
        )

        total_terms = bisq2_term_count + bisq1_term_count
        if total_terms > 0:
            signals["terminology"] = min(1.0, total_terms / 2)
            bisq2_score += bisq2_term_count * 0.5
            bisq1_score += bisq1_term_count * 0.5

        # Signal 4: Context clues (10% weight)
        # Check for version mentions in context
        if re.search(r"v?2\.\d", combined_text):
            signals["context_clues"] = 0.8
            bisq2_score += 0.5
        elif re.search(r"v?1\.\d", combined_text):
            signals["context_clues"] = 0.8
            bisq1_score += 0.5

        # Calculate weighted confidence
        confidence = (
            signals["explicit_mention"] * 0.40
            + signals["feature_patterns"] * 0.30
            + signals["terminology"] * 0.20
            + signals["context_clues"] * 0.10
        )

        # Determine detected version
        if bisq2_score > bisq1_score:
            detected_version = "bisq2"
        elif bisq1_score > bisq2_score:
            detected_version = "bisq1"
        else:
            detected_version = "unknown"
            # Reduce confidence for unknown
            confidence *= 0.5

        return {
            "detected_version": detected_version,
            "confidence": round(confidence, 2),
            "signals": signals,
        }

    def should_auto_confirm(self, confidence: float, threshold: float = 0.8) -> bool:
        """
        Check if confidence meets auto-confirm threshold.

        Args:
            confidence: Calculated confidence score
            threshold: Auto-confirm threshold (default 80%)

        Returns:
            True if should auto-confirm
        """
        return confidence >= threshold
