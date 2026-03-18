from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.response_dispatcher import (
    ChannelResponseDispatcher,
    DeliveryMode,
    format_escalation_notice,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_autosend_returns_false_when_transport_raises():
    incoming = SimpleNamespace(message_id="m-1", channel_metadata={})
    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )
    channel = MagicMock()
    channel.get_delivery_target.return_value = "target-1"
    channel.send_message = AsyncMock(side_effect=RuntimeError("network failure"))

    dispatcher = ChannelResponseDispatcher(channel=channel, channel_id="bisq2")
    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
    channel.send_message.assert_awaited_once_with("target-1", response)


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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is True
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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    notice = channel.send_message.call_args.args[1]
    assert "team member" in notice.answer.lower()
    assert "#77" not in notice.answer


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

    assert sent is False
    escalation_service.create_escalation.assert_awaited_once()
    channel.send_message.assert_awaited_once()
    notice = channel.send_message.call_args.args[1]
    assert "#88" not in notice.answer
    assert "team member" in notice.answer.lower()
    assert "follow up" in notice.answer.lower()


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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
    channel.send_message.assert_awaited_once()
    notice = channel.send_message.call_args.args[1]
    assert "#99" not in notice.answer
    assert "team member" in notice.answer.lower()


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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
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
        "- React `👍` to send the reply above to the user."
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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
    channel.send_message.assert_awaited_once()
    staff_notice = channel.send_message.await_args_list[0].args[1].answer
    assert "Sources to copy:" in staff_notice
    assert "- Bisq Easy docs: https://docs.bisq.network/easy" in staff_notice
    assert "- FAQ entry: https://faq.bisq.network/q/123" in staff_notice


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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
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
    )

    sent = await dispatcher.dispatch(incoming, response)

    assert sent is False
    assert channel.send_message.await_count == 2
    staff_notice_call = channel.send_message.await_args_list[1]
    assert staff_notice_call.args[0] == "!staff-from-method:matrix.org"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_notify_review_queued_reports_success_when_staff_notice_sends():
    dispatcher = ChannelResponseDispatcher(channel=MagicMock(), channel_id="matrix")
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
