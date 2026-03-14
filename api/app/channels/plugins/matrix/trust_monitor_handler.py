from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.channels.plugins.matrix.room_filter import normalize_room_ids
from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.models import TrustEventType


class _MissingNioEvent:
    pass


RoomMemberEvent: Any = _MissingNioEvent
ReceiptEvent: Any = _MissingNioEvent

try:
    from nio import ReceiptEvent as _NioReceiptEvent
    from nio import RoomMemberEvent as _NioRoomMemberEvent
except ImportError:  # pragma: no cover
    pass
else:
    RoomMemberEvent = _NioRoomMemberEvent
    ReceiptEvent = _NioReceiptEvent


class MatrixTrustMonitorHandler:
    def __init__(
        self,
        *,
        client: Any,
        trust_monitor_service: Any,
        allowed_room_ids: Any,
        staff_room_id: str | None,
    ) -> None:
        self.client = client
        self.trust_monitor_service = trust_monitor_service
        self.allowed_room_ids = normalize_room_ids(allowed_room_ids)
        self.staff_room_id = str(staff_room_id or "").strip()
        self._callback_registered = False

    async def start(self) -> None:
        if self._callback_registered:
            return
        self.client.add_event_callback(self._on_member_event, RoomMemberEvent)
        self.client.add_event_callback(self._on_receipt_event, ReceiptEvent)
        self._callback_registered = True

    async def stop(self) -> None:
        if self._callback_registered and hasattr(self.client, "remove_event_callback"):
            self.client.remove_event_callback(self._on_member_event)
            self.client.remove_event_callback(self._on_receipt_event)
        self._callback_registered = False

    async def _on_member_event(self, room: Any, event: Any) -> None:
        room_id = str(getattr(room, "room_id", "") or "").strip()
        if room_id not in self.allowed_room_ids:
            return
        membership = str(getattr(event, "membership", "") or "").strip().lower()
        event_type = (
            TrustEventType.MEMBER_JOINED
            if membership == "join"
            else TrustEventType.IDENTITY_CHANGED
        )
        timestamp = getattr(event, "server_timestamp", None) or 0
        occurred_at = (
            datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            if timestamp
            else datetime.now(UTC)
        )
        self.trust_monitor_service.ingest_event(
            TrustEvent(
                channel_id="matrix",
                space_id=room_id,
                actor_id=str(getattr(event, "sender", "") or ""),
                actor_display_name=str(getattr(event, "displayname", "") or ""),
                event_type=event_type,
                occurred_at=occurred_at,
                external_event_id=str(getattr(event, "event_id", "") or ""),
            )
        )

    async def _on_receipt_event(self, room: Any, event: Any) -> None:
        room_id = str(getattr(room, "room_id", "") or "").strip()
        if room_id not in self.allowed_room_ids or room_id == self.staff_room_id:
            return
        content = getattr(event, "source", {}).get("content", {})
        for target_message_id, receipt_payload in content.items():
            readers = (
                receipt_payload.get("m.read", {})
                if isinstance(receipt_payload, dict)
                else {}
            )
            for actor_id, metadata in readers.items():
                ts = int((metadata or {}).get("ts") or 0)
                occurred_at = (
                    datetime.fromtimestamp(ts / 1000, tz=UTC)
                    if ts
                    else datetime.now(UTC)
                )
                self.trust_monitor_service.ingest_event(
                    TrustEvent(
                        channel_id="matrix",
                        space_id=room_id,
                        actor_id=str(actor_id),
                        actor_display_name="",
                        event_type=TrustEventType.MESSAGE_READ,
                        occurred_at=occurred_at,
                        external_event_id=f"receipt:{room_id}:{target_message_id}:{actor_id}:{ts}",
                        target_message_id=str(target_message_id),
                    )
                )
