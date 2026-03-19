"""Admin endpoints for channel autoresponse policy."""

from __future__ import annotations

from typing import List

from app.core.security import verify_admin_access
from app.services.channel_autoresponse_policy_service import (
    ChannelAutoResponsePolicy,
    ChannelAutoResponsePolicyService,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter(
    prefix="/admin/channels/autoresponse",
    tags=["Admin Channel Autoresponse"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


class ChannelAutoResponsePolicyResponse(BaseModel):
    channel_id: str
    enabled: bool
    generation_enabled: bool
    ai_response_mode: str
    hitl_approval_timeout_seconds: int
    draft_assistant_enabled: bool
    knowledge_amplifier_enabled: bool
    staff_assist_surface: str
    first_response_delay_seconds: int
    staff_active_cooldown_seconds: int
    max_proactive_ai_replies_per_question: int
    public_escalation_notice_enabled: bool
    acknowledgment_mode: str
    acknowledgment_reaction_key: str
    acknowledgment_message_template: str
    group_clarification_immediate: bool
    escalation_user_notice_template: str
    escalation_user_notice_mode: str
    dispatch_failure_message_template: str
    escalation_notification_channel: str
    explicit_invocation_enabled: bool
    explicit_invocation_user_rate_limit_per_5m: int
    explicit_invocation_room_rate_limit_per_min: int
    community_response_cancels_ai: bool
    community_substantive_min_chars: int
    staff_presence_aware_delay: bool
    min_delay_no_staff_seconds: int
    mandatory_escalation_topics: list[str]
    timer_jitter_max_seconds: int
    updated_at: str


class UpdateChannelAutoResponsePolicyRequest(BaseModel):
    enabled: bool | None = None
    generation_enabled: bool | None = None
    ai_response_mode: str | None = None
    hitl_approval_timeout_seconds: int | None = None
    draft_assistant_enabled: bool | None = None
    knowledge_amplifier_enabled: bool | None = None
    staff_assist_surface: str | None = None
    first_response_delay_seconds: int | None = None
    staff_active_cooldown_seconds: int | None = None
    max_proactive_ai_replies_per_question: int | None = None
    public_escalation_notice_enabled: bool | None = None
    acknowledgment_mode: str | None = None
    acknowledgment_reaction_key: str | None = None
    acknowledgment_message_template: str | None = None
    group_clarification_immediate: bool | None = None
    escalation_user_notice_template: str | None = None
    escalation_user_notice_mode: str | None = None
    dispatch_failure_message_template: str | None = None
    escalation_notification_channel: str | None = None
    explicit_invocation_enabled: bool | None = None
    explicit_invocation_user_rate_limit_per_5m: int | None = None
    explicit_invocation_room_rate_limit_per_min: int | None = None
    community_response_cancels_ai: bool | None = None
    community_substantive_min_chars: int | None = None
    staff_presence_aware_delay: bool | None = None
    min_delay_no_staff_seconds: int | None = None
    mandatory_escalation_topics: list[str] | None = None
    timer_jitter_max_seconds: int | None = None


def _service_from_app(request: Request) -> ChannelAutoResponsePolicyService:
    service = getattr(request.app.state, "channel_autoresponse_policy_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel autoresponse policy service is not available",
        )
    return service


def _to_response(
    policy: ChannelAutoResponsePolicy,
) -> ChannelAutoResponsePolicyResponse:
    return ChannelAutoResponsePolicyResponse(
        channel_id=policy.channel_id,
        enabled=policy.enabled,
        generation_enabled=policy.generation_enabled,
        ai_response_mode=policy.ai_response_mode,
        hitl_approval_timeout_seconds=policy.hitl_approval_timeout_seconds,
        draft_assistant_enabled=policy.draft_assistant_enabled,
        knowledge_amplifier_enabled=policy.knowledge_amplifier_enabled,
        staff_assist_surface=policy.staff_assist_surface,
        first_response_delay_seconds=policy.first_response_delay_seconds,
        staff_active_cooldown_seconds=policy.staff_active_cooldown_seconds,
        max_proactive_ai_replies_per_question=policy.max_proactive_ai_replies_per_question,
        public_escalation_notice_enabled=policy.public_escalation_notice_enabled,
        acknowledgment_mode=policy.acknowledgment_mode,
        acknowledgment_reaction_key=policy.acknowledgment_reaction_key,
        acknowledgment_message_template=policy.acknowledgment_message_template,
        group_clarification_immediate=policy.group_clarification_immediate,
        escalation_user_notice_template=policy.escalation_user_notice_template,
        escalation_user_notice_mode=policy.escalation_user_notice_mode,
        dispatch_failure_message_template=policy.dispatch_failure_message_template,
        escalation_notification_channel=policy.escalation_notification_channel,
        explicit_invocation_enabled=policy.explicit_invocation_enabled,
        explicit_invocation_user_rate_limit_per_5m=policy.explicit_invocation_user_rate_limit_per_5m,
        explicit_invocation_room_rate_limit_per_min=policy.explicit_invocation_room_rate_limit_per_min,
        community_response_cancels_ai=policy.community_response_cancels_ai,
        community_substantive_min_chars=policy.community_substantive_min_chars,
        staff_presence_aware_delay=policy.staff_presence_aware_delay,
        min_delay_no_staff_seconds=policy.min_delay_no_staff_seconds,
        mandatory_escalation_topics=policy.mandatory_escalation_topics,
        timer_jitter_max_seconds=policy.timer_jitter_max_seconds,
        updated_at=policy.updated_at,
    )


@router.get(
    "",
    response_model=List[ChannelAutoResponsePolicyResponse],
)
def list_channel_autoresponse_policies(
    request: Request,
) -> List[ChannelAutoResponsePolicyResponse]:
    service = _service_from_app(request)
    return [_to_response(policy) for policy in service.list_policies()]


@router.get(
    "/{channel_id}",
    response_model=ChannelAutoResponsePolicyResponse,
)
def get_channel_autoresponse_policy(
    channel_id: str,
    request: Request,
) -> ChannelAutoResponsePolicyResponse:
    service = _service_from_app(request)
    try:
        return _to_response(service.get_policy(channel_id))
    except ValueError:
        supported = ", ".join(service.supported_channels)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel_id '{channel_id}'. Supported channels: {supported}",
        ) from None
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy found for channel_id '{channel_id}'",
        ) from None


@router.put(
    "/{channel_id}",
    response_model=ChannelAutoResponsePolicyResponse,
)
def update_channel_autoresponse_policy(
    channel_id: str,
    payload: UpdateChannelAutoResponsePolicyRequest,
    request: Request,
) -> ChannelAutoResponsePolicyResponse:
    service = _service_from_app(request)
    if (
        payload.enabled is None
        and payload.generation_enabled is None
        and payload.ai_response_mode is None
        and payload.hitl_approval_timeout_seconds is None
        and payload.draft_assistant_enabled is None
        and payload.knowledge_amplifier_enabled is None
        and payload.staff_assist_surface is None
        and payload.first_response_delay_seconds is None
        and payload.staff_active_cooldown_seconds is None
        and payload.max_proactive_ai_replies_per_question is None
        and payload.public_escalation_notice_enabled is None
        and payload.acknowledgment_mode is None
        and payload.acknowledgment_reaction_key is None
        and payload.acknowledgment_message_template is None
        and payload.group_clarification_immediate is None
        and payload.escalation_user_notice_template is None
        and payload.escalation_user_notice_mode is None
        and payload.dispatch_failure_message_template is None
        and payload.escalation_notification_channel is None
        and payload.explicit_invocation_enabled is None
        and payload.explicit_invocation_user_rate_limit_per_5m is None
        and payload.explicit_invocation_room_rate_limit_per_min is None
        and payload.community_response_cancels_ai is None
        and payload.community_substantive_min_chars is None
        and payload.staff_presence_aware_delay is None
        and payload.min_delay_no_staff_seconds is None
        and payload.mandatory_escalation_topics is None
        and payload.timer_jitter_max_seconds is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one policy field must be provided",
        )
    try:
        updated = service.set_policy(
            channel_id=channel_id,
            enabled=payload.enabled,
            generation_enabled=payload.generation_enabled,
            ai_response_mode=payload.ai_response_mode,
            hitl_approval_timeout_seconds=payload.hitl_approval_timeout_seconds,
            draft_assistant_enabled=payload.draft_assistant_enabled,
            knowledge_amplifier_enabled=payload.knowledge_amplifier_enabled,
            staff_assist_surface=payload.staff_assist_surface,
            first_response_delay_seconds=payload.first_response_delay_seconds,
            staff_active_cooldown_seconds=payload.staff_active_cooldown_seconds,
            max_proactive_ai_replies_per_question=payload.max_proactive_ai_replies_per_question,
            public_escalation_notice_enabled=payload.public_escalation_notice_enabled,
            acknowledgment_mode=payload.acknowledgment_mode,
            acknowledgment_reaction_key=payload.acknowledgment_reaction_key,
            acknowledgment_message_template=payload.acknowledgment_message_template,
            group_clarification_immediate=payload.group_clarification_immediate,
            escalation_user_notice_template=payload.escalation_user_notice_template,
            escalation_user_notice_mode=payload.escalation_user_notice_mode,
            dispatch_failure_message_template=payload.dispatch_failure_message_template,
            escalation_notification_channel=payload.escalation_notification_channel,
            explicit_invocation_enabled=payload.explicit_invocation_enabled,
            explicit_invocation_user_rate_limit_per_5m=payload.explicit_invocation_user_rate_limit_per_5m,
            explicit_invocation_room_rate_limit_per_min=payload.explicit_invocation_room_rate_limit_per_min,
            community_response_cancels_ai=payload.community_response_cancels_ai,
            community_substantive_min_chars=payload.community_substantive_min_chars,
            staff_presence_aware_delay=payload.staff_presence_aware_delay,
            min_delay_no_staff_seconds=payload.min_delay_no_staff_seconds,
            mandatory_escalation_topics=payload.mandatory_escalation_topics,
            timer_jitter_max_seconds=payload.timer_jitter_max_seconds,
        )
    except ValueError:
        supported = ", ".join(service.supported_channels)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel_id '{channel_id}'. Supported channels: {supported}",
        ) from None
    return _to_response(updated)
