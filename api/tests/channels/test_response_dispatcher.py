import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.response_dispatcher import (
    ChannelResponseDispatcher,
    DeliveryMode,
    DispatchOutcome,
    format_escalation_notice,
)
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.services.channel_launch_control_service import ChannelLaunchControlService


class _AllowingLaunchControl:
    def authorize_autonomous_delivery(self, channel_id, message_id):
        return SimpleNamespace(allowed=True, reason="test_allowed")

    def review_only_reason(self, channel_id):
        return None

    def secondary_delivery_block_reason(self, channel_id):
        return None


ALLOWING_LAUNCH_CONTROL = _AllowingLaunchControl()


def _launch_incoming(message_id: str):
    return SimpleNamespace(
        message_id=message_id,
        question="How does Bisq Easy work?",
        channel_metadata={"room_id": "support-room"},
        user=SimpleNamespace(user_id="user-1", channel_user_id="alice"),
    )


def _launch_response():
    return SimpleNamespace(
        answer="Bisq Easy is a trade protocol.",
        original_question="How does Bisq Easy work?",
        sources=[],
        requires_human=False,
        metadata=SimpleNamespace(
            routing_action="auto_send",
            routing_reason="high confidence",
            confidence_score=0.95,
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_autosend_returns_failed_when_transport_raises():
    incoming = SimpleNamespace(message_id="m-1", channel_metadata={})
    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )
    channel = MagicMock()
    channel.get_delivery_target.return_value = "target-1"
    channel.send_message = AsyncMock(side_effect=RuntimeError("network failure"))

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="bisq2",
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )
    outcome = await dispatcher.dispatch(incoming, response)

    assert outcome is DispatchOutcome.FAILED
    channel.send_message.assert_awaited_once_with("target-1", response)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shadow_mode_queues_would_have_sent_without_delivery(tmp_path):
    launch_control = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    launch_control.set_autonomous_delivery_enabled(True)
    channel = MagicMock()
    channel.runtime = None
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=401)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=launch_control,
    )

    outcome = await dispatcher.dispatch(
        _launch_incoming("shadow-1"), _launch_response()
    )

    assert outcome is DispatchOutcome.QUEUED
    channel.send_message.assert_not_awaited()
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_action == "auto_send"
    assert payload.routing_reason == (
        "launch_control=shadow_mode; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kill_switch_is_checked_for_each_message(tmp_path):
    launch_control = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    launch_control.set_autonomous_delivery_enabled(True)
    launch_control.set_channel_policy("matrix", shadow_mode=False)
    channel = MagicMock()
    channel.runtime = None
    channel.get_delivery_target.return_value = "support-room"
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=402)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=launch_control,
    )

    first = await dispatcher.dispatch(_launch_incoming("kill-1"), _launch_response())
    launch_control.set_autonomous_delivery_enabled(False)
    second = await dispatcher.dispatch(_launch_incoming("kill-2"), _launch_response())

    assert first is DispatchOutcome.SENT
    assert second is DispatchOutcome.QUEUED
    assert channel.send_message.await_count == 1
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_reason == (
        "launch_control=kill_switch; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_canary_over_cap_routes_to_review_without_delivery(tmp_path):
    launch_control = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    launch_control.set_autonomous_delivery_enabled(True)
    launch_control.set_channel_policy(
        "bisq2",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=1,
        canary_daily_limit=1,
    )
    channel = MagicMock()
    channel.runtime = None
    channel.get_delivery_target.return_value = "support-room"
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=403)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="bisq2",
        escalation_service=escalation_service,
        launch_control_service=launch_control,
    )

    first = await dispatcher.dispatch(_launch_incoming("canary-1"), _launch_response())
    second = await dispatcher.dispatch(_launch_incoming("canary-2"), _launch_response())

    assert first is DispatchOutcome.SENT
    assert second is DispatchOutcome.QUEUED
    assert channel.send_message.await_count == 1
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_reason == (
        "launch_control=canary_hourly_limit; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_canary_suppresses_unreserved_review_notice(tmp_path):
    launch_control = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    launch_control.set_autonomous_delivery_enabled(True)
    launch_control.set_channel_policy(
        "matrix",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=1,
        canary_daily_limit=1,
    )
    incoming = _launch_incoming("canary-review")
    response = SimpleNamespace(
        answer="A staff-reviewed response is required.",
        original_question=incoming.question,
        sources=[],
        requires_human=True,
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.2,
        ),
    )
    channel = MagicMock()
    channel.runtime = None
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=408)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=launch_control,
    )
    dispatcher._notify_review_queued = AsyncMock(return_value=True)

    outcome = await dispatcher.dispatch(incoming, response)

    assert outcome is DispatchOutcome.QUEUED
    escalation_service.create_escalation.assert_awaited_once()
    dispatcher._notify_review_queued.assert_not_awaited()
    channel.send_message.assert_not_awaited()
    assert launch_control.reservation_count("matrix") == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_launch_control_queues_autonomous_response() -> None:
    channel = MagicMock()
    channel.runtime = None
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=404)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
    )

    outcome = await dispatcher.dispatch(
        _launch_incoming("missing-control"), _launch_response()
    )

    assert outcome is DispatchOutcome.QUEUED
    channel.send_message.assert_not_awaited()
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_reason == (
        "launch_control=launch_control_unavailable; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_launch_control_service_queues_autonomous_response() -> None:
    channel = MagicMock()
    channel.runtime = None
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=406)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=SimpleNamespace(),
    )

    outcome = await dispatcher.dispatch(
        _launch_incoming("malformed-service"), _launch_response()
    )

    assert outcome is DispatchOutcome.QUEUED
    channel.send_message.assert_not_awaited()
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_reason == (
        "launch_control=launch_control_invalid_service; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_launch_control_result_queues_autonomous_response() -> None:
    malformed_control = SimpleNamespace(
        authorize_autonomous_delivery=lambda channel_id, message_id: SimpleNamespace(
            allowed="yes",
            reason="not-a-valid-decision",
        ),
        review_only_reason=lambda channel_id: None,
    )
    channel = MagicMock()
    channel.runtime = None
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=405)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="bisq2",
        escalation_service=escalation_service,
        launch_control_service=malformed_control,
    )

    outcome = await dispatcher.dispatch(
        _launch_incoming("malformed-control"), _launch_response()
    )

    assert outcome is DispatchOutcome.QUEUED
    channel.send_message.assert_not_awaited()
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_reason == (
        "launch_control=launch_control_invalid_result; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failing_launch_control_queues_autonomous_response() -> None:
    def fail_authorization(channel_id, message_id):
        raise RuntimeError("launch guard unavailable")

    failing_control = SimpleNamespace(
        authorize_autonomous_delivery=fail_authorization,
        review_only_reason=lambda channel_id: None,
    )
    channel = MagicMock()
    channel.runtime = None
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=407)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=failing_control,
    )

    outcome = await dispatcher.dispatch(
        _launch_incoming("failing-control"), _launch_response()
    )

    assert outcome is DispatchOutcome.QUEUED
    channel.send_message.assert_not_awaited()
    payload = escalation_service.create_escalation.await_args.args[0]
    assert payload.routing_reason == (
        "launch_control=launch_control_error; would_have_sent=auto_send"
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("routing_action", ["", "legacy_auto_send"])
async def test_dispatch_queues_missing_or_unknown_routing_action(
    routing_action, caplog
):
    incoming = SimpleNamespace(
        message_id="m-fail-closed",
        question="How does Bisq Easy work?",
        channel_metadata={"room_id": "support-room"},
        user=SimpleNamespace(user_id="u-1", channel_user_id="alice"),
    )
    response = SimpleNamespace(
        answer="Draft answer",
        original_question=incoming.question,
        sources=[],
        requires_human=False,
        metadata=SimpleNamespace(
            routing_action=routing_action,
            routing_reason=None,
            confidence_score=0.99,
        ),
    )
    channel = MagicMock()
    channel.runtime = None
    channel.get_delivery_target.return_value = "support-room"
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=101)
    )
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="bisq2",
        escalation_service=escalation_service,
    )

    with caplog.at_level(logging.ERROR):
        outcome = await dispatcher.dispatch(incoming, response)

    assert outcome is DispatchOutcome.QUEUED
    escalation_service.create_escalation.assert_awaited_once()
    assert all(
        call.args[1] is not response for call in channel.send_message.await_args_list
    )
    assert "routing_action" in caplog.text
    assert "review" in caplog.text.lower()


