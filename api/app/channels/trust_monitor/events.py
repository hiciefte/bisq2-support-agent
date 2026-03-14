from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.channels.trust_monitor.models import ALLOWED_EVENT_TYPES, TrustEventType


@dataclass(slots=True)
class TrustEvent:
    channel_id: str
    space_id: str
    actor_id: str
    actor_display_name: str
    event_type: TrustEventType
    occurred_at: datetime
    external_event_id: str | None = None
    thread_id: str | None = None
    target_actor_id: str | None = None
    target_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_type.value not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"Unsupported trust-monitor event type: {self.event_type}")
        if self.occurred_at.tzinfo is None:
            self.occurred_at = self.occurred_at.replace(tzinfo=UTC)
        if not self.channel_id.strip():
            raise ValueError("channel_id is required")
        if not self.space_id.strip():
            raise ValueError("space_id is required")
        if not self.actor_id.strip():
            raise ValueError("actor_id is required")
