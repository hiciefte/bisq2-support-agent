from __future__ import annotations

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