@pytest.mark.unit
@pytest.mark.parametrize("routing_action", ["auto_send", "needs_clarification"])
def test_known_direct_delivery_actions_remain_autosend(routing_action):
    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action=routing_action),
    )

    assert ChannelResponseDispatcher.should_autosend_response(response) is True
    assert ChannelResponseDispatcher.should_create_escalation(response) is False


@pytest.mark.unit
def test_format_escalation_notice_localizes_generic_fallback():
    message = format_escalation_notice(
        channel_id="web",
        username="alice",
        escalation_id=42,
        support_handle="support",
        language_code="de",
        channel=None,
        channel_registry=None,
    )

    assert "#42" not in message
    assert "teammitglied" in message.lower()


@pytest.mark.unit
def test_format_escalation_notice_handles_legacy_formatter_signature():
    class LegacyFormatter:
        def format_escalation_message(self, username, escalation_id, support_handle):
            return (
                f"Escalated to {support_handle} for {username} "
                f"(Reference: #{escalation_id})"
            )

    message = format_escalation_notice(
        channel_id="web",
        username="alice",
        escalation_id=7,
        support_handle="support",
        language_code="de",
        channel=LegacyFormatter(),
        channel_registry=None,
    )

    assert message == "Escalated to support for alice (Reference: #7)"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_escalation_prefers_canonical_english_and_keeps_localized_context():
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(return_value=SimpleNamespace(id=1))
    dispatcher = ChannelResponseDispatcher(
        channel=None,
        channel_id="matrix",
        escalation_service=escalation_service,
    )

    incoming = SimpleNamespace(
        message_id="msg-1",
        question="Wie funktioniert Bisq Easy?",
        user=SimpleNamespace(user_id="u-1", channel_user_id="alice"),
        channel_metadata={"room_id": "!room:example.org"},
    )
    response = SimpleNamespace(
        answer="Bisq Easy nutzt ein Reputationssystem.",
        sources=[],
        metadata=SimpleNamespace(
            confidence_score=0.41,
            routing_action="needs_human",
            routing_reason="low confidence",
            canonical_question_en="How does Bisq Easy work?",
            canonical_answer_en="Bisq Easy uses a reputation system.",
            original_language="de",
            translation_applied=True,
        ),
    )

    await dispatcher.create_escalation_for_review(incoming, response)

    escalation_service.create_escalation.assert_awaited_once()
    payload = escalation_service.create_escalation.call_args.args[0]
    assert payload.question == "How does Bisq Easy work?"
    assert payload.question_original == "Wie funktioniert Bisq Easy?"
    assert payload.ai_draft_answer == "Bisq Easy uses a reputation system."
    assert payload.ai_draft_answer_original == "Bisq Easy nutzt ein Reputationssystem."
    assert payload.user_language == "de"
    assert payload.translation_applied is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_falls_back_to_buffered_when_native_stream_fails(monkeypatch):
    incoming = SimpleNamespace(message_id="m-1", channel_metadata={})
    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )
    channel = MagicMock()
    channel.get_delivery_target.return_value = "target-1"

    native = AsyncMock(return_value=False)
    buffered = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.channels.response_dispatcher.deliver_native_stream", native
    )
    monkeypatch.setattr(
        "app.channels.response_dispatcher.deliver_buffered_stream",
        buffered,
    )

    planner = MagicMock()
    planner.plan.return_value = SimpleNamespace(mode=DeliveryMode.STREAM_NATIVE)
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        delivery_planner=planner,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.SENT
    native.assert_awaited_once_with(channel, "target-1", response)
    buffered.assert_awaited_once_with(channel, "target-1", response)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_suppresses_public_escalation_notice_for_group_channels_by_policy():
    incoming = SimpleNamespace(
        message_id="m-2",
        question="my trade is stuck",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.33,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=77)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    notice = channel.send_message.call_args.args[1]
    assert "team member" in notice.answer.lower()
    assert "#77" not in notice.answer


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queued_dispatch_stays_terminal_when_review_notice_delivery_raises():
    incoming = SimpleNamespace(
        message_id="m-notice-failure",
        question="my trade is stuck",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.2,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=78)
    )
    channel = MagicMock()
    channel.runtime = None
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(side_effect=RuntimeError("transport down"))
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    outcome = await dispatcher.dispatch(incoming, response)

    assert outcome is DispatchOutcome.QUEUED
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_sends_public_escalation_notice_when_enabled():
    incoming = SimpleNamespace(
        message_id="m-3",
        question="need help with wallet",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.3,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=88)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=True,
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="web",
        escalation_service=escalation_service,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    notice = channel.send_message.call_args.args[1]
    assert "#88" not in notice.answer
    assert "team member" in notice.answer.lower()
    assert "follow up" in notice.answer.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_escalation_notice_preserves_exact_static_safety_warning():
    incoming = SimpleNamespace(
        message_id="m-safety-public",
        question="An app asked me to enter my seed phrase.",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer=f"{SAFETY_REFLEX_WARNING}\n\nEvidence-backed safety detail.",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="safety review",
            confidence_score=0.3,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=188)
    )
    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=True,
        escalation_notification_channel="public_room",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )
    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    await dispatcher.dispatch(incoming, response)

    notice = channel.send_message.call_args.args[1]
    assert notice.answer.startswith(SAFETY_REFLEX_WARNING)
    assert notice.answer.count(SAFETY_REFLEX_WARNING) == 1
    assert "team member" in notice.answer.lower()
    assert "evidence-backed safety detail" not in notice.answer.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_uses_user_notice_when_escalation_notification_channel_is_none():
    incoming = SimpleNamespace(
        message_id="m-4",
        question="need help",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.1,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=99)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=True,
        escalation_notification_channel="none",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    channel.send_message.assert_awaited_once()
    notice = channel.send_message.call_args.args[1]
    assert "#99" not in notice.answer
    assert "team member" in notice.answer.lower()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("channel_id", ["matrix", "bisq2"])
