"""Persistent launch controls for autonomous channel delivery."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Iterable

logger = logging.getLogger(__name__)

LAUNCH_CONTROLLED_CHANNELS: tuple[str, ...] = ("matrix", "bisq2")
_MAX_HOURLY_SENDS = 10_000
_MAX_DAILY_SENDS = 100_000
DELIVERY_RESERVATION_RETENTION_DAYS = 2
_RESERVATION_RETENTION_SECONDS = DELIVERY_RESERVATION_RETENTION_DAYS * 24 * 60 * 60


@dataclass(frozen=True)
class GlobalLaunchControl:
    """Global autonomous-delivery state."""

    autonomous_delivery_enabled: bool
    updated_at: str


@dataclass(frozen=True)
class ChannelLaunchPolicy:
    """Per-channel shadow and canary settings."""

    channel_id: str
    shadow_mode: bool
    canary_enabled: bool
    canary_hourly_limit: int
    canary_daily_limit: int
    updated_at: str


@dataclass(frozen=True)
class DeliveryAuthorization:
    """Result of a per-message autonomous-delivery check."""

    allowed: bool
    reason: str


class ChannelLaunchControlService:
    """Store launch controls and atomically reserve canary sends."""

    def __init__(
        self,
        db_path: str,
        *,
        environment_enabled: bool = False,
        supported_channels: Iterable[str] | None = None,
    ) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._environment_enabled = bool(environment_enabled)
        self._supported_channels = self._normalize_supported_channels(
            supported_channels
        )
        self._init_db()
        self._seed_channel_defaults()
        self._apply_environment_guard()

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
                    CREATE TABLE IF NOT EXISTS channel_launch_global (
                        singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                        autonomous_delivery_enabled INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS channel_launch_policy (
                        channel_id TEXT PRIMARY KEY,
                        shadow_mode INTEGER NOT NULL,
                        canary_enabled INTEGER NOT NULL,
                        canary_hourly_limit INTEGER NOT NULL,
                        canary_daily_limit INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS channel_delivery_reservations (
                        channel_id TEXT NOT NULL,
                        message_key TEXT NOT NULL,
                        reserved_at REAL NOT NULL,
                        PRIMARY KEY (channel_id, message_key)
                    )
                    """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_channel_delivery_reservations_time
                    ON channel_delivery_reservations(channel_id, reserved_at)
                    """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_channel_delivery_reservations_reserved_at
                    ON channel_delivery_reservations(reserved_at)
                    """)
                conn.commit()
            finally:
                conn.close()

    def _seed_channel_defaults(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                for channel_id in self._supported_channels:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO channel_launch_policy (
                            channel_id,
                            shadow_mode,
                            canary_enabled,
                            canary_hourly_limit,
                            canary_daily_limit,
                            updated_at
                        ) VALUES (?, ?, 0, 0, 0, ?)
                        """,
                        (
                            channel_id,
                            1,
                            now,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

    def _apply_environment_guard(self) -> None:
        """Seed global state and enforce an environment-level stop on startup.

        A fresh database always starts stopped, even when the environment flag
        permits a later admin enable. A false environment flag also forces any
        persisted admin enable back off on restart.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO channel_launch_global (
                        singleton_id,
                        autonomous_delivery_enabled,
                        updated_at
                    ) VALUES (1, ?, ?)
                    ON CONFLICT(singleton_id) DO NOTHING
                    """,
                    (0, now),
                )
                if not self._environment_enabled:
                    conn.execute(
                        """
                        UPDATE channel_launch_global
                        SET autonomous_delivery_enabled = 0, updated_at = ?
                        WHERE singleton_id = 1
                        """,
                        (now,),
                    )
                conn.commit()
            finally:
                conn.close()

    def get_global_control(self) -> GlobalLaunchControl:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("""
                    SELECT autonomous_delivery_enabled, updated_at
                    FROM channel_launch_global
                    WHERE singleton_id = 1
                    """).fetchone()
            finally:
                conn.close()
        if row is None:
            raise RuntimeError("Global channel launch control is not initialized")
        return GlobalLaunchControl(
            autonomous_delivery_enabled=self._strict_persisted_flag(
                row["autonomous_delivery_enabled"],
                "autonomous_delivery_enabled",
            ),
            updated_at=str(row["updated_at"]),
        )

    def set_autonomous_delivery_enabled(self, enabled: bool) -> GlobalLaunchControl:
        if enabled and not self._environment_enabled:
            raise ValueError(
                "AUTONOMOUS_DELIVERY_ENABLED must permit delivery before admin enable"
            )
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE channel_launch_global
                    SET autonomous_delivery_enabled = ?, updated_at = ?
                    WHERE singleton_id = 1
                    """,
                    (1 if enabled else 0, now),
                )
                conn.commit()
            finally:
                conn.close()
        logger.warning("Global autonomous delivery changed enabled=%s", bool(enabled))
        return self.get_global_control()

    def list_channel_policies(self) -> list[ChannelLaunchPolicy]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("""
                    SELECT *
                    FROM channel_launch_policy
                    ORDER BY channel_id
                    """).fetchall()
            finally:
                conn.close()
        return [self._row_to_policy(row) for row in rows]

    def check_readiness(self) -> bool:
        """Validate that global and per-channel launch controls are readable."""
        self.get_global_control()
        for channel_id in self._supported_channels:
            self.get_channel_policy(channel_id)
        return True

    def get_channel_policy(self, channel_id: str) -> ChannelLaunchPolicy:
        normalized = self._validate_channel_id(channel_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT *
                    FROM channel_launch_policy
                    WHERE channel_id = ?
                    """,
                    (normalized,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            raise KeyError(normalized)
        return self._row_to_policy(row)

    def set_channel_policy(
        self,
        channel_id: str,
        *,
        shadow_mode: bool | None = None,
        canary_enabled: bool | None = None,
        canary_hourly_limit: int | None = None,
        canary_daily_limit: int | None = None,
    ) -> ChannelLaunchPolicy:
        if all(
            value is None
            for value in (
                shadow_mode,
                canary_enabled,
                canary_hourly_limit,
                canary_daily_limit,
            )
        ):
            raise ValueError("At least one launch policy field must be set")

        normalized = self._validate_channel_id(channel_id)
        current = self.get_channel_policy(normalized)
        next_shadow = current.shadow_mode if shadow_mode is None else bool(shadow_mode)
        next_canary = (
            current.canary_enabled if canary_enabled is None else bool(canary_enabled)
        )
        next_hourly = (
            current.canary_hourly_limit
            if canary_hourly_limit is None
            else int(canary_hourly_limit)
        )
        next_daily = (
            current.canary_daily_limit
            if canary_daily_limit is None
            else int(canary_daily_limit)
        )
        if not 0 <= next_hourly <= _MAX_HOURLY_SENDS:
            raise ValueError(
                f"canary_hourly_limit must be between 0 and {_MAX_HOURLY_SENDS}"
            )
        if not 0 <= next_daily <= _MAX_DAILY_SENDS:
            raise ValueError(
                f"canary_daily_limit must be between 0 and {_MAX_DAILY_SENDS}"
            )
        if next_hourly > next_daily:
            raise ValueError("canary_hourly_limit must not exceed canary_daily_limit")

        now = datetime.now(timezone.utc).isoformat()
        updated = ChannelLaunchPolicy(
            channel_id=normalized,
            shadow_mode=next_shadow,
            canary_enabled=next_canary,
            canary_hourly_limit=next_hourly,
            canary_daily_limit=next_daily,
            updated_at=now,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE channel_launch_policy
                    SET shadow_mode = ?,
                        canary_enabled = ?,
                        canary_hourly_limit = ?,
                        canary_daily_limit = ?,
                        updated_at = ?
                    WHERE channel_id = ?
                    """,
                    (
                        1 if updated.shadow_mode else 0,
                        1 if updated.canary_enabled else 0,
                        updated.canary_hourly_limit,
                        updated.canary_daily_limit,
                        updated.updated_at,
                        updated.channel_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        logger.warning(
            "Channel launch policy updated channel=%s shadow=%s canary=%s hourly=%s daily=%s",
            normalized,
            updated.shadow_mode,
            updated.canary_enabled,
            updated.canary_hourly_limit,
            updated.canary_daily_limit,
        )
        return updated

    def review_only_reason(self, channel_id: str) -> str | None:
        """Return why all channel output must remain review-only."""
        if not self.get_global_control().autonomous_delivery_enabled:
            return "kill_switch"
        if self.get_channel_policy(channel_id).shadow_mode:
            return "shadow_mode"
        return None

    def secondary_delivery_block_reason(self, channel_id: str) -> str | None:
        """Block unreserved notices whenever autonomous output is constrained."""
        reason = self.review_only_reason(channel_id)
        if reason is not None:
            return reason
        if self.get_channel_policy(channel_id).canary_enabled:
            return "canary_requires_reservation"
        return None

    def authorize_autonomous_delivery(
        self,
        channel_id: str,
        message_id: str,
        *,
        now: datetime | None = None,
    ) -> DeliveryAuthorization:
        """Check launch controls and reserve one canary delivery atomically."""
        normalized = self._validate_channel_id(channel_id)
        review_reason = self.review_only_reason(normalized)
        if review_reason is not None:
            return DeliveryAuthorization(False, review_reason)

        policy = self.get_channel_policy(normalized)
        if not policy.canary_enabled:
            return DeliveryAuthorization(True, "fully_enabled")

        normalized_message_id = str(message_id or "").strip()
        if not normalized_message_id:
            return DeliveryAuthorization(False, "missing_message_id")
        message_key = hashlib.sha256(normalized_message_id.encode("utf-8")).hexdigest()

        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        timestamp = current.timestamp()
        hour_cutoff = timestamp - (60 * 60)
        day_cutoff = timestamp - (24 * 60 * 60)

        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "DELETE FROM channel_delivery_reservations WHERE reserved_at < ?",
                    (timestamp - _RESERVATION_RETENTION_SECONDS,),
                )
                duplicate = conn.execute(
                    """
                    SELECT 1
                    FROM channel_delivery_reservations
                    WHERE channel_id = ? AND message_key = ?
                    """,
                    (normalized, message_key),
                ).fetchone()
                if duplicate is not None:
                    conn.commit()
                    return DeliveryAuthorization(False, "duplicate_reservation")

                hourly_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM channel_delivery_reservations
                        WHERE channel_id = ? AND reserved_at >= ?
                        """,
                        (normalized, hour_cutoff),
                    ).fetchone()[0]
                )
                if hourly_count >= policy.canary_hourly_limit:
                    conn.commit()
                    return DeliveryAuthorization(False, "canary_hourly_limit")

                daily_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM channel_delivery_reservations
                        WHERE channel_id = ? AND reserved_at >= ?
                        """,
                        (normalized, day_cutoff),
                    ).fetchone()[0]
                )
                if daily_count >= policy.canary_daily_limit:
                    conn.commit()
                    return DeliveryAuthorization(False, "canary_daily_limit")

                conn.execute(
                    """
                    INSERT INTO channel_delivery_reservations (
                        channel_id, message_key, reserved_at
                    ) VALUES (?, ?, ?)
                    """,
                    (normalized, message_key, timestamp),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return DeliveryAuthorization(True, "canary_reserved")

    def reservation_count(self, channel_id: str) -> int:
        """Return retained reservations for diagnostics and tests."""
        normalized = self._validate_channel_id(channel_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM channel_delivery_reservations
                    WHERE channel_id = ?
                    """,
                    (normalized,),
                ).fetchone()
            finally:
                conn.close()
        return int(row[0]) if row is not None else 0

    def _validate_channel_id(self, channel_id: str) -> str:
        normalized = str(channel_id or "").strip().lower()
        if normalized not in self._supported_channels:
            raise ValueError(f"Unsupported channel_id: {channel_id}")
        return normalized

    @staticmethod
    def _normalize_supported_channels(
        configured_channels: Iterable[str] | None,
    ) -> tuple[str, ...]:
        configured = (
            LAUNCH_CONTROLLED_CHANNELS
            if configured_channels is None
            else configured_channels
        )
        normalized = {
            str(channel_id or "").strip().lower()
            for channel_id in configured
            if str(channel_id or "").strip()
        }
        if not normalized:
            raise ValueError("At least one launch-controlled channel is required")
        return tuple(sorted(normalized))

    @staticmethod
    def _strict_persisted_flag(value: object, field: str) -> bool:
        """Parse a persisted boolean without accepting fail-open values."""
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1):
            raise RuntimeError(f"Persisted channel launch field {field} is invalid")
        return value == 1

    @staticmethod
    def _strict_persisted_limit(value: object, field: str, maximum: int) -> int:
        """Parse a persisted canary limit within its supported range."""
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= maximum
        ):
            raise RuntimeError(f"Persisted channel launch field {field} is invalid")
        return value

    @classmethod
    def _row_to_policy(cls, row: sqlite3.Row) -> ChannelLaunchPolicy:
        shadow_mode = cls._strict_persisted_flag(row["shadow_mode"], "shadow_mode")
        canary_enabled = cls._strict_persisted_flag(
            row["canary_enabled"], "canary_enabled"
        )
        hourly_limit = cls._strict_persisted_limit(
            row["canary_hourly_limit"],
            "canary_hourly_limit",
            _MAX_HOURLY_SENDS,
        )
        daily_limit = cls._strict_persisted_limit(
            row["canary_daily_limit"],
            "canary_daily_limit",
            _MAX_DAILY_SENDS,
        )
        if hourly_limit > daily_limit:
            raise RuntimeError(
                "Persisted channel launch limits have invalid hourly/daily ordering"
            )
        return ChannelLaunchPolicy(
            channel_id=str(row["channel_id"]),
            shadow_mode=shadow_mode,
            canary_enabled=canary_enabled,
            canary_hourly_limit=hourly_limit,
            canary_daily_limit=daily_limit,
            updated_at=str(row["updated_at"]),
        )
