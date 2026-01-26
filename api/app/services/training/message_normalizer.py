"""Unified message normalization for multi-source FAQ extraction.

This module provides a common message format for processing messages from
different sources (Bisq2 API, Matrix) through the LLM extraction pipeline.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from app.core.pii_utils import PII_LLM_PATTERNS


class MessageSource(Enum):
    """Supported message sources for FAQ extraction."""

    BISQ2 = "bisq2"
    MATRIX = "matrix"


@dataclass
class UnifiedMessage:
    """Normalized message format for all sources.

    Attributes:
        source: The source system (bisq2 or matrix)
        source_id: Original message ID from the source system
        text: Message content (PII-anonymized)
        author: Sender identifier
        timestamp: Message timestamp in UTC
        is_staff: Whether the sender is a trusted staff member
        raw_data: Original message data for debugging (excluded from repr)
    """

    source: MessageSource
    source_id: str
    text: str
    author: str
    timestamp: datetime
    is_staff: bool
    raw_data: Optional[Dict[str, Any]] = field(default=None, repr=False)


class MessageNormalizer:
    """Converts source-specific messages to unified format.

    This normalizer handles messages from different sources and converts them
    to a common format suitable for LLM-based FAQ extraction.

    Attributes:
        staff_ids: Set of staff user IDs (lowercased for case-insensitive matching)
    """

    def __init__(self, staff_ids: Optional[Set[str]] = None):
        """Initialize the normalizer with staff IDs.

        Args:
            staff_ids: Set of user IDs that should be marked as staff.
                      Defaults to empty set if not provided.
        """
        self.staff_ids = {s.lower() for s in (staff_ids or set())}

    def normalize_bisq2(self, msg: Dict[str, Any]) -> UnifiedMessage:
        """Convert Bisq2 message to unified format.

        Args:
            msg: Raw Bisq2 message dict with keys like 'messageId', 'message', 'author', 'date'

        Returns:
            UnifiedMessage with normalized fields
        """
        author = msg.get("author", "")
        text = self._anonymize_pii(msg.get("message", ""))

        return UnifiedMessage(
            source=MessageSource.BISQ2,
            source_id=msg.get("messageId", ""),
            text=text,
            author=author,
            timestamp=self._parse_bisq_timestamp(msg.get("date")),
            is_staff=author.lower() in self.staff_ids,
            raw_data=msg,
        )

    def normalize_matrix(self, event: Dict[str, Any]) -> UnifiedMessage:
        """Convert Matrix event to unified format.

        Args:
            event: Raw Matrix event dict with keys like 'event_id', 'sender', 'content', 'origin_server_ts'

        Returns:
            UnifiedMessage with normalized fields
        """
        sender = event.get("sender", "")
        content = event.get("content", {})
        text = self._anonymize_pii(content.get("body", ""))

        return UnifiedMessage(
            source=MessageSource.MATRIX,
            source_id=event.get("event_id", ""),
            text=text,
            author=sender,
            timestamp=self._parse_matrix_timestamp(event.get("origin_server_ts")),
            is_staff=sender.lower() in self.staff_ids,
            raw_data=event,
        )

    def normalize_batch(
        self,
        messages: List[Dict[str, Any]],
        source: MessageSource,
    ) -> List[UnifiedMessage]:
        """Normalize a batch of messages from a single source.

        Args:
            messages: List of raw messages from the source
            source: The message source type

        Returns:
            List of normalized UnifiedMessage objects
        """
        normalizer = (
            self.normalize_bisq2
            if source == MessageSource.BISQ2
            else self.normalize_matrix
        )
        return [normalizer(msg) for msg in messages]

    def format_for_llm(self, messages: List[UnifiedMessage]) -> str:
        """Format unified messages for LLM extraction.

        Creates a text representation suitable for the LLM to identify
        Q&A pairs. Messages are sorted by timestamp and prefixed with
        [STAFF] or [USER] role indicators.

        Args:
            messages: List of normalized messages

        Returns:
            Formatted text string for LLM input
        """
        lines = []
        for msg in sorted(messages, key=lambda m: m.timestamp):
            role = "[STAFF]" if msg.is_staff else "[USER]"
            lines.append(f"{role} {msg.author}: {msg.text}")
        return "\n".join(lines)

    def _parse_bisq_timestamp(self, date_str: Optional[str]) -> datetime:
        """Parse Bisq2 date string to datetime.

        Bisq2 uses ISO format: "2025-01-20T10:30:00Z"

        Args:
            date_str: ISO format date string or None

        Returns:
            Parsed datetime in UTC, or current time if parsing fails
        """
        if not date_str:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return datetime.now(timezone.utc)

    def _parse_matrix_timestamp(self, ts_ms: Any) -> datetime:
        """Parse Matrix timestamp (milliseconds since epoch) to datetime.

        Args:
            ts_ms: Timestamp in milliseconds since Unix epoch (int, str, or None)

        Returns:
            Parsed datetime in UTC, or current time if input is invalid/zero
        """
        if ts_ms is None or ts_ms == 0:
            return datetime.now(timezone.utc)
        try:
            # Handle string input by converting to int/float
            if isinstance(ts_ms, str):
                ts_ms = int(float(ts_ms))
            elif not isinstance(ts_ms, (int, float)):
                return datetime.now(timezone.utc)
            # Treat 0 as invalid (would result in epoch 1970-01-01)
            if ts_ms == 0:
                return datetime.now(timezone.utc)
            return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return datetime.now(timezone.utc)

    def _anonymize_pii(self, text: str) -> str:
        """Anonymize PII in text using centralized PII patterns.

        Args:
            text: Text that may contain PII

        Returns:
            Text with PII replaced by [TYPE_REDACTED] placeholders
        """
        if not text:
            return text
        for pii_type, pattern in PII_LLM_PATTERNS.items():
            text = re.sub(
                pattern, f"[{pii_type.upper()}_REDACTED]", text, flags=re.IGNORECASE
            )
        return text