async def test_user_escalation_notice_preserves_exact_static_safety_warning(channel_id):
    incoming = SimpleNamespace(
        message_id="m-safety-user",
        question="An app asked me to enter my seed phrase.",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer=f"{SAFETY_REFLEX_WARNING}\n\nEvidence-backed safety detail.",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="safety review",
            confidence_score=0.1,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=199)
    )
    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="none",
        escalation_user_notice_mode="message",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )
    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)
    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id=channel_id,
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    await dispatcher.dispatch(incoming, response)

    notice = channel.send_message.call_args.args[1]
    assert notice.answer.startswith(SAFETY_REFLEX_WARNING)
    assert notice.answer.count(SAFETY_REFLEX_WARNING) == 1
    assert "team member" in notice.answer.lower()
    assert "evidence-backed safety detail" not in notice.answer.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_sends_staff_room_notice_when_configured():
    incoming = SimpleNamespace(
        message_id="m-5",
        question="trade stuck at payout",
        channel_metadata={
            "room_id": "!support:matrix.org",
            "staff_room_id": "!staff:matrix.org",
        },
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.1,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=123)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="staff_room",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    assert channel.send_message.await_count == 2
    user_notice_call = channel.send_message.await_args_list[0]
    staff_notice_call = channel.send_message.await_args_list[1]
    assert user_notice_call.args[0] == "!support:matrix.org"
    assert "team member" in user_notice_call.args[1].answer.lower()
    assert staff_notice_call.args[0] == "!staff:matrix.org"
    assert "Escalation #123 for matrix" in staff_notice_call.args[1].answer
    assert "Reply to user (copy-ready):" in staff_notice_call.args[1].answer
    assert "draft" in staff_notice_call.args[1].answer
    assert "Sources to copy:" in staff_notice_call.args[1].answer
    assert "- No source links available." in staff_notice_call.args[1].answer
    assert "Review context:" in staff_notice_call.args[1].answer
    assert "Routing reason: manual_review" in staff_notice_call.args[1].answer
    assert "Confidence: 10%" in staff_notice_call.args[1].answer
    assert "/admin/escalations?search=123" in staff_notice_call.args[1].answer
    assert (
        "- Reply in thread with `/send <edited reply>`"
        in staff_notice_call.args[1].answer
    )
    assert "- Reply in thread with `/dismiss`" in staff_notice_call.args[1].answer
    assert (
        "- React `👍` to send only the copy-ready reply to the user."
        in staff_notice_call.args[1].answer
    )
    assert "- React `👎` to dismiss with no reply." in staff_notice_call.args[1].answer
    assert staff_notice_call.args[1].message_id == "staff-escalation-123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_staff_room_can_be_silent_to_user_when_notice_mode_is_none():
    incoming = SimpleNamespace(
        message_id="m-5b",
        question="trade stuck at payout",
        channel_metadata={
            "room_id": "!support:matrix.org",
            "staff_room_id": "!staff:matrix.org",
        },
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.1,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=125)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="staff_room",
        escalation_user_notice_mode="none",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    channel.send_message.assert_awaited_once()
    staff_notice_call = channel.send_message.await_args_list[0]
    assert staff_notice_call.args[0] == "!staff:matrix.org"
    assert "Escalation #125 for matrix" in staff_notice_call.args[1].answer
    assert "Reply to user (copy-ready):" in staff_notice_call.args[1].answer
    assert "draft" in staff_notice_call.args[1].answer
    assert staff_notice_call.args[1].message_id == "staff-escalation-125"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_staff_room_notice_includes_copyable_source_links():
    incoming = SimpleNamespace(
        message_id="m-5c",
        question="how to recover trade",
        channel_metadata={
            "room_id": "!support:matrix.org",
            "staff_room_id": "!staff:matrix.org",
        },
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[
            SimpleNamespace(
                title="Bisq Easy docs", url="https://docs.bisq.network/easy"
            ),
            SimpleNamespace(title="FAQ entry", url="https://faq.bisq.network/q/123"),
        ],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.55,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=126)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="staff_room",
        escalation_user_notice_mode="none",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    channel.send_message.assert_awaited_once()
    staff_notice = channel.send_message.await_args_list[0].args[1].answer
    assert "Sources to copy:" in staff_notice
    assert "- Bisq Easy docs: https://docs.bisq.network/easy" in staff_notice
    assert "- FAQ entry: https://faq.bisq.network/q/123" in staff_notice


