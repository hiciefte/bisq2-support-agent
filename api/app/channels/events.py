"""Canonical inbound event helpers for channel-agnostic orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from app.channels.models import IncomingMessage

_THREAD_METADATA_KEYS = (
    "thread_id",
    "conversation_id",
    "room_id",
    "channel_id",
    "session_id",
)


@dataclass(frozen=True)
class CanonicalInboundEvent:
    """Normalized inbound event representation used by shared orchestration."""

    event_id: str
    channel_id: str
    thread_id: str
    user_id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_incoming(
        cls, channel_id: str, incoming: IncomingMessage
    ) -> "CanonicalInboundEvent":
        metadata = _normalize_metadata(getattr(incoming, "channel_metadata", {}) or {})
        event_id = derive_event_id(incoming)
        user_id = str(
            getattr(getattr(incoming, "user", None), "user_id", "") or ""
        ).strip()
        thread_id = derive_thread_id(
            channel_id=channel_id,
            metadata=metadata,
            user_id=user_id,
            fallback_event_id=event_id,
        )
        text = str(getattr(incoming, "question", "") or "").strip()
        return cls(
            event_id=event_id,
            channel_id=str(channel_id or "").strip().lower(),
            thread_id=thread_id,
            user_id=user_id,
            text=text,
            metadata=metadata,
        )


def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        key_str = str(key or "").strip().lower()
        if not key_str:
            continue
        value_str = str(value or "").strip()
        if not value_str:
            continue
        normalized[key_str] = value_str
    return normalized


def derive_event_id(incoming: Any) -> str:
    message_id = str(getattr(incoming, "message_id", "") or "").strip()
    if message_id:
        return message_id
    return "unknown-event"


def derive_thread_id(
    *,
    channel_id: str,
    metadata: Mapping[str, Any] | None,
    user_id: str,
    fallback_event_id: str,
) -> str:
    normalized = _normalize_metadata(metadata or {})
    for key in _THREAD_METADATA_KEYS:
        value = normalized.get(key)
        if value:
            return value

    normalized_user = str(user_id or "").strip()
    if normalized_user:
        return normalized_user

    return str(fallback_event_id or "unknown-thread").strip() or "unknown-thread"


def dedup_key(channel_id: str, event_id: str) -> str:
    normalized_channel = str(channel_id or "").strip().lower() or "unknown"
    normalized_event = str(event_id or "").strip() or "unknown-event"
    return f"dedup:{normalized_channel}:{normalized_event}"


def thread_lock_key(channel_id: str, thread_id: str) -> str:
    normalized_channel = str(channel_id or "").strip().lower() or "unknown"
    normalized_thread = str(thread_id or "").strip() or "unknown-thread"
    return f"lock:{normalized_channel}:{normalized_thread}"


def thread_state_key(channel_id: str, thread_id: str) -> str:
    normalized_channel = str(channel_id or "").strip().lower() or "unknown"
    normalized_thread = str(thread_id or "").strip() or "unknown-thread"
    return f"thread:{normalized_channel}:{normalized_thread}"
