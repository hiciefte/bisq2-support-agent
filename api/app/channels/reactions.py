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
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from contextlib import suppress
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
    in_reply_to: Optional[str] = None
    delivery_target: Optional[str] = None


@dataclass
class _ReactionAggregate:
    """In-memory active reaction set for one user/message key."""

    ratings_by_token: Dict[str, ReactionRating]

    def add(self, token: str, rating: ReactionRating) -> None:
        self.ratings_by_token[token] = rating

    def remove(self, token: str) -> None:
        self.ratings_by_token.pop(token, None)

    def clear(self) -> None:
        self.ratings_by_token.clear()

    def is_empty(self) -> bool:
        return not self.ratings_by_token

    def effective_rating(self) -> Optional[ReactionRating]:
        if not self.ratings_by_token:
            return None
        distinct = set(self.ratings_by_token.values())
        if len(distinct) == 1:
            return next(iter(distinct))
        return None

    def representative_token(self) -> str:
        if not self.ratings_by_token:
            return ""
        return sorted(self.ratings_by_token.keys())[0]


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
        in_reply_to: Optional[str] = None,
        delivery_target: Optional[str] = None,
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
            in_reply_to=in_reply_to,
            delivery_target=delivery_target,
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
    _ESCALATION_MESSAGE_PATTERN = re.compile(r"^escalation-(\d+)$")
    _IGNORED_ROUTING_ACTIONS = frozenset(
        {"escalation_notice", "feedback_followup_prompt", "feedback_followup_ack"}
    )

    def __init__(
        self,
        tracker: SentMessageTracker,
        feedback_service: Any,
        reactor_identity_salt: str = "",
        escalation_service: Any = None,
        auto_escalation_delay_seconds: float = 0.0,
        followup_coordinator: Any = None,
    ):
        self.tracker = tracker
        self.feedback_service = feedback_service
        self.reactor_identity_salt = reactor_identity_salt
        self.escalation_service = escalation_service
        self.followup_coordinator = followup_coordinator
        self.auto_escalation_delay_seconds = max(
            0.0, float(auto_escalation_delay_seconds)
        )
        self._untracked_count: int = 0
        # Debounced learning trigger
        self._learning_cooldown_seconds: float = 5.0
        self._last_learning_trigger: float = 0.0
        self._learning_lock: asyncio.Lock = asyncio.Lock()
        self._pending_auto_escalations: Dict[str, asyncio.Task] = {}
        self._pending_auto_escalations_lock: asyncio.Lock = asyncio.Lock()
        self._active_reactions: Dict[str, _ReactionAggregate] = {}
        self._active_reactions_lock: asyncio.Lock = asyncio.Lock()

    def hash_reactor_identity(self, channel_id: str, reactor_id: str) -> str:
        """Compute deterministic privacy-safe hash of reactor identity."""
        normalized = f"{channel_id}:{reactor_id}"
        salted = f"{self.reactor_identity_salt}{normalized}"
        return hashlib.sha256(salted.encode()).hexdigest()

    @staticmethod
    def _normalize_identity(identity: Any) -> str:
        return str(identity or "").strip()

    def _is_original_asker_reaction(
        self, record: SentMessageRecord, reactor_id: str
    ) -> bool:
        """Return True when the reaction author matches the original asker."""
        record_user_id = self._normalize_identity(record.user_id)
        reactor_user_id = self._normalize_identity(reactor_id)
        if not record_user_id or not reactor_user_id:
            return False
        return record_user_id == reactor_user_id

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

        if not self._is_original_asker_reaction(record, event.reactor_id):
            logger.debug(
                "Ignoring reaction from non-asker: channel=%s ext_id=%s reactor=%s asker=%s",
                event.channel_id,
                event.external_message_id,
                self._normalize_identity(event.reactor_id),
                self._normalize_identity(record.user_id),
            )
            return ProcessResult(success=False)

        if self._should_ignore_record(record):
            logger.debug(
                "Ignoring reaction for non-learning routing_action=%s ext_id=%s",
                str(record.routing_action or "").strip(),
                event.external_message_id,
            )
            return ProcessResult(success=False)

        reactor_hash = self.hash_reactor_identity(event.channel_id, event.reactor_id)
        aggregate = await self._apply_add_reaction(event, reactor_hash)
        effective_rating = aggregate.effective_rating()
        if effective_rating is None:
            await self._clear_reaction_projection(
                event.channel_id,
                event.external_message_id,
                reactor_hash,
            )
            await self._cancel_pending_auto_escalation(
                event.channel_id,
                event.external_message_id,
                reactor_hash,
            )
            await self._cancel_feedback_followup(
                record=record,
                channel_id=event.channel_id,
                external_message_id=event.external_message_id,
                reactor_hash=reactor_hash,
            )
            await self._trigger_learning()
            return ProcessResult(success=True)

        feedback_data = {
            "message_id": record.internal_message_id,
            "question": record.question,
            "answer": record.answer,
            "rating": (
                "positive"
                if effective_rating == ReactionRating.POSITIVE
                else "negative"
            ),
            "channel": event.channel_id,
            "feedback_method": "reaction",
            "external_message_id": event.external_message_id,
            "reactor_identity_hash": reactor_hash,
            "reaction_emoji": aggregate.representative_token(),
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

        # Route staff-response reactions into escalation rating/orchestration path.
        await self._record_staff_response_rating(record, event, reactor_hash)

        # Auto-escalation: negative reaction on high-confidence auto-sent message
        escalation_created = False
        escalation_message_id = None
        if self.escalation_service is not None:
            if (
                effective_rating == ReactionRating.NEGATIVE
                and self._should_auto_escalate(record)
            ):
                (
                    escalation_created,
                    escalation_message_id,
                ) = await self._handle_negative_reaction(
                    record=record,
                    event=event,
                    reactor_hash=reactor_hash,
                )
            else:
                await self._cancel_pending_auto_escalation(
                    event.channel_id, event.external_message_id, reactor_hash
                )
                if (
                    effective_rating == ReactionRating.POSITIVE
                    and self._should_auto_escalate(record)
                ):
                    await self._try_auto_close_reversed_escalation(
                        record, reason="reaction_changed_to_positive"
                    )

        if effective_rating == ReactionRating.NEGATIVE:
            await self._maybe_start_feedback_followup(
                record=record,
                event=event,
                reactor_hash=reactor_hash,
            )
        else:
            await self._cancel_feedback_followup(
                record=record,
                channel_id=event.channel_id,
                external_message_id=event.external_message_id,
                reactor_hash=reactor_hash,
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
        if self._is_staff_response_record(record):
            return False  # Staff responses are rated; do not auto-escalate.
        if record.confidence_score is None:
            return False
        return record.confidence_score >= self._AUTO_ESCALATION_CONFIDENCE_THRESHOLD

    def _should_ignore_record(self, record: SentMessageRecord) -> bool:
        routing_action = str(record.routing_action or "").strip().lower()
        return routing_action in self._IGNORED_ROUTING_ACTIONS

    def _is_staff_response_record(self, record: SentMessageRecord) -> bool:
        routing_action = str(record.routing_action or "").strip().lower()
        if routing_action == "staff_response":
            return True
        return self._extract_escalation_id(record.internal_message_id) is not None

    def _extract_escalation_id(self, internal_message_id: str) -> Optional[int]:
        match = self._ESCALATION_MESSAGE_PATTERN.match(str(internal_message_id or ""))
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    async def _resolve_staff_response_escalation(
        self, record: SentMessageRecord
    ) -> Optional[Any]:
        if self.escalation_service is None:
            return None

        repository = getattr(self.escalation_service, "repository", None)
        if repository is None:
            return None

        escalation_id = self._extract_escalation_id(record.internal_message_id)
        if escalation_id is not None and hasattr(repository, "get_by_id"):
            try:
                escalation = await repository.get_by_id(escalation_id)
                if escalation is not None:
                    return escalation
            except Exception:
                logger.debug(
                    "Failed to lookup escalation by id=%s for internal_message_id=%s",
                    escalation_id,
                    record.internal_message_id,
                    exc_info=True,
                )

        reply_message_id = str(record.in_reply_to or "").strip()
        if reply_message_id and hasattr(repository, "get_by_message_id"):
            try:
                escalation = await repository.get_by_message_id(reply_message_id)
                if escalation is not None:
                    return escalation
            except Exception:
                logger.debug(
                    "Failed to lookup escalation by message_id=%s",
                    reply_message_id,
                    exc_info=True,
                )

        return None

    async def _record_staff_response_rating(
        self,
        record: SentMessageRecord,
        event: ReactionEvent,
        reactor_hash: str,
    ) -> None:
        if not self._is_staff_response_record(record):
            return

        escalation = await self._resolve_staff_response_escalation(record)
        if escalation is None:
            return

        rating = int(event.rating)
        escalation_user_id = str(getattr(escalation, "user_id", "") or "").strip()
        trusted = bool(
            escalation_user_id
            and escalation_user_id == str(event.reactor_id or "").strip()
        )

        record_rating = getattr(
            self.escalation_service, "record_staff_answer_rating", None
        )
        if not callable(record_rating):
            logger.debug("Escalation service has no record_staff_answer_rating method")
            return

        try:
            await record_rating(
                escalation=escalation,
                rating=rating,
                rater_id=reactor_hash,
                trusted=trusted,
            )
        except Exception:
            logger.exception(
                "Failed to record staff response rating for escalation_id=%s",
                getattr(escalation, "id", "unknown"),
            )

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
                    "auto_reaction_negative:"
                    f"user_reported_incorrect(confidence={conf:.0%})"
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

    def _reaction_key(
        self,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
    ) -> str:
        return f"{channel_id}:{external_message_id}:{reactor_hash}"

    async def _cancel_pending_auto_escalation(
        self,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
    ) -> None:
        key = self._reaction_key(channel_id, external_message_id, reactor_hash)
        task: Optional[asyncio.Task] = None
        async with self._pending_auto_escalations_lock:
            task = self._pending_auto_escalations.pop(key, None)

        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _handle_negative_reaction(
        self,
        record: SentMessageRecord,
        event: ReactionEvent,
        reactor_hash: str,
    ) -> tuple[bool, Optional[str]]:
        delay = self.auto_escalation_delay_seconds
        if delay <= 0.0:
            return await self._try_auto_escalate(record, event)

        key = self._reaction_key(
            event.channel_id, event.external_message_id, reactor_hash
        )
        await self._cancel_pending_auto_escalation(
            event.channel_id,
            event.external_message_id,
            reactor_hash,
        )
        task = asyncio.create_task(
            self._run_delayed_auto_escalation(
                key=key,
                record=record,
                event=event,
                reactor_hash=reactor_hash,
                delay_seconds=delay,
            )
        )
        async with self._pending_auto_escalations_lock:
            self._pending_auto_escalations[key] = task
        return False, None

    async def _run_delayed_auto_escalation(
        self,
        key: str,
        record: SentMessageRecord,
        event: ReactionEvent,
        reactor_hash: str,
        delay_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(delay_seconds)
            if not await self._is_current_reaction_negative(
                channel_id=event.channel_id,
                external_message_id=event.external_message_id,
                reactor_hash=reactor_hash,
            ):
                return
            if not self._should_auto_escalate(record):
                return
            await self._try_auto_escalate(record, event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Delayed auto-escalation task failed: channel=%s ext_id=%s",
                event.channel_id,
                event.external_message_id,
            )
        finally:
            async with self._pending_auto_escalations_lock:
                task = self._pending_auto_escalations.get(key)
                if task is asyncio.current_task():
                    self._pending_auto_escalations.pop(key, None)

    async def _is_current_reaction_negative(
        self,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
    ) -> bool:
        if self.feedback_service is None:
            return False
        getter = getattr(self.feedback_service, "get_active_reaction_rating", None)
        if not callable(getter):
            # Missing state introspection support: fail-safe to prevent false escalations.
            return False
        try:
            rating = await asyncio.to_thread(
                getter,
                channel_id,
                external_message_id,
                reactor_hash,
            )
            return rating == int(ReactionRating.NEGATIVE)
        except Exception:
            logger.exception(
                "Failed to read active reaction state: channel=%s ext_id=%s",
                channel_id,
                external_message_id,
            )
            return False

    async def _try_auto_close_reversed_escalation(
        self,
        record: SentMessageRecord,
        reason: str,
    ) -> None:
        if self.escalation_service is None:
            return
        close_fn = getattr(
            self.escalation_service,
            "auto_close_reaction_escalation",
            None,
        )
        if not callable(close_fn):
            return
        try:
            await close_fn(
                message_id=record.internal_message_id,
                reason=reason,
            )
        except Exception:
            logger.warning(
                "Auto-close failed (non-fatal): message_id=%s",
                record.internal_message_id,
                exc_info=True,
            )

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
        raw_reaction: Optional[str] = None,
    ) -> bool:
        """Revoke a reaction (soft delete -- marks revoked, does not delete feedback).

        Returns True if revocation was processed.
        """
        record = self.tracker.lookup(channel_id, external_message_id)
        if record is None:
            logger.debug(
                "Untracked reaction revoke dropped: channel=%s ext_id=%s",
                channel_id,
                external_message_id,
            )
            return False
        if not self._is_original_asker_reaction(record, reactor_id):
            logger.debug(
                "Ignoring revoke from non-asker: channel=%s ext_id=%s reactor=%s asker=%s",
                channel_id,
                external_message_id,
                self._normalize_identity(reactor_id),
                self._normalize_identity(record.user_id),
            )
            return False

        reactor_hash = self.hash_reactor_identity(channel_id, reactor_id)
        try:
            aggregate = await self._apply_remove_reaction(
                channel_id=channel_id,
                external_message_id=external_message_id,
                reactor_hash=reactor_hash,
                raw_reaction=raw_reaction,
            )
            effective_rating = aggregate.effective_rating() if aggregate else None

            await self._cancel_pending_auto_escalation(
                channel_id,
                external_message_id,
                reactor_hash,
            )
            await self._cancel_feedback_followup(
                record=record,
                channel_id=channel_id,
                external_message_id=external_message_id,
                reactor_hash=reactor_hash,
            )

            if effective_rating is None:
                if self.feedback_service and hasattr(
                    self.feedback_service, "revoke_reaction_feedback"
                ):
                    await asyncio.to_thread(
                        self._run_revoke,
                        channel_id,
                        external_message_id,
                        reactor_hash,
                    )
                    if record is not None and self._should_auto_escalate(record):
                        await self._try_auto_close_reversed_escalation(
                            record,
                            reason="reaction_removed",
                        )
                    await self._trigger_learning()
                    return True
                logger.debug("FeedbackService unavailable for revocation")
                return False

            feedback_data = {
                "message_id": record.internal_message_id,
                "question": record.question,
                "answer": record.answer,
                "rating": (
                    "positive"
                    if effective_rating == ReactionRating.POSITIVE
                    else "negative"
                ),
                "channel": channel_id,
                "feedback_method": "reaction",
                "external_message_id": external_message_id,
                "reactor_identity_hash": reactor_hash,
                "reaction_emoji": aggregate.representative_token() if aggregate else "",
                "sources": record.sources,
            }
            await asyncio.to_thread(self._store_feedback, feedback_data)

            synthetic_event = ReactionEvent(
                channel_id=channel_id,
                external_message_id=external_message_id,
                reactor_id=reactor_id,
                rating=effective_rating,
                raw_reaction=aggregate.representative_token() if aggregate else "",
                timestamp=datetime.now(timezone.utc),
            )
            if self.escalation_service is not None and self._should_auto_escalate(
                record
            ):
                if effective_rating == ReactionRating.NEGATIVE:
                    await self._handle_negative_reaction(
                        record=record,
                        event=synthetic_event,
                        reactor_hash=reactor_hash,
                    )
                else:
                    await self._cancel_pending_auto_escalation(
                        channel_id,
                        external_message_id,
                        reactor_hash,
                    )
                    await self._try_auto_close_reversed_escalation(
                        record,
                        reason="reaction_changed_to_positive",
                    )

            if effective_rating == ReactionRating.NEGATIVE:
                await self._maybe_start_feedback_followup(
                    record=record,
                    event=synthetic_event,
                    reactor_hash=reactor_hash,
                )
            else:
                await self._cancel_feedback_followup(
                    record=record,
                    channel_id=channel_id,
                    external_message_id=external_message_id,
                    reactor_hash=reactor_hash,
                )

            await self._trigger_learning()
            return True
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

    def _reaction_token(self, raw_reaction: Any) -> str:
        return str(raw_reaction or "").strip().upper()

    async def _apply_add_reaction(
        self, event: ReactionEvent, reactor_hash: str
    ) -> _ReactionAggregate:
        key = self._reaction_key(
            event.channel_id,
            event.external_message_id,
            reactor_hash,
        )
        token = self._reaction_token(event.raw_reaction)
        if not token:
            token = f"__RATING__{int(event.rating)}"
        async with self._active_reactions_lock:
            aggregate = self._active_reactions.get(key)
            if aggregate is None:
                aggregate = _ReactionAggregate(ratings_by_token={})
                self._active_reactions[key] = aggregate
            aggregate.add(token, event.rating)
            return aggregate

    async def _apply_remove_reaction(
        self,
        *,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
        raw_reaction: Optional[str],
    ) -> Optional[_ReactionAggregate]:
        key = self._reaction_key(channel_id, external_message_id, reactor_hash)
        token = self._reaction_token(raw_reaction)
        async with self._active_reactions_lock:
            aggregate = self._active_reactions.get(key)
            if aggregate is None:
                return None
            if token:
                aggregate.remove(token)
            else:
                aggregate.clear()
            if aggregate.is_empty():
                self._active_reactions.pop(key, None)
                return None
            return aggregate

    async def _clear_reaction_projection(
        self,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
    ) -> None:
        if self.feedback_service is None or not hasattr(
            self.feedback_service, "revoke_reaction_feedback"
        ):
            return
        try:
            await asyncio.to_thread(
                self._run_revoke,
                channel_id,
                external_message_id,
                reactor_hash,
            )
        except Exception:
            logger.exception(
                "Failed to clear reaction projection: channel=%s ext_id=%s",
                channel_id,
                external_message_id,
            )

    async def _maybe_start_feedback_followup(
        self,
        *,
        record: SentMessageRecord,
        event: ReactionEvent,
        reactor_hash: str,
    ) -> None:
        coordinator = self.followup_coordinator
        if coordinator is None:
            return
        start_fn = getattr(coordinator, "start_followup", None)
        if not callable(start_fn):
            return
        try:
            await start_fn(
                record=record,
                channel_id=event.channel_id,
                external_message_id=event.external_message_id,
                reactor_id=self._normalize_identity(event.reactor_id),
                reactor_identity_hash=reactor_hash,
            )
        except Exception:
            logger.exception(
                "Failed to start feedback follow-up: channel=%s ext_id=%s",
                event.channel_id,
                event.external_message_id,
            )

    async def _cancel_feedback_followup(
        self,
        *,
        record: SentMessageRecord,
        channel_id: str,
        external_message_id: str,
        reactor_hash: str,
    ) -> None:
        coordinator = self.followup_coordinator
        if coordinator is None:
            return
        cancel_fn = getattr(coordinator, "cancel_followup", None)
        if not callable(cancel_fn):
            return
        try:
            await cancel_fn(
                record=record,
                channel_id=channel_id,
                external_message_id=external_message_id,
                reactor_identity_hash=reactor_hash,
            )
        except Exception:
            logger.exception(
                "Failed to cancel feedback follow-up: channel=%s ext_id=%s",
                channel_id,
                external_message_id,
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
    "\U0001f604": ReactionRating.POSITIVE,  # 😄
    "\U0001f389": ReactionRating.POSITIVE,  # 🎉
    "\U0001f680": ReactionRating.POSITIVE,  # 🚀
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
        self._normalized_emoji_map: Dict[str, ReactionRating] = {}
        for token, rating in self._emoji_map.items():
            normalized = self._normalize_reaction_token(token)
            if normalized:
                self._normalized_emoji_map[normalized] = rating
        self._logger = logging.getLogger(f"reaction.{self.__class__.__name__}")

    def map_emoji_to_rating(self, emoji: str) -> Optional[ReactionRating]:
        """Map an emoji to a rating. Returns None if unmapped."""
        if emoji in self._emoji_map:
            return self._emoji_map.get(emoji)
        normalized = self._normalize_reaction_token(emoji)
        if not normalized:
            return None
        return self._normalized_emoji_map.get(normalized)

    @staticmethod
    def _normalize_reaction_token(token: Any) -> str:
        """Normalize reaction tokens across emoji variants and enum-like names."""
        value = str(token or "").strip()
        if not value:
            return ""

        normalized = unicodedata.normalize("NFKC", value)
        # Matrix emoji keys may include variation selectors or skin tone modifiers.
        normalized = normalized.replace("\ufe0f", "").replace("\ufe0e", "")
        normalized = "".join(
            ch for ch in normalized if not ("\U0001f3fb" <= ch <= "\U0001f3ff")
        )
        return normalized.upper() if normalized.isascii() else normalized

    @abstractmethod
    async def start_listening(self) -> None:
        """Start listening for reactions on this channel."""
        ...

    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop listening for reactions on this channel."""
        ...
