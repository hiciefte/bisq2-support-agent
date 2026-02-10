"""Escalation post-processing hook.

Creates escalations when outgoing.requires_human is True,
replacing the AI answer with a channel-appropriate escalation message.
"""

import logging
from typing import Optional

from app.channels.hooks import BasePostProcessingHook, HookPriority
from app.channels.models import GatewayError, IncomingMessage, OutgoingMessage
from app.models.escalation import EscalationCreate
from prometheus_client import Counter

logger = logging.getLogger(__name__)

ESCALATION_CREATED = Counter(
    "escalation_created_total",
    "Total escalations created",
    ["channel"],
)
ESCALATION_HOOK_ERRORS = Counter(
    "escalation_hook_errors_total",
    "Errors during escalation hook execution",
    ["channel"],
)

_GENERIC_ESCALATION_MSG = (
    "Your question has been forwarded to our support team. "
    "A staff member will review and respond shortly. "
    "(Reference: #{escalation_id})"
)


class EscalationPostHook(BasePostProcessingHook):
    """PostProcessingHook that creates escalations for low-confidence answers.

    Priority: HookPriority.HIGH (100) — runs before metrics.

    Behavior:
    - requires_human=False: pass through (return None)
    - requires_human=True: create escalation, replace answer
    - Delegates message formatting to adapter.format_escalation_message()
    """

    def __init__(self, escalation_service, channel_registry, settings=None):
        super().__init__(name="escalation", priority=HookPriority.HIGH)
        self.escalation_service = escalation_service
        self.channel_registry = channel_registry
        self._settings = settings

    def _is_enabled(self) -> bool:
        """Check ESCALATION_ENABLED feature flag."""
        if self._settings is None:
            return True
        return getattr(self._settings, "ESCALATION_ENABLED", True)

    async def execute(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage
    ) -> Optional[GatewayError]:
        if not self._is_enabled():
            return None

        if not outgoing.requires_human:
            return None

        channel = incoming.channel.value
        try:
            escalation = await self._create_escalation(incoming, outgoing)
            self._replace_answer(incoming, outgoing, escalation.id)
            ESCALATION_CREATED.labels(channel=channel).inc()
            logger.info(
                "Escalation created",
                extra={
                    "escalation_id": escalation.id,
                    "channel": channel,
                    "message_id": incoming.message_id,
                },
            )
        except Exception:
            ESCALATION_HOOK_ERRORS.labels(channel=channel).inc()
            logger.exception(
                "Failed to create escalation for message %s", incoming.message_id
            )
            # Don't block the pipeline — original answer survives

        return None

    async def _create_escalation(self, incoming, outgoing):
        """Build EscalationCreate and persist via service."""
        confidence = getattr(outgoing.metadata, "confidence_score", None) or 0.0
        routing_action = (
            getattr(outgoing.metadata, "routing_action", None) or "needs_human"
        )
        sources = (
            [s.model_dump() for s in outgoing.sources] if outgoing.sources else None
        )

        data = EscalationCreate(
            message_id=incoming.message_id,
            channel=incoming.channel.value,
            user_id=incoming.user.user_id,
            username=incoming.user.channel_user_id or incoming.user.user_id,
            channel_metadata=incoming.channel_metadata or None,
            question=incoming.question,
            ai_draft_answer=outgoing.answer,
            confidence_score=confidence,
            routing_action=routing_action,
            sources=sources,
        )
        return await self.escalation_service.create_escalation(data)

    def _replace_answer(self, incoming, outgoing, escalation_id: int):
        """Replace outgoing.answer with channel-specific escalation message."""
        adapter = self.channel_registry.get(incoming.channel.value)
        if adapter is not None:
            username = incoming.user.channel_user_id or incoming.user.user_id
            support_handle = "support"
            outgoing.answer = adapter.format_escalation_message(
                username=username,
                escalation_id=escalation_id,
                support_handle=support_handle,
            )
        else:
            logger.warning(
                "No adapter found for channel %s, using generic message",
                incoming.channel.value,
            )
            outgoing.answer = _GENERIC_ESCALATION_MSG.format(
                escalation_id=escalation_id
            )
