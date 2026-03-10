from types import SimpleNamespace

from app.channels.policy import (
    get_escalation_user_notice_mode,
    get_hitl_approval_timeout_seconds,
)


def test_get_hitl_timeout_reads_policy_value() -> None:
    policy_service = SimpleNamespace(
        get_policy=lambda _channel_id: SimpleNamespace(hitl_approval_timeout_seconds=1234)
    )

    timeout = get_hitl_approval_timeout_seconds(policy_service, "matrix")

    assert timeout == 1234


def test_get_hitl_timeout_clamps_negative_values() -> None:
    policy_service = SimpleNamespace(
        get_policy=lambda _channel_id: SimpleNamespace(hitl_approval_timeout_seconds=-5)
    )

    timeout = get_hitl_approval_timeout_seconds(policy_service, "matrix")

    assert timeout == 0


def test_get_escalation_user_notice_mode_reads_policy_value() -> None:
    policy_service = SimpleNamespace(
        get_policy=lambda _channel_id: SimpleNamespace(escalation_user_notice_mode="none")
    )

    mode = get_escalation_user_notice_mode(policy_service, "matrix")

    assert mode == "none"


def test_get_escalation_user_notice_mode_falls_back_for_invalid_value() -> None:
    policy_service = SimpleNamespace(
        get_policy=lambda _channel_id: SimpleNamespace(escalation_user_notice_mode="reaction")
    )

    mode = get_escalation_user_notice_mode(policy_service, "matrix")

    assert mode == "message"
