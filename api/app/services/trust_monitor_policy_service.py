from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.channels.trust_monitor.models import TrustAlertSurface, TrustPolicy


class TrustMonitorPolicyService:
    def __init__(self, *, db_path: str, settings: Any) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self._lock = Lock()
        self._initialize()
        self._seed_defaults()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_monitor_policy (
                    policy_key TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    name_collision_enabled INTEGER NOT NULL,
                    silent_observer_enabled INTEGER NOT NULL,
                    alert_surface TEXT NOT NULL,
                    matrix_public_room_ids_json TEXT NOT NULL,
                    matrix_staff_room_id TEXT NOT NULL,
                    silent_observer_window_days INTEGER NOT NULL,
                    early_read_window_seconds INTEGER NOT NULL,
                    minimum_observations INTEGER NOT NULL,
                    minimum_early_read_hits INTEGER NOT NULL,
                    read_to_reply_ratio_threshold REAL NOT NULL,
                    evidence_ttl_days INTEGER NOT NULL,
                    aggregate_ttl_days INTEGER NOT NULL,
                    finding_ttl_days INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """)
            conn.commit()

    def _default_policy(self) -> TrustPolicy:
        return TrustPolicy(
            enabled=bool(getattr(self.settings, "TRUST_MONITOR_ENABLED", True)),
            name_collision_enabled=bool(
                getattr(self.settings, "TRUST_MONITOR_NAME_COLLISION_ENABLED", True)
            ),
            silent_observer_enabled=bool(
                getattr(self.settings, "TRUST_MONITOR_SILENT_OBSERVER_ENABLED", True)
            ),
            alert_surface=TrustAlertSurface(
                str(
                    getattr(self.settings, "TRUST_MONITOR_ALERT_SURFACE", "admin_ui")
                    or "admin_ui"
                )
            ),
            matrix_public_room_ids=list(
                getattr(self.settings, "TRUST_MONITOR_MATRIX_PUBLIC_ROOMS", []) or []
            ),
            matrix_staff_room_id=str(
                getattr(self.settings, "TRUST_MONITOR_MATRIX_STAFF_ROOM", "") or ""
            ),
            silent_observer_window_days=int(
                getattr(self.settings, "TRUST_MONITOR_SILENT_OBSERVER_WINDOW_DAYS", 14)
            ),
            early_read_window_seconds=int(
                getattr(self.settings, "TRUST_MONITOR_EARLY_READ_WINDOW_SECONDS", 30)
            ),
            minimum_observations=int(
                getattr(self.settings, "TRUST_MONITOR_MINIMUM_OBSERVATIONS", 10)
            ),
            minimum_early_read_hits=int(
                getattr(self.settings, "TRUST_MONITOR_MINIMUM_EARLY_READ_HITS", 8)
            ),
            read_to_reply_ratio_threshold=float(
                getattr(
                    self.settings, "TRUST_MONITOR_READ_TO_REPLY_RATIO_THRESHOLD", 12.0
                )
            ),
            evidence_ttl_days=int(
                getattr(self.settings, "TRUST_MONITOR_EVIDENCE_TTL_DAYS", 7)
            ),
            aggregate_ttl_days=int(
                getattr(self.settings, "TRUST_MONITOR_AGGREGATE_TTL_DAYS", 30)
            ),
            finding_ttl_days=int(
                getattr(self.settings, "TRUST_MONITOR_FINDING_TTL_DAYS", 30)
            ),
            updated_at=datetime.now(UTC).isoformat(),
        )

    def _seed_defaults(self) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT policy_key FROM trust_monitor_policy WHERE policy_key = 'default'"
            ).fetchone()
            if row is not None:
                return
            self._write_policy(conn, self._default_policy())
            conn.commit()

    def _write_policy(self, conn: sqlite3.Connection, policy: TrustPolicy) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO trust_monitor_policy (
                policy_key, enabled, name_collision_enabled, silent_observer_enabled,
                alert_surface, matrix_public_room_ids_json, matrix_staff_room_id,
                silent_observer_window_days, early_read_window_seconds,
                minimum_observations, minimum_early_read_hits,
                read_to_reply_ratio_threshold, evidence_ttl_days, aggregate_ttl_days,
                finding_ttl_days, updated_at
            ) VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1 if policy.enabled else 0,
                1 if policy.name_collision_enabled else 0,
                1 if policy.silent_observer_enabled else 0,
                policy.alert_surface.value,
                json.dumps(policy.matrix_public_room_ids),
                policy.matrix_staff_room_id,
                policy.silent_observer_window_days,
                policy.early_read_window_seconds,
                policy.minimum_observations,
                policy.minimum_early_read_hits,
                policy.read_to_reply_ratio_threshold,
                policy.evidence_ttl_days,
                policy.aggregate_ttl_days,
                policy.finding_ttl_days,
                policy.updated_at,
            ),
        )

    def get_policy(self) -> TrustPolicy:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trust_monitor_policy WHERE policy_key = 'default'"
            ).fetchone()
        if row is None:
            return self._default_policy()
        return TrustPolicy(
            enabled=bool(row["enabled"]),
            name_collision_enabled=bool(row["name_collision_enabled"]),
            silent_observer_enabled=bool(row["silent_observer_enabled"]),
            alert_surface=TrustAlertSurface(row["alert_surface"]),
            matrix_public_room_ids=list(
                json.loads(row["matrix_public_room_ids_json"] or "[]")
            ),
            matrix_staff_room_id=row["matrix_staff_room_id"],
            silent_observer_window_days=int(row["silent_observer_window_days"]),
            early_read_window_seconds=int(row["early_read_window_seconds"]),
            minimum_observations=int(row["minimum_observations"]),
            minimum_early_read_hits=int(row["minimum_early_read_hits"]),
            read_to_reply_ratio_threshold=float(row["read_to_reply_ratio_threshold"]),
            evidence_ttl_days=int(row["evidence_ttl_days"]),
            aggregate_ttl_days=int(row["aggregate_ttl_days"]),
            finding_ttl_days=int(row["finding_ttl_days"]),
            updated_at=row["updated_at"],
        )

    def set_policy(self, **patch: Any) -> TrustPolicy:
        with self._lock:
            current = self.get_policy()
            data = asdict(current)
            data.update(
                {key: value for key, value in patch.items() if value is not None}
            )
            data["alert_surface"] = TrustAlertSurface(str(data["alert_surface"]))
            data["updated_at"] = datetime.now(UTC).isoformat()
            updated = TrustPolicy(**data)
            with self._connect() as conn:
                self._write_policy(conn, updated)
                conn.commit()
            return updated
