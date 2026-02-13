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
import time
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
    confidence_score: Optional[float] = None
    requires_human: Optional[bool] = None
    routing_action: Optional[str] = None


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
        confidence_score: Optional[float] = None,
        requires_human: Optional[bool] = None,
        routing_action: Optional[str] = None,
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
            confidence_score=confidence_score,
            requires_human=requires_human,
            routing_action=routing_action,
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


@dataclass
class ProcessResult:
    """Result of processing a reaction event."""

    success: bool
    escalation_created: bool = False
    escalation_message_id: Optional[str] = None

    def __bool__(self) -> bool:
        """Backward-compat: old callers checked ``if result:``."""
        return self.success


class ReactionProcessor:
    """Processes reaction events into feedback entries.

    Channel-agnostic: accepts normalized ReactionEvents and delegates
    to FeedbackService for storage.
    """

    # Minimum confidence for auto-escalation on negative reaction
    _AUTO_ESCALATION_CONFIDENCE_THRESHOLD: float = 0.70

    def __init__(
        self,
        tracker: SentMessageTracker,
        feedback_service: Any,
        reactor_identity_salt: str = "",
        escalation_service: Any = None,
    ):
        self.tracker = tracker
        self.feedback_service = feedback_service
        self.reactor_identity_salt = reactor_identity_salt
        self.escalation_service = escalation_service
        self._untracked_count: int = 0
        # Debounced learning trigger
        self._learning_cooldown_seconds: float = 5.0
        self._last_learning_trigger: float = 0.0
        self._learning_lock: asyncio.Lock = asyncio.Lock()

    def hash_reactor_identity(self, channel_id: str, reactor_id: str) -> str:
        """Compute deterministic privacy-safe hash of reactor identity."""
        normalized = f"{channel_id}:{reactor_id}"
        salted = f"{self.reactor_identity_salt}{normalized}"
        return hashlib.sha256(salted.encode()).hexdigest()

    async def process(self, event: ReactionEvent) -> ProcessResult:
        """Process a reaction event into feedback.

        Returns ProcessResult (truthy if feedback stored, falsy otherwise).
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
            return ProcessResult(success=False)

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
        except Exception:
            logger.exception(
                "Failed to store reaction feedback: channel=%s ext_id=%s",
                event.channel_id,
                event.external_message_id,
            )
            return ProcessResult(success=False)

        # Auto-escalation: negative reaction on high-confidence auto-sent message
        escalation_created = False
        escalation_message_id = None
        if (
            event.rating == ReactionRating.NEGATIVE
            and self.escalation_service is not None
            and self._should_auto_escalate(record)
        ):
            escalation_created, escalation_message_id = await self._try_auto_escalate(
                record, event
            )

        # Trigger learning after successful storage (best-effort, debounced)
        await self._trigger_learning()
        return ProcessResult(
            success=True,
            escalation_created=escalation_created,
            escalation_message_id=escalation_message_id,
        )

    def _should_auto_escalate(self, record: SentMessageRecord) -> bool:
        """Check whether a negative reaction warrants auto-escalation."""
        if record.requires_human:
            return False  # Already escalated via normal pipeline
        if record.confidence_score is None:
            return False
        return record.confidence_score >= self._AUTO_ESCALATION_CONFIDENCE_THRESHOLD

    async def _try_auto_escalate(
        self, record: SentMessageRecord, event: ReactionEvent
    ) -> tuple:
        """Attempt to create an escalation. Returns (created, message_id)."""
        try:
            from app.models.escalation import EscalationCreate

            conf = record.confidence_score or 0.0
            data = EscalationCreate(
                message_id=record.internal_message_id,
                channel=record.channel_id,
                user_id=record.user_id,
                username=record.user_id,
                question=record.question,
                ai_draft_answer=record.answer,
                confidence_score=conf,
                routing_action=record.routing_action or "auto_send",
                routing_reason=(
                    f"User reported incorrect answer " f"(confidence={conf:.0%})"
                ),
                sources=record.sources,
            )
            await self.escalation_service.create_escalation(data)
            logger.info(
                "Auto-escalation created for negative reaction: ext_id=%s conf=%.2f",
                event.external_message_id,
                conf,
            )
            return True, event.external_message_id
        except Exception:
            logger.warning(
                "Auto-escalation failed (non-fatal): ext_id=%s",
                event.external_message_id,
                exc_info=True,
            )
            return False, None

    async def _trigger_learning(self) -> None:
        """Trigger feedback weight recalculation with debounce.

        Uses a cooldown window to prevent rapid-fire recalculations when
        multiple reactions arrive in quick succession.
        """
        now = time.monotonic()
        if now - self._last_learning_trigger < self._learning_cooldown_seconds:
            return  # Within cooldown window

        async with self._learning_lock:
            # Double-check under lock
            if now - self._last_learning_trigger < self._learning_cooldown_seconds:
                return
            try:
                if hasattr(self.feedback_service, "apply_feedback_weights_async"):
                    await self.feedback_service.apply_feedback_weights_async()
                    self._last_learning_trigger = time.monotonic()
            except Exception as e:
                logger.warning("Learning trigger failed (non-fatal): %s", e)

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
