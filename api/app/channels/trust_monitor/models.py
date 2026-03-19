from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TrustEventType(StrEnum):
    MEMBER_JOINED = "member_joined"
    IDENTITY_CHANGED = "identity_changed"
    MESSAGE_SENT = "message_sent"
    MESSAGE_REPLIED = "message_replied"
    MESSAGE_READ = "message_read"


class TrustAlertSurface(StrEnum):
    ADMIN_UI = "admin_ui"
    STAFF_ROOM = "staff_room"
    BOTH = "both"
    NONE = "none"


class TrustFindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"
    SUPPRESSED = "suppressed"
    BENIGN = "benign"


class TrustFeedbackAction(StrEnum):
    USEFUL = "useful"
    FALSE_POSITIVE = "false_positive"
    SUPPRESS = "suppress"
    RESOLVE = "resolve"
    MARK_BENIGN = "mark_benign"


@dataclass(slots=True)
class TrustActorProfile:
    channel_id: str
    actor_key: str
    actor_id: str
    current_display_name: str
    normalized_display_name: str
    trusted_staff: bool
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrustEvidenceRecord:
    id: int
    channel_id: str
    space_id: str
    thread_id: str | None
    actor_key: str
    actor_id: str
    actor_display_name: str
    event_type: TrustEventType
    target_actor_key: str | None
    target_actor_id: str | None
    target_message_id: str | None
    external_event_id: str | None
    occurred_at: datetime
    trusted_staff: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrustFinding:
    id: int
    detector_key: str
    channel_id: str
    space_id: str
    suspect_actor_key: str
    suspect_actor_id: str
    suspect_display_name: str
    score: float
    status: TrustFindingStatus
    alert_surface: TrustAlertSurface
    evidence_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_notified_at: datetime | None
    notification_count: int
    suppressed_until: datetime | None = None
    benign_until: datetime | None = None


@dataclass(slots=True)
class TrustFindingList:
    items: list[TrustFinding]
    total: int


@dataclass(slots=True)
class TrustFindingCounts:
    total: int = 0
    open: int = 0
    resolved: int = 0
    false_positive: int = 0
    suppressed: int = 0
    benign: int = 0


@dataclass(slots=True)
class TrustAccessAuditEntry:
    id: int
    actor_id: str
    action: str
    target_type: str
    target_id: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TrustPolicy:
    enabled: bool
    name_collision_enabled: bool
    silent_observer_enabled: bool
    alert_surface: TrustAlertSurface
    matrix_public_room_ids: list[str]
    matrix_staff_room_id: str
    silent_observer_window_days: int
    early_read_window_seconds: int
    minimum_observations: int
    minimum_early_read_hits: int
    read_to_reply_ratio_threshold: float
    evidence_ttl_days: int
    aggregate_ttl_days: int
    finding_ttl_days: int
    updated_at: datetime


ALLOWED_EVENT_TYPES = {event_type.value for event_type in TrustEventType}


def utc_now() -> datetime:
    return datetime.now(UTC)