@pytest.mark.unit
@pytest.mark.asyncio
async def test_staff_room_notice_includes_internal_code_enrichment_without_replacing_copy_ready_reply():
    incoming = SimpleNamespace(
        message_id="m-5d",
        question="why can I not create a sell offer",
        channel_metadata={
            "room_id": "!support:matrix.org",
            "staff_room_id": "!staff:matrix.org",
        },
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="Ask for the exact error text before suggesting changes.",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="queue_medium",
            routing_reason="Codebase evidence attached for staff-room review.",
            confidence_score=0.91,
            staff_enriched_answer=(
                "Ask for the exact error text before suggesting changes.\n\n"
                "Staff-only codebase context:\n"
                "- Sell offer creation checks reputation."
            ),
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=127)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="staff_room",
        escalation_user_notice_mode="none",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    channel.send_message.assert_awaited_once()
    staff_notice = channel.send_message.await_args_list[0].args[1].answer
    assert "Reply to user (copy-ready):" in staff_notice
    assert "Ask for the exact error text before suggesting changes." in staff_notice
    assert "Customer-safe codebase draft" not in staff_notice
    assert "Review and send with `/send <edited reply>`" not in staff_notice
    assert "Codebase-enriched staff context" in staff_notice
    assert "Staff-only codebase context" in staff_notice
    assert "Sell offer creation checks reputation." in staff_notice
    assert "not sent by reactions or `/send`" in staff_notice
    assert "- React `👍` to send only the copy-ready reply to the user." in staff_notice


