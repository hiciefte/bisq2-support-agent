from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channels.services.live_polling_service import LivePollingService


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_once_does_not_poll_when_generation_disabled():
    channel = MagicMock()
    channel.channel_id = "bisq2"
    channel.poll_conversations = AsyncMock(
        return_value=[SimpleNamespace(message_id="m1")]
    )

    service = LivePollingService(channel=channel, channel_id="bisq2")

    with patch(
        "app.channels.services.live_polling_service.is_generation_enabled",
        return_value=False,
    ):
        processed = await service.run_once()

    assert processed == 0
    channel.poll_conversations.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_once_polls_and_dispatches_when_generation_enabled():
    incoming = SimpleNamespace(message_id="m1")
    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )
    channel = MagicMock()
    channel.channel_id = "bisq2"
    channel.poll_conversations = AsyncMock(return_value=[incoming])
    channel.handle_incoming = AsyncMock(return_value=response)

    service = LivePollingService(channel=channel, channel_id="bisq2")
    service.dispatcher.dispatch = AsyncMock(return_value=True)

    with patch(
        "app.channels.services.live_polling_service.is_generation_enabled",
        return_value=True,
    ), patch(
        "app.channels.services.live_polling_service.is_autosend_enabled",
        return_value=True,
    ):
        processed = await service.run_once()

    assert processed == 1
    channel.poll_conversations.assert_awaited_once()
    channel.handle_incoming.assert_awaited_once_with(incoming)
    service.dispatcher.dispatch.assert_awaited_once_with(incoming, response)
