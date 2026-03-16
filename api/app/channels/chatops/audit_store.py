"""Durable audit storage for shared ChatOps actions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Generator

from app.metrics.operator_metrics import record_chatops_audit_write


@dataclass(slots=True)
class ChatOpsAuditEntry:
    id: int
    channel_id: str
    room_id: str
    actor_id: str
    command_name: str
    case_id: int | None
    source_message_id: str
    ok: bool
    idempotent: bool
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class ChatOpsAuditStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chatops_action_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    room_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    command_name TEXT NOT NULL,
                    case_id INTEGER,
                    source_message_id TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    idempotent INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """)

    def add_entry(
        self,
        *,
        channel_id: str,
        room_id: str,
        actor_id: str,
        command_name: str,
        case_id: int | None,
        source_message_id: str,
        ok: bool,
        idempotent: bool,
        metadata: dict[str, Any] | None = None,
        created_at: datetime,
    ) -> ChatOpsAuditEntry:
        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chatops_action_audit (
                    channel_id,
                    room_id,
                    actor_id,
                    command_name,
                    case_id,
                    source_message_id,
                    ok,
                    idempotent,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_id,
                    room_id,
                    actor_id,
                    command_name,
                    case_id,
                    source_message_id,
                    1 if ok else 0,
                    1 if idempotent else 0,
                    metadata_json,
                    created_at.astimezone(UTC).isoformat(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM chatops_action_audit WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        record_chatops_audit_write(
            channel=channel_id or "unknown",
            result="success",
        )
        return self._entry_from_row(row)

    def list_entries(
        self,
        *,
        limit: int = 50,
        channel_id: str | None = None,
    ) -> list[ChatOpsAuditEntry]:
        if channel_id:
            query = """
                SELECT * FROM chatops_action_audit
                WHERE channel_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """
            params: tuple[Any, ...] = (channel_id, limit)
        else:
            query = """
                SELECT * FROM chatops_action_audit
                ORDER BY created_at DESC
                LIMIT ?
            """
            params = (limit,)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._entry_from_row(row) for row in rows]

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> ChatOpsAuditEntry:
        return ChatOpsAuditEntry(
            id=int(row["id"]),
            channel_id=row["channel_id"],
            room_id=row["room_id"],
            actor_id=row["actor_id"],
            command_name=row["command_name"],
            case_id=int(row["case_id"]) if row["case_id"] is not None else None,
            source_message_id=row["source_message_id"],
            ok=bool(row["ok"]),
            idempotent=bool(row["idempotent"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
