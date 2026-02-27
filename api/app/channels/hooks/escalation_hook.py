"""Escalation post-processing hook.

Creates escalations when a response should be queued for review
(`needs_human` or `queue_medium`),
replacing the AI answer with a channel-appropriate escalation message.
"""

import logging
from typing import Optional

from app.channels.hooks import BasePostProcessingHook, HookPriority
from app.channels.models import GatewayError, IncomingMessage, OutgoingMessage
from app.channels.response_dispatcher import (
    ChannelResponseDispatcher,
    format_escalation_notice,
)
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


class EscalationPostHook(BasePostProcessingHook):
    """PostProcessingHook that creates escalations for review-routed answers.

    Priority: HookPriority.NORMAL (200) — runs after PII filtering, before metrics.

    Behavior:
    - auto_send: pass through (return None)
    - queue_medium / needs_human / requires_human=True: create escalation, replace answer
    - Delegates message formatting to adapter.format_escalation_message()
    """

    def __init__(self, escalation_service, channel_registry, settings=None):
        super().__init__(name="escalation", priority=HookPriority.NORMAL)
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

        if not ChannelResponseDispatcher.should_create_escalation(outgoing):
            return None

        channel = incoming.channel.value
        try:
            dispatcher = ChannelResponseDispatcher(
                channel=None,
                channel_id=channel,
                escalation_service=self.escalation_service,
            )
            escalation = await dispatcher.create_escalation_for_review(
                incoming, outgoing
            )
            if escalation is None:
                return None
            # Web chat and escalation polling expect this flag for pending-review states.
            outgoing.requires_human = True
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

    def _replace_answer(self, incoming, outgoing, escalation_id: int):
        """Replace outgoing.answer with channel-specific escalation message."""
        username = incoming.user.channel_user_id or incoming.user.user_id
        outgoing.answer = format_escalation_notice(
            channel_id=incoming.channel.value,
            username=username,
            escalation_id=escalation_id,
            support_handle="support",
            channel=None,
            channel_registry=self.channel_registry,
        )
