"""Tests for channel feedback follow-up coordinator."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.feedback_followup import FeedbackFollowupCoordinator
from app.channels.models import ChannelType, IncomingMessage, UserContext
from app.channels.reactions import SentMessageRecord


def _record() -> SentMessageRecord:
    return SentMessageRecord(
        internal_message_id="int-1",
        external_message_id="ext-1",
        channel_id="bisq2",
        question="Q",
        answer="A",
        user_id="user-1",
        timestamp=datetime.now(timezone.utc),
        delivery_target="support.support",
    )


@pytest.mark.asyncio
async def test_start_followup_sends_prompt_when_channel_registered() -> None:
    feedback_service = MagicMock()
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)

    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        ttl_seconds=900,
    )

    started = await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    assert started is True
    channel.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_consume_if_pending_updates_feedback_and_acks() -> None:
    feedback_service = MagicMock()
    feedback_service.analyze_feedback_text = AsyncMock(return_value=["incomplete"])
    feedback_service.update_feedback_entry = AsyncMock(return_value=True)
    channel = MagicMock()
    channel.send_message = AsyncMock(return_value=True)
    channel.get_delivery_target = MagicMock(return_value="support.support")
    registry = MagicMock()
    registry.get = MagicMock(return_value=channel)

    coordinator = FeedbackFollowupCoordinator(
        feedback_service=feedback_service,
        channel_registry=registry,
        ttl_seconds=900,
    )

    await coordinator.start_followup(
        record=_record(),
        channel_id="bisq2",
        external_message_id="ext-1",
        reactor_id="user-1",
        reactor_identity_hash="hash-1",
    )

    incoming = IncomingMessage(
        message_id="m-2",
        channel=ChannelType.BISQ2,
        question="The answer missed trade limits.",
        user=UserContext(user_id="user-1", channel_user_id="user-1"),
        channel_metadata={"conversation_id": "support.support"},
        channel_signature=None,
    )

    consumed = await coordinator.consume_if_pending(incoming=incoming, channel=channel)

    assert consumed is True
    feedback_service.update_feedback_entry.assert_awaited_once()
    assert channel.send_message.await_count >= 2
