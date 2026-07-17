"""Tests for Bisq2 WebSocket listen_forever loop."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.plugins.bisq2.client import websocket as ws_module
from app.channels.plugins.bisq2.client.websocket import Bisq2WebSocketClient


@pytest.mark.asyncio
async def test_listen_forever_dispatches_events() -> None:
    client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
    callback = AsyncMock()
    client.on_event(callback)

    ws = MagicMock()
    ws.recv = AsyncMock(
        return_value=json.dumps(
            {
                "type": "WebSocketEvent",
                "payload": {"reaction": "THUMBS_UP"},
            }
        )
    )
    client._connected = True
    client._ws = ws

    async def stop_after_first(raw: str) -> None:
        await Bisq2WebSocketClient._handle_message(client, raw)
        client._listening = False

    client._handle_message = AsyncMock(side_effect=stop_after_first)

    await client.listen_forever(reconnect_delay_seconds=0)

    callback.assert_called_once()


@pytest.mark.asyncio
async def test_listen_forever_reconnects_and_resubscribes(monkeypatch) -> None:
    class FakeConnectionClosed(Exception):
        pass

    monkeypatch.setattr(ws_module, "ConnectionClosed", FakeConnectionClosed)
    monkeypatch.setattr(
        ws_module.asyncio,
        "sleep",
        AsyncMock(return_value=None),
    )

    client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
    order: list[str] = []

    async def on_snapshot(topic, _parameter, payload) -> None:
        assert topic == "SUPPORT_CHAT_MESSAGES"
        assert payload == '[{"messageId":"snapshot-message"}]'
        order.append("snapshot")

    async def on_event(_event) -> None:
        order.append("incremental")
        client._listening = False

    callback = AsyncMock(side_effect=on_event)
    client.on_event(callback)
    client.on_subscription_snapshot(on_snapshot)

    ws1 = MagicMock()
    ws1.close = AsyncMock()
    ws1.recv = AsyncMock(side_effect=FakeConnectionClosed("closed"))
    client._connected = True
    client._ws = ws1
    client._subscriptions = [("SUPPORT_CHAT_MESSAGES", None)]

    ws2 = MagicMock()
    ws2.send = AsyncMock()
    ws2.recv = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "type": "SubscriptionResponse",
                    "requestId": "1",
                    "payload": '[{"messageId":"snapshot-message"}]',
                    "errorMessage": None,
                }
            ),
            json.dumps(
                {
                    "type": "WebSocketEvent",
                    "payload": {"reaction": "THUMBS_UP"},
                }
            ),
        ]
    )

    monkeypatch.setattr(
        ws_module,
        "websockets_connect",
        AsyncMock(return_value=ws2),
    )

    await client.listen_forever(reconnect_delay_seconds=0)

    ws2.send.assert_called_once()
    ws1.close.assert_awaited_once()
    callback.assert_called_once()
    assert order == ["snapshot", "incremental"]


@pytest.mark.asyncio
async def test_reconnect_ack_only_support_message_reaches_channel_buffer(
    monkeypatch,
) -> None:
    """An unseen scoped message in a reconnect snapshot is not discarded."""
    from app.channels.plugins.bisq2.channel import Bisq2Channel
    from app.channels.runtime import ChannelRuntime

    class FakeConnectionClosed(Exception):
        pass

    settings = SimpleNamespace(
        BISQ2_ALLOWED_CHANNEL_IDS=["channel-allowed"],
        BISQ2_ALLOWED_SENDER_PROFILE_IDS=["profile-allowed"],
        BISQ2_CHATOPS_CHANNEL_IDS=[],
        BISQ2_STAFF_PROFILE_IDS=[],
        BISQ2_STAFF_NOTIFICATION_TARGET="",
    )
    runtime = MagicMock(spec=ChannelRuntime)
    runtime.settings = settings
    runtime.resolve_optional = MagicMock(return_value=None)
    channel = Bisq2Channel(runtime)
    channel._support_subscription_established = True
    channel._scope_rebaseline_pending = False
    channel._last_poll_since = datetime.fromtimestamp(0, tz=UTC)
    client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
    client._subscriptions = [("SUPPORT_CHAT_MESSAGES", None)]

    async def reconcile_and_stop(topic, parameter, payload) -> None:
        await channel._on_support_subscription_snapshot(topic, parameter, payload)
        client._listening = False

    client.on_subscription_snapshot(reconcile_and_stop)

    ws1 = MagicMock()
    ws1.close = AsyncMock()
    ws1.recv = AsyncMock(side_effect=FakeConnectionClosed("closed"))
    client._connected = True
    client._ws = ws1

    snapshot_message = {
        "messageId": "snapshot-only-message",
        "channelId": "channel-allowed",
        "conversationId": "channel-allowed",
        "senderUserProfileId": "profile-allowed",
        "author": "Allowed user",
        "text": "Was this reconnect-only question retained?",
        "timestamp": 100,
    }
    ws2 = MagicMock()
    ws2.close = AsyncMock()
    ws2.send = AsyncMock()
    ws2.recv = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "type": "SubscriptionResponse",
                    "requestId": "1",
                    "payload": json.dumps([snapshot_message]),
                    "errorMessage": None,
                }
            ),
            FakeConnectionClosed("stop after snapshot"),
        ]
    )

    monkeypatch.setattr(ws_module, "ConnectionClosed", FakeConnectionClosed)
    monkeypatch.setattr(ws_module.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(ws_module, "websockets_connect", AsyncMock(return_value=ws2))

    await client.listen_forever(reconnect_delay_seconds=0)

    assert [message["messageId"] for message in channel._ws_message_buffer] == [
        "snapshot-only-message"
    ]
    assert channel._support_snapshot_reconciled is True
    ws2.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_negative_reconnect_ack_clears_active_subscription(monkeypatch) -> None:
    class FakeConnectionClosed(Exception):
        pass

    client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
    client._subscriptions = [("SUPPORT_CHAT_REACTIONS", None)]
    client._active_subscriptions.add(("SUPPORT_CHAT_REACTIONS", None))

    ws1 = MagicMock()
    ws1.close = AsyncMock()
    ws1.recv = AsyncMock(side_effect=FakeConnectionClosed("closed"))
    client._connected = True
    client._ws = ws1

    ws2 = MagicMock()
    ws2.close = AsyncMock()
    ws2.send = AsyncMock()
    ws2.recv = AsyncMock(
        return_value=json.dumps(
            {
                "type": "SubscriptionResponse",
                "requestId": "1",
                "payload": None,
                "errorMessage": "rejected",
            }
        )
    )

    sleep_count = 0

    async def stop_after_negative_ack(_delay: float) -> None:
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 2:
            client._listening = False

    monkeypatch.setattr(ws_module, "ConnectionClosed", FakeConnectionClosed)
    monkeypatch.setattr(ws_module.asyncio, "sleep", stop_after_negative_ack)
    monkeypatch.setattr(ws_module, "websockets_connect", AsyncMock(return_value=ws2))

    await client.listen_forever(reconnect_delay_seconds=0)

    assert client.is_connected is False
    assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS") is False
    ws1.close.assert_awaited_once()
    ws2.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconnect_continues_after_subscription_ack_timeout(monkeypatch) -> None:
    class FakeConnectionClosed(Exception):
        pass

    client = Bisq2WebSocketClient(
        url="ws://localhost:8090/websocket",
        connect_timeout_seconds=0.01,
        subscription_timeout_seconds=0.01,
    )
    client._subscriptions = [("SUPPORT_CHAT_REACTIONS", None)]
    callback = AsyncMock(
        side_effect=lambda _event: setattr(client, "_listening", False)
    )
    client.on_event(callback)

    ws1 = MagicMock()
    ws1.close = AsyncMock()
    ws1.recv = AsyncMock(side_effect=FakeConnectionClosed("closed"))
    client._connected = True
    client._ws = ws1

    no_ack = asyncio.Event()
    no_close = asyncio.Event()
    ws2 = MagicMock()
    ws2.close = AsyncMock(side_effect=no_close.wait)
    ws2.send = AsyncMock()
    ws2.recv = AsyncMock(side_effect=no_ack.wait)

    ws3 = MagicMock()
    ws3.close = AsyncMock()
    ws3.send = AsyncMock()
    ws3.recv = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "type": "SubscriptionResponse",
                    "requestId": "2",
                    "payload": "[]",
                    "errorMessage": None,
                }
            ),
            json.dumps(
                {
                    "type": "WebSocketEvent",
                    "payload": {"reaction": "THUMBS_UP"},
                }
            ),
        ]
    )

    connect = AsyncMock(side_effect=[ws2, ws3])
    monkeypatch.setattr(ws_module, "ConnectionClosed", FakeConnectionClosed)
    monkeypatch.setattr(ws_module.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(ws_module, "websockets_connect", connect)

    await client.listen_forever(reconnect_delay_seconds=0)

    assert connect.await_count == 2
    ws1.close.assert_awaited_once()
    ws2.close.assert_awaited_once()
    ws3.send.assert_awaited_once()
    callback.assert_awaited_once()
    assert client.has_active_subscription("SUPPORT_CHAT_REACTIONS") is True


@pytest.mark.asyncio
async def test_handle_message_parses_string_payload_json() -> None:
    client = Bisq2WebSocketClient(url="ws://localhost:8090/websocket")
    callback = AsyncMock()
    client.on_event(callback)

    await client._handle_message(
        json.dumps(
            {
                "type": "WebSocketEvent",
                "payload": '{"reaction":"THUMBS_UP","messageId":"m-1"}',
            }
        )
    )

    callback.assert_called_once()
    event = callback.call_args[0][0]
    assert isinstance(event["payload"], dict)
    assert event["payload"]["reaction"] == "THUMBS_UP"
