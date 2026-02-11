"""Reaction-based feedback collection for channel plugins.

Provides channel-agnostic reaction handling:
- ReactionEvent: normalized event model
- SentMessageTracker: maps external IDs to internal Q&A records
- ReactionProcessor: processes reactions into feedback
- ReactionHandlerBase: ABC for channel-specific handlers
"""

import asyncio
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class ReactionRating(IntEnum):
    """Feedback rating derived from emoji reactions."""

    NEGATIVE = 0
    POSITIVE = 1


# =============================================================================
# Models
# =============================================================================


class ReactionEvent(BaseModel):
    """Normalized reaction event from any channel."""

    channel_id: str = Field(..., description="Source channel identifier")
    external_message_id: str = Field(
        ..., description="Channel-native message ID (Matrix event_id, Bisq2 messageId)"
    )
    reactor_id: str = Field(..., description="Channel-native user ID of reactor")
    rating: ReactionRating = Field(..., description="Normalized rating")
    raw_reaction: str = Field(..., description="Original emoji or reaction key")
    timestamp: datetime = Field(..., description="When reaction occurred")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional channel-specific data"
    )


@dataclass
class SentMessageRecord:
    """Record of a sent AI response for reaction tracking."""

    internal_message_id: str
    external_message_id: str
    channel_id: str
    question: str
    answer: str
    user_id: str
    timestamp: datetime
    sources: Optional[List[Dict[str, Any]]] = None


# =============================================================================
# Protocol
# =============================================================================


@runtime_checkable
class ReactionHandlerProtocol(Protocol):
    """Protocol for reaction handlers (runtime-checkable)."""

    channel_id: str

    async def start_listening(self) -> None: ...

    async def stop_listening(self) -> None: ...


# =============================================================================
# SentMessageTracker
# =============================================================================


