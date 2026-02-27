"""Tests for Bisq2 live chat polling/response service."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.plugins.bisq2.services.live_chat_service import Bisq2LiveChatService


def _incoming(message_id: str = "m-1", conversation_id: str = "support.support"):
    msg = MagicMock()
    msg.message_id = message_id
    msg.question = "What is Bisq Easy?"
    msg.channel_metadata = {"conversation_id": conversation_id}
    msg.user = MagicMock()
    msg.user.user_id = "user-1"
    msg.user.channel_user_id = "alice"
    return msg


def _outgoing(routing_action: str = "auto_send", requires_human: bool = False):
    msg = MagicMock()
    msg.answer = "Bisq Easy is a protocol in Bisq 2."
    msg.original_question = "What is Bisq Easy?"
    msg.sources = []
    msg.metadata = MagicMock()
    msg.metadata.routing_action = routing_action
    msg.metadata.routing_reason = "Low confidence"
    msg.metadata.confidence_score = 0.71
    msg.requires_human = requires_human
    return msg


def _policy_service(enabled: bool = True, generation_enabled: bool = True):
    policy_service = MagicMock()
    policy_service.get_policy.return_value = MagicMock(
        enabled=enabled,
        generation_enabled=generation_enabled,
    )
    return policy_service


@pytest.mark.asyncio
async def test_run_once_polls_and_sends_responses() -> None:
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="auto_send")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=_policy_service(),
        poll_interval_seconds=0.01,
    )

    processed = await service.run_once()

    assert processed == 1
    channel.poll_conversations.assert_awaited_once()
    channel.handle_incoming.assert_awaited_once_with(incoming)
    channel.send_message.assert_awaited_once_with("support.support", outgoing)


@pytest.mark.asyncio
async def test_run_once_skips_message_without_delivery_target() -> None:
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="auto_send")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="")
    channel.send_message = AsyncMock(return_value=True)

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=_policy_service(),
        poll_interval_seconds=0.01,
    )

    processed = await service.run_once()

    assert processed == 0
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_creates_escalation_for_non_autosend_routing_actions() -> None:
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="queue_medium")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(return_value=MagicMock(id=123))

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=_policy_service(),
        escalation_service=escalation_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 0
    channel.send_message.assert_awaited_once()
    queued_notification = channel.send_message.call_args.args[1]
    assert "review" in queued_notification.answer.lower()
    assert "#123" in queued_notification.answer
    assert queued_notification.requires_human is True
    escalation_service.create_escalation.assert_awaited_once()
    escalation_payload = escalation_service.create_escalation.call_args.args[0]
    assert escalation_payload.message_id == incoming.message_id
    assert escalation_payload.question == incoming.question
    assert escalation_payload.routing_action == "queue_medium"


@pytest.mark.asyncio
async def test_run_once_sends_clarification_messages_without_escalation() -> None:
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="needs_clarification")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(return_value=MagicMock(id=456))

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=_policy_service(),
        escalation_service=escalation_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 1
    channel.send_message.assert_awaited_once_with("support.support", outgoing)
    escalation_service.create_escalation.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_fails_open_and_sends_for_unknown_routing_action() -> None:
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(return_value=MagicMock(id=999))

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=_policy_service(),
        escalation_service=escalation_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 1
    channel.send_message.assert_awaited_once_with("support.support", outgoing)
    escalation_service.create_escalation.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_skips_when_channel_autoresponse_disabled() -> None:
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="auto_send")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)

    policy_service = MagicMock()
    policy_service.get_policy.return_value = MagicMock(enabled=False)

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=policy_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 0
    channel.handle_incoming.assert_not_awaited()
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_skips_when_policy_lookup_fails_and_default_is_disabled() -> (
    None
):
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="auto_send")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)

    policy_service = MagicMock()
    policy_service.get_policy.side_effect = RuntimeError("db unavailable")

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=policy_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 0
    channel.handle_incoming.assert_not_awaited()
    channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_queues_for_review_when_generation_enabled_and_autosend_disabled() -> (
    None
):
    channel = MagicMock()
    incoming = _incoming()
    outgoing = _outgoing(routing_action="auto_send")
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    channel.send_message = AsyncMock(return_value=True)

    policy_service = MagicMock()
    policy_service.get_policy.return_value = MagicMock(
        enabled=False,
        generation_enabled=True,
    )

    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(return_value=MagicMock(id=123))

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=policy_service,
        escalation_service=escalation_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 0
    channel.handle_incoming.assert_awaited_once_with(incoming)
    channel.send_message.assert_awaited_once()
    queued_notification = channel.send_message.call_args.args[1]
    assert queued_notification.requires_human is True
    escalation_service.create_escalation.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_ignores_messages_when_ai_generation_disabled() -> None:
    channel = MagicMock()
    incoming = _incoming()
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="support.support")

    followup_coordinator = MagicMock()
    followup_coordinator.consume_if_pending = AsyncMock(return_value=True)
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=followup_coordinator)
    channel.runtime = runtime

    policy_service = MagicMock()
    policy_service.get_policy.return_value = MagicMock(enabled=False)

    service = Bisq2LiveChatService(
        channel=channel,
        autoresponse_policy_service=policy_service,
        poll_interval_seconds=0.01,
    )
    processed = await service.run_once()

    assert processed == 0
    followup_coordinator.consume_if_pending.assert_not_awaited()
    channel.handle_incoming.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_and_stop_manage_background_task() -> None:
    channel = MagicMock()
    channel.start = AsyncMock(return_value=None)
    channel.stop = AsyncMock(return_value=None)
    channel.poll_conversations = AsyncMock(return_value=[])

    service = Bisq2LiveChatService(channel=channel, poll_interval_seconds=0.01)

    await service.start()
    await asyncio.sleep(0.03)
    assert service.is_running is True
    channel.start.assert_awaited_once()

    await service.stop()
    assert service.is_running is False
    channel.stop.assert_awaited_once()