@pytest.mark.unit
def test_staff_room_notice_deduplicates_static_safety_warning_from_enrichment():
    incoming = SimpleNamespace(
        question="An app asked me to enter my seed phrase.",
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer=f"{SAFETY_REFLEX_WARNING}\n\nCopy-ready safety detail.",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="queue_medium",
            routing_reason="Codebase evidence attached for staff-room review.",
            confidence_score=0.91,
            staff_enriched_answer=(
                f"{SAFETY_REFLEX_WARNING}\n\nCopy-ready safety detail.\n\n"
                "Staff-only codebase context:\n- Never request seed words."
            ),
        ),
    )
    dispatcher = ChannelResponseDispatcher(channel=MagicMock(), channel_id="matrix")

    notice = dispatcher._build_staff_room_escalation_notice_response(
        incoming=incoming,
        response=response,
        escalation=SimpleNamespace(id=128),
    )

    assert notice.answer.count(SAFETY_REFLEX_WARNING) == 1
    assert "Copy-ready safety detail." in notice.answer
    assert "Staff-only codebase context" in notice.answer
    assert "Never request seed words." in notice.answer


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_falls_back_to_message_for_unsupported_user_notice_mode():
    incoming = SimpleNamespace(
        message_id="m-5c",
        question="trade stuck at payout",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.1,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=126)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="none",
        escalation_user_notice_mode="reaction",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    channel = MagicMock()
    channel.runtime = runtime
    channel.get_delivery_target.return_value = "!support:matrix.org"
    channel.send_message = AsyncMock(return_value=True)

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    channel.send_message.assert_awaited_once()
    sent_notice = channel.send_message.call_args.args[1]
    assert "team member" in sent_notice.answer.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_resolves_staff_room_from_channel_method():
    incoming = SimpleNamespace(
        message_id="m-6",
        question="trade stuck at payout",
        channel_metadata={"room_id": "!support:matrix.org"},
        user=SimpleNamespace(
            user_id="@alice:matrix.org", channel_user_id="@alice:matrix.org"
        ),
    )
    response = SimpleNamespace(
        requires_human=True,
        answer="draft",
        sources=[],
        metadata=SimpleNamespace(
            routing_action="needs_human",
            routing_reason="manual_review",
            confidence_score=0.1,
        ),
    )
    escalation_service = AsyncMock()
    escalation_service.create_escalation = AsyncMock(
        return_value=SimpleNamespace(id=124)
    )

    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        public_escalation_notice_enabled=False,
        escalation_notification_channel="staff_room",
        escalation_user_notice_template="this needs a team member. someone will follow up.",
    )
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(
        side_effect=lambda name: (
            policy_service if name == "channel_autoresponse_policy_service" else None
        )
    )

    class _MatrixChannelStub:
        def __init__(self):
            self.runtime = runtime
            self.send_message = AsyncMock(return_value=True)

        def get_delivery_target(self, _metadata):
            return "!support:matrix.org"

        def get_staff_notification_target(self, _metadata):
            return "!staff-from-method:matrix.org"

    channel = _MatrixChannelStub()

    dispatcher = ChannelResponseDispatcher(
        channel=channel,
        channel_id="matrix",
        escalation_service=escalation_service,
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is DispatchOutcome.QUEUED
    assert channel.send_message.await_count == 2
    staff_notice_call = channel.send_message.await_args_list[1]
    assert staff_notice_call.args[0] == "!staff-from-method:matrix.org"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_review_queued_reports_success_when_staff_notice_sends():
    dispatcher = ChannelResponseDispatcher(
        channel=MagicMock(),
        channel_id="matrix",
        launch_control_service=ALLOWING_LAUNCH_CONTROL,
    )
    dispatcher._notification_channel_mode = MagicMock(return_value="staff_room")
    dispatcher._send_user_escalation_notice = AsyncMock(return_value=False)
    dispatcher._send_staff_room_escalation_notice = AsyncMock(return_value=True)

    sent = await dispatcher.notify_review_queued(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert sent is True


@pytest.mark.unit
def test_format_source_lines_supports_dict_sources():
    dispatcher = ChannelResponseDispatcher(channel=None, channel_id="matrix")

    lines = dispatcher._build_staff_notice_source_lines(
        [{"title": "Doc 1", "url": "https://example.org"}],
        limit=5,
    )

    assert lines == ["- Doc 1: https://example.org"]
