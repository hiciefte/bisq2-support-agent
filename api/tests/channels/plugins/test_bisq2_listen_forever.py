"""Tests for Bisq2 WebSocket listen_forever loop."""

import json
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
    callback = AsyncMock(side_effect=lambda event: setattr(client, "_listening", False))
    client.on_event(callback)

    ws1 = MagicMock()
    ws1.recv = AsyncMock(side_effect=FakeConnectionClosed("closed"))
    client._connected = True
    client._ws = ws1
    client._subscriptions = ["SUPPORT_CHAT_REACTIONS"]

    ws2 = MagicMock()
    ws2.send = AsyncMock()
    ws2.recv = AsyncMock(
        side_effect=[
            json.dumps(
                {
                    "responseType": "SubscriptionResponse",
                    "requestId": "1",
                    "success": True,
                    "payload": [],
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
    callback.assert_called_once()


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
