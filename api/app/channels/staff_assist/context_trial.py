"""Opt-in, durable admission limits for one Matrix staff-context trial."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
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
    budget_nanodollars: int | None = None
    daily_budget_nanodollars: int | None = None
    input_nanodollars_per_token: int | None = None
    output_nanodollars_per_token: int | None = None
    model: str | None = None
    max_output_tokens: int | None = None

    @property
    def spend_bounded(self) -> bool:
        return self.budget_nanodollars is not None

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
        money_fields = (
            "MATRIX_CONTEXT_TRIAL_BUDGET_USD",
            "MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD",
            "MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION",
            "MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION",
        )
        values = [
            str(getattr(settings, name, "") or "").strip() for name in money_fields
        ]
        spend_bounded = any(values)
        budget: int | None = None
        daily: int | None = None
        input_rate: int | None = None
        output_rate: int | None = None
        model: str | None = None
        maximum: int | None = None
        if spend_bounded:
            if not all(values):
                raise ValueError(
                    "Matrix spend trials require both budgets and both price ceilings"
                )
            budget, daily, input_rate, output_rate = (
                _money(value, scale)
                for value, scale in zip(values, (10**9, 10**9, 1000, 1000))
            )
            if daily > budget:
                raise ValueError("Matrix daily budget cannot exceed the trial budget")
            model = str(getattr(settings, "OPENAI_MODEL", "") or "")
            maximum = getattr(settings, "MAX_TOKENS", None)
            if not model or type(maximum) is not int or not 1 <= maximum <= 32768:
                raise ValueError(
                    "Matrix spend trials require a model and bounded MAX_TOKENS"
                )
        days = 30 if spend_bounded else 7
        if not timedelta(0) < end_at - start_at <= timedelta(days=days):
            raise ValueError(
                f"Matrix trial duration must be positive and at most {days} days"
            )
        max_cases = int(getattr(settings, "MATRIX_CONTEXT_TRIAL_MAX_CASES", 10))
        if not spend_bounded and not 1 <= max_cases <= 20:
            raise ValueError("MATRIX_CONTEXT_TRIAL_MAX_CASES must be between 1 and 20")
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
        return cls(
            trial_id,
            rooms,
            staff,
            start_at,
            end_at,
            0 if spend_bounded else max_cases,
            budget_nanodollars=budget,
            daily_budget_nanodollars=daily,
            input_nanodollars_per_token=input_rate,
            output_nanodollars_per_token=output_rate,
            model=model,
            max_output_tokens=maximum,
        )

    def reason(self, now: datetime | None = None) -> str | None:
        current = now or utc_now()
        if current < self.start_at:
            return "context_trial_not_started"
        if current >= self.end_at:
            return "context_trial_expired"
        return None

    def descriptor(self) -> str:
        # Old descriptors are immutable receipts: new optional fields must not
        # change their bytes or silently reopen/extend a count-bound trial.
        values = asdict(self)
        if not self.spend_bounded:
            values = {key: value for key, value in values.items() if value is not None}
        else:
            values.pop("max_cases")
            values["version"] = 2
        return json.dumps(
            values, sort_keys=True, default=lambda value: value.isoformat()
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
        if self.trial.spend_bounded:
            await db.execute(
                "INSERT OR IGNORE INTO matrix_context_trials VALUES (?, ?)",
                (self.trial.trial_id, self.trial.descriptor()),
            )
        cursor = await db.execute(
            "SELECT descriptor FROM matrix_context_trials WHERE trial_id=?",
            (self.trial.trial_id,),
        )
        row = await cursor.fetchone()
        if row is None and not self.trial.spend_bounded:
            return "context_trial_budget_required"
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
        if self.trial.spend_bounded:
            return "context_trial_call_bound_required"
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

    def reserve_call(
        self,
        case_id: int,
        *,
        kind: str,
        call_id: str,
        input_tokens_bound: int,
    ) -> str | None:
        """Reserve one actual provider invocation, immediately before starting it.

        Integer nanodollars avoid floating-point budget races. A crash, timeout,
        missing usage, or cancellation keeps the entire reservation spent. Gate
        calls share the monetary bounds but never consume a note generation.
        """
        trial = self.trial
        if not trial.spend_bounded:
            return "context_trial_spend_bound_required"
        if (
            kind not in {"note", "gate", "update"}
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", call_id)
            or type(case_id) is not int
            or type(input_tokens_bound) is not int
            or not 0 < input_tokens_bound <= MAX_BUDGET_INPUT_TOKENS
        ):
            return "context_trial_invalid_call_bound"
        reserved = (
            input_tokens_bound * trial.input_nanodollars_per_token
            + trial.max_output_tokens * trial.output_nanodollars_per_token
        )
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            reason = self._bind_spend(db)
            now = utc_now()
            reason = reason or trial.reason(now)
            if reason:
                return reason
            key = (trial.trial_id, case_id, kind, call_id)
            if db.execute(
                "SELECT 1 FROM matrix_context_trial_spend WHERE trial_id=? "
                "AND escalation_id=? AND kind=? AND call_id=?",
                key,
            ).fetchone():
                return "context_trial_call_already_started"
            # Only one original draft and one material update per request. Gates
            # use content-version IDs so a replay cannot spend twice on a version.
            if (
                kind != "gate"
                and db.execute(
                    "SELECT 1 FROM matrix_context_trial_spend WHERE trial_id=? "
                    "AND escalation_id=? AND kind=? AND status!='not_started'",
                    key[:3],
                ).fetchone()
            ):
                return "context_trial_call_already_started"
            if db.execute(
                "SELECT 1 FROM matrix_context_trial_spend WHERE trial_id=? AND status='overrun'",
                (trial.trial_id,),
            ).fetchone():
                return "context_trial_usage_bound_violated"
            day = now.date().isoformat()
            total, daily = db.execute(
                "SELECT COALESCE(SUM(COALESCE(actual_nanodollars, reserved_nanodollars)), 0), "
                "COALESCE(SUM(CASE WHEN utc_day=? THEN COALESCE(actual_nanodollars, reserved_nanodollars) ELSE 0 END), 0) "
                "FROM matrix_context_trial_spend WHERE trial_id=?",
                (day, trial.trial_id),
            ).fetchone()
            if total + reserved > trial.budget_nanodollars:
                return "context_trial_budget_exhausted"
            if daily + reserved > trial.daily_budget_nanodollars:
                return "context_trial_daily_budget_exhausted"
            # The DB lock may have waited across a cutoff or UTC day boundary.
            if trial.reason() or utc_now().date().isoformat() != day:
                return trial.reason() or "context_trial_day_changed"
            db.execute(
                "INSERT INTO matrix_context_trial_spend "
                "(trial_id, escalation_id, kind, call_id, started_at, utc_day, "
                "input_tokens_bound, max_output_tokens, reserved_nanodollars, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uncertain')",
                (
                    *key,
                    now.isoformat(),
                    day,
                    input_tokens_bound,
                    trial.max_output_tokens,
                    reserved,
                ),
            )
            if kind != "gate":
                db.execute(
                    "INSERT OR IGNORE INTO matrix_context_trial_cases VALUES (?, ?, ?)",
                    (trial.trial_id, case_id, now.isoformat()),
                )
        return None

    def _bind_spend(self, db: sqlite3.Connection) -> str | None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS matrix_context_trials (trial_id TEXT PRIMARY KEY, descriptor TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS matrix_context_trial_cases (trial_id TEXT NOT NULL, escalation_id INTEGER NOT NULL, reserved_at TEXT NOT NULL, PRIMARY KEY (trial_id, escalation_id))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS matrix_context_trial_spend ("
            "trial_id TEXT NOT NULL, escalation_id INTEGER NOT NULL, kind TEXT NOT NULL, "
            "call_id TEXT NOT NULL, started_at TEXT NOT NULL, utc_day TEXT NOT NULL, "
            "input_tokens_bound INTEGER NOT NULL, max_output_tokens INTEGER NOT NULL, "
            "reserved_nanodollars INTEGER NOT NULL, actual_nanodollars INTEGER, "
            "input_tokens INTEGER, output_tokens INTEGER, status TEXT NOT NULL, "
            "PRIMARY KEY (trial_id, escalation_id, kind, call_id))"
        )
        db.execute(
            "INSERT OR IGNORE INTO matrix_context_trials VALUES (?, ?)",
            (self.trial.trial_id, self.trial.descriptor()),
        )
        row = db.execute(
            "SELECT descriptor FROM matrix_context_trials WHERE trial_id=?",
            (self.trial.trial_id,),
        ).fetchone()
        return (
            None
            if row and row[0] == self.trial.descriptor()
            else "context_trial_configuration_changed"
        )

    def cancel_unstarted_call(self, case_id: int, *, kind: str, call_id: str) -> None:
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE matrix_context_trial_spend SET actual_nanodollars=0, status='not_started' "
                "WHERE trial_id=? AND escalation_id=? AND kind=? AND call_id=? AND status='uncertain'",
                (self.trial.trial_id, case_id, kind, call_id),
            )
            db.execute(
                "DELETE FROM matrix_context_trial_cases WHERE trial_id=? AND escalation_id=? "
                "AND NOT EXISTS (SELECT 1 FROM matrix_context_trial_spend WHERE trial_id=? "
                "AND escalation_id=? AND kind IN ('note', 'update') AND status!='not_started')",
                (self.trial.trial_id, case_id, self.trial.trial_id, case_id),
            )

    def settle_call(self, case_id: int, *, kind: str, call_id: str, usage: Any) -> bool:
        """Release only measured unused capacity; do not guess missing tokens.

        Input is charged at the approved worst-case price, including cache-write
        premiums. Thus this is a conservative spend ledger, not an invoice.
        """
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        if not self.trial.spend_bounded or not isinstance(usage, dict):
            return False
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        if any(
            type(value) is not int or value < 0
            for value in (input_tokens, output_tokens)
        ):
            return False
        key = (self.trial.trial_id, case_id, kind, call_id)
        with closing(sqlite3.connect(self.db_path, timeout=30)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if self._bind_spend(db):
                return False
            row = db.execute(
                "SELECT input_tokens_bound, max_output_tokens, status FROM matrix_context_trial_spend "
                "WHERE trial_id=? AND escalation_id=? AND kind=? AND call_id=?",
                key,
            ).fetchone()
            if not row or row[2] != "uncertain":
                return False
            cost = (
                input_tokens * self.trial.input_nanodollars_per_token
                + output_tokens * self.trial.output_nanodollars_per_token
            )
            exceeded = input_tokens > row[0] or output_tokens > row[1]
            # On a provider-contract overrun record the greater real liability;
            # retain the hold and halt all further trial calls.
            db.execute(
                "UPDATE matrix_context_trial_spend SET actual_nanodollars="
                + ("MAX(reserved_nanodollars, ?)" if exceeded else "?")
                + ", input_tokens=?, output_tokens=?, status=? "
                "WHERE trial_id=? AND escalation_id=? AND kind=? AND call_id=?",
                (
                    cost,
                    input_tokens,
                    output_tokens,
                    "overrun" if exceeded else "settled",
                    *key,
                ),
            )
        return not exceeded


# Below the short-context price tier and bounded independently of character
# limits. UTF-8 byte count is a conservative token ceiling for byte tokenizers;
# 1024 further tokens cover the fixed two-message protocol framing.
MAX_BUDGET_INPUT_TOKENS = 100_000


def _money(value: str, scale: int) -> int:
    try:
        amount = Decimal(value) * scale
        if (
            not amount.is_finite()
            or amount > 10**15
            or amount <= 0
            or amount != amount.to_integral_value()
        ):
            raise ValueError
        return int(amount)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(
            "Matrix budgets and price ceilings must be positive finite decimal amounts"
        ) from exc


class BudgetedContextLLM:
    """Apply spend admission only when the preview actually invokes a model."""

    def __init__(
        self,
        store: ContextTrialStore,
        llm: Any,
        case_id: int,
        *,
        kind: str = "note",
        call_id: str = "initial",
        before_call: Any = None,
        before_provider: Any = None,
        on_not_started: Any = None,
    ):
        self.store, self.llm, self.case_id = store, llm, case_id
        self.kind, self.call_id = kind, call_id
        self.before_call = before_call
        self.before_provider = before_provider
        self.on_not_started = on_not_started
        self.started = False
        self.reason: str | None = None
        self.unstarted_cleanup_error: str | None = None

    def invoke(self, prompt: str, system_content: str | None = None):
        from app.services.rag.openai_responses import (
            OpenAIResponsesLLMWrapper,
            ResponsesGenerationError,
        )

        trial = self.store.trial
        # Only the known single-call, no-tool, no-retry Responses adapter has a
        # provable maximum. Do not mutate the shared wrapper used by web chat.
        valid_wrapper = (
            isinstance(self.llm, OpenAIResponsesLLMWrapper)
            and self.llm.model_id == trial.model
            and self.llm.max_tokens == trial.max_output_tokens
            and self.llm.client.max_retries == 0
        )
        if valid_wrapper:
            rates = [self.llm.input_rate, self.llm.cached_rate, self.llm.write_rate]
            valid_wrapper = (
                all(
                    Decimal(str(rate)).is_finite()
                    and Decimal(str(rate)) >= 0
                    and Decimal(str(rate)) * 10**9 <= trial.input_nanodollars_per_token
                    for rate in rates
                )
                and 0
                <= Decimal(str(self.llm.output_rate)) * 10**9
                <= trial.output_nanodollars_per_token
            )
        if not valid_wrapper:
            self.reason = "context_trial_unbounded_model"
            raise RuntimeError(self.reason)
        bound = (
            len(prompt.encode("utf-8"))
            + len((system_content or "").encode("utf-8"))
            + 1024
        )
        admission_day = utc_now().date()
        self.reason = self.store.reserve_call(
            self.case_id, kind=self.kind, call_id=self.call_id, input_tokens_bound=bound
        )
        if self.reason:
            raise RuntimeError(self.reason)
        try:
            self.reason = trial.reason() or (
                "context_trial_day_changed"
                if utc_now().date() != admission_day
                else None
            )
            if not self.reason and self.before_call:
                self.reason = self.before_call()
            # The durable intent hook can block on disk I/O across the cutoff
            # or UTC day. Recheck immediately at the provider boundary.
            self.reason = (
                self.reason
                or trial.reason()
                or (
                    "context_trial_day_changed"
                    if utc_now().date() != admission_day
                    else None
                )
            )
            if not self.reason and self.before_provider:
                self.reason = self.before_provider()
            # The last hook can itself cross the trial cutoff or UTC midnight.
            # Use one observation for both checks immediately before invocation.
            current = utc_now()
            self.reason = (
                self.reason
                or trial.reason(current)
                or (
                    "context_trial_day_changed"
                    if current.date() != admission_day
                    else None
                )
            )
            if self.reason:
                raise RuntimeError(self.reason)
        except Exception as original:
            try:
                self.store.cancel_unstarted_call(
                    self.case_id, kind=self.kind, call_id=self.call_id
                )
            except Exception as cleanup:
                # Keep the reservation held if cancellation did not commit. A
                # storage error must not hide the refusal or skip its audit hook.
                self.unstarted_cleanup_error = type(cleanup).__name__
                original.add_note(
                    "Unstarted reservation cleanup requires reconciliation: "
                    + self.unstarted_cleanup_error
                )
            if self.on_not_started:
                # Keep the original pre-call error even if the audit disk fails.
                try:
                    self.on_not_started(self.reason or "pre_call_hook_failed")
                except Exception:
                    pass
            raise
        self.started = True
        try:
            response = self.llm.invoke(prompt, system_content=system_content)
        except ResponsesGenerationError as exc:
            self.store.settle_call(
                self.case_id, kind=self.kind, call_id=self.call_id, usage=exc.usage
            )
            raise
        self.store.settle_call(
            self.case_id,
            kind=self.kind,
            call_id=self.call_id,
            usage=getattr(response, "usage", None),
        )
        return response
