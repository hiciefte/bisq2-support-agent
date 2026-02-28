"""Async SQLite repository for escalation records.

Uses aiosqlite for non-blocking database access in the async API.
Stores channel_metadata and sources as JSON text columns.
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Tuple

import aiosqlite
from app.models.escalation import (
    Escalation,
    EscalationCountsResponse,
    EscalationCreate,
    EscalationFilters,
    EscalationUpdate,
)

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT,
    channel_metadata TEXT,
    question_original TEXT,
    question TEXT NOT NULL,
    ai_draft_answer_original TEXT,
    ai_draft_answer TEXT NOT NULL,
    user_language TEXT,
    translation_applied INTEGER NOT NULL DEFAULT 0
        CHECK(translation_applied IN (0, 1)),
    confidence_score REAL NOT NULL,
    routing_action TEXT NOT NULL,
    routing_reason TEXT,
    sources TEXT,
    staff_answer TEXT,
    staff_id TEXT,
    edit_distance REAL
        CHECK(edit_distance IS NULL OR (edit_distance >= 0.0 AND edit_distance <= 1.0)),
    delivery_status TEXT NOT NULL DEFAULT 'not_required'
        CHECK(delivery_status IN ('not_required', 'pending', 'delivered', 'failed')),
    delivery_error TEXT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    last_delivery_at TEXT,
    generated_faq_id TEXT,
    staff_answer_rating INTEGER
        CHECK(staff_answer_rating IS NULL OR staff_answer_rating IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_review', 'responded', 'closed')),
    priority TEXT NOT NULL DEFAULT 'normal'
        CHECK(priority IN ('normal', 'high')),
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    responded_at TEXT,
    closed_at TEXT,
    CHECK(LENGTH(question) <= 4000),
    CHECK(LENGTH(question_original) <= 4000),
    CHECK(LENGTH(ai_draft_answer) <= 10000),
    CHECK(LENGTH(ai_draft_answer_original) <= 10000),
    CHECK(LENGTH(staff_answer) <= 10000)
);
"""

CREATE_INDICES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);",
    "CREATE INDEX IF NOT EXISTS idx_escalations_channel ON escalations(channel);",
    "CREATE INDEX IF NOT EXISTS idx_escalations_priority ON escalations(priority, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_escalations_message_id ON escalations(message_id);",
    "CREATE INDEX IF NOT EXISTS idx_escalations_responded_at ON escalations(responded_at);",
]

