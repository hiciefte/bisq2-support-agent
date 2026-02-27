"""Shared conversational follow-up flow for negative reaction feedback."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.channels.models import (
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)

logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE_BY_CHANNEL: Dict[str, str] = {
    "bisq2": (
        "Thanks for the feedback. What was incorrect or missing in the previous AI "
        "answer? A short reply helps us improve."
    ),
    "matrix": (
        "Thanks for the feedback. What was incorrect or missing in the previous AI "
        "answer? Reply in this room and I will record it."
    ),
}

_ACK_TEMPLATE_BY_CHANNEL: Dict[str, str] = {
    "bisq2": "Thanks. I have recorded your clarification for quality improvement.",
    "matrix": "Thanks. I have recorded your clarification for quality improvement.",
}


@dataclass
class PendingFollowup:
    """Pending clarification request keyed by user + thread context."""

    channel_id: str
    delivery_target: str
    reactor_id: str
    reactor_identity_hash: str
    internal_message_id: str
    external_message_id: str
    created_at: datetime
    expires_at: datetime


class FeedbackFollowupCoordinator:
    """Coordinates channel-side clarification prompts for negative feedback."""

    def __init__(
        self,
        feedback_service: Any,
        *,
        channel_registry: Any | None = None,
        ttl_seconds: float = 900.0,
    ) -> None:
        self.feedback_service = feedback_service
        self.channel_registry = channel_registry
        self.ttl_seconds = max(30.0, float(ttl_seconds))
        self._pending_by_context: Dict[str, PendingFollowup] = {}
        self._context_by_reaction_key: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def start_followup(
        self,
        *,
        record: Any,
        channel_id: str,
        external_message_id: str,
        reactor_id: str,
        reactor_identity_hash: str,
    ) -> bool:
        """Register and send a clarification prompt for a negative reaction."""
        if not reactor_id:
            return False

        delivery_target = str(getattr(record, "delivery_target", "") or "").strip()
        if not delivery_target:
            return False

        context_key = self._context_key(channel_id, delivery_target, reactor_id)
        reaction_key = self._reaction_key(
            channel_id,
            external_message_id,
            reactor_identity_hash,
        )
        now = datetime.now(timezone.utc)
        pending = PendingFollowup(
            channel_id=channel_id,
            delivery_target=delivery_target,
            reactor_id=reactor_id,
            reactor_identity_hash=reactor_identity_hash,
            internal_message_id=str(
                getattr(record, "internal_message_id", "") or ""
            ).strip(),
            external_message_id=external_message_id,
            created_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )

        should_send_prompt = False
        async with self._lock:
            existing = self._pending_by_context.get(context_key)
            if existing is None or existing.external_message_id != external_message_id:
                should_send_prompt = True
            self._pending_by_context[context_key] = pending
            self._context_by_reaction_key[reaction_key] = context_key

        if not should_send_prompt:
            return True

        channel = self._resolve_channel(channel_id)
        if channel is None:
            async with self._lock:
                self._pending_by_context.pop(context_key, None)
                self._context_by_reaction_key.pop(reaction_key, None)
            return False
        prompt_text = _PROMPT_TEMPLATE_BY_CHANNEL.get(
            channel_id, _PROMPT_TEMPLATE_BY_CHANNEL["bisq2"]
        )
        sent = await self._send_system_message(
            channel=channel,
            channel_id=channel_id,
            target=delivery_target,
            user_id=reactor_id,
            text=prompt_text,
            routing_action="feedback_followup_prompt",
        )
        if not sent:
            async with self._lock:
                self._pending_by_context.pop(context_key, None)
                self._context_by_reaction_key.pop(reaction_key, None)
        return sent

    async def cancel_followup(
        self,
        *,
        record: Any,
        channel_id: str,
        external_message_id: str,
        reactor_identity_hash: str,
    ) -> None:
        """Cancel pending clarification request when sentiment reverses/removes."""
        reaction_key = self._reaction_key(
            channel_id,
            external_message_id,
            reactor_identity_hash,
        )
        async with self._lock:
            context_key = self._context_by_reaction_key.pop(reaction_key, None)
            if context_key:
                self._pending_by_context.pop(context_key, None)

    async def consume_if_pending(
        self,
        *,
        incoming: IncomingMessage,
        channel: Any,
    ) -> bool:
        """Consume user message as clarification if follow-up is pending."""
        channel_id = incoming.channel.value
        delivery_target = ""
        get_target = getattr(channel, "get_delivery_target", None)
        if callable(get_target):
            delivery_target = str(
                get_target(incoming.channel_metadata or {}) or ""
            ).strip()
        if not delivery_target:
            return False

        reactor_id = str(getattr(incoming.user, "user_id", "") or "").strip()
        if not reactor_id:
            return False

        context_key = self._context_key(channel_id, delivery_target, reactor_id)

        async with self._lock:
            pending = self._pending_by_context.get(context_key)
            if pending is None:
                return False
            if pending.expires_at <= datetime.now(timezone.utc):
                self._pending_by_context.pop(context_key, None)
                self._context_by_reaction_key.pop(
                    self._reaction_key(
                        pending.channel_id,
                        pending.external_message_id,
                        pending.reactor_identity_hash,
                    ),
                    None,
                )
                return False

        explanation = str(incoming.question or "").strip()
        if not explanation:
            return False

        issues = []
        analyze_fn = getattr(self.feedback_service, "analyze_feedback_text", None)
        if callable(analyze_fn):
            try:
                issues = await analyze_fn(explanation)
            except Exception:
                logger.debug("Failed to analyze feedback follow-up text", exc_info=True)
                issues = []

        update_fn = getattr(self.feedback_service, "update_feedback_entry", None)
        if not callable(update_fn):
            return False

        try:
            updated = await update_fn(
                message_id=pending.internal_message_id,
                explanation=explanation,
                issues=issues,
            )
        except Exception:
            logger.exception(
                "Failed to persist feedback clarification: channel=%s message_id=%s",
                channel_id,
                pending.internal_message_id,
            )
            return False

        if not updated:
            return False

        async with self._lock:
            self._pending_by_context.pop(context_key, None)
            self._context_by_reaction_key.pop(
                self._reaction_key(
                    pending.channel_id,
                    pending.external_message_id,
                    pending.reactor_identity_hash,
                ),
                None,
            )

        ack_text = _ACK_TEMPLATE_BY_CHANNEL.get(
            channel_id, _ACK_TEMPLATE_BY_CHANNEL["bisq2"]
        )
        await self._send_system_message(
            channel=channel,
            channel_id=channel_id,
            target=delivery_target,
            user_id=reactor_id,
            text=ack_text,
            routing_action="feedback_followup_ack",
            in_reply_to=incoming.message_id,
        )
        return True

    @staticmethod
    def _context_key(channel_id: str, delivery_target: str, reactor_id: str) -> str:
        return (
            f"{str(channel_id or '').strip().lower()}::"
            f"{str(delivery_target or '').strip()}::"
            f"{str(reactor_id or '').strip()}"
        )

    @staticmethod
    def _reaction_key(
        channel_id: str,
        external_message_id: str,
        reactor_identity_hash: str,
    ) -> str:
        return (
            f"{str(channel_id or '').strip().lower()}::"
            f"{str(external_message_id or '').strip()}::"
            f"{str(reactor_identity_hash or '').strip()}"
        )

    def _resolve_channel(self, channel_id: str) -> Optional[Any]:
        registry = self.channel_registry
        if registry is None:
            return None
        getter = getattr(registry, "get", None)
        if not callable(getter):
            return None
        try:
            return getter(channel_id)
        except Exception:
            logger.debug(
                "Failed to resolve channel adapter for follow-up: channel=%s",
                channel_id,
                exc_info=True,
            )
            return None

    async def _send_system_message(
        self,
        *,
        channel: Any,
        channel_id: str,
        target: str,
        user_id: str,
        text: str,
        routing_action: str,
        in_reply_to: str = "",
    ) -> bool:
        channel_type = self._channel_type_from_id(channel_id)
        message = OutgoingMessage(
            message_id=str(uuid.uuid4()),
            in_reply_to=str(in_reply_to or ""),
            channel=channel_type,
            answer=text,
            sources=[],
            user=UserContext(
                user_id=user_id,
                channel_user_id=user_id,
            ),
            metadata=ResponseMetadata(
                processing_time_ms=0.0,
                rag_strategy="feedback_followup",
                model_name="system",
                tokens_used=None,
                confidence_score=None,
                routing_action=routing_action,
                routing_reason="reaction_feedback_followup",
                detected_version=None,
                version_confidence=None,
                hooks_executed=[],
            ),
            original_question="",
            suggested_questions=None,
            requires_human=False,
        )
        try:
            return bool(await channel.send_message(target, message))
        except Exception:
            logger.exception(
                "Failed to send feedback follow-up system message: channel=%s target=%s",
                channel_id,
                target,
            )
            return False

    @staticmethod
    def _channel_type_from_id(channel_id: str) -> ChannelType:
        normalized = str(channel_id or "").strip().lower()
        if normalized == "matrix":
            return ChannelType.MATRIX
        if normalized == "bisq2":
            return ChannelType.BISQ2
        return ChannelType.WEB
