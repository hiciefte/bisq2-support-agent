"""Shared channel auto-response policy helpers."""

from __future__ import annotations

import logging
from typing import Any

from app.channels.response_dispatcher import ChannelResponseDispatcher
from app.services.channel_autoresponse_policy_service import (
    DEFAULT_AUTORESPONSE_ENABLED,
    DEFAULT_GENERATION_ENABLED,
)

logger = logging.getLogger(__name__)

AUTOSEND_DISABLED_REASON = "Channel auto-response disabled by admin policy."


def is_generation_enabled(policy_service: Any | None, channel_id: str) -> bool:
    if policy_service is None:
        return True
    try:
        policy = policy_service.get_policy(channel_id)
        generation_enabled = getattr(policy, "generation_enabled", None)
        if isinstance(generation_enabled, bool):
            return generation_enabled
        return bool(getattr(policy, "enabled", False))
    except Exception:
        logger.exception(
            "Failed to read generation policy for channel=%s; falling back to default=%s",
            channel_id,
            DEFAULT_GENERATION_ENABLED.get(channel_id, False),
        )
        return bool(DEFAULT_GENERATION_ENABLED.get(channel_id, False))


def is_autosend_enabled(policy_service: Any | None, channel_id: str) -> bool:
    if policy_service is None:
        return True
    try:
        policy = policy_service.get_policy(channel_id)
        return bool(getattr(policy, "enabled", False))
    except Exception:
        logger.exception(
            "Failed to read auto-send policy for channel=%s; falling back to default=%s",
            channel_id,
            DEFAULT_AUTORESPONSE_ENABLED.get(channel_id, False),
        )
        return bool(DEFAULT_AUTORESPONSE_ENABLED.get(channel_id, False))


def apply_autosend_policy(response: Any, autosend_enabled: bool) -> Any:
    """Force review-queue routing when channel auto-send is disabled."""
    if autosend_enabled:
        return response
    if ChannelResponseDispatcher.should_create_escalation(response):
        return response

    response.requires_human = True
    metadata = getattr(response, "metadata", None)
    if metadata is not None:
        metadata.routing_action = "queue_medium"
        if not getattr(metadata, "routing_reason", None):
            metadata.routing_reason = AUTOSEND_DISABLED_REASON
    return response
