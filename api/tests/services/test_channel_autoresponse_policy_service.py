"""Tests for channel-level autoresponse policy persistence."""

from __future__ import annotations

import pytest
from app.services.channel_autoresponse_policy_service import (
    DEFAULT_ACKNOWLEDGMENT_MODE,
    DEFAULT_ACKNOWLEDGMENT_REACTION_KEY,
    DEFAULT_AI_RESPONSE_MODE,
    DEFAULT_AUTORESPONSE_ENABLED,
    DEFAULT_COMMUNITY_RESPONSE_CANCELS_AI,
    DEFAULT_COMMUNITY_SUBSTANTIVE_MIN_CHARS,
    DEFAULT_DISPATCH_FAILURE_MESSAGE_TEMPLATE,
    DEFAULT_DRAFT_ASSISTANT_ENABLED,
    DEFAULT_ESCALATION_NOTIFICATION_CHANNEL,
    DEFAULT_ESCALATION_USER_NOTICE_MODE,
    DEFAULT_ESCALATION_USER_NOTICE_TEMPLATE,
    DEFAULT_EXPLICIT_INVOCATION_ENABLED,
    DEFAULT_EXPLICIT_INVOCATION_ROOM_RATE_LIMIT_PER_MIN,
    DEFAULT_EXPLICIT_INVOCATION_USER_RATE_LIMIT_PER_5M,
    DEFAULT_FIRST_RESPONSE_DELAY_SECONDS,
    DEFAULT_GENERATION_ENABLED,
    DEFAULT_GROUP_CLARIFICATION_IMMEDIATE,
    DEFAULT_HITL_APPROVAL_TIMEOUT_SECONDS,
    DEFAULT_KNOWLEDGE_AMPLIFIER_ENABLED,
    DEFAULT_MANDATORY_ESCALATION_TOPICS,
    DEFAULT_MAX_PROACTIVE_AI_REPLIES_PER_QUESTION,
    DEFAULT_MIN_DELAY_NO_STAFF_SECONDS,
    DEFAULT_PUBLIC_ESCALATION_NOTICE_ENABLED,
    DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS,
    DEFAULT_STAFF_ASSIST_SURFACE,
    DEFAULT_STAFF_PRESENCE_AWARE_DELAY,
    DEFAULT_TIMER_JITTER_MAX_SECONDS,
    SUPPORTED_CHANNELS,
    ChannelAutoResponsePolicyService,
)


