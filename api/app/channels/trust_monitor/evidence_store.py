from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Generator

from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.models import (
    TrustAccessAuditEntry,
    TrustActorProfile,
    TrustAlertSurface,
    TrustEventType,
    TrustEvidenceRecord,
    TrustFeedbackAction,
    TrustFinding,
    TrustFindingCounts,
    TrustFindingList,
    TrustFindingStatus,
    TrustPolicy,
)


class TrustMonitorStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    @contextmanager
    def connection(
        self,
        *,
        commit: bool = True,
    ) -> Generator[sqlite3.Connection, None, None]:
        with self._lock:
            conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False, timeout=30.0
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                if commit:
                    conn.commit()
            finally:
                conn.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS trust_actor_profiles (
            actor_key TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            current_display_name TEXT NOT NULL DEFAULT '',
            normalized_display_name TEXT NOT NULL DEFAULT '',
            trusted_staff INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS trust_evidence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            space_id TEXT NOT NULL,
            thread_id TEXT,
            actor_key TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_display_name TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            target_actor_key TEXT,
            target_actor_id TEXT,
            target_message_id TEXT,
            external_event_id TEXT,
            occurred_at TEXT NOT NULL,
            trusted_staff INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trust_evidence_external
            ON trust_evidence_events(channel_id, external_event_id)
            WHERE external_event_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS trust_actor_aggregates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detector_key TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            space_id TEXT NOT NULL,
            actor_key TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            window_start_at TEXT NOT NULL,
            metrics_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(detector_key, channel_id, space_id, actor_key)
        );
        CREATE TABLE IF NOT EXISTS trust_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detector_key TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            space_id TEXT NOT NULL,
            suspect_actor_key TEXT NOT NULL,
            suspect_actor_id TEXT NOT NULL,
            suspect_display_name TEXT NOT NULL DEFAULT '',
            score REAL NOT NULL,
            status TEXT NOT NULL,
            alert_surface TEXT NOT NULL,
            evidence_summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_notified_at TEXT,
            notification_count INTEGER NOT NULL DEFAULT 0,
            suppressed_until TEXT,
            benign_until TEXT,
            UNIQUE(detector_key, channel_id, space_id, suspect_actor_key)
        );
        CREATE TABLE IF NOT EXISTS trust_finding_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(finding_id) REFERENCES trust_findings(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS trust_access_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        """
        with self.connection() as conn:
            conn.executescript(schema)

    @staticmethod
    def _serialize_metadata(metadata: dict[str, Any]) -> str:
        return json.dumps(metadata, sort_keys=True)

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(metadata or {})
        sanitized.pop("body", None)
        sanitized.pop("message", None)
        sanitized.pop("text", None)
        return sanitized

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    def upsert_actor_profile(
        self,
        *,
        channel_id: str,
        actor_key: str,
        actor_id: str,
        display_name: str,
        normalized_display_name: str,
        trusted_staff: bool,
        occurred_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> TrustActorProfile:
        metadata_json = self._serialize_metadata(
            self._sanitize_metadata(metadata or {})
        )
        ts = occurred_at.astimezone(UTC).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trust_actor_profiles (
                    actor_key, channel_id, actor_id, current_display_name,
                    normalized_display_name, trusted_staff, first_seen_at,
                    last_seen_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(actor_key) DO UPDATE SET
                    current_display_name = excluded.current_display_name,
                    normalized_display_name = excluded.normalized_display_name,
                    trusted_staff = excluded.trusted_staff,
                    last_seen_at = excluded.last_seen_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    actor_key,
                    channel_id,
                    actor_id,
                    display_name,
                    normalized_display_name,
                    1 if trusted_staff else 0,
                    ts,
                    ts,
                    metadata_json,
                ),
            )
            row = conn.execute(
                "SELECT * FROM trust_actor_profiles WHERE actor_key = ?", (actor_key,)
            ).fetchone()
        return self._profile_from_row(row)

    def insert_event(
        self,
        *,
        event: TrustEvent,
        actor_key: str,
        target_actor_key: str | None,
        trusted_staff: bool,
    ) -> TrustEvidenceRecord | None:
        metadata_json = self._serialize_metadata(
            self._sanitize_metadata(event.metadata)
        )
        values = (
            event.channel_id,
            event.space_id,
            event.thread_id,
            actor_key,
            event.actor_id,
            event.actor_display_name,
            event.event_type.value,
            target_actor_key,
            event.target_actor_id,
            event.target_message_id,
            event.external_event_id,
            event.occurred_at.astimezone(UTC).isoformat(),
            1 if trusted_staff else 0,
            metadata_json,
        )
        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO trust_evidence_events (
                        channel_id, space_id, thread_id, actor_key, actor_id,
                        actor_display_name, event_type, target_actor_key,
                        target_actor_id, target_message_id, external_event_id,
                        occurred_at, trusted_staff, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT * FROM trust_evidence_events WHERE channel_id = ? AND external_event_id = ?",
                    (event.channel_id, event.external_event_id),
                ).fetchone()
                return self._evidence_from_row(row) if row else None
            row = conn.execute(
                "SELECT * FROM trust_evidence_events WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._evidence_from_row(row)

    def upsert_aggregate(
        self,
        *,
        detector_key: str,
        channel_id: str,
        space_id: str,
        actor_key: str,
        actor_id: str,
        observed_at: datetime,
        window_start_at: datetime,
        metrics: dict[str, Any],
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trust_actor_aggregates (
                    detector_key, channel_id, space_id, actor_key, actor_id,
                    observed_at, window_start_at, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(detector_key, channel_id, space_id, actor_key) DO UPDATE SET
                    observed_at = excluded.observed_at,
                    window_start_at = excluded.window_start_at,
                    metrics_json = excluded.metrics_json,
                    actor_id = excluded.actor_id
                """,
                (
                    detector_key,
                    channel_id,
                    space_id,
                    actor_key,
                    actor_id,
                    observed_at.astimezone(UTC).isoformat(),
                    window_start_at.astimezone(UTC).isoformat(),
                    self._serialize_metadata(metrics),
                ),
            )

    def upsert_finding(
        self,
        *,
        detector_key: str,
        channel_id: str,
        space_id: str,
        suspect_actor_key: str,
        suspect_actor_id: str,
        suspect_display_name: str,
        score: float,
        alert_surface: TrustAlertSurface,
        evidence_summary: dict[str, Any],
        created_at: datetime,
        notify: bool,
    ) -> TrustFinding:
        ts = created_at.astimezone(UTC).isoformat()
        evidence_json = self._serialize_metadata(evidence_summary)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM trust_findings WHERE detector_key = ? AND channel_id = ? AND space_id = ? AND suspect_actor_key = ?",
                (detector_key, channel_id, space_id, suspect_actor_key),
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO trust_findings (
                        detector_key, channel_id, space_id, suspect_actor_key,
                        suspect_actor_id, suspect_display_name, score, status,
                        alert_surface, evidence_summary_json, created_at,
                        updated_at, last_notified_at, notification_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        detector_key,
                        channel_id,
                        space_id,
                        suspect_actor_key,
                        suspect_actor_id,
                        suspect_display_name,
                        score,
                        TrustFindingStatus.OPEN.value,
                        alert_surface.value,
                        evidence_json,
                        ts,
                        ts,
                        ts if notify else None,
                        1 if notify else 0,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM trust_findings WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            else:
                notification_count = int(row["notification_count"] or 0)
                last_notified_at = row["last_notified_at"]
                conn.execute(
                    """
                    UPDATE trust_findings SET
                        suspect_actor_id = ?,
                        suspect_display_name = ?,
                        score = ?,
                        status = ?,
                        alert_surface = ?,
                        evidence_summary_json = ?,
                        updated_at = ?,
                        last_notified_at = ?,
                        notification_count = ?
                    WHERE id = ?
                    """,
                    (
                        suspect_actor_id,
                        suspect_display_name,
                        score,
                        TrustFindingStatus.OPEN.value,
                        alert_surface.value,
                        evidence_json,
                        ts,
                        ts if notify else last_notified_at,
                        notification_count + (1 if notify else 0),
                        row["id"],
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM trust_findings WHERE id = ?", (row["id"],)
                ).fetchone()
        return self._finding_from_row(row)

    def find_existing_finding(
        self,
        *,
        detector_key: str,
        channel_id: str,
        space_id: str,
        suspect_actor_key: str,
    ) -> TrustFinding | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM trust_findings WHERE detector_key = ? AND channel_id = ? AND space_id = ? AND suspect_actor_key = ?",
                (detector_key, channel_id, space_id, suspect_actor_key),
            ).fetchone()
        return self._finding_from_row(row) if row else None

    def get_finding(self, finding_id: int) -> TrustFinding | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM trust_findings WHERE id = ?", (finding_id,)
            ).fetchone()
        return self._finding_from_row(row) if row else None

    def list_findings(
        self,
        *,
        status: str | None = None,
        detector_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TrustFindingList:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if detector_key:
            clauses.append("detector_key = ?")
            params.append(detector_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM trust_findings {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM trust_findings {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return TrustFindingList(
            items=[self._finding_from_row(row) for row in rows],
            total=int(total),
        )

    def count_findings(self) -> TrustFindingCounts:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM trust_findings GROUP BY status"
            ).fetchall()
        counts = TrustFindingCounts()
        for row in rows:
            status = row["status"]
            count = int(row["count"])
            counts.total += count
            if status == TrustFindingStatus.OPEN.value:
                counts.open = count
            elif status == TrustFindingStatus.RESOLVED.value:
                counts.resolved = count
            elif status == TrustFindingStatus.FALSE_POSITIVE.value:
                counts.false_positive = count
            elif status == TrustFindingStatus.SUPPRESSED.value:
                counts.suppressed = count
            elif status == TrustFindingStatus.BENIGN.value:
                counts.benign = count
        return counts

    def add_feedback(
        self,
        *,
        finding_id: int,
        actor_id: str,
        action: TrustFeedbackAction,
        created_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO trust_finding_feedback (finding_id, actor_id, action, created_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
                (
                    finding_id,
                    actor_id,
                    action.value,
                    created_at.astimezone(UTC).isoformat(),
                    self._serialize_metadata(metadata or {}),
                ),
            )

    def update_finding_status(
        self,
        *,
        finding_id: int,
        status: TrustFindingStatus,
        updated_at: datetime,
        suppressed_until: datetime | None = None,
        benign_until: datetime | None = None,
    ) -> TrustFinding:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE trust_findings SET
                    status = ?,
                    updated_at = ?,
                    suppressed_until = ?,
                    benign_until = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    updated_at.astimezone(UTC).isoformat(),
                    (
                        suppressed_until.astimezone(UTC).isoformat()
                        if suppressed_until
                        else None
                    ),
                    benign_until.astimezone(UTC).isoformat() if benign_until else None,
                    finding_id,
                ),
            )
            row = conn.execute(
                "SELECT * FROM trust_findings WHERE id = ?", (finding_id,)
            ).fetchone()
        return self._finding_from_row(row)

    def add_access_audit(
        self,
        *,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        metadata: dict[str, Any] | None = None,
        created_at: datetime,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO trust_access_audit (actor_id, action, target_type, target_id, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    actor_id,
                    action,
                    target_type,
                    target_id,
                    self._serialize_metadata(metadata or {}),
                    created_at.astimezone(UTC).isoformat(),
                ),
            )

    def list_access_audit(self, *, limit: int = 50) -> list[TrustAccessAuditEntry]:
        with self.connection(commit=False) as conn:
            rows = conn.execute(
                "SELECT * FROM trust_access_audit ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._audit_from_row(row) for row in rows]

    def list_evidence(self, *, limit: int = 50) -> list[TrustEvidenceRecord]:
        with self.connection(commit=False) as conn:
            rows = conn.execute(
                "SELECT * FROM trust_evidence_events ORDER BY occurred_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def purge_expired(self, *, policy: TrustPolicy, now: datetime) -> None:
        evidence_cutoff = (
            (now - timedelta(days=policy.evidence_ttl_days)).astimezone(UTC).isoformat()
        )
        aggregate_cutoff = (
            (now - timedelta(days=policy.aggregate_ttl_days))
            .astimezone(UTC)
            .isoformat()
        )
        finding_cutoff = (
            (now - timedelta(days=policy.finding_ttl_days)).astimezone(UTC).isoformat()
        )
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM trust_evidence_events WHERE occurred_at < ?",
                (evidence_cutoff,),
            )
            conn.execute(
                "DELETE FROM trust_actor_aggregates WHERE observed_at < ?",
                (aggregate_cutoff,),
            )
            conn.execute(
                "DELETE FROM trust_findings WHERE updated_at < ?",
                (finding_cutoff,),
            )
            conn.execute(
                "DELETE FROM trust_finding_feedback WHERE created_at < ?",
                (finding_cutoff,),
            )
            conn.execute(
                "DELETE FROM trust_access_audit WHERE created_at < ?",
                (finding_cutoff,),
            )

    def count_early_reads(
        self,
        *,
        channel_id: str,
        space_id: str,
        actor_key: str,
        since: datetime,
        early_read_window_seconds: int,
    ) -> tuple[int, int, int]:
        since_iso = since.astimezone(UTC).isoformat()
        with self.connection(commit=False) as conn:
            observation_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM trust_evidence_events
                    WHERE channel_id = ?
                      AND space_id = ?
                      AND event_type = ?
                      AND trusted_staff = 0
                      AND occurred_at >= ?
                    """,
                    (
                        channel_id,
                        space_id,
                        TrustEventType.MESSAGE_SENT.value,
                        since_iso,
                    ),
                ).fetchone()[0]
            )
            early_hits = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT sent.id)
                    FROM trust_evidence_events AS sent
                    JOIN trust_evidence_events AS read
                      ON read.channel_id = sent.channel_id
                     AND read.space_id = sent.space_id
                     AND read.event_type = ?
                     AND read.actor_key = ?
                     AND read.target_message_id = sent.target_message_id
                     AND julianday(read.occurred_at) >= julianday(sent.occurred_at)
                     AND julianday(read.occurred_at) <= (
                           julianday(sent.occurred_at) + (? / 86400.0)
                     )
                    WHERE sent.channel_id = ?
                      AND sent.space_id = ?
                      AND sent.event_type = ?
                      AND sent.trusted_staff = 0
                      AND sent.occurred_at >= ?
                    """,
                    (
                        TrustEventType.MESSAGE_READ.value,
                        actor_key,
                        early_read_window_seconds,
                        channel_id,
                        space_id,
                        TrustEventType.MESSAGE_SENT.value,
                        since_iso,
                    ),
                ).fetchone()[0]
            )
            reply_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM trust_evidence_events
                    WHERE channel_id = ?
                      AND space_id = ?
                      AND event_type = ?
                      AND actor_key = ?
                      AND occurred_at >= ?
                    """,
                    (
                        channel_id,
                        space_id,
                        TrustEventType.MESSAGE_REPLIED.value,
                        actor_key,
                        since_iso,
                    ),
                ).fetchone()[0]
            )
        return observation_count, early_hits, int(reply_count)

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> TrustActorProfile:
        return TrustActorProfile(
            channel_id=row["channel_id"],
            actor_key=row["actor_key"],
            actor_id=row["actor_id"],
            current_display_name=row["current_display_name"],
            normalized_display_name=row["normalized_display_name"],
            trusted_staff=bool(row["trusted_staff"]),
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> TrustEvidenceRecord:
        return TrustEvidenceRecord(
            id=int(row["id"]),
            channel_id=row["channel_id"],
            space_id=row["space_id"],
            thread_id=row["thread_id"],
            actor_key=row["actor_key"],
            actor_id=row["actor_id"],
            actor_display_name=row["actor_display_name"],
            event_type=TrustEventType(row["event_type"]),
            target_actor_key=row["target_actor_key"],
            target_actor_id=row["target_actor_id"],
            target_message_id=row["target_message_id"],
            external_event_id=row["external_event_id"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            trusted_staff=bool(row["trusted_staff"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _finding_from_row(row: sqlite3.Row) -> TrustFinding:
        return TrustFinding(
            id=int(row["id"]),
            detector_key=row["detector_key"],
            channel_id=row["channel_id"],
            space_id=row["space_id"],
            suspect_actor_key=row["suspect_actor_key"],
            suspect_actor_id=row["suspect_actor_id"],
            suspect_display_name=row["suspect_display_name"],
            score=float(row["score"]),
            status=TrustFindingStatus(row["status"]),
            alert_surface=TrustAlertSurface(row["alert_surface"]),
            evidence_summary=json.loads(row["evidence_summary_json"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_notified_at=TrustMonitorStore._parse_timestamp(
                row["last_notified_at"]
            ),
            notification_count=int(row["notification_count"] or 0),
            suppressed_until=TrustMonitorStore._parse_timestamp(
                row["suppressed_until"]
            ),
            benign_until=TrustMonitorStore._parse_timestamp(row["benign_until"]),
        )

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> TrustAccessAuditEntry:
        return TrustAccessAuditEntry(
            id=int(row["id"]),
            actor_id=row["actor_id"],
            action=row["action"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