class SentMessageTracker:
    """Tracks sent AI messages for reaction correlation.

    Maps channel_id:external_message_id -> SentMessageRecord.
    TTL-based expiry ensures bounded memory usage.
    """

    def __init__(self, ttl_hours: int = 24, max_size: int = 10_000):
        self.ttl_hours = ttl_hours
        self._max_size = max_size
        self._records: Dict[str, SentMessageRecord] = {}
        self._track_count: int = 0
        self._purge_interval: int = 100

    def _key(self, channel_id: str, external_message_id: str) -> str:
        return f"{channel_id}:{external_message_id}"

    def _purge_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.ttl_hours)
        expired_keys = [k for k, v in self._records.items() if v.timestamp < cutoff]
        for key in expired_keys:
            del self._records[key]

    def track(
        self,
        channel_id: str,
        external_message_id: str,
        internal_message_id: str,
        question: str,
        answer: str,
        user_id: str,
        sources: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Track a sent message for future reaction correlation."""
        if len(self._records) >= self._max_size:
            oldest_key = min(self._records, key=lambda k: self._records[k].timestamp)
            del self._records[oldest_key]

        key = self._key(channel_id, external_message_id)
        self._records[key] = SentMessageRecord(
            internal_message_id=internal_message_id,
            external_message_id=external_message_id,
            channel_id=channel_id,
            question=question,
            answer=answer,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc),
            sources=sources,
        )
        self._track_count += 1
        if self._track_count % self._purge_interval == 0:
            self._purge_expired()

    def lookup(
        self, channel_id: str, external_message_id: str
    ) -> Optional[SentMessageRecord]:
        """Look up a tracked message. Returns None if not found or expired."""
        key = self._key(channel_id, external_message_id)
        record = self._records.get(key)
        if record is None:
            return None

        # Check TTL
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.ttl_hours)
        if record.timestamp < cutoff:
            del self._records[key]
            return None

        return record

    def remove(self, channel_id: str, external_message_id: str) -> bool:
        """Explicitly remove a tracked message. Returns True if found."""
        key = self._key(channel_id, external_message_id)
        if key in self._records:
            del self._records[key]
            return True
        return False


# =============================================================================
# ReactionProcessor
# =============================================================================


class ReactionProcessor:
    """Processes reaction events into feedback entries.

    Channel-agnostic: accepts normalized ReactionEvents and delegates
    to FeedbackService for storage.
    """

    def __init__(
        self,
        tracker: SentMessageTracker,
        feedback_service: Any,
        reactor_identity_salt: str = "",
    ):
        self.tracker = tracker
        self.feedback_service = feedback_service
        self.reactor_identity_salt = reactor_identity_salt
        self._untracked_count: int = 0

    def hash_reactor_identity(self, channel_id: str, reactor_id: str) -> str:
        """Compute deterministic privacy-safe hash of reactor identity."""
        normalized = f"{channel_id}:{reactor_id}"
        salted = f"{self.reactor_identity_salt}{normalized}"
        return hashlib.sha256(salted.encode()).hexdigest()

    async def process(self, event: ReactionEvent) -> bool:
        """Process a reaction event into feedback.

        Returns True if feedback was stored, False if reaction was
        untracked (message not found in tracker).
        """
        record = self.tracker.lookup(event.channel_id, event.external_message_id)
        if record is None:
            self._untracked_count += 1
            logger.debug(
                "Untracked reaction dropped: channel=%s ext_id=%s (total_dropped=%d)",
                event.channel_id,
                event.external_message_id,
                self._untracked_count,
            )
            return False

        reactor_hash = self.hash_reactor_identity(event.channel_id, event.reactor_id)

        feedback_data = {
            "message_id": record.internal_message_id,
            "question": record.question,
            "answer": record.answer,
            "rating": (
                "positive" if event.rating == ReactionRating.POSITIVE else "negative"
            ),
            "channel": event.channel_id,
            "feedback_method": "reaction",
            "external_message_id": event.external_message_id,
            "reactor_identity_hash": reactor_hash,
            "reaction_emoji": event.raw_reaction,
            "sources": record.sources,
        }

        try:
            await asyncio.to_thread(self._store_feedback, feedback_data)
            return True
        except Exception:
            logger.exception(
                "Failed to store reaction feedback: channel=%s ext_id=%s",
                event.channel_id,
                event.external_message_id,
            )
            return False

    async def revoke_reaction(
        self,
        channel_id: str,
        external_message_id: str,
        reactor_id: str,
    ) -> bool:
        """Revoke a reaction (soft delete -- marks revoked, does not delete feedback).

        Returns True if revocation was processed.
        """
        reactor_hash = self.hash_reactor_identity(channel_id, reactor_id)
        try:
            if self.feedback_service and hasattr(
                self.feedback_service, "revoke_reaction_feedback"
            ):
                await asyncio.to_thread(
                    self._run_revoke,
                    channel_id,
                    external_message_id,
                    reactor_hash,
                )
                return True
            logger.debug("FeedbackService unavailable for revocation")
            return False
        except Exception:
            logger.exception(
                "Failed to revoke reaction: channel=%s ext_id=%s",
                channel_id,
                external_message_id,
            )
            return False

    def _store_feedback(self, feedback_data: Dict[str, Any]) -> None:
        """Store feedback via FeedbackService (synchronous).

        Raises RuntimeError when the service is unavailable so that
        callers (process()) can distinguish success from silent no-op.
        """
        if self.feedback_service and hasattr(
            self.feedback_service, "store_reaction_feedback"
        ):
            self.feedback_service.store_reaction_feedback(**feedback_data)
        else:
            raise RuntimeError(
                "FeedbackService not available or missing store_reaction_feedback"
            )

    def _run_revoke(
        self,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
    ) -> None:
        """Run revoke on feedback service (synchronous)."""
        self.feedback_service.revoke_reaction_feedback(
            channel=channel_id,
            external_message_id=external_message_id,
            reactor_identity_hash=reactor_hash,
        )


# =============================================================================
# ReactionHandlerBase (ABC)
# =============================================================================

# Default emoji-to-rating mapping
DEFAULT_EMOJI_MAP: Dict[str, ReactionRating] = {
    "\U0001f44d": ReactionRating.POSITIVE,  # 👍
    "\U0001f44e": ReactionRating.NEGATIVE,  # 👎
    "\u2764\ufe0f": ReactionRating.POSITIVE,  # ❤️
    "\u2764": ReactionRating.POSITIVE,  # ❤ (without variation selector)
    "\U0001f60a": ReactionRating.POSITIVE,  # 😊
    "\U0001f615": ReactionRating.NEGATIVE,  # 😕
}


class ReactionHandlerBase(ABC):
    """Base class for channel-specific reaction handlers.

    Subclasses implement transport-specific listener registration.
    """

    channel_id: str = ""

    def __init__(
        self,
        runtime: Any,
        processor: "ReactionProcessor",
        emoji_rating_map: Optional[Dict[str, ReactionRating]] = None,
    ):
        self.runtime = runtime
        self.processor = processor
        self._emoji_map = emoji_rating_map or dict(DEFAULT_EMOJI_MAP)
        self._logger = logging.getLogger(f"reaction.{self.__class__.__name__}")

    def map_emoji_to_rating(self, emoji: str) -> Optional[ReactionRating]:
        """Map an emoji to a rating. Returns None if unmapped."""
        return self._emoji_map.get(emoji)

    @abstractmethod
    async def start_listening(self) -> None:
        """Start listening for reactions on this channel."""
        ...

    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop listening for reactions on this channel."""
        ...