def test_service_seeds_default_policies(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    policies = service.list_policies()
    assert [policy.channel_id for policy in policies] == sorted(SUPPORTED_CHANNELS)

    for policy in policies:
        assert policy.enabled == DEFAULT_AUTORESPONSE_ENABLED[policy.channel_id]
        assert (
            policy.generation_enabled == DEFAULT_GENERATION_ENABLED[policy.channel_id]
        )
        assert policy.ai_response_mode == DEFAULT_AI_RESPONSE_MODE[policy.channel_id]
        assert (
            policy.hitl_approval_timeout_seconds
            == DEFAULT_HITL_APPROVAL_TIMEOUT_SECONDS[policy.channel_id]
        )
        assert (
            policy.draft_assistant_enabled
            == DEFAULT_DRAFT_ASSISTANT_ENABLED[policy.channel_id]
        )
        assert (
            policy.knowledge_amplifier_enabled
            == DEFAULT_KNOWLEDGE_AMPLIFIER_ENABLED[policy.channel_id]
        )
        assert (
            policy.staff_assist_surface
            == DEFAULT_STAFF_ASSIST_SURFACE[policy.channel_id]
        )
        assert (
            policy.first_response_delay_seconds
            == DEFAULT_FIRST_RESPONSE_DELAY_SECONDS[policy.channel_id]
        )
        assert (
            policy.staff_active_cooldown_seconds
            == DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS[policy.channel_id]
        )
        assert (
            policy.max_proactive_ai_replies_per_question
            == DEFAULT_MAX_PROACTIVE_AI_REPLIES_PER_QUESTION[policy.channel_id]
        )
        assert (
            policy.public_escalation_notice_enabled
            == DEFAULT_PUBLIC_ESCALATION_NOTICE_ENABLED[policy.channel_id]
        )
        assert (
            policy.acknowledgment_mode == DEFAULT_ACKNOWLEDGMENT_MODE[policy.channel_id]
        )
        assert (
            policy.acknowledgment_reaction_key
            == DEFAULT_ACKNOWLEDGMENT_REACTION_KEY[policy.channel_id]
        )
        assert (
            policy.escalation_user_notice_template
            == DEFAULT_ESCALATION_USER_NOTICE_TEMPLATE[policy.channel_id]
        )
        assert (
            policy.escalation_user_notice_mode
            == DEFAULT_ESCALATION_USER_NOTICE_MODE[policy.channel_id]
        )
        assert (
            policy.group_clarification_immediate
            == DEFAULT_GROUP_CLARIFICATION_IMMEDIATE[policy.channel_id]
        )
        assert (
            policy.dispatch_failure_message_template
            == DEFAULT_DISPATCH_FAILURE_MESSAGE_TEMPLATE[policy.channel_id]
        )
        assert (
            policy.escalation_notification_channel
            == DEFAULT_ESCALATION_NOTIFICATION_CHANNEL[policy.channel_id]
        )
        assert (
            policy.explicit_invocation_enabled
            == DEFAULT_EXPLICIT_INVOCATION_ENABLED[policy.channel_id]
        )
        assert (
            policy.explicit_invocation_user_rate_limit_per_5m
            == DEFAULT_EXPLICIT_INVOCATION_USER_RATE_LIMIT_PER_5M[policy.channel_id]
        )
        assert (
            policy.explicit_invocation_room_rate_limit_per_min
            == DEFAULT_EXPLICIT_INVOCATION_ROOM_RATE_LIMIT_PER_MIN[policy.channel_id]
        )
        assert (
            policy.community_response_cancels_ai
            == DEFAULT_COMMUNITY_RESPONSE_CANCELS_AI[policy.channel_id]
        )
        assert (
            policy.community_substantive_min_chars
            == DEFAULT_COMMUNITY_SUBSTANTIVE_MIN_CHARS[policy.channel_id]
        )
        assert (
            policy.staff_presence_aware_delay
            == DEFAULT_STAFF_PRESENCE_AWARE_DELAY[policy.channel_id]
        )
        assert (
            policy.min_delay_no_staff_seconds
            == DEFAULT_MIN_DELAY_NO_STAFF_SECONDS[policy.channel_id]
        )
        assert (
            policy.mandatory_escalation_topics
            == DEFAULT_MANDATORY_ESCALATION_TOPICS[policy.channel_id]
        )
        assert (
            policy.timer_jitter_max_seconds
            == DEFAULT_TIMER_JITTER_MAX_SECONDS[policy.channel_id]
        )
        assert policy.updated_at

    assert DEFAULT_AUTORESPONSE_ENABLED == {
        "web": True,
        "matrix": False,
        "bisq2": False,
    }
    assert DEFAULT_GENERATION_ENABLED == {
        "web": True,
        "matrix": False,
        "bisq2": False,
    }


def test_set_enabled_persists_value(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    updated = service.set_enabled("web", False)
    fetched = service.get_policy("web")

    assert updated.channel_id == "web"
    assert updated.enabled is False
    assert fetched.enabled is False
    assert fetched.generation_enabled is True


def test_set_generation_enabled_turns_on_generation_without_autosend(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    updated = service.set_generation_enabled("matrix", True)
    fetched = service.get_policy("matrix")

    assert updated.channel_id == "matrix"
    assert updated.generation_enabled is True
    assert fetched.generation_enabled is True
    assert fetched.enabled is False


def test_set_policy_updates_hitl_and_staff_assist_fields(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    updated = service.set_policy(
        "matrix",
        ai_response_mode="hitl",
        hitl_approval_timeout_seconds=900,
        draft_assistant_enabled=True,
        knowledge_amplifier_enabled=True,
        staff_assist_surface="admin_ui",
        first_response_delay_seconds=120,
        staff_active_cooldown_seconds=240,
        max_proactive_ai_replies_per_question=2,
        public_escalation_notice_enabled=False,
        acknowledgment_mode="reaction",
        acknowledgment_reaction_key="👀",
        group_clarification_immediate=False,
        escalation_user_notice_template="this needs a team member's attention. someone will follow up.",
        escalation_user_notice_mode="none",
        dispatch_failure_message_template="we were unable to process your question automatically. a team member will follow up.",
        escalation_notification_channel="staff_room",
        explicit_invocation_enabled=True,
        explicit_invocation_user_rate_limit_per_5m=4,
        explicit_invocation_room_rate_limit_per_min=8,
        community_response_cancels_ai=True,
        community_substantive_min_chars=22,
        staff_presence_aware_delay=True,
        min_delay_no_staff_seconds=180,
        mandatory_escalation_topics=["seed phrase", "scam dm"],
        timer_jitter_max_seconds=30,
    )

    assert updated.ai_response_mode == "hitl"
    assert updated.hitl_approval_timeout_seconds == 900
    assert updated.draft_assistant_enabled is True
    assert updated.knowledge_amplifier_enabled is True
    assert updated.staff_assist_surface == "admin_ui"
    assert updated.first_response_delay_seconds == 120
    assert updated.staff_active_cooldown_seconds == 240
    assert updated.max_proactive_ai_replies_per_question == 2
    assert updated.public_escalation_notice_enabled is False
    assert updated.acknowledgment_mode == "reaction"
    assert updated.acknowledgment_reaction_key == "👀"
    assert updated.group_clarification_immediate is False
    assert "team member" in updated.escalation_user_notice_template
    assert updated.escalation_user_notice_mode == "none"
    assert "unable to process" in updated.dispatch_failure_message_template
    assert updated.escalation_notification_channel == "staff_room"
    assert updated.explicit_invocation_enabled is True
    assert updated.explicit_invocation_user_rate_limit_per_5m == 4
    assert updated.explicit_invocation_room_rate_limit_per_min == 8
    assert updated.community_response_cancels_ai is True
    assert updated.community_substantive_min_chars == 22
    assert updated.staff_presence_aware_delay is True
    assert updated.min_delay_no_staff_seconds == 180
    assert updated.mandatory_escalation_topics == ["seed phrase", "scam dm"]
    assert updated.timer_jitter_max_seconds == 30


def test_set_policy_rejects_invalid_staff_assist_surface(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    with pytest.raises(ValueError):
        service.set_policy("matrix", staff_assist_surface="public_room")


def test_set_policy_rejects_invalid_escalation_notification_channel(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    with pytest.raises(ValueError):
        service.set_policy("matrix", escalation_notification_channel="matrix_room")


def test_set_policy_rejects_invalid_escalation_user_notice_mode(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    with pytest.raises(ValueError):
        service.set_policy("matrix", escalation_user_notice_mode="reaction")


def test_disabling_generation_forces_autosend_off(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    service.set_policy("web", enabled=True, generation_enabled=True)
    updated = service.set_policy("web", generation_enabled=False)

    assert updated.generation_enabled is False
    assert updated.enabled is False


def test_invalid_channel_raises_value_error(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))

    with pytest.raises(ValueError):
        service.get_policy("unknown")
