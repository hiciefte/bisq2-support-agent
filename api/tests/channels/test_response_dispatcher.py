from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.response_dispatcher import ChannelResponseDispatcher


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
