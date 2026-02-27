"""Response delivery service for escalation pipeline.

Routes staff responses to the correct channel adapter.
"""

import logging
import re
from typing import Any

from app.channels.models import (
    ChannelType,
    DocumentReference,
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
            include_ai_provenance = _answers_match(
                escalation.ai_draft_answer,
                staff_answer,
            )
            sources = (
                _coerce_sources(escalation.sources) if include_ai_provenance else []
            )
            confidence_score = (
                escalation.confidence_score if include_ai_provenance else None
            )

            # Build outgoing message
            outgoing_msg = OutgoingMessage(
                message_id=f"escalation-{escalation.id}",
                channel=ChannelType(escalation.channel),
                answer=staff_answer,
                sources=sources,
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
                    confidence_score=confidence_score,
                    routing_action="staff_response",
                    routing_reason="staff_response_delivery",
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


def _answers_match(draft_answer: str, staff_answer: str) -> bool:
    """Treat harmless whitespace differences as equivalent acceptance."""
    return _normalize_for_compare(draft_answer) == _normalize_for_compare(staff_answer)


def _normalize_for_compare(text: str) -> str:
    normalized = (text or "").strip().lower()
    return re.sub(r"\s+", " ", normalized)


def _coerce_sources(raw_sources: Any) -> list[DocumentReference]:
    if not isinstance(raw_sources, list):
        return []
    parsed: list[DocumentReference] = []
    for raw_source in raw_sources:
        if isinstance(raw_source, dict):
            try:
                parsed.append(DocumentReference.model_validate(raw_source))
            except Exception:
                continue
    return parsed
