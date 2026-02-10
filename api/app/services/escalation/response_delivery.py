"""Response delivery service for escalation pipeline.

Routes staff responses to the correct channel adapter.
"""

import logging
from typing import Any

from app.channels.models import (
    ChannelType,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)
from app.models.escalation import Escalation

logger = logging.getLogger(__name__)


class ResponseDelivery:
    """Routes staff responses to the correct channel adapter."""

    def __init__(self, channel_registry: Any) -> None:
        """Initialize response delivery service.

        Args:
            channel_registry: ChannelRegistry instance with get(channel_id) method
        """
        self.channel_registry = channel_registry

    async def deliver(self, escalation: Escalation, staff_answer: str) -> bool:
        """Deliver staff response to user's original channel.

        Args:
            escalation: Escalation record with routing information
            staff_answer: Staff's response to deliver

        Returns:
            True if delivered (or web channel, which uses polling).
            False if delivery failed. Does NOT raise exceptions.
        """
        # Web channel uses polling, no push needed
        if escalation.channel == "web":
            logger.info(
                f"Escalation {escalation.id}: Web channel, response available via polling"
            )
            return True

        # Look up channel adapter
        adapter = self.channel_registry.get(escalation.channel)
        if not adapter:
            logger.warning(
                f"Escalation {escalation.id}: No adapter found for channel '{escalation.channel}'"
            )
            return False

        try:
            # Get delivery target from metadata
            metadata = escalation.channel_metadata or {}
            target = adapter.get_delivery_target(metadata)

            # Build outgoing message
            outgoing_msg = OutgoingMessage(
                message_id=f"escalation-{escalation.id}",
                channel=ChannelType(escalation.channel),
                answer=staff_answer,
                user=UserContext(
                    user_id=escalation.user_id,
                    session_id=None,
                    channel_user_id=None,
                    auth_token=None,
                ),
                in_reply_to=escalation.message_id,
                original_question=escalation.question,
                metadata=ResponseMetadata(
                    processing_time_ms=0.0,
                    rag_strategy="escalation",
                    model_name="staff",
                    confidence_score=None,
                    version_confidence=None,
                ),
            )

            # Send via adapter
            success = await adapter.send_message(target, outgoing_msg)

            if success:
                logger.info(
                    f"Escalation {escalation.id}: Delivered to {escalation.channel} channel"
                )
            else:
                logger.warning(
                    f"Escalation {escalation.id}: Failed to deliver to {escalation.channel} channel"
                )

            return success

        except Exception as e:
            logger.exception(
                f"Escalation {escalation.id}: Exception during delivery to {escalation.channel}: {e}"
            )
            return False