CREATE_RATING_TOKEN_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS escalation_rating_consumed_tokens (
    token_jti TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    consumed_at TEXT NOT NULL
);
"""


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-formatted datetime string."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_json(value: Optional[str]) -> Optional[Any]:
    """Parse a JSON text column."""
    if value is None:
        return None
    return json.loads(value)


def _row_to_escalation(row: aiosqlite.Row) -> Escalation:
    """Convert an aiosqlite Row to an Escalation model."""
    d = dict(row)
    d["channel_metadata"] = _parse_json(d.get("channel_metadata"))
    d["sources"] = _parse_json(d.get("sources"))
    d["created_at"] = _parse_datetime(d["created_at"])
    d["claimed_at"] = _parse_datetime(d.get("claimed_at"))
    d["responded_at"] = _parse_datetime(d.get("responded_at"))
    d["closed_at"] = _parse_datetime(d.get("closed_at"))
    d["last_delivery_at"] = _parse_datetime(d.get("last_delivery_at"))
    d["edit_distance"] = d.get("edit_distance")
    d["staff_answer_rating"] = d.get("staff_answer_rating")
    d["translation_applied"] = bool(d.get("translation_applied"))
    return Escalation(**d)


class EscalationRepository:
    """Async repository for escalation CRUD."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialized = False

    async def initialize(self) -> None:
        """Create the table and indices if not present."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(CREATE_TABLE_SQL)
            for idx_sql in CREATE_INDICES_SQL:
                await db.execute(idx_sql)
            await db.execute(CREATE_RATING_TOKEN_TABLE_SQL)
            # Self-migration: add staff_answer_rating for existing databases
            try:
                await db.execute(
                    "ALTER TABLE escalations ADD COLUMN staff_answer_rating INTEGER"
                    " CHECK(staff_answer_rating IS NULL OR staff_answer_rating IN (0, 1))"
                )
                logger.info("Added staff_answer_rating column to escalations table")
            except Exception:
                pass  # Column already exists
            # Self-migration: add edit_distance for existing databases
            try:
                await db.execute(
                    "ALTER TABLE escalations ADD COLUMN edit_distance REAL "
                    "CHECK(edit_distance IS NULL OR (edit_distance >= 0.0 AND edit_distance <= 1.0))"
                )
                logger.info("Added edit_distance column to escalations table")
            except Exception:
                pass  # Column already exists
            # Self-migration: add multilingual escalation context columns
            try:
                await db.execute(
                    "ALTER TABLE escalations ADD COLUMN question_original TEXT"
                )
                logger.info("Added question_original column to escalations table")
            except Exception:
                pass  # Column already exists
            try:
                await db.execute(
                    "ALTER TABLE escalations ADD COLUMN ai_draft_answer_original TEXT"
                )
                logger.info(
                    "Added ai_draft_answer_original column to escalations table"
                )
            except Exception:
                pass  # Column already exists
            try:
                await db.execute(
                    "ALTER TABLE escalations ADD COLUMN user_language TEXT"
                )
                logger.info("Added user_language column to escalations table")
            except Exception:
                pass  # Column already exists
            try:
                await db.execute(
                    "ALTER TABLE escalations ADD COLUMN translation_applied INTEGER NOT NULL DEFAULT 0 "
                    "CHECK(translation_applied IN (0, 1))"
                )
                logger.info("Added translation_applied column to escalations table")
            except Exception:
                pass  # Column already exists
            await db.commit()
        self._initialized = True
        logger.info("EscalationRepository initialized at %s", self.db_path)

    async def _connect(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        return db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(self, data: EscalationCreate) -> Escalation:
        """Insert a new escalation. Raises DuplicateEscalationError on duplicate message_id."""
        from app.models.escalation import DuplicateEscalationError

        now = datetime.now(timezone.utc).isoformat()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    INSERT INTO escalations (
                        message_id, channel, user_id, username,
                        channel_metadata, question_original, question,
                        ai_draft_answer_original, ai_draft_answer,
                        user_language, translation_applied,
                        confidence_score, routing_action, routing_reason,
                        sources, priority, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.message_id,
                        data.channel,
                        data.user_id,
                        data.username,
                        (
                            json.dumps(data.channel_metadata)
                            if data.channel_metadata
                            else None
                        ),
                        data.question_original,
                        data.question,
                        data.ai_draft_answer_original,
                        data.ai_draft_answer,
                        data.user_language,
                        int(bool(data.translation_applied)),
                        data.confidence_score,
                        data.routing_action,
                        data.routing_reason,
                        json.dumps(data.sources) if data.sources else None,
                        data.priority.value,
                        now,
                    ),
                )
                await db.commit()
                row_id = cursor.lastrowid

                cursor = await db.execute(
                    "SELECT * FROM escalations WHERE id = ?", (row_id,)
                )
                row = await cursor.fetchone()
                return _row_to_escalation(row)
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise DuplicateEscalationError(
                    f"Escalation with message_id={data.message_id} already exists"
                ) from e
            raise

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, escalation_id: int) -> Optional[Escalation]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM escalations WHERE id = ?", (escalation_id,)
            )
            row = await cursor.fetchone()
            return _row_to_escalation(row) if row else None

    async def get_by_message_id(self, message_id: str) -> Optional[Escalation]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM escalations WHERE message_id = ?", (message_id,)
            )
            row = await cursor.fetchone()
            return _row_to_escalation(row) if row else None

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update(self, escalation_id: int, patch: EscalationUpdate) -> Escalation:
        """Apply partial update. Raises EscalationNotFoundError if missing."""
        from app.models.escalation import EscalationNotFoundError

        fields: List[str] = []
        values: List[Any] = []

        for field_name, value in patch.model_dump(exclude_none=True).items():
            if isinstance(value, datetime):
                values.append(value.isoformat())
            elif isinstance(value, Enum):
                values.append(value.value)
            else:
                values.append(value)
            fields.append(f"{field_name} = ?")

        if not fields:
            existing = await self.get_by_id(escalation_id)
            if existing is None:
                raise EscalationNotFoundError(f"Escalation {escalation_id} not found")
            return existing

        values.append(escalation_id)
        sql = f"UPDATE escalations SET {', '.join(fields)} WHERE id = ?"

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, values)
            await db.commit()

            if cursor.rowcount == 0:
                raise EscalationNotFoundError(f"Escalation {escalation_id} not found")

            cursor = await db.execute(
                "SELECT * FROM escalations WHERE id = ?", (escalation_id,)
            )
            row = await cursor.fetchone()
            return _row_to_escalation(row)

    # ------------------------------------------------------------------
    # Rating
    # ------------------------------------------------------------------

    async def update_rating(self, message_id: str, rating: int) -> bool:
        """Atomic rating update. Returns False if escalation not found or has no staff_answer."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE escalations
                SET staff_answer_rating = ?
                WHERE message_id = ? AND staff_answer IS NOT NULL
                """,
                (rating, message_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def consume_rating_token_jti(self, message_id: str, token_jti: str) -> bool:
        """Mark token jti as consumed. Returns False when replayed."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO escalation_rating_consumed_tokens (
                        token_jti, message_id, consumed_at
                    ) VALUES (?, ?, ?)
                    """,
                    (token_jti, message_id, now),
                )
                await db.commit()
            return True
        except Exception:
            logger.warning(
                "Rejected replayed rating token jti for message %s", message_id
            )
            return False

    # ------------------------------------------------------------------
    # List / filter
    # ------------------------------------------------------------------

    async def list_escalations(
        self, filters: EscalationFilters
    ) -> Tuple[List[Escalation], int]:
        """Return filtered escalations and total count."""
        where_clauses: List[str] = []
        params: List[Any] = []

        if filters.status:
            where_clauses.append("status = ?")
            params.append(filters.status.value)
        if filters.channel:
            where_clauses.append("channel = ?")
            params.append(filters.channel)
        if filters.priority:
            where_clauses.append("priority = ?")
            params.append(filters.priority.value)
        if filters.staff_id:
            where_clauses.append("staff_id = ?")
            params.append(filters.staff_id)
        if filters.search:
            search_pattern = f"%{filters.search}%"
            where_clauses.append(
                "(question LIKE ? OR COALESCE(question_original, '') LIKE ? OR "
                "ai_draft_answer LIKE ? OR COALESCE(ai_draft_answer_original, '') LIKE ? OR "
                "COALESCE(staff_answer, '') LIKE ? OR COALESCE(routing_reason, '') LIKE ?)"
            )
            params.extend(
                [
                    search_pattern,
                    search_pattern,
                    search_pattern,
                    search_pattern,
                    search_pattern,
                    search_pattern,
                ]
            )

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Total count
            cursor = await db.execute(
                f"SELECT COUNT(*) as cnt FROM escalations WHERE {where_sql}",
                params,
            )
            row = await cursor.fetchone()
            total = row["cnt"]

            # Paginated results
            cursor = await db.execute(
                f"SELECT * FROM escalations WHERE {where_sql} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, filters.limit, filters.offset],
            )
            rows = await cursor.fetchall()
            return [_row_to_escalation(r) for r in rows], total

    async def get_counts(self) -> EscalationCountsResponse:
        """Return counts by status."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM escalations GROUP BY status"
            )
            rows = await cursor.fetchall()

        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        return EscalationCountsResponse(
            pending=counts.get("pending", 0),
            in_review=counts.get("in_review", 0),
            responded=counts.get("responded", 0),
            closed=counts.get("closed", 0),
            total=total,
        )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def close_stale(self, older_than: datetime) -> int:
        """Close pending escalations older than the given timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE escalations
                SET status = 'closed', closed_at = ?
                WHERE status = 'pending' AND created_at < ?
                """,
                (now, older_than.isoformat()),
            )
            await db.commit()
            return cursor.rowcount

    async def purge_old(self, older_than: datetime) -> int:
        """Delete resolved escalations older than retention threshold.

        Retention is measured from resolution timestamps:
        - closed escalations use `closed_at`
        - responded escalations use `responded_at`
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM escalations
                WHERE (status = 'closed' AND closed_at IS NOT NULL AND closed_at < ?)
                   OR (status = 'responded' AND responded_at IS NOT NULL AND responded_at < ?)
                """,
                (older_than.isoformat(), older_than.isoformat()),
            )
            await db.commit()
            return cursor.rowcount
