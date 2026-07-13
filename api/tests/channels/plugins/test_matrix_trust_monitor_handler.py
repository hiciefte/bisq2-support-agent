from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app.channels.plugins.matrix.trust_monitor_handler import MatrixTrustMonitorHandler


class DummyMemberEvent:
    pass


class DummyReceiptEvent:
    pass


@pytest.mark.asyncio
async def test_member_event_is_forwarded_to_service(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.channels.plugins.matrix.trust_monitor_handler.RoomMemberEvent",
        DummyMemberEvent,
    )
    service = MagicMock()
    client = MagicMock()
    connection_manager = MagicMock()
    connection_manager.sync_forever = MagicMock()
    handler = MatrixTrustMonitorHandler(
        client=client,
        trust_monitor_service=service,
        allowed_room_ids=["!support:matrix.org"],
        staff_room_id="!staff:matrix.org",
    )

    room = MagicMock(room_id="!support:matrix.org")
    event = DummyMemberEvent()
    event.sender = "@copycat:matrix.org"
    event.event_id = "$member-1"
    event.server_timestamp = int(datetime.now(UTC).timestamp() * 1000)
    event.membership = "join"
    event.displayname = "Alice Support"

    await handler._on_member_event(room, event)

    service.ingest_event.assert_called_once()
    forwarded = service.ingest_event.call_args.args[0]
    assert forwarded.event_type.value == "member_joined"
    assert forwarded.actor_display_name == "Alice Support"


@pytest.mark.asyncio
async def test_member_event_does_not_wait_for_default_executor(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.channels.plugins.matrix.trust_monitor_handler.RoomMemberEvent",
        DummyMemberEvent,
    )
    service = MagicMock()
    handler = MatrixTrustMonitorHandler(
        client=MagicMock(),
        trust_monitor_service=service,
        allowed_room_ids=["!support:matrix.org"],
        staff_room_id="!staff:matrix.org",
    )
    room = MagicMock(room_id="!support:matrix.org")
    event = DummyMemberEvent()
    event.sender = "@copycat:matrix.org"
    event.event_id = "$member-dedicated-executor"
    event.server_timestamp = int(datetime.now(UTC).timestamp() * 1000)
    event.membership = "join"
    event.displayname = "Alice Support"

    blocker_started = threading.Event()
    blocker_release = threading.Event()

    def block_default_executor() -> None:
        blocker_started.set()
        blocker_release.wait(timeout=2)

    loop = asyncio.get_running_loop()
    default_executor = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(default_executor)
    blocker = loop.run_in_executor(None, block_default_executor)

    async def wait_for_blocker() -> None:
        while not blocker_started.is_set():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_blocker(), timeout=1)

    try:
        await asyncio.wait_for(handler._on_member_event(room, event), timeout=0.5)
    finally:
        blocker_release.set()
        await blocker
        default_executor.shutdown(wait=True)

    service.ingest_event.assert_called_once()


@pytest.mark.asyncio
async def test_member_event_ignores_non_join_memberships(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.channels.plugins.matrix.trust_monitor_handler.RoomMemberEvent",
        DummyMemberEvent,
    )
    service = MagicMock()
    client = MagicMock()
    handler = MatrixTrustMonitorHandler(
        client=client,
        trust_monitor_service=service,
        allowed_room_ids=["!support:matrix.org"],
        staff_room_id="!staff:matrix.org",
    )

    room = MagicMock(room_id="!support:matrix.org")
    event = DummyMemberEvent()
    event.sender = "@copycat:matrix.org"
    event.event_id = "$member-2"
    event.server_timestamp = int(datetime.now(UTC).timestamp() * 1000)
    event.membership = "leave"

    await handler._on_member_event(room, event)

    service.ingest_event.assert_not_called()


@pytest.mark.asyncio
async def test_receipts_ignore_staff_room(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.channels.plugins.matrix.trust_monitor_handler.ReceiptEvent",
        DummyReceiptEvent,
    )
    service = MagicMock()
    client = MagicMock()
    handler = MatrixTrustMonitorHandler(
        client=client,
        trust_monitor_service=service,
        allowed_room_ids=["!support:matrix.org"],
        staff_room_id="!staff:matrix.org",
    )

    room = MagicMock(room_id="!staff:matrix.org")
    event = DummyReceiptEvent()
    event.source = {
        "content": {
            "$message-1": {
                "m.read": {
                    "@lurker:matrix.org": {
                        "ts": int(datetime.now(UTC).timestamp() * 1000)
                    },
                }
            }
        }
    }

    await handler._on_receipt_event(room, event)

    service.ingest_event.assert_not_called()


@pytest.mark.asyncio
async def test_receipts_emit_message_read_events(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.channels.plugins.matrix.trust_monitor_handler.ReceiptEvent",
        DummyReceiptEvent,
    )
    service = MagicMock()
    client = MagicMock()
    handler = MatrixTrustMonitorHandler(
        client=client,
        trust_monitor_service=service,
        allowed_room_ids=["!support:matrix.org"],
        staff_room_id="!staff:matrix.org",
    )

    room = MagicMock(room_id="!support:matrix.org")
    event = DummyReceiptEvent()
    event.source = {
        "content": {
            "$message-1": {
                "m.read": {
                    "@lurker:matrix.org": {
                        "ts": int(datetime.now(UTC).timestamp() * 1000)
                    },
                }
            }
        }
    }

    await handler._on_receipt_event(room, event)

    assert service.ingest_event.call_count == 1
    forwarded = service.ingest_event.call_args.args[0]
    assert forwarded.event_type.value == "message_read"
    assert forwarded.target_message_id == "$message-1"
