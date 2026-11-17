"""Shared Staff request intake for subscription events and chronological replay.

The existing escalation row owns every request and retained turn. This module has
no Matrix client, provider client, timer, delivery, or learning dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import aiosqlite
from app.channels.ingress.service import _HIGH_RISK_PATTERNS
from app.channels.plugins.matrix.context_text import context_relationships, context_text
from app.channels.security import PIIDetector
from app.channels.staff_assist.context_incidents import (
    acknowledgement_only,
    gratitude_only,
    new_issue,
)
from app.channels.staff_assist.public_context import RoomMessage
from app.channels.staff_assist.staff_context import StaffContextRequest
from app.models.escalation import EscalationCreate

WORKFLOW_VERSION = 3
MAX_EXCHANGE_TURNS = 128
MAX_REQUEST_CHARS = 32000
MAX_EXCHANGE_BYTES = 32000


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class ConversationTurn:
    room_id: str
    event_id: str
    sender_id: str
    timestamp_ms: int
    text: str = ""
    is_staff: bool = False
    is_bot: bool = False
    reply_to_event_id: str | None = None
    thread_root_event_id: str | None = None
    replaces_event_id: str | None = None
    redacts_event_id: str | None = None
    non_text: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ConversationTurn:
        return cls(
            **{key: value[key] for key in cls.__dataclass_fields__ if key in value}
        )


def conversation_turn(
    room_id: str, event: Any, *, is_staff: bool, is_bot: bool = False
) -> ConversationTurn:
    """Use the same authored-text/native-relation parser for live and replay."""
    source = getattr(event, "source", None) or {}
    content = source.get("content", {}) if isinstance(source, dict) else {}
    content = content if isinstance(content, dict) else {}
    timestamp = getattr(event, "server_timestamp", None)
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("Conversation event needs an actual server timestamp")
    event_id = getattr(event, "event_id", "")
    sender = getattr(event, "sender", "")
    if (
        not room_id
        or not isinstance(event_id, str)
        or not event_id
        or not isinstance(sender, str)
        or not sender
    ):
        raise ValueError("Conversation event identity is missing")
    redacts = (
        getattr(event, "redacts", None)
        or content.get("redacts")
        or source.get("redacts")
    )
    msgtype = content.get("msgtype")
    non_text = (
        msgtype
        if isinstance(msgtype, str) and msgtype not in {"m.text", "m.notice", "m.emote"}
        else None
    )
    text = (
        context_text(event)
        if not non_text
        else f"[Attachment: {non_text}; contents unavailable]"
    )
    return ConversationTurn(
        room_id=room_id,
        event_id=event_id,
        sender_id=sender,
        timestamp_ms=timestamp,
        text=PIIDetector().redact(text).replace("@", "＠").strip(),
        is_staff=is_staff,
        is_bot=is_bot,
        redacts_event_id=redacts if isinstance(redacts, str) else None,
        non_text=non_text,
        **context_relationships(event),
    )


def effective_turns(turns: list[ConversationTurn]) -> list[ConversationTurn]:
    """Project only observed, author-valid edits; preserve original stored events."""
    known = {turn.event_id: turn for turn in turns}
    redacted = {turn.redacts_event_id for turn in turns if turn.redacts_event_id}
    replacements: dict[str, ConversationTurn] = {}
    for turn in sorted(turns, key=lambda item: (item.timestamp_ms, item.event_id)):
        target = known.get(turn.replaces_event_id or "")
        if (
            target
            and turn.sender_id == target.sender_id
            and turn.event_id not in redacted
        ):
            replacements[target.event_id] = turn
    projected = []
    for turn in turns:
        if turn.replaces_event_id or turn.redacts_event_id or turn.event_id in redacted:
            continue
        replacement = replacements.get(turn.event_id)
        projected.append(
            replace(
                replacement,
                reply_to_event_id=turn.reply_to_event_id,
                thread_root_event_id=turn.thread_root_event_id,
            )
            if replacement
            else turn
        )
    return sorted(projected, key=lambda item: (item.timestamp_ms, item.event_id))


@dataclass(frozen=True)
class IntakeResult:
    case_id: int | None = None
    created: bool = False
    changed: bool = False
    affected_case_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class RequestSnapshot:
    case_id: int
    room_id: str
    requester_id: str
    revision: int
    turns: tuple[ConversationTurn, ...]
    last_requester_at_ms: int
    kind: str = "note"
    previous_generated_snapshot: dict[str, Any] | None = None
    overflow: bool = False
    omitted_event_ids: tuple[str, ...] = ()
    observed_at_ms: int = 0
    draft_presented: bool = False
    replacement_allowed: bool = False
    speaker_aliases: dict[str, str] = field(default_factory=dict)
    request_started_at_ms: int = 0
    staff_replied: bool = False

    def should_draft(self, decision: Any) -> bool:
        """A withheld first draft can use the one bounded replacement slot."""
        return (
            decision.category == "unanswered_support_request"
            and not self.staff_replied
            and not self.staff_reply_event_ids(decision.selected_event_ids)
            and (
                self.kind == "note"
                or decision.material_change
                or self.replacement_allowed
            )
        )

    def staff_reply_event_ids(
        self, selected_event_ids: list[str] | None = None
    ) -> tuple[str, ...]:
        """Native replies are certain; unthreaded membership comes from the gate.

        A Staff diagnostic question already counts as taking the request, even
        while the issue remains open. Prior Staff context for a distinct new
        request must not count, nor may unrelated room presence create a hold.
        """
        own = [
            turn
            for turn in self.turns
            if turn.sender_id == self.requester_id and not turn.is_staff
        ]
        started_at = self.request_started_at_ms or min(
            (turn.timestamp_ms for turn in own), default=0
        )
        own_ids = {
            event_id
            for turn in own
            for event_id in (turn.event_id, turn.replaces_event_id)
            if event_id
        }
        selected = set(selected_event_ids or [])
        return tuple(
            turn.event_id
            for turn in self.turns
            if turn.is_staff
            and not turn.is_bot
            and turn.timestamp_ms >= started_at
            and (
                turn.reply_to_event_id in own_ids
                or turn.thread_root_event_id in own_ids
                or turn.event_id in selected
            )
        )

    @property
    def version(self) -> str:
        return _digest(
            [self.case_id, self.revision, [asdict(turn) for turn in self.turns]]
        )

    @property
    def anchor(self) -> ConversationTurn:
        own = [
            turn
            for turn in self.turns
            if turn.sender_id == self.requester_id
            and not turn.is_staff
            and not acknowledgement_only(turn.text)
        ]
        return own[-1]

    def prompt_payload(self) -> dict[str, Any]:
        speakers = {**self.speaker_aliases, self.requester_id: "requester"}
        messages = []
        for turn in self.turns:
            speakers.setdefault(turn.sender_id, f"participant-{len(speakers)}")
            messages.append(
                {
                    "event_id": turn.event_id,
                    "speaker": speakers[turn.sender_id],
                    "role": (
                        "staff"
                        if turn.is_staff
                        else (
                            "requester"
                            if turn.sender_id == self.requester_id
                            else "participant"
                        )
                    ),
                    "text": turn.text,
                    "reply_to": turn.reply_to_event_id,
                    "thread_root": turn.thread_root_event_id,
                }
            )
        return {
            "messages": messages,
            "previous_generated_request": self.previous_generated_snapshot,
            "omitted_event_ids": list(self.omitted_event_ids),
        }


def selected_staff_request(
    snapshot: RequestSnapshot, decision: Any, evidence: list[Any]
) -> StaffContextRequest:
    """One conversion shared by live drafting and replay; never add future turns."""
    selected = set(decision.selected_event_ids)
    turns = [turn for turn in snapshot.turns if turn.event_id in selected]
    own = [
        turn.text
        for turn in turns
        if turn.sender_id == snapshot.requester_id and not turn.is_staff
    ]
    speakers = {**snapshot.speaker_aliases, snapshot.requester_id: "requester"}
    messages = []
    for turn in turns:
        speakers.setdefault(turn.sender_id, f"participant-{len(speakers)}")
        for offset in range(0, len(turn.text), 4000):
            messages.append(
                RoomMessage(
                    role=(
                        "staff"
                        if turn.is_staff
                        else (
                            "user"
                            if turn.sender_id == snapshot.requester_id
                            else "participant"
                        )
                    ),
                    content=turn.text[offset : offset + 4000],
                    speaker=speakers[turn.sender_id],
                )
            )
    return StaffContextRequest(
        question="\n".join(own),
        recent_messages=messages,
        evidence=evidence,
        high_risk_action=any(
            re.search(pattern, "\n".join(own), re.I) for pattern in _HIGH_RISK_PATTERNS
        ),
    )


class StaffConversationCoordinator:
    """Durable request grouping; only new spend-bound trials use this version."""

    def __init__(
        self,
        escalation_service: Any,
        trial_id: str,
        *,
        first_response_delay_seconds: float,
    ):
        self.service = escalation_service
        self.db_path = escalation_service.repository.db_path
        self.trial_id = trial_id
        self.delay_ms = int(first_response_delay_seconds * 1000)
        self._lock = asyncio.Lock()
        self._recent: dict[str, list[ConversationTurn]] = {}

    async def _rows(self, room_id: str | None = None) -> list[Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            sql = "SELECT id, user_id, status, channel_metadata FROM escalations WHERE channel='matrix' AND json_extract(channel_metadata,'$.context_workflow_version')=3 AND json_extract(channel_metadata,'$.context_trial_id')=?"
            params: list[Any] = [self.trial_id]
            if room_id is not None:
                sql += " AND json_extract(channel_metadata,'$.room_id')=?"
                params.append(room_id)
            return list(
                await (await db.execute(sql + " ORDER BY id", params)).fetchall()
            )

    async def _change(self, case_id: int, **changes: Any) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute(
                    "SELECT channel_metadata FROM escalations WHERE id=?", (case_id,)
                )
            ).fetchone()
            if not row:
                raise ValueError("Request no longer exists")
            metadata = json.loads(row[0] or "{}")
            metadata.update(changes)
            await db.execute(
                "UPDATE escalations SET channel_metadata=? WHERE id=?",
                (json.dumps(metadata), case_id),
            )
            await db.commit()

    async def ingest(
        self, turn: ConversationTurn, *, now_ms: int, allow_new: bool = True
    ) -> IntakeResult:
        if turn.timestamp_ms > now_ms:
            raise ValueError("Future events cannot enter a request snapshot")
        if turn.is_bot:
            return IntakeResult()
        async with self._lock:
            rows = await self._rows(turn.room_id)
            states = [
                (row, json.loads(row["channel_metadata"] or "{}")) for row in rows
            ]
            known_member = any(
                any(
                    item["event_id"] == turn.event_id
                    for item in metadata.get("incident_messages", [])
                )
                for _, metadata in states
            )
            known_neighbor = any(
                any(
                    item["event_id"] == turn.event_id
                    for item in metadata.get("conversation_exchange", [])
                )
                for _, metadata in states
            )
            # A bounded context read can see a new requester before their real
            # subscription callback. That incidental observation is not intake.
            if known_member or (known_neighbor and (not allow_new or turn.is_staff)):
                return IntakeResult()
            recent = self._recent.setdefault(turn.room_id, [])
            if not any(item.event_id == turn.event_id for item in recent):
                recent.append(turn)
                del recent[:-MAX_EXCHANGE_TURNS]
            target = (
                turn.replaces_event_id
                or turn.thread_root_event_id
                or turn.reply_to_event_id
                or turn.redacts_event_id
            )
            linked = []
            for row, metadata in states:
                members = metadata.get("incident_messages", [])
                found = next(
                    (item for item in members if item["event_id"] == target), None
                )
                if found:
                    if turn.replaces_event_id and found["sender_id"] != turn.sender_id:
                        return IntakeResult()
                    linked.append((row, metadata))
            own = [
                (row, metadata)
                for row, metadata in states
                if row["user_id"] == turn.sender_id
                and row["status"] in {"pending", "in_review"}
                and not metadata.get("conversation_resolved")
            ]
            chosen = (
                linked[-1]
                if linked and (turn.replaces_event_id or not new_issue(turn.text))
                else own[-1] if own and not new_issue(turn.text) else None
            )
            if chosen is None and acknowledgement_only(turn.text):
                previous = [
                    (row, metadata)
                    for row, metadata in states
                    if row["user_id"] == turn.sender_id
                ]
                chosen = previous[-1] if previous else None
            created = False
            if (
                allow_new
                and chosen is None
                and not (
                    turn.is_staff
                    or turn.replaces_event_id
                    or turn.redacts_event_id
                    or acknowledgement_only(turn.text)
                    or not turn.text
                )
            ):
                metadata = {
                    "response_kind": "public_context",
                    "delivery_audience": "staff_room",
                    "context_workflow_version": 3,
                    "context_trial_id": self.trial_id,
                    "room_id": turn.room_id,
                    "source_event_id": turn.event_id,
                    "conversation_requester_id": turn.sender_id,
                    "conversation_request_started_at_ms": turn.timestamp_ms,
                    "conversation_revision": 0,
                    "conversation_last_gate_revision": -1,
                    "conversation_last_requester_at_ms": turn.timestamp_ms,
                    "conversation_exchange": [],
                    "incident_messages": [],
                    "context_status": "preparing",
                    "context_reason": "request_waiting",
                    "model_called": False,
                    "model_call_status": "not_started",
                }
                case = await self.service.create_escalation(
                    EscalationCreate(
                        message_id="matrix-context:"
                        + _digest([turn.room_id, turn.event_id]),
                        channel="matrix",
                        user_id=turn.sender_id,
                        username=None,
                        question=turn.text[:4000],
                        ai_draft_answer="No Staff draft generated yet.",
                        confidence_score=0,
                        routing_action="needs_human",
                        routing_reason="request_waiting",
                        channel_metadata=metadata,
                    )
                )
                row = {"id": case.id, "user_id": turn.sender_id, "status": "pending"}
                chosen = (row, metadata)
                states.append(chosen)
                created = True
            affected = []
            for row, metadata in states:
                if row["status"] not in {"pending", "in_review"}:
                    continue
                is_chosen = chosen is not None and row["id"] == chosen[0]["id"]
                if metadata.get("conversation_resolved") and not is_chosen:
                    continue
                exchange = metadata.get("conversation_exchange", [])
                if created and is_chosen:
                    exchange = [
                        asdict(item) for item in recent if item.timestamp_ms <= now_ms
                    ]
                elif not any(item["event_id"] == turn.event_id for item in exchange):
                    exchange = [*exchange, asdict(turn)]
                members = metadata.get("incident_messages", [])
                if is_chosen:
                    members = [*members, asdict(turn)]
                # A Staff reply can arrive before its requester event. Reconcile
                # captured native relations now, before optional context is trimmed,
                # so proven Staff ownership survives trimming and process restart.
                requester_members = [
                    item
                    for item in members
                    if item["sender_id"] == row["user_id"] and not item.get("is_staff")
                ]
                requester_ids = {item["event_id"] for item in requester_members}
                started_at = metadata.get("conversation_request_started_at_ms") or min(
                    (item["timestamp_ms"] for item in requester_members), default=0
                )
                native_staff_ids = [
                    item["event_id"]
                    for item in exchange
                    if item.get("is_staff")
                    and not item.get("is_bot")
                    and not item.get("redacts_event_id")
                    and item["timestamp_ms"] >= started_at
                    and (
                        item.get("reply_to_event_id") in requester_ids
                        or item.get("thread_root_event_id") in requester_ids
                    )
                ]
                # Required requester/member turns survive neighborhood trimming.
                required = {item["event_id"] for item in members}
                optional = [
                    item for item in exchange if item["event_id"] not in required
                ][-MAX_EXCHANGE_TURNS:]
                exchange = list(
                    {item["event_id"]: item for item in [*members, *optional]}.values()
                )
                aliases = dict(
                    metadata.get(
                        "conversation_speaker_aliases", {row["user_id"]: "requester"}
                    )
                )
                for item in exchange:
                    aliases.setdefault(item["sender_id"], f"participant-{len(aliases)}")
                changes = {
                    "conversation_exchange": exchange,
                    "incident_messages": members,
                    "conversation_speaker_aliases": aliases,
                }
                obvious_ack = (
                    (
                        gratitude_only(turn.text)
                        or bool(
                            re.fullmatch(
                                r"(?:ok(?:ay)?|great)[.! ]*", turn.text.strip(), re.I
                            )
                        )
                    )
                    and not turn.replaces_event_id
                    and not turn.redacts_event_id
                )
                changed = (is_chosen and not obvious_ack) or (
                    turn.sender_id != row["user_id"]
                    and not obvious_ack
                    and metadata.get("conversation_running_revision") is not None
                )
                if native_staff_ids:
                    changes["conversation_staff_replied"] = True
                    changes["conversation_staff_reply_event_ids"] = list(
                        dict.fromkeys(
                            [
                                *metadata.get("conversation_staff_reply_event_ids", []),
                                *native_staff_ids,
                            ]
                        )
                    )
                    if metadata.get("conversation_generation_count", 0):
                        changes["conversation_staff_replied_after_draft"] = True
                if changed:
                    changes["conversation_revision"] = (
                        metadata.get("conversation_revision", 0) + 1
                    )
                    affected.append(row["id"])
                if is_chosen and turn.sender_id == row["user_id"] and not turn.is_staff:
                    changes["conversation_last_requester_at_ms"] = max(
                        turn.timestamp_ms,
                        metadata.get("conversation_last_requester_at_ms", 0),
                    )
                await self._change(row["id"], **changes)
            return IntakeResult(
                chosen[0]["id"] if chosen else None,
                created,
                bool(affected),
                tuple(affected),
            )

    async def snapshot(self, case_id: int, *, now_ms: int) -> RequestSnapshot:
        case = await self.service.repository.get_by_id(case_id)
        if case is None:
            raise ValueError("Request no longer exists")
        metadata = case.channel_metadata or {}
        raw = [
            ConversationTurn.from_dict(item)
            for item in metadata.get("conversation_exchange", [])
            if item["timestamp_ms"] <= now_ms
        ]
        turns = effective_turns(raw)
        required = {item["event_id"] for item in metadata.get("incident_messages", [])}
        own = [
            turn
            for turn in turns
            if turn.sender_id == case.user_id
            and (turn.event_id in required or turn.replaces_event_id in required)
        ]
        others = [turn for turn in turns if turn.sender_id != case.user_id]
        # Native members are required; neighbors are optional, explicitly bounded.
        linked = [
            turn
            for turn in others
            if turn.event_id in required
            or turn.replaces_event_id in required
            or turn.reply_to_event_id in required
            or turn.thread_root_event_id in required
        ]
        selected = [*own, *linked]

        def fits(items):
            return (
                len(items) <= MAX_EXCHANGE_TURNS
                and sum(len(turn.text.encode("utf-8")) for turn in items)
                <= MAX_EXCHANGE_BYTES
                and sum(max(1, (len(turn.text) + 3999) // 4000) for turn in items)
                <= 128
                and len({turn.sender_id for turn in items}) <= 100
            )

        overflow = sum(len(turn.text) for turn in own) > MAX_REQUEST_CHARS or not fits(
            selected
        )
        selected_ids = {turn.event_id for turn in selected}
        omitted = []
        for turn in reversed(others):
            if turn.event_id in selected_ids:
                continue
            if fits([*selected, turn]):
                selected.append(turn)
            else:
                omitted.append(turn.event_id)
        selected.sort(key=lambda turn: (turn.timestamp_ms, turn.event_id))
        aliases = metadata.get("conversation_speaker_aliases", {})
        overflow = overflow or any(
            alias != "requester" and int(alias.split("-")[-1]) > 99
            for alias in aliases.values()
        )
        return RequestSnapshot(
            case_id,
            metadata["room_id"],
            case.user_id,
            metadata.get("conversation_revision", 0),
            tuple(selected),
            metadata.get("conversation_last_requester_at_ms", 0),
            "update" if metadata.get("conversation_generation_count", 0) else "note",
            metadata.get("conversation_generated_snapshot"),
            overflow,
            tuple(omitted),
            now_ms,
            bool(metadata.get("conversation_draft_presented")),
            bool(metadata.get("conversation_replacement_allowed")),
            aliases,
            metadata.get("conversation_request_started_at_ms")
            or min(
                (
                    item["timestamp_ms"]
                    for item in metadata.get("incident_messages", [])
                    if item["sender_id"] == case.user_id
                ),
                default=0,
            ),
            bool(
                metadata.get("conversation_staff_replied")
                or metadata.get("conversation_staff_replied_after_draft")
            ),
        )

    async def due(self, *, now_ms: int) -> list[RequestSnapshot]:
        result = []
        for row in await self._rows():
            metadata = json.loads(row["channel_metadata"] or "{}")
            if (
                row["status"] not in {"pending", "in_review"}
                or metadata.get("conversation_resolved")
                or metadata.get("conversation_delivery_uncertain")
                or metadata.get("conversation_staff_replied_after_draft")
                or metadata.get("conversation_staff_replied")
            ):
                continue
            if (
                metadata.get("conversation_running_revision") is not None
                or metadata.get("conversation_generation_count", 0) >= 2
            ):
                continue
            if (
                metadata.get("conversation_revision", 0)
                <= metadata.get("conversation_last_gate_revision", -1)
                or now_ms
                < metadata.get("conversation_last_requester_at_ms", 0) + self.delay_ms
            ):
                continue
            snapshot = await self.snapshot(row["id"], now_ms=now_ms)
            if snapshot.staff_reply_event_ids():
                continue
            if any(
                turn.sender_id == snapshot.requester_id
                and not turn.is_staff
                and not acknowledgement_only(turn.text)
                for turn in snapshot.turns
            ):
                result.append(snapshot)
        return result

    async def claim(self, snapshot: RequestSnapshot) -> bool:
        if snapshot.staff_replied or snapshot.staff_reply_event_ids():
            return False
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute(
                    "SELECT channel_metadata, status FROM escalations WHERE id=?",
                    (snapshot.case_id,),
                )
            ).fetchone()
            metadata = json.loads(row[0] or "{}") if row else {}
            if (
                not row
                or row[1] not in {"pending", "in_review"}
                or metadata.get("conversation_resolved")
                or metadata.get("conversation_last_gate_revision", -1)
                >= snapshot.revision
                or metadata.get("conversation_revision") != snapshot.revision
                or metadata.get("conversation_running_revision") is not None
                or metadata.get("conversation_delivery_uncertain")
                or metadata.get("conversation_staff_replied_after_draft")
                or metadata.get("conversation_staff_replied")
            ):
                return False
            metadata["conversation_running_revision"] = snapshot.revision
            await db.execute(
                "UPDATE escalations SET channel_metadata=? WHERE id=?",
                (json.dumps(metadata), snapshot.case_id),
            )
            await db.commit()
            return True

    async def record_gate(self, snapshot: RequestSnapshot, decision: Any) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute(
                    "SELECT channel_metadata, status FROM escalations WHERE id=?",
                    (snapshot.case_id,),
                )
            ).fetchone()
            metadata = json.loads(row[0] or "{}") if row else {}
            if (
                not row
                or row[1] not in {"pending", "in_review"}
                or metadata.get("conversation_revision") != snapshot.revision
                or metadata.get("conversation_staff_replied")
                or metadata.get("conversation_staff_replied_after_draft")
            ):
                return False
            staff_reply_ids = snapshot.staff_reply_event_ids(
                decision.selected_event_ids
            )
            if staff_reply_ids:
                metadata["conversation_staff_replied"] = True
                metadata["conversation_staff_reply_event_ids"] = list(staff_reply_ids)
                if metadata.get("conversation_generation_count", 0):
                    metadata["conversation_staff_replied_after_draft"] = True
            metadata.update(
                conversation_last_gate_revision=snapshot.revision,
                conversation_gate=decision.model_dump(),
                conversation_resolved=decision.category
                in {"not_a_request", "helping_another"}
                or getattr(decision, "request_resolved", False),
            )
            await db.execute(
                "UPDATE escalations SET channel_metadata=? WHERE id=?",
                (json.dumps(metadata), snapshot.case_id),
            )
            await db.commit()
            return True

    async def record_draft(
        self,
        snapshot: RequestSnapshot,
        preview: Any,
        *,
        selected_event_ids: list[str] | None = None,
        presented: bool = True,
    ) -> None:
        case = await self.service.repository.get_by_id(snapshot.case_id)
        metadata = case.channel_metadata or {}
        count = metadata.get("conversation_generation_count", 0) + int(
            preview.model_called
        )
        selected = set(selected_event_ids or [turn.event_id for turn in snapshot.turns])
        await self._change(
            snapshot.case_id,
            conversation_generation_count=count,
            conversation_last_preview_renderable=bool(
                getattr(preview, "rendered_note", None)
            ),
            conversation_replacement_allowed=False,
            conversation_draft_presented=bool(
                metadata.get("conversation_draft_presented")
                or (presented and getattr(preview, "rendered_note", None))
            ),
            conversation_generated_revision=snapshot.revision,
            conversation_generated_snapshot={
                "observed_at_ms": snapshot.observed_at_ms,
                "messages": [
                    item
                    for item in snapshot.prompt_payload()["messages"]
                    if item["event_id"] in selected
                ],
            },
            conversation_last_gate_revision=snapshot.revision,
        )

    async def record_withheld(self, snapshot: RequestSnapshot) -> None:
        """Allow one replacement only for a renderable draft invalidated by input."""
        case = await self.service.repository.get_by_id(snapshot.case_id)
        metadata = case.channel_metadata or {}
        delivery = metadata.get("staff_note_delivery")
        not_attempted = delivery is None or delivery.get("operation_started") is False
        allowed = (
            metadata.get("conversation_generation_count") == 1
            and metadata.get("conversation_last_preview_renderable")
            and metadata.get("conversation_revision") != snapshot.revision
            and metadata.get("context_status") == "deferred"
            and not metadata.get("staff_note_event_id")
            and not_attempted
        )
        await self._change(
            snapshot.case_id, conversation_replacement_allowed=bool(allowed)
        )

    async def record_delivery(self, snapshot: RequestSnapshot) -> None:
        """Record sink acceptance; never a claim about Staff judgment or reuse."""
        await self._change(snapshot.case_id, conversation_draft_presented=True)

    async def finish(
        self, snapshot: RequestSnapshot, *, uncertain: bool = False
    ) -> None:
        await self._change(
            snapshot.case_id,
            conversation_running_revision=None,
            conversation_delivery_uncertain=uncertain,
        )

    async def is_current(self, snapshot: RequestSnapshot) -> bool:
        case = await self.service.repository.get_by_id(snapshot.case_id)
        metadata = case.channel_metadata or {} if case else {}
        return bool(
            case
            and case.status.value in {"pending", "in_review"}
            and metadata.get("conversation_revision") == snapshot.revision
            and not metadata.get("conversation_resolved")
            and not metadata.get("conversation_delivery_uncertain")
            and not metadata.get("conversation_staff_replied")
            and not metadata.get("conversation_staff_replied_after_draft")
        )
