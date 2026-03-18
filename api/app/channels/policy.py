"""Shared channel auto-response policy helpers."""

from __future__ import annotations

import logging
from typing import Any

from app.channels.constants import REVIEW_QUEUE_ACTIONS
from app.services.channel_autoresponse_policy_service import (
    DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE,
    DEFAULT_ACKNOWLEDGMENT_MODE,
    DEFAULT_ACKNOWLEDGMENT_REACTION_KEY,
    DEFAULT_AI_RESPONSE_MODE,
    DEFAULT_AUTORESPONSE_ENABLED,
    DEFAULT_DISPATCH_FAILURE_MESSAGE_TEMPLATE,
    DEFAULT_ESCALATION_NOTIFICATION_CHANNEL,
    DEFAULT_ESCALATION_USER_NOTICE_MODE,
    DEFAULT_ESCALATION_USER_NOTICE_TEMPLATE,
    DEFAULT_FIRST_RESPONSE_DELAY_SECONDS,
    DEFAULT_GENERATION_ENABLED,
    DEFAULT_HITL_APPROVAL_TIMEOUT_SECONDS,
    DEFAULT_PUBLIC_ESCALATION_NOTICE_ENABLED,
    DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS,
    DEFAULT_TIMER_JITTER_MAX_SECONDS,
)

logger = logging.getLogger(__name__)

AUTOSEND_DISABLED_REASON = "Channel auto-response disabled by admin policy."


def is_generation_enabled(policy_service: Any | None, channel_id: str) -> bool:
    normalized = str(channel_id or "").strip().lower()
    if policy_service is None:
        return bool(DEFAULT_GENERATION_ENABLED.get(normalized, normalized == "web"))
    try:
        policy = policy_service.get_policy(normalized)
        generation_enabled = getattr(policy, "generation_enabled", None)
        if isinstance(generation_enabled, bool):
            return generation_enabled
        return bool(getattr(policy, "enabled", False))
    except Exception:
        logger.exception(
            "Failed to read generation policy for channel=%s; falling back to default=%s",
            normalized,
            DEFAULT_GENERATION_ENABLED.get(normalized, normalized == "web"),
        )
        return bool(DEFAULT_GENERATION_ENABLED.get(normalized, normalized == "web"))


def is_autosend_enabled(policy_service: Any | None, channel_id: str) -> bool:
    normalized = str(channel_id or "").strip().lower()
    if policy_service is None:
        return bool(DEFAULT_AUTORESPONSE_ENABLED.get(normalized, normalized == "web"))
    try:
        policy = policy_service.get_policy(normalized)
        return bool(getattr(policy, "enabled", False))
    except Exception:
        logger.exception(
            "Failed to read auto-send policy for channel=%s; falling back to default=%s",
            normalized,
            DEFAULT_AUTORESPONSE_ENABLED.get(normalized, normalized == "web"),
        )
        return bool(DEFAULT_AUTORESPONSE_ENABLED.get(normalized, normalized == "web"))


def get_ai_response_mode(policy_service: Any | None, channel_id: str) -> str:
    normalized = str(channel_id or "").strip().lower()
    if policy_service is None:
        return str(DEFAULT_AI_RESPONSE_MODE.get(normalized, "autonomous"))
    try:
        policy = policy_service.get_policy(normalized)
        mode = str(getattr(policy, "ai_response_mode", "") or "").strip().lower()
        if mode in {"autonomous", "hitl"}:
            return mode
        return str(DEFAULT_AI_RESPONSE_MODE.get(normalized, "autonomous"))
    except Exception:
        logger.exception(
            "Failed to read ai_response_mode for channel=%s; falling back to default=%s",
            normalized,
            DEFAULT_AI_RESPONSE_MODE.get(normalized, "autonomous"),
        )
        return str(DEFAULT_AI_RESPONSE_MODE.get(normalized, "autonomous"))


def get_first_response_delay_seconds(
    policy_service: Any | None, channel_id: str
) -> int:
    normalized = str(channel_id or "").strip().lower()
    if policy_service is None:
        return int(DEFAULT_FIRST_RESPONSE_DELAY_SECONDS.get(normalized, 0))
    try:
        policy = policy_service.get_policy(normalized)
        return max(
            0,
            int(
                getattr(
                    policy,
                    "first_response_delay_seconds",
                    DEFAULT_FIRST_RESPONSE_DELAY_SECONDS.get(normalized, 0),
                )
            ),
        )
    except Exception:
        logger.exception(
            "Failed to read first_response_delay_seconds for channel=%s; falling back to default=%s",
            normalized,
            DEFAULT_FIRST_RESPONSE_DELAY_SECONDS.get(normalized, 0),
        )
        return int(DEFAULT_FIRST_RESPONSE_DELAY_SECONDS.get(normalized, 0))


def get_staff_active_cooldown_seconds(
    policy_service: Any | None, channel_id: str
) -> int:
    normalized = str(channel_id or "").strip().lower()
    if policy_service is None:
        return int(DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS.get(normalized, 0))
    try:
        policy = policy_service.get_policy(normalized)
        return max(
            0,
            int(
                getattr(
                    policy,
                    "staff_active_cooldown_seconds",
                    DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS.get(normalized, 0),
                )
            ),
        )
    except Exception:
        logger.exception(
            "Failed to read staff_active_cooldown_seconds for channel=%s; falling back to default=%s",
            normalized,
            DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS.get(normalized, 0),
        )
        return int(DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS.get(normalized, 0))


