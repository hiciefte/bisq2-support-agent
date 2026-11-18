"""Staff-context judgments. This path has no delivery or learning dependency."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from app.services.escalation.feedback_metrics import compute_edit_distance

STAFF_CONTEXT_VERDICTS = {
    "👍": "would_send_as_is",
    "✏": "would_send_after_edit",
    "❌": "wrong",
    "🚫": "not_needed",
}
STAFF_CONTEXT_VERDICT_HINT = (
    "React: 👍 as is · ✏️ after edit · ❌ wrong · 🚫 not needed"
)

CREATE_VERDICT_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS matrix_context_verdict_events (
    event_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    escalation_id INTEGER REFERENCES escalations(id) ON DELETE CASCADE,
    reviewer TEXT,
    target_event_id TEXT,
    verdict TEXT,
    timestamp_ms INTEGER,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0, 1))
)
"""

CREATE_ANSWER_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS matrix_context_answer_events (
    event_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    escalation_id INTEGER REFERENCES escalations(id) ON DELETE CASCADE,
    original_event_id TEXT,
    reviewer TEXT,
    answer TEXT,
    draft TEXT,
    timestamp_ms INTEGER,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0, 1)),
    reply_to_event_id TEXT
)
"""


def is_context_feedback_room(settings: Any, room_id: str) -> bool:
    """The configured Staff room is a read-only feedback destination."""
    configured = getattr(settings, "MATRIX_STAFF_ROOM", None)
    return (
        isinstance(configured, str) and bool(room_id) and room_id == configured.strip()
    )


def event_timestamp_ms(event: Any) -> int | None:
    value = getattr(event, "server_timestamp", None)
    if type(value) is not int or value < 0:
        return None
    return value


def _published_draft(metadata: dict[str, Any], reply_to_event_id: str) -> str | None:
    """Compare only the exact published event explicitly answered by Staff.

    Local send-acknowledgement clocks cannot establish which version existed at
    a Matrix server timestamp. A root reply or unresolved target stays unknown.
    """
    saved_history = metadata.get("staff_note_history")
    if not isinstance(saved_history, list):
        return None
    history = [
        item
        for item in saved_history
        if isinstance(item, dict)
        and isinstance(item.get("event_id"), str)
        and item["event_id"]
        and isinstance(item.get("reply"), str)
    ]
    explicit = [item for item in history if item["event_id"] == reply_to_event_id]
    replies = {item["reply"] for item in explicit}
    return replies.pop() if len(replies) == 1 else None


class ContextFeedbackStore:
    """Persist native-event feedback atomically, independent of generation state.

    Events are durable so duplicate sync delivery, restart, and out-of-order
    reactions cannot replace a newer verdict. Removing the newest reaction
    reveals that reviewer's previous non-redacted verdict.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @staticmethod
    async def _case(
        db: aiosqlite.Connection,
        room_id: str,
        target_event_id: str,
        *,
        thread: bool = False,
    ) -> aiosqlite.Row | None:
        # Exact persisted native event IDs; no text matching or room-history read.
        field = "staff_root_event_id" if thread else "staff_note_event_id"
        cursor = await db.execute(
            "SELECT id, channel_metadata FROM escalations "
            "WHERE channel='matrix' AND json_valid(channel_metadata) "
            "AND json_extract(channel_metadata, '$.delivery_audience')='staff_room' "
            "AND json_extract(channel_metadata, '$.response_kind')='public_context' "
            "AND json_extract(channel_metadata, '$.staff_room_id')=? "
            + (
                f"AND json_extract(channel_metadata, '$.{field}')=?"
                if thread
                else "AND (json_extract(channel_metadata, '$.staff_note_event_id')=? "
                "OR EXISTS (SELECT 1 FROM json_each("
                "json_extract(channel_metadata, '$.staff_note_history')) "
                "WHERE json_extract(value, '$.event_id')=?))"
            ),
            (
                (room_id, target_event_id)
                if thread
                else (room_id, target_event_id, target_event_id)
            ),
        )
        return await cursor.fetchone()

    async def has_note(self, room_id: str, event_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            return await self._case(db, room_id, event_id) is not None

    @staticmethod
    async def _project(db: aiosqlite.Connection, case_id: int) -> None:
        cursor = await db.execute(
            "SELECT event_id, target_event_id, reviewer, verdict, timestamp_ms "
            "FROM matrix_context_verdict_events WHERE escalation_id=? AND revoked=0 "
            "ORDER BY timestamp_ms DESC, event_id DESC",
            (case_id,),
        )
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in await cursor.fetchall():
            reviewer = row["reviewer"]
            key = (reviewer, row["target_event_id"])
            if key in latest:
                continue
            latest[key] = {
                "event_id": row["event_id"],
                "target_event_id": row["target_event_id"],
                "reviewer": reviewer,
                "verdict": row["verdict"],
                "at": datetime.fromtimestamp(
                    row["timestamp_ms"] / 1000, timezone.utc
                ).isoformat(),
            }
        await db.execute(
            "UPDATE escalations SET staff_context_verdicts=? WHERE id=?",
            (json.dumps(list(latest.values())), case_id),
        )

    async def record_verdict(
        self,
        *,
        room_id: str,
        target_event_id: str,
        event_id: str,
        reviewer: str,
        verdict: str,
        timestamp_ms: int,
    ) -> bool:
        if verdict not in STAFF_CONTEXT_VERDICTS.values():
            raise ValueError("Unknown Staff-context verdict")
        if (
            not event_id
            or not reviewer
            or type(timestamp_ms) is not int
            or timestamp_ms < 0
        ):
            return False
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("BEGIN IMMEDIATE")
            case = await self._case(db, room_id, target_event_id)
            if case is None:
                return False
            # INSERT OR IGNORE preserves both first observation and redaction
            # tombstones: replay cannot resurrect a removed reaction.
            await db.execute(
                "INSERT OR IGNORE INTO matrix_context_verdict_events "
                "(event_id, room_id, escalation_id, reviewer, target_event_id, verdict, timestamp_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    room_id,
                    case["id"],
                    reviewer,
                    target_event_id,
                    verdict,
                    timestamp_ms,
                ),
            )
            await self._project(db, case["id"])
            await db.commit()
            return True

    async def redact_verdict(self, room_id: str, event_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT escalation_id FROM matrix_context_verdict_events "
                "WHERE room_id=? AND event_id=?",
                (room_id, event_id),
            )
            row = await cursor.fetchone()
            await db.execute(
                "INSERT OR IGNORE INTO matrix_context_verdict_events "
                "(event_id, room_id, revoked) VALUES (?, ?, 1)",
                (event_id, room_id),
            )
            await db.execute(
                "UPDATE matrix_context_verdict_events SET revoked=1 "
                "WHERE room_id=? AND event_id=?",
                (room_id, event_id),
            )
            if row and row["escalation_id"] is not None:
                await self._project(db, row["escalation_id"])
            cursor = await db.execute(
                "SELECT escalation_id FROM matrix_context_answer_events WHERE room_id=? AND event_id=?",
                (room_id, event_id),
            )
            answer_row = await cursor.fetchone()
            await db.execute(
                "INSERT OR IGNORE INTO matrix_context_answer_events (event_id, room_id, revoked) VALUES (?, ?, 1)",
                (event_id, room_id),
            )
            await db.execute(
                "UPDATE matrix_context_answer_events SET revoked=1 WHERE room_id=? AND event_id=?",
                (room_id, event_id),
            )
            if answer_row and answer_row["escalation_id"] is not None:
                await self._project_answers(db, answer_row["escalation_id"])
            await db.commit()

    async def reconcile_answers(self, case_id: int) -> None:
        """Resolve explicitly targeted replies after their publication receipt commits."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            await self._project_answers(db, case_id)
            await db.commit()

    @staticmethod
    async def _project_answers(db: aiosqlite.Connection, case_id: int) -> None:
        cursor = await db.execute(
            "SELECT channel_metadata FROM escalations WHERE id=?", (case_id,)
        )
        case = await cursor.fetchone()
        if case is None:
            return
        metadata = json.loads(case["channel_metadata"] or "{}")
        cursor = await db.execute(
            "SELECT event_id, reply_to_event_id FROM matrix_context_answer_events "
            "WHERE escalation_id=? AND draft IS NULL AND reply_to_event_id IS NOT NULL "
            "AND revoked=0",
            (case_id,),
        )
        for pending in await cursor.fetchall():
            draft = _published_draft(metadata, pending["reply_to_event_id"])
            if draft is not None:
                await db.execute(
                    "UPDATE matrix_context_answer_events SET draft=? WHERE event_id=?",
                    (draft, pending["event_id"]),
                )
        cursor = await db.execute(
            "SELECT e.* FROM matrix_context_answer_events e "
            "JOIN matrix_context_answer_events original ON original.event_id=e.original_event_id "
            "WHERE e.escalation_id=? AND e.revoked=0 AND original.revoked=0 "
            "ORDER BY e.timestamp_ms DESC, e.event_id DESC LIMIT 1",
            (case_id,),
        )
        answer = await cursor.fetchone()
        if answer:
            metadata["staff_context_proposed_answer"] = {
                "event_id": answer["event_id"],
                "original_event_id": answer["original_event_id"],
                "timestamp_ms": answer["timestamp_ms"],
                "reviewer": answer["reviewer"],
                "answer": answer["answer"],
                "edit_distance": (
                    compute_edit_distance(answer["draft"], answer["answer"])
                    if isinstance(answer["draft"], str)
                    else None
                ),
                "draft_version_known": isinstance(answer["draft"], str),
            }
        else:
            metadata.pop("staff_context_proposed_answer", None)
        metadata.pop("staff_context_answer_event", None)
        # Matrix proposals are not Admin claims, completed responses or proof of
        # reuse. Updating a proposal must not transfer/revoke a claim or response.
        await db.execute(
            "UPDATE escalations SET channel_metadata=? WHERE id=?",
            (json.dumps(metadata), case_id),
        )

    async def record_answer(
        self,
        *,
        room_id: str,
        root_event_id: str,
        event_id: str,
        reviewer: str,
        answer: str,
        timestamp_ms: int,
        reply_to_event_id: str = "",
        replaces_event_id: str = "",
    ) -> bool:
        answer = answer.strip()
        if (
            not event_id
            or not reviewer
            or not answer
            or len(answer) > 10000
            or type(timestamp_ms) is not int
            or timestamp_ms < 0
        ):
            return False
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("BEGIN IMMEDIATE")
            if replaces_event_id:
                cursor = await db.execute(
                    "SELECT * FROM matrix_context_answer_events WHERE event_id=? AND room_id=? "
                    "AND reviewer=? AND event_id=original_event_id AND escalation_id IS NOT NULL",
                    (replaces_event_id, room_id, reviewer),
                )
                original = await cursor.fetchone()
                if original is None:
                    return False
                case_id, draft = original["escalation_id"], original["draft"]
                reply_to_event_id = original["reply_to_event_id"]
                original_event_id = replaces_event_id
            else:
                case = await self._case(db, room_id, root_event_id, thread=True)
                if case is None:
                    return False
                metadata = json.loads(case["channel_metadata"])
                draft = _published_draft(metadata, reply_to_event_id)
                case_id, original_event_id = case["id"], event_id
            await db.execute(
                "INSERT OR IGNORE INTO matrix_context_answer_events "
                "(event_id, room_id, escalation_id, original_event_id, reviewer, answer, draft, timestamp_ms, reply_to_event_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    room_id,
                    case_id,
                    original_event_id,
                    reviewer,
                    answer,
                    draft,
                    timestamp_ms,
                    reply_to_event_id or None,
                ),
            )
            await self._project_answers(db, case_id)
            await db.commit()
            return True
