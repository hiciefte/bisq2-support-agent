"""Post-processing hook enforcing channel auto-response policy."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.channels.hooks import BasePostProcessingHook, BasePreProcessingHook
from app.channels.models import GatewayError, IncomingMessage, OutgoingMessage
from app.channels.policy import (
    apply_autosend_policy,
    is_autosend_enabled,
    is_generation_enabled,
)
from app.channels.security import ErrorFactory
from app.services.channel_autoresponse_policy_service import (
    discover_supported_channels,
)

logger = logging.getLogger(__name__)


class ChannelAIGenerationPolicyHook(BasePreProcessingHook):
    """Block AI generation for channels where generation is disabled."""

    def __init__(self, policy_service: Any | None) -> None:
        super().__init__(name="channel_ai_generation_policy", priority=110)
        self.policy_service = policy_service

    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        channel_id = message.channel.value
        if channel_id not in discover_supported_channels():
            return None
        if is_generation_enabled(self.policy_service, channel_id):
            return None
        logger.info(
            "AI generation disabled for channel=%s; ignoring message_id=%s",
            channel_id,
            message.message_id,
        )
        return ErrorFactory.service_unavailable(
            "AI generation disabled for this channel"
        )


class ChannelAutoResponsePolicyHook(BasePostProcessingHook):
    """Force review-queue routing when channel auto-response is disabled."""

    def __init__(self, policy_service: Any | None) -> None:
        # Must run before escalation hook so the escalation hook can create queue entries.
        super().__init__(name="channel_autoresponse_policy", priority=150)
        self.policy_service = policy_service

    async def execute(
        self,
        incoming: IncomingMessage,
        outgoing: OutgoingMessage,
    ) -> Optional[GatewayError]:
        channel_id = incoming.channel.value
        if channel_id not in discover_supported_channels():
            return None
        if is_autosend_enabled(self.policy_service, channel_id):
            return None
        apply_autosend_policy(outgoing, autosend_enabled=False)

        logger.info(
            "Auto-response disabled for channel=%s; forcing review queue for message_id=%s",
            channel_id,
            incoming.message_id,
        )
        return None
