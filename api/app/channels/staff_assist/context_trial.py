"""Opt-in, durable admission limits for one Matrix staff-context trial."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from app.channels.plugins.matrix.room_filter import resolve_allowed_context_source_rooms


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ContextTrial:
    trial_id: str
    source_rooms: tuple[str, ...]
    staff_room: str
    start_at: datetime
    end_at: datetime
    max_cases: int

    @classmethod
    def from_settings(cls, settings: Any) -> ContextTrial | None:
        trial_id = str(getattr(settings, "MATRIX_CONTEXT_TRIAL_ID", "") or "").strip()
        start = str(getattr(settings, "MATRIX_CONTEXT_TRIAL_START_AT", "") or "")
        end = str(getattr(settings, "MATRIX_CONTEXT_TRIAL_END_AT", "") or "")
        if not trial_id:
            if start or end:
                raise ValueError("Matrix trial dates require MATRIX_CONTEXT_TRIAL_ID")
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", trial_id):
            raise ValueError(
                "MATRIX_CONTEXT_TRIAL_ID must be a short stable identifier"
            )
        try:
            start_at, end_at = datetime.fromisoformat(start), datetime.fromisoformat(
                end
            )
        except ValueError as exc:
            raise ValueError(
                "Matrix trial requires ISO start and end timestamps"
            ) from exc
        if start_at.utcoffset() is None or end_at.utcoffset() is None:
            raise ValueError("Matrix trial timestamps require an explicit timezone")
        start_at, end_at = start_at.astimezone(timezone.utc), end_at.astimezone(
            timezone.utc
        )
        if not timedelta(0) < end_at - start_at <= timedelta(hours=48):
            raise ValueError(
                "Matrix trial duration must be positive and at most 48 hours"
            )
        max_cases = int(getattr(settings, "MATRIX_CONTEXT_TRIAL_MAX_CASES", 10))
        if not 1 <= max_cases <= 10:
            raise ValueError("MATRIX_CONTEXT_TRIAL_MAX_CASES must be between 1 and 10")
        rooms = tuple(sorted(resolve_allowed_context_source_rooms(settings)))
        staff = str(getattr(settings, "MATRIX_STAFF_ROOM", "") or "").strip()
        if (
            not rooms
            or not staff.startswith("!")
            or ":" not in staff
            or any(char.isspace() for char in staff)
            or staff in rooms
        ):
            raise ValueError(
                "Matrix trial requires source rooms and a distinct staff room"
            )
        return cls(trial_id, rooms, staff, start_at, end_at, max_cases)

    def reason(self, now: datetime | None = None) -> str | None:
        current = now or utc_now()
        if current < self.start_at:
            return "context_trial_not_started"
        if current >= self.end_at:
            return "context_trial_expired"
        return None

    def descriptor(self) -> str:
        return json.dumps(
            asdict(self), sort_keys=True, default=lambda value: value.isoformat()
        )


class ContextTrialStore:
    """The immutable descriptor and reservations share the case database."""

    def __init__(self, db_path: str, trial: ContextTrial) -> None:
        self.db_path, self.trial = db_path, trial

    async def _bind(self, db: aiosqlite.Connection) -> str | None:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS matrix_context_trials "
            "(trial_id TEXT PRIMARY KEY, descriptor TEXT NOT NULL)"
        )
        # Reservations deliberately survive case retention: deleting a review
        # must never replenish a trial's paid-call or delivery allowance.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS matrix_context_trial_cases "
            "(trial_id TEXT NOT NULL, escalation_id INTEGER NOT NULL, "
            "reserved_at TEXT NOT NULL, PRIMARY KEY (trial_id, escalation_id))"
        )
        await db.execute(
            "INSERT OR IGNORE INTO matrix_context_trials VALUES (?, ?)",
            (self.trial.trial_id, self.trial.descriptor()),
        )
        cursor = await db.execute(
            "SELECT descriptor FROM matrix_context_trials WHERE trial_id=?",
            (self.trial.trial_id,),
        )
        row = await cursor.fetchone()
        return (
            None
            if row and row[0] == self.trial.descriptor()
            else "context_trial_configuration_changed"
        )

    async def check(self, case_id: int | None = None) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            reason = await self._bind(db)
            if reason is None:
                reason = self.trial.reason()
            if reason is None and case_id is not None:
                cursor = await db.execute(
                    "SELECT 1 FROM matrix_context_trial_cases WHERE trial_id=? AND escalation_id=?",
                    (self.trial.trial_id, case_id),
                )
                if await cursor.fetchone() is None:
                    reason = "context_trial_case_not_reserved"
            await db.commit()
        # Closing/committing the database may itself wait across expiration.
        return reason or self.trial.reason()

    async def reserve(self, case_id: int) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            reason = await self._bind(db) or self.trial.reason()
            if reason is None:
                cursor = await db.execute(
                    "SELECT 1 FROM matrix_context_trial_cases WHERE trial_id=? AND escalation_id=?",
                    (self.trial.trial_id, case_id),
                )
                if await cursor.fetchone() is not None:
                    reason = "context_trial_case_already_reserved"
            if reason is None:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM matrix_context_trial_cases WHERE trial_id=?",
                    (self.trial.trial_id,),
                )
                row = await cursor.fetchone()
                if row and row[0] >= self.trial.max_cases:
                    reason = "context_trial_capacity_reached"
            if reason is None:
                await db.execute(
                    "INSERT INTO matrix_context_trial_cases VALUES (?, ?, ?)",
                    (self.trial.trial_id, case_id, utc_now().isoformat()),
                )
            await db.commit()
            return reason