def get_hitl_approval_timeout_seconds(
    policy_service: Any | None, channel_id: str
) -> int:
    normalized = str(channel_id or "").strip().lower()
    default = int(DEFAULT_HITL_APPROVAL_TIMEOUT_SECONDS.get(normalized, 3600))
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        return max(0, int(getattr(policy, "hitl_approval_timeout_seconds", default)))
    except Exception:
        logger.exception(
            "Failed to read hitl_approval_timeout_seconds for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def is_public_escalation_notice_enabled(
    policy_service: Any | None,
    channel_id: str,
) -> bool:
    normalized = str(channel_id or "").strip().lower()
    default = bool(
        DEFAULT_PUBLIC_ESCALATION_NOTICE_ENABLED.get(normalized, normalized == "web")
    )
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        raw = getattr(policy, "public_escalation_notice_enabled", default)
        return bool(raw)
    except Exception:
        logger.exception(
            "Failed to read public_escalation_notice_enabled for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def get_acknowledgment_mode(policy_service: Any | None, channel_id: str) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(DEFAULT_ACKNOWLEDGMENT_MODE.get(normalized, "none"))
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        mode = (
            str(getattr(policy, "acknowledgment_mode", default) or "").strip().lower()
        )
        return mode if mode in {"none", "reaction", "message"} else default
    except Exception:
        logger.exception(
            "Failed to read acknowledgment_mode for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def get_acknowledgment_reaction_key(policy_service: Any | None, channel_id: str) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(DEFAULT_ACKNOWLEDGMENT_REACTION_KEY.get(normalized, "👀"))
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        value = str(
            getattr(policy, "acknowledgment_reaction_key", default) or ""
        ).strip()
        return value or default
    except Exception:
        logger.exception(
            "Failed to read acknowledgment_reaction_key for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def get_acknowledgment_message_template(
    policy_service: Any | None, channel_id: str
) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(
        DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE.get(
            normalized,
            "Thanks for your question. A team member or our assistant will respond shortly.",
        )
    )
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        value = str(
            getattr(policy, "acknowledgment_message_template", default) or ""
        ).strip()
        return value or default
    except Exception:
        logger.exception(
            "Failed to read acknowledgment_message_template for channel=%s; falling back to default",
            normalized,
        )
        return default


def get_escalation_user_notice_template(
    policy_service: Any | None, channel_id: str
) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(
        DEFAULT_ESCALATION_USER_NOTICE_TEMPLATE.get(
            normalized,
            "This question needs a team member's attention. Someone will follow up.",
        )
    )
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        value = str(
            getattr(policy, "escalation_user_notice_template", default) or ""
        ).strip()
        return value or default
    except Exception:
        logger.exception(
            "Failed to read escalation_user_notice_template for channel=%s; falling back to default",
            normalized,
        )
        return default


def get_escalation_user_notice_mode(
    policy_service: Any | None,
    channel_id: str,
) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(DEFAULT_ESCALATION_USER_NOTICE_MODE.get(normalized, "message"))
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        value = (
            str(getattr(policy, "escalation_user_notice_mode", default) or "")
            .strip()
            .lower()
        )
        return value if value in {"none", "message"} else default
    except Exception:
        logger.exception(
            "Failed to read escalation_user_notice_mode for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def get_dispatch_failure_message_template(
    policy_service: Any | None, channel_id: str
) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(
        DEFAULT_DISPATCH_FAILURE_MESSAGE_TEMPLATE.get(
            normalized,
            "We were unable to process your question automatically. A team member will follow up.",
        )
    )
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        value = str(
            getattr(policy, "dispatch_failure_message_template", default) or ""
        ).strip()
        return value or default
    except Exception:
        logger.exception(
            "Failed to read dispatch_failure_message_template for channel=%s; falling back to default",
            normalized,
        )
        return default


def get_escalation_notification_channel(
    policy_service: Any | None,
    channel_id: str,
) -> str:
    normalized = str(channel_id or "").strip().lower()
    default = str(
        DEFAULT_ESCALATION_NOTIFICATION_CHANNEL.get(normalized, "public_room")
    )
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        value = (
            str(getattr(policy, "escalation_notification_channel", default) or "")
            .strip()
            .lower()
        )
        return value if value in {"public_room", "staff_room", "none"} else default
    except Exception:
        logger.exception(
            "Failed to read escalation_notification_channel for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def get_timer_jitter_max_seconds(policy_service: Any | None, channel_id: str) -> int:
    normalized = str(channel_id or "").strip().lower()
    default = int(DEFAULT_TIMER_JITTER_MAX_SECONDS.get(normalized, 0))
    if policy_service is None:
        return default
    try:
        policy = policy_service.get_policy(normalized)
        return max(0, int(getattr(policy, "timer_jitter_max_seconds", default)))
    except Exception:
        logger.exception(
            "Failed to read timer_jitter_max_seconds for channel=%s; falling back to default=%s",
            normalized,
            default,
        )
        return default


def apply_autosend_policy(response: Any, autosend_enabled: bool) -> Any:
    """Force review-queue routing when channel auto-send is disabled."""
    if autosend_enabled:
        return response
    metadata = getattr(response, "metadata", None)
    routing_action = str(getattr(metadata, "routing_action", "") or "").strip().lower()
    requires_human_raw = getattr(response, "requires_human", False)
    requires_human = (
        requires_human_raw if isinstance(requires_human_raw, bool) else False
    )
    if requires_human or routing_action in REVIEW_QUEUE_ACTIONS:
        return response

    response.requires_human = True
    metadata = getattr(response, "metadata", None)
    if metadata is not None:
        metadata.routing_action = "queue_medium"
        if not getattr(metadata, "routing_reason", None):
            metadata.routing_reason = AUTOSEND_DISABLED_REASON
    return response
