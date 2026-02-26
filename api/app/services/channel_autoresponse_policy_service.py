"""Persistent channel-level autoresponse policy storage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Iterable, List

from app.channels.registry import get_registered_channel_types

SUPPORTED_CHANNELS: tuple[str, ...] = ("web", "matrix", "bisq2")
DEFAULT_AUTORESPONSE_ENABLED: Dict[str, bool] = {
    "web": True,
    "matrix": False,
    "bisq2": False,
}
DEFAULT_GENERATION_ENABLED: Dict[str, bool] = {
    "web": True,
    "matrix": False,
    "bisq2": False,
}


def _normalized_channel_ids(ids: Iterable[str]) -> list[str]:
    normalized = {str(channel_id or "").strip().lower() for channel_id in ids}
    normalized.discard("")
    return sorted(normalized)


def discover_supported_channels(
    configured_channels: Iterable[str] | None = None,
) -> tuple[str, ...]:
    discovered = set(SUPPORTED_CHANNELS)
    if configured_channels is not None:
        discovered.update(_normalized_channel_ids(configured_channels))
    discovered.update(_normalized_channel_ids(get_registered_channel_types().keys()))
    return tuple(sorted(discovered))


def default_generation_enabled(channel_id: str) -> bool:
    normalized = str(channel_id or "").strip().lower()
    return bool(DEFAULT_GENERATION_ENABLED.get(normalized, normalized == "web"))


def default_autoresponse_enabled(channel_id: str) -> bool:
    normalized = str(channel_id or "").strip().lower()
    return bool(DEFAULT_AUTORESPONSE_ENABLED.get(normalized, normalized == "web"))


@dataclass(frozen=True)
class ChannelAutoResponsePolicy:
    channel_id: str
    enabled: bool
    generation_enabled: bool
    updated_at: str


class ChannelAutoResponsePolicyService:
    """Store and retrieve per-channel autoresponse enable flags."""

    def __init__(
        self,
        db_path: str,
        supported_channels: Iterable[str] | None = None,
    ) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self._supported_channels = discover_supported_channels(supported_channels)
        self._init_db()
        self._seed_defaults()

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
                    CREATE TABLE IF NOT EXISTS channel_autoresponse_policy (
                        channel_id TEXT PRIMARY KEY,
                        enabled INTEGER NOT NULL,
                        generation_enabled INTEGER,
                        updated_at TEXT NOT NULL
                    )
                    """)
                columns = {
                    str(row["name"])
                    for row in conn.execute(
                        "PRAGMA table_info(channel_autoresponse_policy)"
                    ).fetchall()
                }
                if "generation_enabled" not in columns:
                    conn.execute("""
                        ALTER TABLE channel_autoresponse_policy
                        ADD COLUMN generation_enabled INTEGER
                        """)
                conn.commit()
            finally:
                conn.close()

    def _seed_defaults(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                for channel_id in self._supported_channels:
                    enabled = 1 if default_autoresponse_enabled(channel_id) else 0
                    generation_enabled = (
                        1 if default_generation_enabled(channel_id) else 0
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO channel_autoresponse_policy
                        (channel_id, enabled, generation_enabled, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (channel_id, enabled, generation_enabled, now),
                    )
                    conn.execute(
                        """
                        UPDATE channel_autoresponse_policy
                        SET generation_enabled = COALESCE(generation_enabled, ?)
                        WHERE channel_id = ?
                        """,
                        (generation_enabled, channel_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def list_policies(self) -> List[ChannelAutoResponsePolicy]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("""
                    SELECT channel_id, enabled, generation_enabled, updated_at
                    FROM channel_autoresponse_policy
                    ORDER BY channel_id
                    """).fetchall()
            finally:
                conn.close()

        return [self._row_to_policy(row) for row in rows]

    def get_policy(self, channel_id: str) -> ChannelAutoResponsePolicy:
        normalized = self._validate_channel_id(channel_id)
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT channel_id, enabled, generation_enabled, updated_at
                    FROM channel_autoresponse_policy
                    WHERE channel_id = ?
                    """,
                    (normalized,),
                ).fetchone()
            finally:
                conn.close()

        if row is None:
            raise KeyError(normalized)
        return self._row_to_policy(row)

    def set_enabled(self, channel_id: str, enabled: bool) -> ChannelAutoResponsePolicy:
        return self.set_policy(channel_id=channel_id, enabled=enabled)

    def set_generation_enabled(
        self,
        channel_id: str,
        generation_enabled: bool,
    ) -> ChannelAutoResponsePolicy:
        return self.set_policy(
            channel_id=channel_id,
            generation_enabled=generation_enabled,
        )

    def set_policy(
        self,
        channel_id: str,
        enabled: bool | None = None,
        generation_enabled: bool | None = None,
    ) -> ChannelAutoResponsePolicy:
        if enabled is None and generation_enabled is None:
            raise ValueError("At least one policy field must be set")

        normalized = self._validate_channel_id(channel_id)
        current = self.get_policy(normalized)
        next_enabled = current.enabled if enabled is None else bool(enabled)
        next_generation_enabled = (
            current.generation_enabled
            if generation_enabled is None
            else bool(generation_enabled)
        )
        if not next_generation_enabled:
            next_enabled = False

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO channel_autoresponse_policy (
                        channel_id,
                        enabled,
                        generation_enabled,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        enabled = excluded.enabled,
                        generation_enabled = excluded.generation_enabled,
                        updated_at = excluded.updated_at
                    """,
                    (
                        normalized,
                        1 if next_enabled else 0,
                        1 if next_generation_enabled else 0,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_policy(normalized)

    @staticmethod
    def _row_to_policy(row: sqlite3.Row) -> ChannelAutoResponsePolicy:
        channel_id = str(row["channel_id"])
        generation_raw = row["generation_enabled"]
        if generation_raw is None:
            generation_enabled = default_generation_enabled(channel_id)
        else:
            generation_enabled = bool(generation_raw)
        return ChannelAutoResponsePolicy(
            channel_id=channel_id,
            enabled=bool(row["enabled"]),
            generation_enabled=generation_enabled,
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _normalize_channel_id(channel_id: str) -> str:
        normalized = str(channel_id or "").strip().lower()
        if not normalized:
            raise ValueError("channel_id is required")
        return normalized

    def _validate_channel_id(self, channel_id: str) -> str:
        normalized = self._normalize_channel_id(channel_id)
        if normalized not in self._supported_channels:
            raise ValueError(f"Unsupported channel_id: {channel_id}")
        return normalized
