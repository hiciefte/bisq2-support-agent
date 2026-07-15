"""Privacy retention across persisted personal-data stores."""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from app.metrics.privacy_metrics import (
    record_privacy_retention_failure,
    record_privacy_retention_run,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionStoreResult:
    """Outcome for one bounded retention store."""

    deleted_rows: int
    oldest_age_seconds: float | None
    window_seconds: float
    anonymized_rows: int = 0

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "deleted_rows": self.deleted_rows,
            "anonymized_rows": self.anonymized_rows,
            "oldest_age_seconds": self.oldest_age_seconds,
            "window_seconds": self.window_seconds,
        }


@dataclass
class PrivacyRetentionReport:
    """Serializable result of one retention pass."""

    dry_run: bool
    cutoff: datetime
    completed_at: datetime
    stores: dict[str, RetentionStoreResult] = field(default_factory=dict)
    vacuumed_databases: list[str] = field(default_factory=list)
    failed_store_groups: list[str] = field(default_factory=list)

    @property
    def deleted_rows(self) -> int:
        return sum(result.deleted_rows for result in self.stores.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "dry_run" if self.dry_run else "completed",
            "dry_run": self.dry_run,
            "cutoff": self.cutoff.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "deleted_rows": self.deleted_rows,
            "stores": {
                name: result.as_dict() for name, result in sorted(self.stores.items())
            },
            "vacuumed_databases": sorted(self.vacuumed_databases),
            "failed_store_groups": sorted(self.failed_store_groups),
        }


