"""Models for shared ChatOps command parsing and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChatOpsCommandName(str, Enum):
    LIST = "list"
    VIEW = "view"
    CLAIM = "claim"
    UNCLAIM = "unclaim"
    SEND = "send"
    EDIT_SEND = "edit-send"
    REWRITE = "rewrite"
    ESCALATE = "escalate"
    RESOLVE = "resolve"
    SNOOZE = "snooze"
    FAQ_CREATE = "faq-create"
    FAQ_LINK = "faq-link"
    HELP = "help"


@dataclass(frozen=True)
class ChatOpsCommand:
    """Parsed ChatOps command."""

    name: ChatOpsCommandName
    actor_id: str
    source_message_id: str
    room_id: str
    raw_text: str
    channel_id: str = ""
    case_id: int | None = None
    options: dict[str, str] = field(default_factory=dict)
    message: str | None = None


@dataclass(frozen=True)
class ChatOpsParseResult:
    """Result of parsing a ChatOps command string."""

    command: ChatOpsCommand | None
    handled: bool
    error_message: str | None = None


@dataclass(frozen=True)
class ChatOpsResult:
    """Execution result for a ChatOps command."""

    handled: bool
    ok: bool
    message: str
    command_name: str
    case_id: int | None = None
    idempotent: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
