from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.response_dispatcher import (
    ChannelResponseDispatcher,
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

    assert "#42" in message
    assert "frage" in message.lower()


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