class PrivacyRetentionError(RuntimeError):
    """Raised after all store groups run when one or more failed."""

    def __init__(self, report: PrivacyRetentionReport) -> None:
        super().__init__("Privacy retention did not complete")
        self.report = report


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromtimestamp(float(raw), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return _utc(parsed)


def _record_timestamp(record: dict[str, Any]) -> datetime | None:
    for key in (
        "timestamp",
        "created_at",
        "source_timestamp",
        "processed_at",
        "updated_at",
        "last_updated_at",
    ):
        parsed = _parse_timestamp(record.get(key))
        if parsed is not None:
            return parsed
    return None


def _remove_path(path: Path) -> int:
    """Remove a file, symlink, or directory without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return 1
    if path.is_dir():
        count = sum(1 for candidate in path.rglob("*") if not candidate.is_dir())
        shutil.rmtree(path)
        return max(1, count)
    return 0


def _latest_mtime(path: Path) -> float | None:
    """Return the newest mtime in a path tree without following symlinks."""
    try:
        newest = path.lstat().st_mtime
    except FileNotFoundError:
        return None
    if path.is_symlink() or not path.is_dir():
        return newest
    for root, directories, files in os.walk(path, followlinks=False):
        for name in [*directories, *files]:
            candidate = Path(root) / name
            try:
                newest = max(newest, candidate.lstat().st_mtime)
            except FileNotFoundError:
                continue
    return newest


def prune_matrix_session_artifacts(
    *,
    session_file: Path,
    retention_days: int,
    now: datetime,
    dry_run: bool = False,
) -> RetentionStoreResult:
    """Expire a Matrix session and its crypto store as one atomic generation."""
    now = _utc(now)
    window_seconds = float(retention_days * 86400)
    if session_file.name in {"", ".", ".."} or session_file.is_dir():
        raise ValueError("Matrix session path must identify a file")
    session_mtime = _latest_mtime(session_file)
    store_dir = session_file.parent / f"{session_file.stem}_store"
    store_mtime = _latest_mtime(store_dir)
    generation_mtime: float | None = None
    if session_file.is_file() and not session_file.is_symlink():
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
            raw_created_at = (
                payload.get("created_at") if isinstance(payload, dict) else None
            )
            if isinstance(raw_created_at, str):
                created_at = datetime.fromisoformat(
                    raw_created_at.replace("Z", "+00:00")
                )
                generation_mtime = _utc(created_at).timestamp()
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            generation_mtime = None
    if generation_mtime is None:
        available_mtimes = [
            value for value in (session_mtime, store_mtime) if value is not None
        ]
        generation_mtime = max(available_mtimes, default=None)
    if generation_mtime is None:
        return RetentionStoreResult(0, None, window_seconds)

    age_seconds = max(0.0, now.timestamp() - generation_mtime)
    if age_seconds < window_seconds:
        return RetentionStoreResult(0, age_seconds, window_seconds)

    candidates = [
        path
        for path in (
            session_file,
            session_file.with_suffix(".tmp"),
            store_dir,
        )
        if path.exists() or path.is_symlink()
    ]
    deleted = sum(
        (
            max(1, sum(1 for item in path.rglob("*") if not item.is_dir()))
            if path.is_dir() and not path.is_symlink()
            else 1
        )
        for path in candidates
    )
    if not dry_run:
        for path in candidates:
            _remove_path(path)
    return RetentionStoreResult(
        deleted, None if not dry_run else age_seconds, window_seconds
    )


class PrivacyRetentionService:
    """Apply configured retention to all local personal-data stores."""

    _LEGACY_PERSONAL_FILES = (
        "conversations.jsonl",
        "processed_message_ids.jsonl",
        "processed_conversations.json",
        "support_chat_export.csv",
        "support_chat_export.json",
        "unified_conversations_output.json",
    )
    _LEGACY_PERSONAL_DATABASES = (
        "faq_candidates.db",
        "training_pipeline.db",
        "unified_candidates.db",
        "unified_faq_candidates.db",
        "unified_faq_training.db",
        "unified_faqs.db",
    )
    _LEGACY_TIMESTAMP_COLUMNS = (
        "timestamp",
        "created_at",
        "source_timestamp",
        "processed_at",
        "updated_at",
        "last_updated_at",
        "reviewed_at",
        "occurred_at",
        "observed_at",
    )

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.data_dir = Path(str(settings.DATA_DIR))
        self.retention_days = int(getattr(settings, "DATA_RETENTION_DAYS", 30))
        if self.retention_days < 1:
            raise ValueError("DATA_RETENTION_DAYS must be at least one day")

    @property
    def _window_seconds(self) -> float:
        return float(self.retention_days * 86400)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(str(path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _oldest_text_age(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        timestamp_expression: str,
        now: datetime,
        restriction: str | None = None,
    ) -> float | None:
        where = restriction or "1 = 1"
        row = connection.execute(
            f"""
            SELECT (julianday(?) - MIN(julianday({timestamp_expression}))) * 86400
            FROM {table}
            WHERE ({where}) AND julianday({timestamp_expression}) IS NOT NULL
            """,
            (now.isoformat(),),
        ).fetchone()
        age = (
            max(0.0, float(row[0])) if row is not None and row[0] is not None else None
        )
        unknown = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE ({where}) AND julianday({timestamp_expression}) IS NULL"
            ).fetchone()[0]
        )
        if unknown:
            return max(age or 0.0, self._window_seconds + 1.0)
        return age

    def _cleanup_text_table(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        timestamp_expression: str,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
        retention_days: int | None = None,
        restriction: str | None = None,
        extra_or: str | None = None,
        extra_params: tuple[Any, ...] = (),
    ) -> RetentionStoreResult:
        window_days = retention_days or self.retention_days
        window_seconds = float(window_days * 86400)
        if not self._table_exists(connection, table):
            return RetentionStoreResult(0, None, window_seconds)

        effective_cutoff = now - timedelta(days=window_days)
        timestamp_sql = f"julianday({timestamp_expression}) < julianday(?)"
        if restriction:
            timestamp_sql = f"(({restriction}) AND {timestamp_sql})"
        condition = timestamp_sql
        params: tuple[Any, ...] = (effective_cutoff.isoformat(),)
        if extra_or:
            condition = f"({condition}) OR ({extra_or})"
            params += extra_params

        count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {condition}", params
            ).fetchone()[0]
        )
        if count and not dry_run:
            connection.execute(f"DELETE FROM {table} WHERE {condition}", params)

        oldest = self._oldest_text_age(
            connection,
            table=table,
            timestamp_expression=timestamp_expression,
            now=now,
            restriction=restriction,
        )
        return RetentionStoreResult(count, oldest, window_seconds)

    @staticmethod
    def _vacuum(
        connection: sqlite3.Connection,
        *,
        path: Path,
        changed: int,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> None:
        marker = path.with_name(f".{path.name}.retention-vacuum-pending")
        if not dry_run and changed:
            if marker.is_symlink() or (marker.exists() and not marker.is_file()):
                raise ValueError("Invalid retention compaction marker")
            descriptor = os.open(
                marker,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(descriptor)
        connection.commit()
        if not dry_run and marker.is_file():
            checkpoint = connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            if checkpoint is not None and int(checkpoint[0]) != 0:
                raise sqlite3.OperationalError("SQLite WAL checkpoint remained busy")
            connection.execute("VACUUM")
            report.vacuumed_databases.append(path.name)
            marker.unlink()

    def _cleanup_feedback_parents(
        self,
        connection: sqlite3.Connection,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if not self._table_exists(connection, "feedback"):
            return RetentionStoreResult(0, None, self._window_seconds)

        rows = connection.execute(
            """
            SELECT id FROM feedback
            WHERE message_id NOT LIKE 'retained:%'
              AND julianday(COALESCE(timestamp, created_at)) < julianday(?)
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        old_ids = {int(row[0]) for row in rows}
        retained_child_parents: set[int] = set()
        if old_ids:
            placeholders = ",".join("?" for _ in old_ids)
            child_tables = {
                "conversation_messages": "created_at",
                "feedback_metadata": "created_at",
                "feedback_issues": "created_at",
                "feedback_reactions": (
                    "COALESCE(revoked_at, last_updated_at, created_at)"
                ),
            }
            for child_table, timestamp_expression in child_tables.items():
                if not self._table_exists(connection, child_table):
                    continue
                retained_condition = ""
                params: tuple[Any, ...] = tuple(sorted(old_ids))
                if dry_run:
                    retained_condition = (
                        f" AND julianday({timestamp_expression}) >= julianday(?)"
                    )
                    params += (cutoff.isoformat(),)
                child_rows = connection.execute(
                    f"SELECT DISTINCT feedback_id FROM {child_table} "
                    f"WHERE feedback_id IN ({placeholders}){retained_condition}",
                    params,
                ).fetchall()
                retained_child_parents.update(int(row[0]) for row in child_rows)

        anonymized_ids = old_ids & retained_child_parents
        deleted_ids = old_ids - retained_child_parents
        if not dry_run:
            if anonymized_ids:
                columns = self._table_columns(connection, "feedback")
                replacements: dict[str, str] = {
                    "message_id": "'retained:' || id",
                    "question": "''",
                    "answer": "''",
                    "explanation": "NULL",
                    "sources": "NULL",
                    "sources_used": "NULL",
                    "channel": "'retained'",
                    "feedback_method": "'retained'",
                    "external_message_id": "NULL",
                    "reactor_identity_hash": "NULL",
                    "reaction_emoji": "NULL",
                }
                assignments = ", ".join(
                    f"{column} = {value}"
                    for column, value in replacements.items()
                    if column in columns
                )
                placeholders = ",".join("?" for _ in anonymized_ids)
                connection.execute(
                    f"UPDATE feedback SET {assignments} "
                    f"WHERE id IN ({placeholders})",
                    tuple(sorted(anonymized_ids)),
                )
            if deleted_ids:
                placeholders = ",".join("?" for _ in deleted_ids)
                connection.execute(
                    f"DELETE FROM feedback WHERE id IN ({placeholders})",
                    tuple(sorted(deleted_ids)),
                )

        oldest = self._oldest_text_age(
            connection,
            table="feedback",
            timestamp_expression="COALESCE(timestamp, created_at)",
            now=now,
            restriction="message_id NOT LIKE 'retained:%'",
        )
        return RetentionStoreResult(
            len(deleted_ids),
            oldest,
            (now - cutoff).total_seconds(),
            anonymized_rows=len(anonymized_ids),
        )

    def _cleanup_trust_findings(
        self,
        connection: sqlite3.Connection,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if not self._table_exists(connection, "trust_findings"):
            return RetentionStoreResult(0, None, self._window_seconds)

        rows = connection.execute(
            """
            SELECT id FROM trust_findings
            WHERE suspect_actor_key NOT LIKE 'retained:%'
              AND julianday(updated_at) < julianday(?)
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        old_ids = {int(row[0]) for row in rows}
        retained_feedback_parents: set[int] = set()
        if old_ids and self._table_exists(connection, "trust_finding_feedback"):
            placeholders = ",".join("?" for _ in old_ids)
            retained_condition = ""
            params: tuple[Any, ...] = tuple(sorted(old_ids))
            if dry_run:
                retained_condition = " AND julianday(created_at) >= julianday(?)"
                params += (cutoff.isoformat(),)
            feedback_rows = connection.execute(
                "SELECT DISTINCT finding_id FROM trust_finding_feedback "
                f"WHERE finding_id IN ({placeholders}){retained_condition}",
                params,
            ).fetchall()
            retained_feedback_parents = {int(row[0]) for row in feedback_rows}

        anonymized_ids = old_ids & retained_feedback_parents
        deleted_ids = old_ids - retained_feedback_parents
        if not dry_run:
            if anonymized_ids:
                placeholders = ",".join("?" for _ in anonymized_ids)
                connection.execute(
                    f"""
                    UPDATE trust_findings
                    SET suspect_actor_key = 'retained:' || id,
                        suspect_actor_id = '',
                        suspect_display_name = '',
                        channel_id = '',
                        space_id = '',
                        evidence_summary_json = '{{}}'
                    WHERE id IN ({placeholders})
                    """,
                    tuple(sorted(anonymized_ids)),
                )
            if deleted_ids:
                placeholders = ",".join("?" for _ in deleted_ids)
                connection.execute(
                    f"DELETE FROM trust_findings WHERE id IN ({placeholders})",
                    tuple(sorted(deleted_ids)),
                )

        oldest = self._oldest_text_age(
            connection,
            table="trust_findings",
            timestamp_expression="updated_at",
            now=now,
            restriction="suspect_actor_key NOT LIKE 'retained:%'",
        )
        return RetentionStoreResult(
            len(deleted_ids),
            oldest,
            (now - cutoff).total_seconds(),
            anonymized_rows=len(anonymized_ids),
        )

    def _cleanup_feedback_database(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> None:
        path = self.data_dir / "feedback.db"
        if not path.exists():
            for name in (
                "feedback",
                "feedback_conversations",
                "feedback_metadata",
                "feedback_issues",
                "feedback_reactions",
                "chatops_audit",
                "trust_profiles",
                "trust_evidence",
                "trust_aggregates",
                "trust_findings",
                "trust_finding_feedback",
                "trust_access_audit",
            ):
                report.stores[name] = RetentionStoreResult(
                    0, None, self._window_seconds
                )
            return

        connection = self._connect(path)
        try:
            plans = (
                (
                    "feedback_conversations",
                    "conversation_messages",
                    "created_at",
                    None,
                ),
                (
                    "feedback_metadata",
                    "feedback_metadata",
                    "created_at",
                    None,
                ),
                (
                    "feedback_issues",
                    "feedback_issues",
                    "created_at",
                    None,
                ),
                (
                    "feedback_reactions",
                    "feedback_reactions",
                    "COALESCE(revoked_at, last_updated_at, created_at)",
                    None,
                ),
                ("chatops_audit", "chatops_action_audit", "created_at", None),
            )
            changed = 0
            for label, table, timestamp_expression, orphan_condition in plans:
                result = self._cleanup_text_table(
                    connection,
                    table=table,
                    timestamp_expression=timestamp_expression,
                    cutoff=cutoff,
                    now=now,
                    dry_run=dry_run,
                    extra_or=orphan_condition,
                )
                report.stores[label] = result
                changed += result.deleted_rows

            feedback_result = self._cleanup_feedback_parents(
                connection,
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["feedback"] = feedback_result
            changed += feedback_result.deleted_rows + feedback_result.anonymized_rows

            trust_plans = (
                (
                    "trust_finding_feedback",
                    "trust_finding_feedback",
                    "created_at",
                    min(
                        self.retention_days,
                        int(
                            getattr(self.settings, "TRUST_MONITOR_FINDING_TTL_DAYS", 30)
                        ),
                    ),
                    None,
                ),
                (
                    "trust_evidence",
                    "trust_evidence_events",
                    "occurred_at",
                    min(
                        self.retention_days,
                        int(
                            getattr(self.settings, "TRUST_MONITOR_EVIDENCE_TTL_DAYS", 7)
                        ),
                    ),
                    None,
                ),
                (
                    "trust_aggregates",
                    "trust_actor_aggregates",
                    "observed_at",
                    min(
                        self.retention_days,
                        int(
                            getattr(
                                self.settings, "TRUST_MONITOR_AGGREGATE_TTL_DAYS", 30
                            )
                        ),
                    ),
                    None,
                ),
                (
                    "trust_access_audit",
                    "trust_access_audit",
                    "created_at",
                    self.retention_days,
                    None,
                ),
                (
                    "trust_profiles",
                    "trust_actor_profiles",
                    "last_seen_at",
                    self.retention_days,
                    None,
                ),
            )
            for (
                label,
                table,
                timestamp_expression,
                days,
                orphan_condition,
            ) in trust_plans:
                result = self._cleanup_text_table(
                    connection,
                    table=table,
                    timestamp_expression=timestamp_expression,
                    cutoff=cutoff,
                    now=now,
                    dry_run=dry_run,
                    retention_days=days,
                    extra_or=orphan_condition,
                )
                report.stores[label] = result
                changed += result.deleted_rows

            trust_finding_result = self._cleanup_trust_findings(
                connection,
                cutoff=now
                - timedelta(
                    days=min(
                        self.retention_days,
                        int(
                            getattr(self.settings, "TRUST_MONITOR_FINDING_TTL_DAYS", 30)
                        ),
                    )
                ),
                now=now,
                dry_run=dry_run,
            )
            report.stores["trust_findings"] = trust_finding_result
            changed += (
                trust_finding_result.deleted_rows + trust_finding_result.anonymized_rows
            )

            self._vacuum(
                connection,
                path=path,
                changed=changed,
                dry_run=dry_run,
                report=report,
            )
        finally:
            connection.close()

    def _cleanup_escalation_database(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> None:
        path = self.data_dir / "escalations.db"
        if not path.exists():
            report.stores["escalations"] = RetentionStoreResult(
                0, None, self._window_seconds
            )
            report.stores["escalation_rating_tokens"] = RetentionStoreResult(
                0, None, self._window_seconds
            )
            return

        connection = self._connect(path)
        try:
            token_result = self._cleanup_text_table(
                connection,
                table="escalation_rating_consumed_tokens",
                timestamp_expression="consumed_at",
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            escalation_result = self._cleanup_text_table(
                connection,
                table="escalations",
                timestamp_expression="created_at",
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["escalation_rating_tokens"] = token_result
            report.stores["escalations"] = escalation_result
            self._vacuum(
                connection,
                path=path,
                changed=token_result.deleted_rows + escalation_result.deleted_rows,
                dry_run=dry_run,
                report=report,
            )
        finally:
            connection.close()

    def _cleanup_training_threads(
        self,
        connection: sqlite3.Connection,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if not self._table_exists(connection, "conversation_threads"):
            return RetentionStoreResult(0, None, self._window_seconds)

        old_condition = """
            thread_key NOT LIKE 'retained:%'
            AND julianday(COALESCE(updated_at, created_at)) < julianday(?)
        """
        old_rows = connection.execute(
            f"SELECT id FROM conversation_threads WHERE {old_condition}",
            (cutoff.isoformat(),),
        ).fetchall()
        old_ids = {int(row[0]) for row in old_rows}
        retained_child_threads: set[int] = set()
        child_tables = {
            "thread_messages": "timestamp",
            "conversation_state_transitions": "created_at",
        }
        for table, timestamp_expression in child_tables.items():
            if not old_ids or not self._table_exists(connection, table):
                continue
            placeholders = ",".join("?" for _ in old_ids)
            retained_condition = ""
            params: tuple[Any, ...] = tuple(sorted(old_ids))
            if dry_run:
                retained_condition = (
                    f" AND julianday({timestamp_expression}) >= julianday(?)"
                )
                params += (cutoff.isoformat(),)
            rows = connection.execute(
                f"SELECT DISTINCT thread_id FROM {table} "
                f"WHERE thread_id IN ({placeholders}){retained_condition}",
                params,
            ).fetchall()
            retained_child_threads.update(int(row[0]) for row in rows)

        anonymized_ids = old_ids & retained_child_threads
        deleted_ids = old_ids - retained_child_threads
        if not dry_run:
            if anonymized_ids:
                placeholders = ",".join("?" for _ in anonymized_ids)
                connection.execute(
                    f"""
                    UPDATE conversation_threads
                    SET thread_key = 'retained:' || id,
                        room_id = NULL,
                        first_question_id = 'retained:' || id,
                        correction_reason = NULL
                    WHERE id IN ({placeholders})
                    """,
                    tuple(sorted(anonymized_ids)),
                )
            if deleted_ids:
                placeholders = ",".join("?" for _ in deleted_ids)
                connection.execute(
                    f"DELETE FROM conversation_threads WHERE id IN ({placeholders})",
                    tuple(sorted(deleted_ids)),
                )

        oldest = self._oldest_text_age(
            connection,
            table="conversation_threads",
            timestamp_expression="COALESCE(updated_at, created_at)",
            now=now,
            restriction="thread_key NOT LIKE 'retained:%'",
        )
        if not dry_run and not old_ids:
            oldest = self._oldest_text_age(
                connection,
                table="conversation_threads",
                timestamp_expression="COALESCE(updated_at, created_at)",
                now=now,
                restriction="thread_key NOT LIKE 'retained:%'",
            )
        return RetentionStoreResult(
            len(deleted_ids),
            oldest,
            self._window_seconds,
            anonymized_rows=len(anonymized_ids),
        )

    def _cleanup_training_candidates(
        self,
        connection: sqlite3.Connection,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        table = "unified_faq_candidates"
        if not self._table_exists(connection, table):
            return RetentionStoreResult(0, None, self._window_seconds)

        rows = connection.execute(
            """
            SELECT id FROM unified_faq_candidates
            WHERE source IN ('bisq2', 'matrix')
              AND source_event_id NOT LIKE 'retained:%'
              AND julianday(source_timestamp) < julianday(?)
            """,
            (cutoff.isoformat(),),
        ).fetchall()
        old_ids = {int(row[0]) for row in rows}
        referenced_ids: set[int] = set()
        if old_ids:
            placeholders = ",".join("?" for _ in old_ids)
            for reference_table in (
                "conversation_threads",
                "knowledge_update_proposals",
            ):
                if not self._table_exists(connection, reference_table):
                    continue
                reference_rows = connection.execute(
                    f"SELECT DISTINCT candidate_id FROM {reference_table} "
                    f"WHERE candidate_id IN ({placeholders})",
                    tuple(sorted(old_ids)),
                ).fetchall()
                referenced_ids.update(
                    int(row[0]) for row in reference_rows if row[0] is not None
                )

        anonymized_ids = old_ids & referenced_ids
        deleted_ids = old_ids - referenced_ids
        if not dry_run:
            if anonymized_ids:
                placeholders = ",".join("?" for _ in anonymized_ids)
                connection.execute(
                    f"""
                    UPDATE unified_faq_candidates
                    SET source_event_id = 'retained:' || id,
                        question_text = '',
                        staff_answer = '',
                        generated_answer = NULL,
                        staff_sender = NULL,
                        llm_reasoning = NULL,
                        reviewed_by = NULL,
                        rejection_reason = NULL,
                        rejection_note = NULL,
                        edited_staff_answer = NULL,
                        edited_question_text = NULL,
                        generated_answer_sources = NULL,
                        original_user_question = NULL,
                        original_staff_answer = NULL
                    WHERE id IN ({placeholders})
                    """,
                    tuple(sorted(anonymized_ids)),
                )
            if deleted_ids:
                placeholders = ",".join("?" for _ in deleted_ids)
                connection.execute(
                    f"DELETE FROM unified_faq_candidates WHERE id IN ({placeholders})",
                    tuple(sorted(deleted_ids)),
                )

        oldest = self._oldest_text_age(
            connection,
            table=table,
            timestamp_expression="source_timestamp",
            now=now,
            restriction=(
                "source IN ('bisq2', 'matrix') "
                "AND source_event_id NOT LIKE 'retained:%'"
            ),
        )
        return RetentionStoreResult(
            len(deleted_ids),
            oldest,
            self._window_seconds,
            anonymized_rows=len(anonymized_ids),
        )

    def _cleanup_training_database(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> None:
        path = self.data_dir / "unified_training.db"
        labels = (
            "training_candidates",
            "training_threads",
            "training_thread_messages",
            "training_thread_transitions",
            "knowledge_update_proposals",
            "knowledge_review_feedback",
            "training_learning_history",
        )
        if not path.exists():
            for label in labels:
                report.stores[label] = RetentionStoreResult(
                    0, None, self._window_seconds
                )
            return

        connection = self._connect(path)
        try:
            changed = 0
            proposal_result = self._cleanup_text_table(
                connection,
                table="knowledge_update_proposals",
                timestamp_expression="created_at",
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["knowledge_update_proposals"] = proposal_result
            changed += proposal_result.deleted_rows

            review_result = self._cleanup_text_table(
                connection,
                table="llm_wiki_review_feedback",
                timestamp_expression="COALESCE(reviewed_at, created_at)",
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["knowledge_review_feedback"] = review_result
            changed += review_result.deleted_rows

            message_result = self._cleanup_text_table(
                connection,
                table="thread_messages",
                timestamp_expression="timestamp",
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["training_thread_messages"] = message_result
            changed += message_result.deleted_rows

            transition_result = self._cleanup_text_table(
                connection,
                table="conversation_state_transitions",
                timestamp_expression="created_at",
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["training_thread_transitions"] = transition_result
            changed += transition_result.deleted_rows

            thread_result = self._cleanup_training_threads(
                connection,
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["training_threads"] = thread_result
            changed += thread_result.deleted_rows + thread_result.anonymized_rows

            candidate_result = self._cleanup_training_candidates(
                connection,
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            report.stores["training_candidates"] = candidate_result
            changed += candidate_result.deleted_rows + candidate_result.anonymized_rows

            history_count = 0
            history_age: float | None = None
            if self._table_exists(connection, "learning_state"):
                row = connection.execute(
                    "SELECT review_history FROM learning_state WHERE id = 1"
                ).fetchone()
                raw_history = row[0] if row is not None else "[]"
                has_unknown_timestamp = False
                history_is_rewritable = True
                try:
                    parsed_history = json.loads(raw_history or "[]")
                except (json.JSONDecodeError, TypeError):
                    parsed_history = []
                    has_unknown_timestamp = bool(raw_history)
                    history_is_rewritable = False
                if not isinstance(parsed_history, list):
                    parsed_history = []
                    has_unknown_timestamp = True
                    history_is_rewritable = False

                retained_history: list[Any] = []
                retained_timestamps: list[datetime] = []
                for review in parsed_history:
                    if not isinstance(review, dict):
                        has_unknown_timestamp = True
                        retained_history.append(review)
                        continue
                    timestamp = _parse_timestamp(review.get("timestamp"))
                    if timestamp is None:
                        has_unknown_timestamp = True
                        retained_history.append(review)
                        continue
                    if timestamp < cutoff:
                        history_count += 1
                        continue
                    retained_history.append(review)
                    retained_timestamps.append(timestamp)

                if retained_timestamps:
                    history_age = max(
                        0.0,
                        now.timestamp() - min(retained_timestamps).timestamp(),
                    )
                if has_unknown_timestamp:
                    history_age = max(
                        history_age or 0.0,
                        self._window_seconds + 1.0,
                    )
                if history_count and history_is_rewritable and not dry_run:
                    connection.execute(
                        "UPDATE learning_state SET review_history = ? WHERE id = 1",
                        (json.dumps(retained_history, sort_keys=True),),
                    )
            report.stores["training_learning_history"] = RetentionStoreResult(
                history_count,
                history_age,
                self._window_seconds,
            )
            changed += history_count

            self._vacuum(
                connection,
                path=path,
                changed=changed,
                dry_run=dry_run,
                report=report,
            )
        finally:
            connection.close()

    def _cleanup_translation_database(
        self,
        *,
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> None:
        path = self.data_dir / "translation_cache.db"
        if not path.exists():
            report.stores["translation_cache"] = RetentionStoreResult(
                0, None, self._window_seconds
            )
            return
        connection = self._connect(path)
        try:
            if not self._table_exists(connection, "translations"):
                report.stores["translation_cache"] = RetentionStoreResult(
                    0, None, self._window_seconds
                )
                return
            cutoff_epoch = int((now - timedelta(days=self.retention_days)).timestamp())
            now_epoch = int(now.timestamp())
            condition = "created_at < ? OR expires_at <= ?"
            count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM translations WHERE {condition}",
                    (cutoff_epoch, now_epoch),
                ).fetchone()[0]
            )
            if count and not dry_run:
                connection.execute(
                    f"DELETE FROM translations WHERE {condition}",
                    (cutoff_epoch, now_epoch),
                )
            oldest_row = connection.execute(
                "SELECT MIN(created_at) FROM translations"
            ).fetchone()
            oldest = (
                max(0.0, now.timestamp() - float(oldest_row[0]))
                if oldest_row and oldest_row[0] is not None
                else None
            )
            report.stores["translation_cache"] = RetentionStoreResult(
                count, oldest, self._window_seconds
            )
            self._vacuum(
                connection,
                path=path,
                changed=count,
                dry_run=dry_run,
                report=report,
            )
        finally:
            connection.close()

    def _expire_paths(
        self,
        *,
        label: str,
        paths: Iterable[Path],
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> None:
        deleted = 0
        retained_ages: list[float] = []
        for path in paths:
            mtime = _latest_mtime(path)
            if mtime is None:
                continue
            age = max(0.0, now.timestamp() - mtime)
            if age < self._window_seconds:
                retained_ages.append(age)
                continue
            if dry_run:
                deleted += max(
                    1,
                    (
                        sum(1 for item in path.rglob("*") if not item.is_dir())
                        if path.is_dir() and not path.is_symlink()
                        else 1
                    ),
                )
            else:
                deleted += _remove_path(path)
        report.stores[label] = RetentionStoreResult(
            deleted,
            max(retained_ages, default=None),
            self._window_seconds,
        )

    @staticmethod
    def _atomic_replace_text(path: Path, content: str) -> None:
        mode = path.stat().st_mode & 0o777
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
                newline="",
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, mode or 0o600)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _retained_record_age(
        *, records: Iterable[dict[str, Any]], now: datetime
    ) -> float | None:
        timestamps = [
            timestamp
            for timestamp in (_record_timestamp(record) for record in records)
            if timestamp is not None
        ]
        if not timestamps:
            return None
        return max(0.0, now.timestamp() - min(timestamps).timestamp())

    def _retained_file_age(
        self,
        *,
        records: Iterable[dict[str, Any]],
        path: Path,
        has_unknown_timestamp: bool,
        now: datetime,
    ) -> float | None:
        ages = [self._retained_record_age(records=records, now=now)]
        if has_unknown_timestamp:
            ages.append(self._window_seconds + 1.0)
        return max((age for age in ages if age is not None), default=None)

    def _cleanup_jsonl_file(
        self,
        *,
        path: Path,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if not path.is_file() or path.is_symlink():
            return RetentionStoreResult(0, None, self._window_seconds)
        retained_lines: list[str] = []
        retained_records: list[dict[str, Any]] = []
        deleted = 0
        has_unknown_timestamp = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                retained_lines.append(line)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                has_unknown_timestamp = True
                retained_lines.append(line)
                continue
            if not isinstance(record, dict):
                has_unknown_timestamp = True
                retained_lines.append(line)
                continue
            timestamp = _record_timestamp(record)
            if timestamp is None:
                has_unknown_timestamp = True
                retained_records.append(record)
                retained_lines.append(line)
                continue
            if timestamp < cutoff:
                deleted += 1
                continue
            retained_records.append(record)
            retained_lines.append(line)
        if deleted and not dry_run:
            content = "\n".join(retained_lines)
            self._atomic_replace_text(path, f"{content}\n" if content else "")
        return RetentionStoreResult(
            deleted,
            self._retained_file_age(
                records=retained_records,
                path=path,
                has_unknown_timestamp=has_unknown_timestamp,
                now=now,
            ),
            self._window_seconds,
        )

    def _cleanup_csv_file(
        self,
        *,
        path: Path,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if not path.is_file() or path.is_symlink():
            return RetentionStoreResult(0, None, self._window_seconds)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            records = [dict(row) for row in reader]
        retained: list[dict[str, Any]] = []
        has_unknown_timestamp = False
        for record in records:
            timestamp = _record_timestamp(record)
            if timestamp is None:
                has_unknown_timestamp = True
                retained.append(record)
            elif timestamp >= cutoff:
                retained.append(record)
        deleted = len(records) - len(retained)
        if deleted and not dry_run:
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=fieldnames)
                if fieldnames:
                    writer.writeheader()
                    writer.writerows(retained)
                out.seek(0)
                self._atomic_replace_text(path, out.read())
        return RetentionStoreResult(
            deleted,
            self._retained_file_age(
                records=retained,
                path=path,
                has_unknown_timestamp=has_unknown_timestamp,
                now=now,
            ),
            self._window_seconds,
        )

    def _cleanup_json_file(
        self,
        *,
        path: Path,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if not path.is_file() or path.is_symlink():
            return RetentionStoreResult(0, None, self._window_seconds)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError):
            return RetentionStoreResult(
                0,
                self._window_seconds + 1.0,
                self._window_seconds,
            )

        container: list[Any] | None = payload if isinstance(payload, list) else None
        container_key: str | None = None
        if isinstance(payload, dict):
            for key in ("records", "messages", "conversations", "processed_ids"):
                if isinstance(payload.get(key), list):
                    container = payload[key]
                    container_key = key
                    break
        if container is None:
            container = [payload]

        retained: list[Any] = []
        retained_records: list[dict[str, Any]] = []
        deleted = 0
        has_unknown_timestamp = False
        for item in container:
            if not isinstance(item, dict):
                has_unknown_timestamp = True
                retained.append(item)
                continue
            timestamp = _record_timestamp(item)
            if timestamp is None:
                has_unknown_timestamp = True
                retained.append(item)
                retained_records.append(item)
                continue
            if timestamp < cutoff:
                deleted += 1
                continue
            retained.append(item)
            retained_records.append(item)

        if deleted and not dry_run:
            if container_key is not None and isinstance(payload, dict):
                payload[container_key] = retained
                rewritten: Any = payload
            elif isinstance(payload, list):
                rewritten = retained
            else:
                rewritten = retained[0] if retained else {}
            self._atomic_replace_text(
                path,
                f"{json.dumps(rewritten, indent=2, sort_keys=True)}\n",
            )
        return RetentionStoreResult(
            deleted,
            self._retained_file_age(
                records=retained_records,
                path=path,
                has_unknown_timestamp=has_unknown_timestamp,
                now=now,
            ),
            self._window_seconds,
        )

    def _cleanup_structured_file(
        self,
        *,
        path: Path,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        if path.suffix == ".jsonl":
            return self._cleanup_jsonl_file(
                path=path, cutoff=cutoff, now=now, dry_run=dry_run
            )
        if path.suffix == ".csv":
            return self._cleanup_csv_file(
                path=path, cutoff=cutoff, now=now, dry_run=dry_run
            )
        return self._cleanup_json_file(
            path=path, cutoff=cutoff, now=now, dry_run=dry_run
        )

    def _cleanup_reviewed_knowledge_pages(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
    ) -> RetentionStoreResult:
        configured_path = str(
            getattr(
                self.settings,
                "LLM_WIKI_DIR_PATH",
                self.data_dir / "knowledge" / "llm_wiki" / "pages",
            )
        )
        configured_dir = Path(configured_path)
        if configured_dir.is_symlink():
            raise ValueError("Knowledge page directory must not be a symlink")
        pages_dir = configured_dir.resolve(strict=False)
        try:
            pages_dir.relative_to(self.data_dir.resolve())
        except ValueError as error:
            raise ValueError(
                "Knowledge page directory must be inside DATA_DIR"
            ) from error
        if not pages_dir.is_dir():
            return RetentionStoreResult(0, None, self._window_seconds)

        anonymized = 0
        retained_timestamps: list[datetime] = []
        for page in pages_dir.glob("*.md"):
            if not page.is_file() or page.is_symlink():
                continue
            lines = page.read_text(encoding="utf-8").splitlines()
            reviewer_index: int | None = None
            reviewer = ""
            reviewed_at: datetime | None = None
            for index, line in enumerate(lines):
                if line.startswith("reviewed_by:"):
                    reviewer_index = index
                    reviewer = line.split(":", maxsplit=1)[1].strip().strip("'\"")
                elif line.startswith("reviewed_at:"):
                    raw_date = line.split(":", maxsplit=1)[1].strip().strip("'\"")
                    reviewed_at = _parse_timestamp(raw_date)
                if index > 30:
                    break
            if not reviewer or reviewer == "support-admin":
                continue
            if reviewed_at is not None and reviewed_at >= cutoff:
                retained_timestamps.append(reviewed_at)
                continue
            anonymized += 1
            if not dry_run and reviewer_index is not None:
                lines[reviewer_index] = "reviewed_by: support-admin"
                self._atomic_replace_text(page, "\n".join(lines) + "\n")

        oldest = (
            max(0.0, now.timestamp() - min(retained_timestamps).timestamp())
            if retained_timestamps
            else None
        )
        return RetentionStoreResult(
            0,
            oldest,
            self._window_seconds,
            anonymized_rows=anonymized,
        )

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return f'"{identifier.replace(chr(34), chr(34) * 2)}"'

    def _cleanup_legacy_database(
        self,
        *,
        path: Path,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
    ) -> RetentionStoreResult:
        """Delete only provably expired rows from an obsolete SQLite schema."""
        if not path.is_file() or path.is_symlink():
            return RetentionStoreResult(0, None, self._window_seconds)

        connection = self._connect(path)
        deleted = 0
        retained_timestamps: list[datetime] = []
        has_unknown_timestamp = False
        try:
            tables = [
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                ).fetchall()
            ]
            for table in tables:
                columns = self._table_columns(connection, table)
                timestamp_columns = [
                    column
                    for column in self._LEGACY_TIMESTAMP_COLUMNS
                    if column in columns
                ]
                if not timestamp_columns:
                    has_unknown_timestamp = True
                    continue

                quoted_table = self._quote_identifier(table)
                projection = ", ".join(
                    self._quote_identifier(column) for column in timestamp_columns
                )
                try:
                    rows = connection.execute(
                        f'SELECT rowid AS "__retention_rowid", {projection} '
                        f"FROM {quoted_table}"
                    ).fetchall()
                except sqlite3.OperationalError:
                    has_unknown_timestamp = True
                    continue

                expired_rowids: list[int] = []
                for row in rows:
                    timestamp = next(
                        (
                            parsed
                            for column in timestamp_columns
                            if (parsed := _parse_timestamp(row[column])) is not None
                        ),
                        None,
                    )
                    if timestamp is None:
                        has_unknown_timestamp = True
                    elif timestamp < cutoff:
                        expired_rowids.append(int(row["__retention_rowid"]))
                    else:
                        retained_timestamps.append(timestamp)

                deleted += len(expired_rowids)
                if expired_rowids and not dry_run:
                    placeholders = ",".join("?" for _ in expired_rowids)
                    connection.execute(
                        f"DELETE FROM {quoted_table} WHERE rowid IN ({placeholders})",
                        tuple(expired_rowids),
                    )

            retained_ages = [
                max(0.0, now.timestamp() - timestamp.timestamp())
                for timestamp in retained_timestamps
            ]
            if has_unknown_timestamp:
                retained_ages.append(self._window_seconds + 1.0)
            self._vacuum(
                connection,
                path=path,
                changed=deleted,
                dry_run=dry_run,
                report=report,
            )
            return RetentionStoreResult(
                deleted,
                max(retained_ages, default=None),
                self._window_seconds,
            )
        finally:
            connection.close()

    def _cleanup_file_stores(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
        matrix_session_results: Mapping[Path, RetentionStoreResult],
    ) -> None:
        for filename in self._LEGACY_PERSONAL_FILES:
            report.stores[f"legacy_file_{Path(filename).stem}"] = (
                self._cleanup_structured_file(
                    path=self.data_dir / filename,
                    cutoff=cutoff,
                    now=now,
                    dry_run=dry_run,
                )
            )
        feedback_exports = list((self.data_dir / "feedback").glob("feedback_*.jsonl"))
        deleted = 0
        oldest: float | None = None
        for feedback_export in feedback_exports:
            result = self._cleanup_jsonl_file(
                path=feedback_export,
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
            deleted += result.deleted_rows
            if result.oldest_age_seconds is not None:
                oldest = (
                    result.oldest_age_seconds
                    if oldest is None
                    else max(oldest, result.oldest_age_seconds)
                )
        report.stores["legacy_feedback_exports"] = RetentionStoreResult(
            deleted,
            oldest,
            self._window_seconds,
        )
        report.stores["reviewed_knowledge_pages"] = (
            self._cleanup_reviewed_knowledge_pages(
                cutoff=cutoff,
                now=now,
                dry_run=dry_run,
            )
        )
        for filename in self._LEGACY_PERSONAL_DATABASES:
            path = self.data_dir / filename
            report.stores[f"legacy_database_{path.stem}"] = (
                self._cleanup_legacy_database(
                    path=path,
                    cutoff=cutoff,
                    now=now,
                    dry_run=dry_run,
                    report=report,
                )
            )
        self._expire_paths(
            label="deployment_data_backups",
            paths=(
                *self.data_dir.glob(".backup_*"),
                *self.data_dir.glob("restore_backup_*"),
            ),
            now=now,
            dry_run=dry_run,
            report=report,
        )
        session_paths: set[Path] = set()
        data_root = self.data_dir.resolve()
        for setting_name in (
            "MATRIX_SYNC_SESSION_PATH",
            "MATRIX_ALERT_SESSION_FILE_PATH",
        ):
            raw_path = str(getattr(self.settings, setting_name, "") or "").strip()
            if not raw_path:
                continue
            session_path = Path(raw_path)
            resolved = session_path.resolve(strict=False)
            if resolved.parent != data_root:
                raise ValueError("Matrix session path must be inside DATA_DIR")
            session_paths.add(resolved)

        active_stores = {path.parent / f"{path.stem}_store" for path in session_paths}
        self._expire_paths(
            label="orphan_matrix_stores",
            paths=(
                path
                for path in self.data_dir.glob("matrix*_store*")
                if path.resolve(strict=False) not in active_stores
            ),
            now=now,
            dry_run=dry_run,
            report=report,
        )

        for index, session_path in enumerate(sorted(session_paths, key=str)):
            result = matrix_session_results.get(session_path)
            if result is None:
                result = prune_matrix_session_artifacts(
                    session_file=session_path,
                    retention_days=self.retention_days,
                    now=now,
                    dry_run=dry_run,
                )
            report.stores[f"matrix_session_{index + 1}"] = result

    def _cleanup_processed_states(
        self,
        *,
        cutoff: datetime,
        dry_run: bool,
        report: PrivacyRetentionReport,
        state_managers: Mapping[Path, Any],
    ) -> None:
        from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
        from app.channels.plugins.matrix.client.polling_state import PollingStateManager

        matrix_path = (self.data_dir / "matrix_polling_state.json").resolve()
        matrix_manager = state_managers.get(matrix_path)
        if matrix_manager is None:
            matrix_manager = PollingStateManager(
                state_file=str(matrix_path),
                retention_days=self.retention_days,
            )
        matrix_deleted = matrix_manager.prune_before(cutoff, dry_run=dry_run)
        matrix_oldest = matrix_manager.oldest_processed_at()
        report.stores["matrix_processed_ids"] = RetentionStoreResult(
            matrix_deleted,
            (
                max(0.0, report.completed_at.timestamp() - matrix_oldest.timestamp())
                if matrix_oldest is not None
                else None
            ),
            self._window_seconds,
        )

        for label, filename in (
            ("bisq_training_processed_ids", "bisq_sync_state.json"),
            ("bisq_live_processed_ids", "bisq_live_channel_sync_state.json"),
        ):
            state_path = (self.data_dir / filename).resolve()
            manager = state_managers.get(state_path)
            if manager is None:
                manager = BisqSyncStateManager(
                    state_file=str(state_path),
                    retention_days=self.retention_days,
                )
            deleted = manager.prune_before(cutoff, dry_run=dry_run)
            oldest = manager.oldest_processed_at()
            report.stores[label] = RetentionStoreResult(
                deleted,
                (
                    max(0.0, report.completed_at.timestamp() - oldest.timestamp())
                    if oldest is not None
                    else None
                ),
                self._window_seconds,
            )

    @staticmethod
    def _run_store_group(
        *,
        report: PrivacyRetentionReport,
        name: str,
        operation: Callable[[], None],
    ) -> None:
        try:
            operation()
        except Exception:
            report.failed_store_groups.append(name)
            logger.exception("Privacy retention store group failed: %s", name)

    def run(
        self,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
        translation_cache: Any | None = None,
        feedback_service: Any | None = None,
        learning_engine: Any | None = None,
        processed_state_managers: Iterable[Any] = (),
        matrix_session_results: Mapping[Path, RetentionStoreResult] | None = None,
    ) -> PrivacyRetentionReport:
        """Run a complete retention pass, raising on any store failure."""
        completed_at = _utc(now or datetime.now(UTC))
        cutoff = completed_at - timedelta(days=self.retention_days)
        report = PrivacyRetentionReport(
            dry_run=dry_run,
            cutoff=cutoff,
            completed_at=completed_at,
        )
        state_managers = {
            Path(str(manager.state_file)).resolve(): manager
            for manager in processed_state_managers
            if getattr(manager, "state_file", None) is not None
        }
        normalized_session_results = {
            Path(path).resolve(): result
            for path, result in (matrix_session_results or {}).items()
        }
        self._run_store_group(
            report=report,
            name="feedback",
            operation=lambda: self._cleanup_feedback_database(
                cutoff=cutoff,
                now=completed_at,
                dry_run=dry_run,
                report=report,
            ),
        )
        self._run_store_group(
            report=report,
            name="escalations",
            operation=lambda: self._cleanup_escalation_database(
                cutoff=cutoff,
                now=completed_at,
                dry_run=dry_run,
                report=report,
            ),
        )
        self._run_store_group(
            report=report,
            name="training",
            operation=lambda: self._cleanup_training_database(
                cutoff=cutoff,
                now=completed_at,
                dry_run=dry_run,
                report=report,
            ),
        )
        self._run_store_group(
            report=report,
            name="translations",
            operation=lambda: self._cleanup_translation_database(
                now=completed_at,
                dry_run=dry_run,
                report=report,
            ),
        )
        self._run_store_group(
            report=report,
            name="processed_ids",
            operation=lambda: self._cleanup_processed_states(
                cutoff=cutoff,
                dry_run=dry_run,
                report=report,
                state_managers=state_managers,
            ),
        )
        self._run_store_group(
            report=report,
            name="file_artifacts",
            operation=lambda: self._cleanup_file_stores(
                cutoff=cutoff,
                now=completed_at,
                dry_run=dry_run,
                report=report,
                matrix_session_results=normalized_session_results,
            ),
        )

        if not dry_run and translation_cache is not None:
            l1_cache = getattr(translation_cache, "l1", None)
            clear = getattr(l1_cache, "clear", None)
            if callable(clear):
                clear()

        if learning_engine is not None:
            prune_history = getattr(
                learning_engine,
                "prune_review_history_before",
                None,
            )
            if callable(prune_history):
                in_memory_deleted = int(prune_history(cutoff, dry_run=dry_run))
                result = report.stores["training_learning_history"]
                if in_memory_deleted > result.deleted_rows:
                    report.stores["training_learning_history"] = RetentionStoreResult(
                        in_memory_deleted,
                        result.oldest_age_seconds,
                        result.window_seconds,
                    )

        if not dry_run and feedback_service is not None:
            invalidate = getattr(
                feedback_service,
                "invalidate_retention_caches",
                None,
            )
            if callable(invalidate):
                invalidate()

        if report.failed_store_groups:
            record_privacy_retention_failure()
            raise PrivacyRetentionError(report)

        if not dry_run:
            record_privacy_retention_run(
                stores=report.stores,
                run_at=completed_at.timestamp(),
            )
        return report
