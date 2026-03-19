"""Persistent channel-level autoresponse policy storage."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Iterable, List

from app.channels.registry import get_registered_channel_types

logger = logging.getLogger(__name__)

SUPPORTED_CHANNELS: tuple[str, ...] = ("web", "matrix", "bisq2")

DEFAULT_AUTORESPONSE_ENABLED: Dict[str, bool] = {
    "web": True,
    "matrix": False,
    "bisq2": False,
}
DEFAULT_GENERATION_ENABLED: Dict[str, bool] = {
    "web": True,
    "matrix": False,
    "bisq2": False,
}
DEFAULT_AI_RESPONSE_MODE: Dict[str, str] = {
    "web": "autonomous",
    "matrix": "autonomous",
    "bisq2": "autonomous",
}
DEFAULT_HITL_APPROVAL_TIMEOUT_SECONDS: Dict[str, int] = {
    "web": 0,
    "matrix": 3600,
    "bisq2": 3600,
}
DEFAULT_DRAFT_ASSISTANT_ENABLED: Dict[str, bool] = {
    "web": False,
    "matrix": True,
    "bisq2": True,
}
DEFAULT_KNOWLEDGE_AMPLIFIER_ENABLED: Dict[str, bool] = {
    "web": False,
    "matrix": True,
    "bisq2": True,
}
DEFAULT_STAFF_ASSIST_SURFACE: Dict[str, str] = {
    "web": "none",
    "matrix": "both",
    "bisq2": "both",
}
DEFAULT_FIRST_RESPONSE_DELAY_SECONDS: Dict[str, int] = {
    "web": 0,
    "matrix": 300,
    "bisq2": 300,
}
DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS: Dict[str, int] = {
    "web": 0,
    "matrix": 600,
    "bisq2": 600,
}
DEFAULT_MAX_PROACTIVE_AI_REPLIES_PER_QUESTION: Dict[str, int] = {
    "web": 1,
    "matrix": 1,
    "bisq2": 1,
}
DEFAULT_PUBLIC_ESCALATION_NOTICE_ENABLED: Dict[str, bool] = {
    "web": True,
    "matrix": False,
    "bisq2": False,
}
DEFAULT_ACKNOWLEDGMENT_MODE: Dict[str, str] = {
    "web": "none",
    "matrix": "reaction",
    "bisq2": "message",
}
DEFAULT_ACKNOWLEDGMENT_REACTION_KEY: Dict[str, str] = {
    "web": "👀",
    "matrix": "👀",
    "bisq2": "👀",
}
DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE: Dict[str, str] = {
    "web": "Thanks for your question. A team member or our assistant will respond shortly.",
    "matrix": "Thanks for your question. A team member or our assistant will respond shortly.",
    "bisq2": "Thanks for your question. A team member or our assistant will respond shortly.",
}
DEFAULT_GROUP_CLARIFICATION_IMMEDIATE: Dict[str, bool] = {
    "web": True,
    "matrix": False,
    "bisq2": False,
}
DEFAULT_ESCALATION_USER_NOTICE_TEMPLATE: Dict[str, str] = {
    "web": "This question needs a team member's attention. Someone will follow up.",
    "matrix": "this needs a team member's attention. someone will follow up.",
    "bisq2": "this needs a team member's attention. someone will follow up.",
}
DEFAULT_ESCALATION_USER_NOTICE_MODE: Dict[str, str] = {
    "web": "message",
    "matrix": "message",
    "bisq2": "message",
}
DEFAULT_DISPATCH_FAILURE_MESSAGE_TEMPLATE: Dict[str, str] = {
    "web": "We were unable to process your question automatically. A team member will follow up.",
    "matrix": "we couldn't process this automatically. a team member will follow up.",
    "bisq2": "we couldn't process this automatically. a team member will follow up.",
}
DEFAULT_ESCALATION_NOTIFICATION_CHANNEL: Dict[str, str] = {
    "web": "public_room",
    "matrix": "staff_room",
    "bisq2": "staff_room",
}
DEFAULT_EXPLICIT_INVOCATION_ENABLED: Dict[str, bool] = {
    "web": False,
    "matrix": True,
    "bisq2": True,
}
DEFAULT_EXPLICIT_INVOCATION_USER_RATE_LIMIT_PER_5M: Dict[str, int] = {
    "web": 0,
    "matrix": 3,
    "bisq2": 3,
}
DEFAULT_EXPLICIT_INVOCATION_ROOM_RATE_LIMIT_PER_MIN: Dict[str, int] = {
    "web": 0,
    "matrix": 6,
    "bisq2": 6,
}
DEFAULT_COMMUNITY_RESPONSE_CANCELS_AI: Dict[str, bool] = {
    "web": False,
    "matrix": True,
    "bisq2": True,
}
DEFAULT_COMMUNITY_SUBSTANTIVE_MIN_CHARS: Dict[str, int] = {
    "web": 20,
    "matrix": 20,
    "bisq2": 20,
}
DEFAULT_STAFF_PRESENCE_AWARE_DELAY: Dict[str, bool] = {
    "web": False,
    "matrix": True,
    "bisq2": True,
}
DEFAULT_MIN_DELAY_NO_STAFF_SECONDS: Dict[str, int] = {
    "web": 0,
    "matrix": 300,
    "bisq2": 300,
}
DEFAULT_MANDATORY_ESCALATION_TOPICS: Dict[str, list[str]] = {
    "web": [],
    "matrix": [],
    "bisq2": [],
}
DEFAULT_TIMER_JITTER_MAX_SECONDS: Dict[str, int] = {
    "web": 0,
    "matrix": 30,
    "bisq2": 30,
}

SUPPORTED_AI_RESPONSE_MODES: tuple[str, ...] = ("autonomous", "hitl")
SUPPORTED_STAFF_ASSIST_SURFACES: tuple[str, ...] = (
    "none",
    "staff_room",
    "admin_ui",
    "both",
)
SUPPORTED_ACKNOWLEDGMENT_MODES: tuple[str, ...] = ("none", "reaction", "message")
SUPPORTED_ESCALATION_USER_NOTICE_MODES: tuple[str, ...] = (
    "none",
    "message",
)
SUPPORTED_ESCALATION_NOTIFICATION_CHANNELS: tuple[str, ...] = (
    "public_room",
    "staff_room",
    "none",
)

_MIN_GROUP_DELAY_SECONDS = 30
_MIN_GROUP_COOLDOWN_SECONDS = 60
_MIN_HITL_TIMEOUT_SECONDS = 60
_MAX_HITL_TIMEOUT_SECONDS = 86400
_MAX_DELAY_SECONDS = 3600
_MAX_COOLDOWN_SECONDS = 7200
_MAX_PROACTIVE_REPLIES = 10
_MAX_JITTER_SECONDS = 300


def _normalized_channel_ids(ids: Iterable[str]) -> list[str]:
    normalized = {str(channel_id or "").strip().lower() for channel_id in ids}
    normalized.discard("")
    return sorted(normalized)


def discover_supported_channels(
    configured_channels: Iterable[str] | None = None,
) -> tuple[str, ...]:
    discovered = set(SUPPORTED_CHANNELS)
    if configured_channels is not None:
        discovered.update(_normalized_channel_ids(configured_channels))
    discovered.update(_normalized_channel_ids(get_registered_channel_types().keys()))
    return tuple(sorted(discovered))


def _default_from_map(defaults: Dict[str, Any], channel_id: str, fallback: Any) -> Any:
    normalized = str(channel_id or "").strip().lower()
    return defaults.get(normalized, fallback)


def default_generation_enabled(channel_id: str) -> bool:
    return bool(
        _default_from_map(DEFAULT_GENERATION_ENABLED, channel_id, channel_id == "web")
    )


def default_autoresponse_enabled(channel_id: str) -> bool:
    return bool(
        _default_from_map(DEFAULT_AUTORESPONSE_ENABLED, channel_id, channel_id == "web")
    )


def default_ai_response_mode(channel_id: str) -> str:
    return str(_default_from_map(DEFAULT_AI_RESPONSE_MODE, channel_id, "autonomous"))


def default_hitl_approval_timeout_seconds(channel_id: str) -> int:
    return int(
        _default_from_map(DEFAULT_HITL_APPROVAL_TIMEOUT_SECONDS, channel_id, 3600)
    )


def default_draft_assistant_enabled(channel_id: str) -> bool:
    return bool(
        _default_from_map(
            DEFAULT_DRAFT_ASSISTANT_ENABLED, channel_id, channel_id != "web"
        )
    )


def default_knowledge_amplifier_enabled(channel_id: str) -> bool:
    return bool(
        _default_from_map(
            DEFAULT_KNOWLEDGE_AMPLIFIER_ENABLED, channel_id, channel_id != "web"
        )
    )


def default_staff_assist_surface(channel_id: str) -> str:
    return str(_default_from_map(DEFAULT_STAFF_ASSIST_SURFACE, channel_id, "both"))


def default_first_response_delay_seconds(channel_id: str) -> int:
    return int(_default_from_map(DEFAULT_FIRST_RESPONSE_DELAY_SECONDS, channel_id, 300))


def default_staff_active_cooldown_seconds(channel_id: str) -> int:
    return int(
        _default_from_map(DEFAULT_STAFF_ACTIVE_COOLDOWN_SECONDS, channel_id, 600)
    )


def default_max_proactive_ai_replies_per_question(channel_id: str) -> int:
    return int(
        _default_from_map(DEFAULT_MAX_PROACTIVE_AI_REPLIES_PER_QUESTION, channel_id, 1)
    )


def default_public_escalation_notice_enabled(channel_id: str) -> bool:
    return bool(
        _default_from_map(
            DEFAULT_PUBLIC_ESCALATION_NOTICE_ENABLED, channel_id, channel_id == "web"
        )
    )


def default_acknowledgment_mode(channel_id: str) -> str:
    return str(_default_from_map(DEFAULT_ACKNOWLEDGMENT_MODE, channel_id, "none"))


def default_acknowledgment_reaction_key(channel_id: str) -> str:
    return str(_default_from_map(DEFAULT_ACKNOWLEDGMENT_REACTION_KEY, channel_id, "👀"))


def default_acknowledgment_message_template(channel_id: str) -> str:
    return str(
        _default_from_map(
            DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE,
            channel_id,
            "Thanks for your question. A team member or our assistant will respond shortly.",
        )
    )


def default_group_clarification_immediate(channel_id: str) -> bool:
    return bool(
        _default_from_map(
            DEFAULT_GROUP_CLARIFICATION_IMMEDIATE, channel_id, channel_id == "web"
        )
    )


def default_escalation_user_notice_template(channel_id: str) -> str:
    return str(
        _default_from_map(
            DEFAULT_ESCALATION_USER_NOTICE_TEMPLATE,
            channel_id,
            "This question needs a team member's attention. Someone will follow up.",
        )
    )


def default_escalation_user_notice_mode(channel_id: str) -> str:
    return str(
        _default_from_map(DEFAULT_ESCALATION_USER_NOTICE_MODE, channel_id, "message")
    )


def default_dispatch_failure_message_template(channel_id: str) -> str:
    return str(
        _default_from_map(
            DEFAULT_DISPATCH_FAILURE_MESSAGE_TEMPLATE,
            channel_id,
            "We were unable to process your question automatically. A team member will follow up.",
        )
    )


def default_escalation_notification_channel(channel_id: str) -> str:
    return str(
        _default_from_map(
            DEFAULT_ESCALATION_NOTIFICATION_CHANNEL,
            channel_id,
            "public_room",
        )
    )


def default_explicit_invocation_enabled(channel_id: str) -> bool:
    return bool(
        _default_from_map(DEFAULT_EXPLICIT_INVOCATION_ENABLED, channel_id, False)
    )


def default_explicit_invocation_user_rate_limit_per_5m(channel_id: str) -> int:
    return int(
        _default_from_map(
            DEFAULT_EXPLICIT_INVOCATION_USER_RATE_LIMIT_PER_5M, channel_id, 0
        )
    )


def default_explicit_invocation_room_rate_limit_per_min(channel_id: str) -> int:
    return int(
        _default_from_map(
            DEFAULT_EXPLICIT_INVOCATION_ROOM_RATE_LIMIT_PER_MIN, channel_id, 0
        )
    )


def default_community_response_cancels_ai(channel_id: str) -> bool:
    return bool(
        _default_from_map(DEFAULT_COMMUNITY_RESPONSE_CANCELS_AI, channel_id, False)
    )


def default_community_substantive_min_chars(channel_id: str) -> int:
    return int(
        _default_from_map(DEFAULT_COMMUNITY_SUBSTANTIVE_MIN_CHARS, channel_id, 20)
    )


def default_staff_presence_aware_delay(channel_id: str) -> bool:
    return bool(
        _default_from_map(
            DEFAULT_STAFF_PRESENCE_AWARE_DELAY, channel_id, channel_id != "web"
        )
    )


def default_min_delay_no_staff_seconds(channel_id: str) -> int:
    return int(_default_from_map(DEFAULT_MIN_DELAY_NO_STAFF_SECONDS, channel_id, 0))


def default_mandatory_escalation_topics(channel_id: str) -> list[str]:
    raw = _default_from_map(DEFAULT_MANDATORY_ESCALATION_TOPICS, channel_id, [])
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def default_timer_jitter_max_seconds(channel_id: str) -> int:
    return int(_default_from_map(DEFAULT_TIMER_JITTER_MAX_SECONDS, channel_id, 0))


@dataclass(frozen=True)
class ChannelAutoResponsePolicy:
    channel_id: str
    enabled: bool
    generation_enabled: bool
    ai_response_mode: str
    hitl_approval_timeout_seconds: int
    draft_assistant_enabled: bool
    knowledge_amplifier_enabled: bool
    staff_assist_surface: str
    first_response_delay_seconds: int
    staff_active_cooldown_seconds: int
    max_proactive_ai_replies_per_question: int
    public_escalation_notice_enabled: bool
    acknowledgment_mode: str
    acknowledgment_reaction_key: str
    acknowledgment_message_template: str
    group_clarification_immediate: bool
    escalation_user_notice_template: str
    escalation_user_notice_mode: str
    dispatch_failure_message_template: str
    escalation_notification_channel: str
    explicit_invocation_enabled: bool
    explicit_invocation_user_rate_limit_per_5m: int
    explicit_invocation_room_rate_limit_per_min: int
    community_response_cancels_ai: bool
    community_substantive_min_chars: int
    staff_presence_aware_delay: bool
    min_delay_no_staff_seconds: int
    mandatory_escalation_topics: list[str]
    timer_jitter_max_seconds: int
    updated_at: str


def _topics_to_storage(topics: list[str]) -> str:
    return json.dumps(topics, ensure_ascii=False)


def _topics_from_storage(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value]
    return []


class ChannelAutoResponsePolicyService:
    """Store and retrieve per-channel autoresponse policy."""

    _ALTER_COLUMN_SQL: Dict[str, str] = {
        "generation_enabled": "INTEGER",
        "ai_response_mode": "TEXT NOT NULL DEFAULT 'autonomous'",
        "hitl_approval_timeout_seconds": "INTEGER NOT NULL DEFAULT 3600",
        "draft_assistant_enabled": "INTEGER NOT NULL DEFAULT 1",
        "knowledge_amplifier_enabled": "INTEGER NOT NULL DEFAULT 1",
        "staff_assist_surface": "TEXT NOT NULL DEFAULT 'both'",
        "first_response_delay_seconds": "INTEGER NOT NULL DEFAULT 300",
        "staff_active_cooldown_seconds": "INTEGER NOT NULL DEFAULT 600",
        "max_proactive_ai_replies_per_question": "INTEGER NOT NULL DEFAULT 1",
        "public_escalation_notice_enabled": "INTEGER NOT NULL DEFAULT 0",
        "acknowledgment_mode": "TEXT NOT NULL DEFAULT 'none'",
        "acknowledgment_reaction_key": "TEXT NOT NULL DEFAULT '👀'",
        "acknowledgment_message_template": "TEXT NOT NULL DEFAULT 'Thanks for your question. A team member or our assistant will respond shortly.'",
        "group_clarification_immediate": "INTEGER NOT NULL DEFAULT 0",
        "escalation_user_notice_template": "TEXT NOT NULL DEFAULT 'This question needs a team member''s attention. Someone will follow up.'",
        "escalation_user_notice_mode": "TEXT NOT NULL DEFAULT 'message'",
        "dispatch_failure_message_template": "TEXT NOT NULL DEFAULT 'We were unable to process your question automatically. A team member will follow up.'",
        "escalation_notification_channel": "TEXT NOT NULL DEFAULT 'public_room'",
        "explicit_invocation_enabled": "INTEGER NOT NULL DEFAULT 0",
        "explicit_invocation_user_rate_limit_per_5m": "INTEGER NOT NULL DEFAULT 0",
        "explicit_invocation_room_rate_limit_per_min": "INTEGER NOT NULL DEFAULT 0",
        "community_response_cancels_ai": "INTEGER NOT NULL DEFAULT 1",
        "community_substantive_min_chars": "INTEGER NOT NULL DEFAULT 20",
        "staff_presence_aware_delay": "INTEGER NOT NULL DEFAULT 1",
        "min_delay_no_staff_seconds": "INTEGER NOT NULL DEFAULT 0",
        "mandatory_escalation_topics": "TEXT NOT NULL DEFAULT '[]'",
        "timer_jitter_max_seconds": "INTEGER NOT NULL DEFAULT 0",
    }

    def __init__(
        self,
        db_path: str,
        supported_channels: Iterable[str] | None = None,
    ) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._supported_channels = discover_supported_channels(supported_channels)
        self._init_db()
        self._seed_defaults()

    @property
    def supported_channels(self) -> tuple[str, ...]:
        return self._supported_channels

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS channel_autoresponse_policy (
                        channel_id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL,
                        generation_enabled INTEGER,
                        ai_response_mode TEXT NOT NULL DEFAULT 'autonomous',
                        hitl_approval_timeout_seconds INTEGER NOT NULL DEFAULT 3600,
                        draft_assistant_enabled INTEGER NOT NULL DEFAULT 1,
                        knowledge_amplifier_enabled INTEGER NOT NULL DEFAULT 1,
                        staff_assist_surface TEXT NOT NULL DEFAULT 'both',
                        first_response_delay_seconds INTEGER NOT NULL DEFAULT 300,
                        staff_active_cooldown_seconds INTEGER NOT NULL DEFAULT 600,
                        max_proactive_ai_replies_per_question INTEGER NOT NULL DEFAULT 1,
                        public_escalation_notice_enabled INTEGER NOT NULL DEFAULT 0,
                        acknowledgment_mode TEXT NOT NULL DEFAULT 'none',
                        acknowledgment_reaction_key TEXT NOT NULL DEFAULT '👀',
                        acknowledgment_message_template TEXT NOT NULL DEFAULT 'Thanks for your question. A team member or our assistant will respond shortly.',
                        group_clarification_immediate INTEGER NOT NULL DEFAULT 0,
                        escalation_user_notice_template TEXT NOT NULL DEFAULT 'This question needs a team member''s attention. Someone will follow up.',
                        escalation_user_notice_mode TEXT NOT NULL DEFAULT 'message',
                        dispatch_failure_message_template TEXT NOT NULL DEFAULT 'We were unable to process your question automatically. A team member will follow up.',
                        escalation_notification_channel TEXT NOT NULL DEFAULT 'public_room',
                        explicit_invocation_enabled INTEGER NOT NULL DEFAULT 0,
                        explicit_invocation_user_rate_limit_per_5m INTEGER NOT NULL DEFAULT 0,
                        explicit_invocation_room_rate_limit_per_min INTEGER NOT NULL DEFAULT 0,
                        community_response_cancels_ai INTEGER NOT NULL DEFAULT 1,
                        community_substantive_min_chars INTEGER NOT NULL DEFAULT 20,
                        staff_presence_aware_delay INTEGER NOT NULL DEFAULT 1,
                        min_delay_no_staff_seconds INTEGER NOT NULL DEFAULT 0,
                        mandatory_escalation_topics TEXT NOT NULL DEFAULT '[]',
                        timer_jitter_max_seconds INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )
                    """)

                columns = {
                    str(row["name"])
                    for row in conn.execute(
                        "PRAGMA table_info(channel_autoresponse_policy)"
                    )
                }
                for column_name, ddl in self._ALTER_COLUMN_SQL.items():
                    if column_name in columns:
                        continue
                    conn.execute(f"""
                        ALTER TABLE channel_autoresponse_policy
                        ADD COLUMN {column_name} {ddl}
                        """)
                conn.commit()
            finally:
                conn.close()

    def _seed_defaults(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                for channel_id in self._supported_channels:
                    defaults = self._default_values(channel_id)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO channel_autoresponse_policy (
                            channel_id,
                            enabled,
                            generation_enabled,
                            ai_response_mode,
                            hitl_approval_timeout_seconds,
                            draft_assistant_enabled,
                            knowledge_amplifier_enabled,
                            staff_assist_surface,
                            first_response_delay_seconds,
                            staff_active_cooldown_seconds,
                            max_proactive_ai_replies_per_question,
                            public_escalation_notice_enabled,
                            acknowledgment_mode,
                            acknowledgment_reaction_key,
                            acknowledgment_message_template,
                            group_clarification_immediate,
                            escalation_user_notice_template,
                            escalation_user_notice_mode,
                            dispatch_failure_message_template,
                            escalation_notification_channel,
                            explicit_invocation_enabled,
                            explicit_invocation_user_rate_limit_per_5m,
                            explicit_invocation_room_rate_limit_per_min,
                            community_response_cancels_ai,
                            community_substantive_min_chars,
                            staff_presence_aware_delay,
                            min_delay_no_staff_seconds,
                            mandatory_escalation_topics,
                            timer_jitter_max_seconds,
                            updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            channel_id,
                            1 if defaults["enabled"] else 0,
                            1 if defaults["generation_enabled"] else 0,
                            defaults["ai_response_mode"],
                            defaults["hitl_approval_timeout_seconds"],
                            1 if defaults["draft_assistant_enabled"] else 0,
                            1 if defaults["knowledge_amplifier_enabled"] else 0,
                            defaults["staff_assist_surface"],
                            defaults["first_response_delay_seconds"],
                            defaults["staff_active_cooldown_seconds"],
                            defaults["max_proactive_ai_replies_per_question"],
                            1 if defaults["public_escalation_notice_enabled"] else 0,
                            defaults["acknowledgment_mode"],
                            defaults["acknowledgment_reaction_key"],
                            defaults["acknowledgment_message_template"],
                            1 if defaults["group_clarification_immediate"] else 0,
                            defaults["escalation_user_notice_template"],
                            defaults["escalation_user_notice_mode"],
                            defaults["dispatch_failure_message_template"],
                            defaults["escalation_notification_channel"],
                            1 if defaults["explicit_invocation_enabled"] else 0,
                            defaults["explicit_invocation_user_rate_limit_per_5m"],
                            defaults["explicit_invocation_room_rate_limit_per_min"],
                            1 if defaults["community_response_cancels_ai"] else 0,
                            defaults["community_substantive_min_chars"],
                            1 if defaults["staff_presence_aware_delay"] else 0,
                            defaults["min_delay_no_staff_seconds"],
                            _topics_to_storage(defaults["mandatory_escalation_topics"]),
                            defaults["timer_jitter_max_seconds"],
                            now,
                        ),
                    )

                    for column_name, value in (
                        (
                            "generation_enabled",
                            1 if defaults["generation_enabled"] else 0,
                        ),
                        ("ai_response_mode", defaults["ai_response_mode"]),
                        (
                            "hitl_approval_timeout_seconds",
                            defaults["hitl_approval_timeout_seconds"],
                        ),
                        (
                            "draft_assistant_enabled",
                            1 if defaults["draft_assistant_enabled"] else 0,
                        ),
                        (
                            "knowledge_amplifier_enabled",
                            1 if defaults["knowledge_amplifier_enabled"] else 0,
                        ),
                        ("staff_assist_surface", defaults["staff_assist_surface"]),
                        (
                            "first_response_delay_seconds",
                            defaults["first_response_delay_seconds"],
                        ),
                        (
                            "staff_active_cooldown_seconds",
                            defaults["staff_active_cooldown_seconds"],
                        ),
                        (
                            "max_proactive_ai_replies_per_question",
                            defaults["max_proactive_ai_replies_per_question"],
                        ),
                        (
                            "public_escalation_notice_enabled",
                            1 if defaults["public_escalation_notice_enabled"] else 0,
                        ),
                        ("acknowledgment_mode", defaults["acknowledgment_mode"]),
                        (
                            "acknowledgment_reaction_key",
                            defaults["acknowledgment_reaction_key"],
                        ),
                        (
                            "acknowledgment_message_template",
                            defaults["acknowledgment_message_template"],
                        ),
                        (
                            "group_clarification_immediate",
                            1 if defaults["group_clarification_immediate"] else 0,
                        ),
                        (
                            "escalation_user_notice_template",
                            defaults["escalation_user_notice_template"],
                        ),
                        (
                            "escalation_user_notice_mode",
                            defaults["escalation_user_notice_mode"],
                        ),
                        (
                            "dispatch_failure_message_template",
                            defaults["dispatch_failure_message_template"],
                        ),
                        (
                            "escalation_notification_channel",
                            defaults["escalation_notification_channel"],
                        ),
                        (
                            "explicit_invocation_enabled",
                            1 if defaults["explicit_invocation_enabled"] else 0,
                        ),
                        (
                            "explicit_invocation_user_rate_limit_per_5m",
                            defaults["explicit_invocation_user_rate_limit_per_5m"],
                        ),
                        (
                            "explicit_invocation_room_rate_limit_per_min",
                            defaults["explicit_invocation_room_rate_limit_per_min"],
                        ),
                        (
                            "community_response_cancels_ai",
                            1 if defaults["community_response_cancels_ai"] else 0,
                        ),
                        (
                            "community_substantive_min_chars",
                            defaults["community_substantive_min_chars"],
                        ),
                        (
                            "staff_presence_aware_delay",
                            1 if defaults["staff_presence_aware_delay"] else 0,
                        ),
                        (
                            "min_delay_no_staff_seconds",
                            defaults["min_delay_no_staff_seconds"],
                        ),
                        (
                            "mandatory_escalation_topics",
                            _topics_to_storage(defaults["mandatory_escalation_topics"]),
                        ),
                        (
                            "timer_jitter_max_seconds",
                            defaults["timer_jitter_max_seconds"],
                        ),
                    ):
                        conn.execute(
                            f"""
                            UPDATE channel_autoresponse_policy
                            SET {column_name} = COALESCE({column_name}, ?)
                            WHERE channel_id = ?
                            """,
                            (value, channel_id),
                        )
                conn.commit()
            finally:
                conn.close()

    def list_policies(self) -> List[ChannelAutoResponsePolicy]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("""
                    SELECT *
                    FROM channel_autoresponse_policy
                    ORDER BY channel_id
                    """).fetchall()
            finally:
                conn.close()
        return [self._row_to_policy(row) for row in rows]

    def get_policy(self, channel_id: str) -> ChannelAutoResponsePolicy:
        normalized = self._validate_channel_id(channel_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT *
                    FROM channel_autoresponse_policy
                    WHERE channel_id = ?
                    """,
                    (normalized,),
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            raise KeyError(normalized)
        return self._row_to_policy(row)

    def set_enabled(self, channel_id: str, enabled: bool) -> ChannelAutoResponsePolicy:
        return self.set_policy(channel_id=channel_id, enabled=enabled)

    def set_generation_enabled(
        self,
        channel_id: str,
        generation_enabled: bool,
    ) -> ChannelAutoResponsePolicy:
        return self.set_policy(
            channel_id=channel_id,
            generation_enabled=generation_enabled,
        )

    def set_policy(
        self,
        channel_id: str,
        enabled: bool | None = None,
        generation_enabled: bool | None = None,
        ai_response_mode: str | None = None,
        hitl_approval_timeout_seconds: int | None = None,
        draft_assistant_enabled: bool | None = None,
        knowledge_amplifier_enabled: bool | None = None,
        staff_assist_surface: str | None = None,
        first_response_delay_seconds: int | None = None,
        staff_active_cooldown_seconds: int | None = None,
        max_proactive_ai_replies_per_question: int | None = None,
        public_escalation_notice_enabled: bool | None = None,
        acknowledgment_mode: str | None = None,
        acknowledgment_reaction_key: str | None = None,
        acknowledgment_message_template: str | None = None,
        group_clarification_immediate: bool | None = None,
        escalation_user_notice_template: str | None = None,
        escalation_user_notice_mode: str | None = None,
        dispatch_failure_message_template: str | None = None,
        escalation_notification_channel: str | None = None,
        explicit_invocation_enabled: bool | None = None,
        explicit_invocation_user_rate_limit_per_5m: int | None = None,
        explicit_invocation_room_rate_limit_per_min: int | None = None,
        community_response_cancels_ai: bool | None = None,
        community_substantive_min_chars: int | None = None,
        staff_presence_aware_delay: bool | None = None,
        min_delay_no_staff_seconds: int | None = None,
        mandatory_escalation_topics: list[str] | None = None,
        timer_jitter_max_seconds: int | None = None,
    ) -> ChannelAutoResponsePolicy:
        if all(
            value is None
            for value in (
                enabled,
                generation_enabled,
                ai_response_mode,
                hitl_approval_timeout_seconds,
                draft_assistant_enabled,
                knowledge_amplifier_enabled,
                staff_assist_surface,
                first_response_delay_seconds,
                staff_active_cooldown_seconds,
                max_proactive_ai_replies_per_question,
                public_escalation_notice_enabled,
                acknowledgment_mode,
                acknowledgment_reaction_key,
                acknowledgment_message_template,
                group_clarification_immediate,
                escalation_user_notice_template,
                escalation_user_notice_mode,
                dispatch_failure_message_template,
                escalation_notification_channel,
                explicit_invocation_enabled,
                explicit_invocation_user_rate_limit_per_5m,
                explicit_invocation_room_rate_limit_per_min,
                community_response_cancels_ai,
                community_substantive_min_chars,
                staff_presence_aware_delay,
                min_delay_no_staff_seconds,
                mandatory_escalation_topics,
                timer_jitter_max_seconds,
            )
        ):
            raise ValueError("At least one policy field must be set")

        normalized = self._validate_channel_id(channel_id)
        current = self.get_policy(normalized)

        next_enabled = current.enabled if enabled is None else bool(enabled)
        next_generation_enabled = (
            current.generation_enabled
            if generation_enabled is None
            else bool(generation_enabled)
        )

        next_ai_response_mode = (
            current.ai_response_mode
            if ai_response_mode is None
            else str(ai_response_mode or "").strip().lower()
        )
        if next_ai_response_mode not in SUPPORTED_AI_RESPONSE_MODES:
            raise ValueError(
                f"Unsupported ai_response_mode '{ai_response_mode}'."
                f" Supported values: {', '.join(SUPPORTED_AI_RESPONSE_MODES)}"
            )

        next_hitl_approval_timeout_seconds = (
            current.hitl_approval_timeout_seconds
            if hitl_approval_timeout_seconds is None
            else int(hitl_approval_timeout_seconds)
        )
        if next_hitl_approval_timeout_seconds != 0 and not (
            _MIN_HITL_TIMEOUT_SECONDS
            <= next_hitl_approval_timeout_seconds
            <= _MAX_HITL_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"hitl_approval_timeout_seconds must be 0 or between {_MIN_HITL_TIMEOUT_SECONDS} and {_MAX_HITL_TIMEOUT_SECONDS}"
            )

        next_draft_assistant_enabled = (
            current.draft_assistant_enabled
            if draft_assistant_enabled is None
            else bool(draft_assistant_enabled)
        )
        next_knowledge_amplifier_enabled = (
            current.knowledge_amplifier_enabled
            if knowledge_amplifier_enabled is None
            else bool(knowledge_amplifier_enabled)
        )

        next_staff_assist_surface = (
            current.staff_assist_surface
            if staff_assist_surface is None
            else str(staff_assist_surface or "").strip().lower()
        )
        if next_staff_assist_surface not in SUPPORTED_STAFF_ASSIST_SURFACES:
            raise ValueError(
                f"Unsupported staff_assist_surface '{staff_assist_surface}'."
                f" Supported values: {', '.join(SUPPORTED_STAFF_ASSIST_SURFACES)}"
            )

        next_first_response_delay_seconds = (
            current.first_response_delay_seconds
            if first_response_delay_seconds is None
            else int(first_response_delay_seconds)
        )
        if normalized == "web":
            if not (0 <= next_first_response_delay_seconds <= _MAX_DELAY_SECONDS):
                raise ValueError(
                    f"first_response_delay_seconds must be between 0 and {_MAX_DELAY_SECONDS}"
                )
        else:
            if not (
                _MIN_GROUP_DELAY_SECONDS
                <= next_first_response_delay_seconds
                <= _MAX_DELAY_SECONDS
            ):
                raise ValueError(
                    f"first_response_delay_seconds must be between {_MIN_GROUP_DELAY_SECONDS} and {_MAX_DELAY_SECONDS} for group channels"
                )

        next_staff_active_cooldown_seconds = (
            current.staff_active_cooldown_seconds
            if staff_active_cooldown_seconds is None
            else int(staff_active_cooldown_seconds)
        )
        if normalized == "web":
            if not (0 <= next_staff_active_cooldown_seconds <= _MAX_COOLDOWN_SECONDS):
                raise ValueError(
                    f"staff_active_cooldown_seconds must be between 0 and {_MAX_COOLDOWN_SECONDS}"
                )
        else:
            if not (
                _MIN_GROUP_COOLDOWN_SECONDS
                <= next_staff_active_cooldown_seconds
                <= _MAX_COOLDOWN_SECONDS
            ):
                raise ValueError(
                    f"staff_active_cooldown_seconds must be between {_MIN_GROUP_COOLDOWN_SECONDS} and {_MAX_COOLDOWN_SECONDS} for group channels"
                )

        next_max_proactive_ai_replies_per_question = (
            current.max_proactive_ai_replies_per_question
            if max_proactive_ai_replies_per_question is None
            else int(max_proactive_ai_replies_per_question)
        )
        if not (
            0 <= next_max_proactive_ai_replies_per_question <= _MAX_PROACTIVE_REPLIES
        ):
            raise ValueError(
                f"max_proactive_ai_replies_per_question must be between 0 and {_MAX_PROACTIVE_REPLIES}"
            )

        next_public_escalation_notice_enabled = (
            current.public_escalation_notice_enabled
            if public_escalation_notice_enabled is None
            else bool(public_escalation_notice_enabled)
        )

        next_acknowledgment_mode = (
            current.acknowledgment_mode
            if acknowledgment_mode is None
            else str(acknowledgment_mode or "").strip().lower()
        )
        if next_acknowledgment_mode not in SUPPORTED_ACKNOWLEDGMENT_MODES:
            raise ValueError(
                f"Unsupported acknowledgment_mode '{acknowledgment_mode}'."
                f" Supported values: {', '.join(SUPPORTED_ACKNOWLEDGMENT_MODES)}"
            )

        next_acknowledgment_reaction_key = (
            current.acknowledgment_reaction_key
            if acknowledgment_reaction_key is None
            else str(acknowledgment_reaction_key or "").strip()
        )
        if not next_acknowledgment_reaction_key:
            next_acknowledgment_reaction_key = default_acknowledgment_reaction_key(
                normalized
            )

        next_acknowledgment_message_template = (
            current.acknowledgment_message_template
            if acknowledgment_message_template is None
            else str(acknowledgment_message_template or "").strip()
        )
        if not next_acknowledgment_message_template:
            next_acknowledgment_message_template = (
                default_acknowledgment_message_template(normalized)
            )

        next_group_clarification_immediate = (
            current.group_clarification_immediate
            if group_clarification_immediate is None
            else bool(group_clarification_immediate)
        )

        next_escalation_user_notice_template = (
            current.escalation_user_notice_template
            if escalation_user_notice_template is None
            else str(escalation_user_notice_template or "").strip()
        )
        if not next_escalation_user_notice_template:
            next_escalation_user_notice_template = (
                default_escalation_user_notice_template(normalized)
            )

        next_escalation_user_notice_mode = (
            current.escalation_user_notice_mode
            if escalation_user_notice_mode is None
            else str(escalation_user_notice_mode or "").strip().lower()
        )
        if (
            next_escalation_user_notice_mode
            not in SUPPORTED_ESCALATION_USER_NOTICE_MODES
        ):
            raise ValueError(
                f"Unsupported escalation_user_notice_mode '{escalation_user_notice_mode}'."
                f" Supported values: {', '.join(SUPPORTED_ESCALATION_USER_NOTICE_MODES)}"
            )

        next_dispatch_failure_message_template = (
            current.dispatch_failure_message_template
            if dispatch_failure_message_template is None
            else str(dispatch_failure_message_template or "").strip()
        )
        if not next_dispatch_failure_message_template:
            next_dispatch_failure_message_template = (
                default_dispatch_failure_message_template(normalized)
            )

        next_escalation_notification_channel = (
            current.escalation_notification_channel
            if escalation_notification_channel is None
            else str(escalation_notification_channel or "").strip().lower()
        )
        if (
            next_escalation_notification_channel
            not in SUPPORTED_ESCALATION_NOTIFICATION_CHANNELS
        ):
            raise ValueError(
                f"Unsupported escalation_notification_channel '{escalation_notification_channel}'."
                f" Supported values: {', '.join(SUPPORTED_ESCALATION_NOTIFICATION_CHANNELS)}"
            )

        next_explicit_invocation_enabled = (
            current.explicit_invocation_enabled
            if explicit_invocation_enabled is None
            else bool(explicit_invocation_enabled)
        )
        next_explicit_invocation_user_rate_limit_per_5m = (
            current.explicit_invocation_user_rate_limit_per_5m
            if explicit_invocation_user_rate_limit_per_5m is None
            else int(explicit_invocation_user_rate_limit_per_5m)
        )
        if next_explicit_invocation_user_rate_limit_per_5m < 0:
            raise ValueError("explicit_invocation_user_rate_limit_per_5m must be >= 0")

        next_explicit_invocation_room_rate_limit_per_min = (
            current.explicit_invocation_room_rate_limit_per_min
            if explicit_invocation_room_rate_limit_per_min is None
            else int(explicit_invocation_room_rate_limit_per_min)
        )
        if next_explicit_invocation_room_rate_limit_per_min < 0:
            raise ValueError("explicit_invocation_room_rate_limit_per_min must be >= 0")

        next_community_response_cancels_ai = (
            current.community_response_cancels_ai
            if community_response_cancels_ai is None
            else bool(community_response_cancels_ai)
        )
        next_community_substantive_min_chars = (
            current.community_substantive_min_chars
            if community_substantive_min_chars is None
            else int(community_substantive_min_chars)
        )
        if next_community_substantive_min_chars < 0:
            raise ValueError("community_substantive_min_chars must be >= 0")

        next_staff_presence_aware_delay = (
            current.staff_presence_aware_delay
            if staff_presence_aware_delay is None
            else bool(staff_presence_aware_delay)
        )
        next_min_delay_no_staff_seconds = (
            current.min_delay_no_staff_seconds
            if min_delay_no_staff_seconds is None
            else int(min_delay_no_staff_seconds)
        )
        if next_min_delay_no_staff_seconds < 0:
            raise ValueError("min_delay_no_staff_seconds must be >= 0")

        next_mandatory_escalation_topics = (
            current.mandatory_escalation_topics
            if mandatory_escalation_topics is None
            else [
                str(topic).strip()
                for topic in mandatory_escalation_topics
                if str(topic).strip()
            ]
        )

        next_timer_jitter_max_seconds = (
            current.timer_jitter_max_seconds
            if timer_jitter_max_seconds is None
            else int(timer_jitter_max_seconds)
        )
        if not (0 <= next_timer_jitter_max_seconds <= _MAX_JITTER_SECONDS):
            raise ValueError(
                f"timer_jitter_max_seconds must be between 0 and {_MAX_JITTER_SECONDS}"
            )

        if not next_generation_enabled:
            next_enabled = False

        now = datetime.now(timezone.utc).isoformat()

        updated = ChannelAutoResponsePolicy(
            channel_id=normalized,
            enabled=next_enabled,
            generation_enabled=next_generation_enabled,
            ai_response_mode=next_ai_response_mode,
            hitl_approval_timeout_seconds=next_hitl_approval_timeout_seconds,
            draft_assistant_enabled=next_draft_assistant_enabled,
            knowledge_amplifier_enabled=next_knowledge_amplifier_enabled,
            staff_assist_surface=next_staff_assist_surface,
            first_response_delay_seconds=next_first_response_delay_seconds,
            staff_active_cooldown_seconds=next_staff_active_cooldown_seconds,
            max_proactive_ai_replies_per_question=next_max_proactive_ai_replies_per_question,
            public_escalation_notice_enabled=next_public_escalation_notice_enabled,
            acknowledgment_mode=next_acknowledgment_mode,
            acknowledgment_reaction_key=next_acknowledgment_reaction_key,
            acknowledgment_message_template=next_acknowledgment_message_template,
            group_clarification_immediate=next_group_clarification_immediate,
            escalation_user_notice_template=next_escalation_user_notice_template,
            escalation_user_notice_mode=next_escalation_user_notice_mode,
            dispatch_failure_message_template=next_dispatch_failure_message_template,
            escalation_notification_channel=next_escalation_notification_channel,
            explicit_invocation_enabled=next_explicit_invocation_enabled,
            explicit_invocation_user_rate_limit_per_5m=next_explicit_invocation_user_rate_limit_per_5m,
            explicit_invocation_room_rate_limit_per_min=next_explicit_invocation_room_rate_limit_per_min,
            community_response_cancels_ai=next_community_response_cancels_ai,
            community_substantive_min_chars=next_community_substantive_min_chars,
            staff_presence_aware_delay=next_staff_presence_aware_delay,
            min_delay_no_staff_seconds=next_min_delay_no_staff_seconds,
            mandatory_escalation_topics=next_mandatory_escalation_topics,
            timer_jitter_max_seconds=next_timer_jitter_max_seconds,
            updated_at=now,
        )

        changes = self._policy_changes(current, updated)
        if changes:
            logger.warning(
                "Channel autoresponse policy updated channel=%s changes=%s",
                normalized,
                changes,
            )

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO channel_autoresponse_policy (
                        channel_id,
                        enabled,
                        generation_enabled,
                        ai_response_mode,
                        hitl_approval_timeout_seconds,
                        draft_assistant_enabled,
                        knowledge_amplifier_enabled,
                        staff_assist_surface,
                        first_response_delay_seconds,
                        staff_active_cooldown_seconds,
                        max_proactive_ai_replies_per_question,
                        public_escalation_notice_enabled,
                        acknowledgment_mode,
                        acknowledgment_reaction_key,
                        acknowledgment_message_template,
                        group_clarification_immediate,
                        escalation_user_notice_template,
                        escalation_user_notice_mode,
                        dispatch_failure_message_template,
                        escalation_notification_channel,
                        explicit_invocation_enabled,
                        explicit_invocation_user_rate_limit_per_5m,
                        explicit_invocation_room_rate_limit_per_min,
                        community_response_cancels_ai,
                        community_substantive_min_chars,
                        staff_presence_aware_delay,
                        min_delay_no_staff_seconds,
                        mandatory_escalation_topics,
                        timer_jitter_max_seconds,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        enabled = excluded.enabled,
                        generation_enabled = excluded.generation_enabled,
                        ai_response_mode = excluded.ai_response_mode,
                        hitl_approval_timeout_seconds = excluded.hitl_approval_timeout_seconds,
                        draft_assistant_enabled = excluded.draft_assistant_enabled,
                        knowledge_amplifier_enabled = excluded.knowledge_amplifier_enabled,
                        staff_assist_surface = excluded.staff_assist_surface,
                        first_response_delay_seconds = excluded.first_response_delay_seconds,
                        staff_active_cooldown_seconds = excluded.staff_active_cooldown_seconds,
                        max_proactive_ai_replies_per_question = excluded.max_proactive_ai_replies_per_question,
                        public_escalation_notice_enabled = excluded.public_escalation_notice_enabled,
                        acknowledgment_mode = excluded.acknowledgment_mode,
                        acknowledgment_reaction_key = excluded.acknowledgment_reaction_key,
                        acknowledgment_message_template = excluded.acknowledgment_message_template,
                        group_clarification_immediate = excluded.group_clarification_immediate,
                        escalation_user_notice_template = excluded.escalation_user_notice_template,
                        escalation_user_notice_mode = excluded.escalation_user_notice_mode,
                        dispatch_failure_message_template = excluded.dispatch_failure_message_template,
                        escalation_notification_channel = excluded.escalation_notification_channel,
                        explicit_invocation_enabled = excluded.explicit_invocation_enabled,
                        explicit_invocation_user_rate_limit_per_5m = excluded.explicit_invocation_user_rate_limit_per_5m,
                        explicit_invocation_room_rate_limit_per_min = excluded.explicit_invocation_room_rate_limit_per_min,
                        community_response_cancels_ai = excluded.community_response_cancels_ai,
                        community_substantive_min_chars = excluded.community_substantive_min_chars,
                        staff_presence_aware_delay = excluded.staff_presence_aware_delay,
                        min_delay_no_staff_seconds = excluded.min_delay_no_staff_seconds,
                        mandatory_escalation_topics = excluded.mandatory_escalation_topics,
                        timer_jitter_max_seconds = excluded.timer_jitter_max_seconds,
                        updated_at = excluded.updated_at
                    """,
                    (
                        updated.channel_id,
                        1 if updated.enabled else 0,
                        1 if updated.generation_enabled else 0,
                        updated.ai_response_mode,
                        updated.hitl_approval_timeout_seconds,
                        1 if updated.draft_assistant_enabled else 0,
                        1 if updated.knowledge_amplifier_enabled else 0,
                        updated.staff_assist_surface,
                        updated.first_response_delay_seconds,
                        updated.staff_active_cooldown_seconds,
                        updated.max_proactive_ai_replies_per_question,
                        1 if updated.public_escalation_notice_enabled else 0,
                        updated.acknowledgment_mode,
                        updated.acknowledgment_reaction_key,
                        updated.acknowledgment_message_template,
                        1 if updated.group_clarification_immediate else 0,
                        updated.escalation_user_notice_template,
                        updated.escalation_user_notice_mode,
                        updated.dispatch_failure_message_template,
                        updated.escalation_notification_channel,
                        1 if updated.explicit_invocation_enabled else 0,
                        updated.explicit_invocation_user_rate_limit_per_5m,
                        updated.explicit_invocation_room_rate_limit_per_min,
                        1 if updated.community_response_cancels_ai else 0,
                        updated.community_substantive_min_chars,
                        1 if updated.staff_presence_aware_delay else 0,
                        updated.min_delay_no_staff_seconds,
                        _topics_to_storage(updated.mandatory_escalation_topics),
                        updated.timer_jitter_max_seconds,
                        updated.updated_at,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

        return updated

    @staticmethod
    def _policy_changes(
        current: ChannelAutoResponsePolicy,
        updated: ChannelAutoResponsePolicy,
    ) -> dict[str, tuple[Any, Any]]:
        changed: dict[str, tuple[Any, Any]] = {}
        for field_name in current.__dataclass_fields__:
            if field_name in {"channel_id", "updated_at"}:
                continue
            old_value = getattr(current, field_name)
            new_value = getattr(updated, field_name)
            if old_value != new_value:
                changed[field_name] = (old_value, new_value)
        return changed

    @staticmethod
    def _normalize_channel_id(channel_id: str) -> str:
        normalized = str(channel_id or "").strip().lower()
        if not normalized:
            raise ValueError("channel_id is required")
        return normalized

    def _validate_channel_id(self, channel_id: str) -> str:
        normalized = self._normalize_channel_id(channel_id)
        if normalized not in self._supported_channels:
            raise ValueError(f"Unsupported channel_id: {channel_id}")
        return normalized

    def _default_values(self, channel_id: str) -> dict[str, Any]:
        return {
            "enabled": default_autoresponse_enabled(channel_id),
            "generation_enabled": default_generation_enabled(channel_id),
            "ai_response_mode": default_ai_response_mode(channel_id),
            "hitl_approval_timeout_seconds": default_hitl_approval_timeout_seconds(
                channel_id
            ),
            "draft_assistant_enabled": default_draft_assistant_enabled(channel_id),
            "knowledge_amplifier_enabled": default_knowledge_amplifier_enabled(
                channel_id
            ),
            "staff_assist_surface": default_staff_assist_surface(channel_id),
            "first_response_delay_seconds": default_first_response_delay_seconds(
                channel_id
            ),
            "staff_active_cooldown_seconds": default_staff_active_cooldown_seconds(
                channel_id
            ),
            "max_proactive_ai_replies_per_question": default_max_proactive_ai_replies_per_question(
                channel_id
            ),
            "public_escalation_notice_enabled": default_public_escalation_notice_enabled(
                channel_id
            ),
            "acknowledgment_mode": default_acknowledgment_mode(channel_id),
            "acknowledgment_reaction_key": default_acknowledgment_reaction_key(
                channel_id
            ),
            "acknowledgment_message_template": default_acknowledgment_message_template(
                channel_id
            ),
            "group_clarification_immediate": default_group_clarification_immediate(
                channel_id
            ),
            "escalation_user_notice_template": default_escalation_user_notice_template(
                channel_id
            ),
            "escalation_user_notice_mode": default_escalation_user_notice_mode(
                channel_id
            ),
            "dispatch_failure_message_template": default_dispatch_failure_message_template(
                channel_id
            ),
            "escalation_notification_channel": default_escalation_notification_channel(
                channel_id
            ),
            "explicit_invocation_enabled": default_explicit_invocation_enabled(
                channel_id
            ),
            "explicit_invocation_user_rate_limit_per_5m": default_explicit_invocation_user_rate_limit_per_5m(
                channel_id
            ),
            "explicit_invocation_room_rate_limit_per_min": default_explicit_invocation_room_rate_limit_per_min(
                channel_id
            ),
            "community_response_cancels_ai": default_community_response_cancels_ai(
                channel_id
            ),
            "community_substantive_min_chars": default_community_substantive_min_chars(
                channel_id
            ),
            "staff_presence_aware_delay": default_staff_presence_aware_delay(
                channel_id
            ),
            "min_delay_no_staff_seconds": default_min_delay_no_staff_seconds(
                channel_id
            ),
            "mandatory_escalation_topics": default_mandatory_escalation_topics(
                channel_id
            ),
            "timer_jitter_max_seconds": default_timer_jitter_max_seconds(channel_id),
        }

    def _row_to_policy(self, row: sqlite3.Row) -> ChannelAutoResponsePolicy:
        channel_id = str(row["channel_id"])
        defaults = self._default_values(channel_id)

        def _int_field(name: str) -> int:
            raw = row[name] if name in row.keys() else None
            return int(defaults[name] if raw is None else raw)

        def _bool_field(name: str) -> bool:
            raw = row[name] if name in row.keys() else None
            return bool(defaults[name] if raw is None else raw)

        def _str_field(name: str) -> str:
            raw = row[name] if name in row.keys() else None
            value = str(defaults[name] if raw is None else raw).strip()
            return value or str(defaults[name])

        mode = _str_field("ai_response_mode").lower()
        if mode not in SUPPORTED_AI_RESPONSE_MODES:
            mode = defaults["ai_response_mode"]

        surface = _str_field("staff_assist_surface").lower()
        if surface not in SUPPORTED_STAFF_ASSIST_SURFACES:
            surface = defaults["staff_assist_surface"]

        acknowledgment_mode = _str_field("acknowledgment_mode").lower()
        if acknowledgment_mode not in SUPPORTED_ACKNOWLEDGMENT_MODES:
            acknowledgment_mode = defaults["acknowledgment_mode"]

        escalation_notification_channel = _str_field(
            "escalation_notification_channel"
        ).lower()
        if (
            escalation_notification_channel
            not in SUPPORTED_ESCALATION_NOTIFICATION_CHANNELS
        ):
            escalation_notification_channel = defaults[
                "escalation_notification_channel"
            ]

        escalation_user_notice_mode = _str_field("escalation_user_notice_mode").lower()
        if escalation_user_notice_mode not in SUPPORTED_ESCALATION_USER_NOTICE_MODES:
            escalation_user_notice_mode = defaults["escalation_user_notice_mode"]

        topics = _topics_from_storage(
            row["mandatory_escalation_topics"]
            if "mandatory_escalation_topics" in row.keys()
            else defaults["mandatory_escalation_topics"]
        )

        return ChannelAutoResponsePolicy(
            channel_id=channel_id,
            enabled=bool(row["enabled"]),
            generation_enabled=_bool_field("generation_enabled"),
            ai_response_mode=mode,
            hitl_approval_timeout_seconds=max(
                0, _int_field("hitl_approval_timeout_seconds")
            ),
            draft_assistant_enabled=_bool_field("draft_assistant_enabled"),
            knowledge_amplifier_enabled=_bool_field("knowledge_amplifier_enabled"),
            staff_assist_surface=surface,
            first_response_delay_seconds=max(
                0, _int_field("first_response_delay_seconds")
            ),
            staff_active_cooldown_seconds=max(
                0, _int_field("staff_active_cooldown_seconds")
            ),
            max_proactive_ai_replies_per_question=max(
                0, _int_field("max_proactive_ai_replies_per_question")
            ),
            public_escalation_notice_enabled=_bool_field(
                "public_escalation_notice_enabled"
            ),
            acknowledgment_mode=acknowledgment_mode,
            acknowledgment_reaction_key=_str_field("acknowledgment_reaction_key"),
            acknowledgment_message_template=_str_field(
                "acknowledgment_message_template"
            ),
            group_clarification_immediate=_bool_field("group_clarification_immediate"),
            escalation_user_notice_template=_str_field(
                "escalation_user_notice_template"
            ),
            escalation_user_notice_mode=escalation_user_notice_mode,
            dispatch_failure_message_template=_str_field(
                "dispatch_failure_message_template"
            ),
            escalation_notification_channel=escalation_notification_channel,
            explicit_invocation_enabled=_bool_field("explicit_invocation_enabled"),
            explicit_invocation_user_rate_limit_per_5m=max(
                0, _int_field("explicit_invocation_user_rate_limit_per_5m")
            ),
            explicit_invocation_room_rate_limit_per_min=max(
                0, _int_field("explicit_invocation_room_rate_limit_per_min")
            ),
            community_response_cancels_ai=_bool_field("community_response_cancels_ai"),
            community_substantive_min_chars=max(
                0, _int_field("community_substantive_min_chars")
            ),
            staff_presence_aware_delay=_bool_field("staff_presence_aware_delay"),
            min_delay_no_staff_seconds=max(0, _int_field("min_delay_no_staff_seconds")),
            mandatory_escalation_topics=topics,
            timer_jitter_max_seconds=max(0, _int_field("timer_jitter_max_seconds")),
            updated_at=str(row["updated_at"]),
        )
