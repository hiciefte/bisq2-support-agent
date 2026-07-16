from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.services.privacy_retention_service import (
    PrivacyRetentionError,
    PrivacyRetentionReport,
    PrivacyRetentionService,
)

NOW = datetime(2026, 1, 31, 12, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=30)
OLD = CUTOFF - timedelta(seconds=1)
EXACT = CUTOFF
NEW = CUTOFF + timedelta(seconds=1)
RESERVATION_CUTOFF = NOW - timedelta(days=2)
RESERVATION_OLD = RESERVATION_CUTOFF - timedelta(seconds=1)
RESERVATION_NEW = RESERVATION_CUTOFF + timedelta(seconds=1)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _message_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _settings(data_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        DATA_DIR=str(data_dir),
        DATA_RETENTION_DAYS=30,
        TRUST_MONITOR_EVIDENCE_TTL_DAYS=30,
        TRUST_MONITOR_AGGREGATE_TTL_DAYS=30,
        TRUST_MONITOR_FINDING_TTL_DAYS=30,
        MATRIX_SYNC_SESSION_PATH=str(data_dir / "matrix_session.json"),
        MATRIX_ALERT_SESSION_FILE_PATH=str(data_dir / "matrix_alert_session.json"),
    )


def _create_feedback_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.executescript("""
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY,
                message_id TEXT UNIQUE NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                rating INTEGER NOT NULL,
                explanation TEXT,
                timestamp TEXT,
                created_at TEXT,
                sources TEXT,
                sources_used TEXT,
                channel TEXT NOT NULL DEFAULT 'web',
                feedback_method TEXT NOT NULL DEFAULT 'web_dialog',
                external_message_id TEXT,
                reactor_identity_hash TEXT,
                reaction_emoji TEXT
            );
            CREATE TABLE conversation_messages (
                id INTEGER PRIMARY KEY,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE feedback_metadata (
                id INTEGER PRIMARY KEY,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                created_at TEXT
            );
            CREATE TABLE feedback_issues (
                id INTEGER PRIMARY KEY,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                created_at TEXT
            );
            CREATE TABLE feedback_reactions (
                id INTEGER PRIMARY KEY,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                created_at TEXT,
                last_updated_at TEXT,
                revoked_at TEXT
            );
            CREATE TABLE chatops_action_audit (
                id INTEGER PRIMARY KEY,
                actor_id TEXT,
                created_at TEXT
            );
            CREATE TABLE channel_delivery_reservations (
                channel_id TEXT NOT NULL,
                message_key TEXT NOT NULL,
                reserved_at REAL NOT NULL,
                PRIMARY KEY (channel_id, message_key)
            );
            CREATE TABLE trust_actor_profiles (
                actor_key TEXT PRIMARY KEY,
                actor_id TEXT,
                last_seen_at TEXT
            );
            CREATE TABLE trust_evidence_events (
                id INTEGER PRIMARY KEY,
                actor_id TEXT,
                occurred_at TEXT
            );
            CREATE TABLE trust_actor_aggregates (
                id INTEGER PRIMARY KEY,
                actor_id TEXT,
                observed_at TEXT
            );
            CREATE TABLE trust_findings (
                id INTEGER PRIMARY KEY,
                detector_key TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                suspect_actor_key TEXT NOT NULL,
                suspect_actor_id TEXT NOT NULL,
                suspect_display_name TEXT NOT NULL,
                evidence_summary_json TEXT NOT NULL,
                updated_at TEXT,
                UNIQUE(detector_key, channel_id, space_id, suspect_actor_key)
            );
            CREATE TABLE trust_finding_feedback (
                id INTEGER PRIMARY KEY,
                finding_id INTEGER NOT NULL REFERENCES trust_findings(id) ON DELETE CASCADE,
                actor_id TEXT,
                created_at TEXT
            );
            CREATE TABLE trust_access_audit (
                id INTEGER PRIMARY KEY,
                actor_id TEXT,
                created_at TEXT
            );
            """)
        feedback_rows = [
            (1, "old", OLD),
            (2, "exact", EXACT),
            (3, "new", NEW),
            (4, "old-with-new-child", OLD),
            (5, "new-with-old-child", NEW),
        ]
        connection.executemany(
            """
            INSERT INTO feedback (
                id, message_id, question, answer, rating, explanation,
                timestamp, created_at
            ) VALUES (?, ?, 'question', 'answer', 1, 'detail', ?, ?)
            """,
            [
                (row_id, message_id, _iso(ts), _iso(ts))
                for row_id, message_id, ts in feedback_rows
            ],
        )
        connection.executemany(
            "INSERT INTO conversation_messages (id, feedback_id, content, created_at) VALUES (?, ?, 'context', ?)",
            [(1, 4, _iso(NEW)), (2, 5, _iso(OLD))],
        )
        connection.executemany(
            """
            INSERT INTO channel_delivery_reservations (
                channel_id, message_key, reserved_at
            ) VALUES ('matrix', ?, ?)
            """,
            [
                (_message_key("old-reservation"), RESERVATION_OLD.timestamp()),
                (_message_key("exact-reservation"), RESERVATION_CUTOFF.timestamp()),
                (_message_key("new-reservation"), RESERVATION_NEW.timestamp()),
                (_message_key("malformed-reservation"), "unknown"),
            ],
        )
        for table, timestamp_column in (
            ("chatops_action_audit", "created_at"),
            ("trust_actor_profiles", "last_seen_at"),
            ("trust_evidence_events", "occurred_at"),
            ("trust_actor_aggregates", "observed_at"),
            ("trust_access_audit", "created_at"),
        ):
            if table == "trust_actor_profiles":
                connection.executemany(
                    f"INSERT INTO {table} (actor_key, actor_id, {timestamp_column}) VALUES (?, 'actor', ?)",
                    [("old", _iso(OLD)), ("exact", _iso(EXACT))],
                )
            else:
                connection.executemany(
                    f"INSERT INTO {table} (id, actor_id, {timestamp_column}) VALUES (?, 'actor', ?)",
                    [(1, _iso(OLD)), (2, _iso(EXACT))],
                )
        connection.executemany(
            """
            INSERT INTO trust_findings (
                id, detector_key, channel_id, space_id, suspect_actor_key,
                suspect_actor_id, suspect_display_name, evidence_summary_json,
                updated_at
            ) VALUES (?, 'detector', 'channel', 'space', ?, 'actor', 'name', '{}', ?)
            """,
            [(1, "old", _iso(OLD)), (2, "exact", _iso(EXACT))],
        )
        connection.execute(
            "INSERT INTO trust_finding_feedback "
            "(id, finding_id, actor_id, created_at) VALUES (1, 1, 'actor', ?)",
            (_iso(NEW),),
        )


def _create_escalation_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.executescript("""
            CREATE TABLE escalations (
                id INTEGER PRIMARY KEY,
                message_id TEXT UNIQUE NOT NULL,
                question TEXT,
                status TEXT,
                created_at TEXT
            );
            CREATE TABLE escalation_rating_consumed_tokens (
                token_jti TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                consumed_at TEXT
            );
            """)
        connection.executemany(
            "INSERT INTO escalations (id, message_id, question, status, created_at) VALUES (?, ?, 'private', ?, ?)",
            [
                (1, "old", "pending", _iso(OLD)),
                (2, "exact", "closed", _iso(EXACT)),
                (3, "new", "responded", _iso(NEW)),
            ],
        )
        connection.executemany(
            "INSERT INTO escalation_rating_consumed_tokens (token_jti, message_id, consumed_at) VALUES (?, ?, ?)",
            [("old", "old", _iso(OLD)), ("exact", "exact", _iso(EXACT))],
        )


def _candidate_columns() -> str:
    return """
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        source_event_id TEXT UNIQUE NOT NULL,
        source_timestamp TEXT,
        question_text TEXT NOT NULL,
        staff_answer TEXT NOT NULL,
        generated_answer TEXT,
        staff_sender TEXT,
        llm_reasoning TEXT,
        reviewed_by TEXT,
        rejection_reason TEXT,
        rejection_note TEXT,
        edited_staff_answer TEXT,
        edited_question_text TEXT,
        generated_answer_sources TEXT,
        original_user_question TEXT,
        original_staff_answer TEXT
    """


def _create_training_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.executescript(f"""
            CREATE TABLE unified_faq_candidates ({_candidate_columns()});
            CREATE TABLE conversation_threads (
                id INTEGER PRIMARY KEY,
                thread_key TEXT UNIQUE NOT NULL,
                room_id TEXT,
                first_question_id TEXT NOT NULL,
                correction_reason TEXT,
                candidate_id INTEGER REFERENCES unified_faq_candidates(id),
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE thread_messages (
                id INTEGER PRIMARY KEY,
                thread_id INTEGER REFERENCES conversation_threads(id),
                content TEXT,
                timestamp TEXT
            );
            CREATE TABLE conversation_state_transitions (
                id INTEGER PRIMARY KEY,
                thread_id INTEGER REFERENCES conversation_threads(id),
                metadata TEXT,
                created_at TEXT
            );
            CREATE TABLE knowledge_update_proposals (
                id INTEGER PRIMARY KEY,
                candidate_id INTEGER REFERENCES unified_faq_candidates(id),
                preview_markdown TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE llm_wiki_review_feedback (
                id INTEGER PRIMARY KEY,
                reviewed_by TEXT,
                original_markdown TEXT,
                created_at TEXT,
                updated_at TEXT,
                reviewed_at TEXT
            );
            CREATE TABLE learning_state (
                id INTEGER PRIMARY KEY,
                review_history TEXT,
                threshold_history TEXT,
                last_updated TEXT
            );
            """)
        candidates = [
            (1, "old-unlinked", OLD),
            (2, "exact", EXACT),
            (3, "new", NEW),
            (4, "old-linked-new-proposal", OLD),
            (5, "old-linked-old-proposal", OLD),
            (6, "old-linked-new-thread", OLD),
        ]
        connection.executemany(
            """
            INSERT INTO unified_faq_candidates (
                id, source, source_event_id, source_timestamp, question_text,
                staff_answer, original_user_question, original_staff_answer
            ) VALUES (?, 'matrix', ?, ?, 'question', 'answer', 'original q', 'original a')
            """,
            [(row_id, event_id, _iso(ts)) for row_id, event_id, ts in candidates],
        )
        connection.executemany(
            """
            INSERT INTO knowledge_update_proposals (
                id, candidate_id, preview_markdown, created_at, updated_at
            ) VALUES (?, ?, 'private proposal', ?, NULL)
            """,
            [(1, 4, _iso(NEW)), (2, 5, _iso(OLD))],
        )
        connection.executemany(
            """
            INSERT INTO conversation_threads (
                id, thread_key, room_id, first_question_id, correction_reason,
                candidate_id, created_at, updated_at
            ) VALUES (?, ?, 'room', 'question-id', 'private', ?, ?, NULL)
            """,
            [
                (1, "old-with-new-message", 6, _iso(OLD)),
                (2, "old-with-old-message", None, _iso(OLD)),
                (3, "exact", None, _iso(EXACT)),
            ],
        )
        connection.executemany(
            "INSERT INTO thread_messages (id, thread_id, content, timestamp) VALUES (?, ?, 'private', ?)",
            [(1, 1, _iso(NEW)), (2, 2, _iso(OLD))],
        )
        connection.executemany(
            "INSERT INTO llm_wiki_review_feedback (id, reviewed_by, original_markdown, created_at) VALUES (?, 'reviewer', 'private', ?)",
            [(1, _iso(OLD)), (2, _iso(EXACT))],
        )
        history = [
            {"question_id": "old", "timestamp": _iso(OLD)},
            {"question_id": "exact", "timestamp": _iso(EXACT)},
            {"question_id": "new", "timestamp": _iso(NEW)},
            {"question_id": "malformed", "timestamp": "unknown"},
        ]
        threshold_history = [{"timestamp": _iso(OLD), "auto_send": 0.9}]
        connection.execute(
            "INSERT INTO learning_state (id, review_history, threshold_history, last_updated) VALUES (1, ?, ?, ?)",
            (json.dumps(history), json.dumps(threshold_history), _iso(NEW)),
        )


def _create_translation_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.execute("""
            CREATE TABLE translations (
                cache_key TEXT PRIMARY KEY,
                value TEXT,
                created_at INTEGER,
                expires_at INTEGER
            )
            """)
        future = int((NOW + timedelta(days=2)).timestamp())
        connection.executemany(
            "INSERT INTO translations VALUES (?, 'private', ?, ?)",
            [
                ("old", int(OLD.timestamp()), future),
                ("exact", int(EXACT.timestamp()), future),
                ("new", int(NEW.timestamp()), future),
                ("unknown", None, future),
            ],
        )


def _create_legacy_database(path: Path) -> None:
    with _connect(path) as connection:
        connection.execute(
            "CREATE TABLE candidates "
            "(id INTEGER PRIMARY KEY, content TEXT, created_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO candidates VALUES (?, 'private', ?)",
            [(1, _iso(OLD)), (2, _iso(EXACT)), (3, None)],
        )


def _create_file_stores(data_dir: Path) -> None:
    records = [
        {"id": "old", "timestamp": _iso(OLD)},
        {"id": "exact", "timestamp": _iso(EXACT)},
        {"id": "new", "timestamp": _iso(NEW)},
    ]
    lines = [*(json.dumps(record) for record in records), "not-json"]
    (data_dir / "conversations.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    with (data_dir / "support_chat_export.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "timestamp"])
        writer.writeheader()
        writer.writerows(records)
        writer.writerow({"id": "unknown", "timestamp": "unknown"})
    (data_dir / "processed_conversations.json").write_text(
        json.dumps(records), encoding="utf-8"
    )
    pages = data_dir / "knowledge/llm_wiki/pages"
    pages.mkdir(parents=True)
    (pages / "old.md").write_text(
        "---\nreviewed_by: reviewer-old\n"
        f"reviewed_at: '{OLD.date().isoformat()}'\n---\nReviewed text\n",
        encoding="utf-8",
    )
    (pages / "exact.md").write_text(
        "---\nreviewed_by: reviewer-exact\n"
        f"reviewed_at: '{_iso(EXACT)}'\n---\nReviewed text\n",
        encoding="utf-8",
    )

    (data_dir / "matrix_polling_state.json").write_text(
        json.dumps(
            {
                "since_token": "current-cursor",
                "room_tokens": {"room": "current-room-cursor"},
                "processed_ids": ["old", "exact", "new"],
                "processed_id_timestamps": {
                    "old": _iso(OLD),
                    "exact": _iso(EXACT),
                    "new": _iso(NEW),
                },
                "last_poll": _iso(NEW),
            }
        ),
        encoding="utf-8",
    )

    for filename in ("bisq_sync_state.json", "bisq_live_channel_sync_state.json"):
        (data_dir / filename).write_text(
            json.dumps(
                {
                    "last_sync_timestamp": _iso(NEW),
                    "processed_message_ids": ["old", "exact", "new"],
                    "processed_message_timestamps": {
                        "old": _iso(OLD),
                        "exact": _iso(EXACT),
                        "new": _iso(NEW),
                    },
                }
            ),
            encoding="utf-8",
        )

    session_file = data_dir / "matrix_session.json"
    session_file.write_text(
        json.dumps(
            {
                "access_token": "fixture-token",
                "device_id": "fixture-device",
                "user_id": "fixture-user",
                "created_at": _iso(OLD),
            }
        ),
        encoding="utf-8",
    )
    store_dir = data_dir / "matrix_session_store"
    store_dir.mkdir()
    (store_dir / "fixture.db").write_text("crypto", encoding="utf-8")


@pytest.fixture
def retention_fixture(tmp_path: Path) -> tuple[PrivacyRetentionService, Path]:
    _create_feedback_db(tmp_path / "feedback.db")
    _create_escalation_db(tmp_path / "escalations.db")
    _create_training_db(tmp_path / "unified_training.db")
    _create_translation_db(tmp_path / "translation_cache.db")
    _create_legacy_database(tmp_path / "faq_candidates.db")
    _create_file_stores(tmp_path)
    return PrivacyRetentionService(_settings(tmp_path)), tmp_path


def _table_rows(path: Path, table: str, columns: str = "*") -> list[tuple]:
    with _connect(path) as connection:
        return connection.execute(
            f"SELECT {columns} FROM {table} ORDER BY 1"
        ).fetchall()


def test_dry_run_reports_actions_without_mutating_fixture_stores(
    retention_fixture: tuple[PrivacyRetentionService, Path],
) -> None:
    service, data_dir = retention_fixture
    before = {
        str(path.relative_to(data_dir)): path.read_bytes()
        for path in data_dir.rglob("*")
        if path.is_file()
    }

    report = service.run(dry_run=True, now=NOW)

    after = {
        str(path.relative_to(data_dir)): path.read_bytes()
        for path in data_dir.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert report.dry_run is True
    assert report.stores["feedback"].deleted_rows == 1
    assert report.stores["feedback"].anonymized_rows == 1
    assert report.stores["channel_delivery_reservations"].deleted_rows == 1
    assert report.stores["escalations"].deleted_rows == 1
    assert report.stores["training_learning_history"].deleted_rows == 1
    assert report.stores["training_candidates"].deleted_rows == 2
    assert report.stores["training_candidates"].anonymized_rows == 2
    assert report.stores["translation_cache"].deleted_rows == 2
    translation_age = report.stores["translation_cache"].oldest_age_seconds
    assert translation_age is not None
    assert translation_age > report.stores["translation_cache"].window_seconds
    oldest_history = report.stores["training_learning_history"].oldest_age_seconds
    assert oldest_history is not None
    assert oldest_history > report.stores["training_learning_history"].window_seconds
    oldest_legacy = report.stores["legacy_file_conversations"].oldest_age_seconds
    assert oldest_legacy is not None
    assert oldest_legacy > report.stores["legacy_file_conversations"].window_seconds
    assert report.vacuumed_databases == []


def test_delivery_reservations_use_scheduled_boundary_safe_retention(
    retention_fixture: tuple[PrivacyRetentionService, Path],
) -> None:
    service, data_dir = retention_fixture
    path = data_dir / "feedback.db"
    before = _table_rows(
        path,
        "channel_delivery_reservations",
        "message_key, reserved_at",
    )

    dry_run = service.run(dry_run=True, now=NOW)

    assert dry_run.stores["channel_delivery_reservations"].deleted_rows == 1
    assert dry_run.stores["channel_delivery_reservations"].window_seconds == 172800
    assert (
        _table_rows(
            path,
            "channel_delivery_reservations",
            "message_key, reserved_at",
        )
        == before
    )

    applied = service.run(now=NOW)
    retained = _table_rows(
        path,
        "channel_delivery_reservations",
        "message_key, reserved_at",
    )

    assert applied.stores["channel_delivery_reservations"].deleted_rows == 1
    assert {row[0] for row in retained} == {
        _message_key("exact-reservation"),
        _message_key("new-reservation"),
        _message_key("malformed-reservation"),
    }
    assert all(len(row[0]) == 64 for row in retained)
    assert all("reservation" not in row[0] for row in retained)
    oldest_age = applied.stores["channel_delivery_reservations"].oldest_age_seconds
    assert oldest_age is not None
    assert oldest_age > applied.stores["channel_delivery_reservations"].window_seconds
    assert (
        service.run(now=NOW).stores["channel_delivery_reservations"].deleted_rows == 0
    )


def test_delivery_reservations_follow_shorter_configured_privacy_window(
    tmp_path: Path,
) -> None:
    path = tmp_path / "feedback.db"
    _create_feedback_db(path)
    settings = _settings(tmp_path)
    settings.DATA_RETENTION_DAYS = 1
    service = PrivacyRetentionService(settings)

    report = service.run(now=NOW)
    retained = _table_rows(
        path,
        "channel_delivery_reservations",
        "message_key",
    )

    result = report.stores["channel_delivery_reservations"]
    assert result.deleted_rows == 3
    assert result.window_seconds == 86400
    assert retained == [(_message_key("malformed-reservation"),)]


def test_training_candidate_dry_run_matches_ordered_cleanup(
    retention_fixture: tuple[PrivacyRetentionService, Path],
) -> None:
    service, data_dir = retention_fixture

    dry_run = service.run(dry_run=True, now=NOW)
    applied = service.run(now=NOW)

    assert (
        dry_run.stores["training_candidates"].deleted_rows
        == applied.stores["training_candidates"].deleted_rows
    )
    assert (
        dry_run.stores["training_candidates"].anonymized_rows
        == applied.stores["training_candidates"].anonymized_rows
    )
    retained_candidate_ids = {
        row[0]
        for row in _table_rows(
            data_dir / "unified_training.db",
            "unified_faq_candidates",
            "id",
        )
    }
    assert 5 not in retained_candidate_ids


def test_run_removes_only_out_of_window_rows_and_is_idempotent(
    retention_fixture: tuple[PrivacyRetentionService, Path],
) -> None:
    service, data_dir = retention_fixture

    report = service.run(now=NOW)

    feedback = _table_rows(
        data_dir / "feedback.db", "feedback", "id, message_id, question"
    )
    assert feedback == [
        (2, "exact", "question"),
        (3, "new", "question"),
        (4, "retained:4", ""),
        (5, "new-with-old-child", "question"),
    ]
    assert _table_rows(
        data_dir / "feedback.db",
        "conversation_messages",
        "id, feedback_id, content",
    ) == [(1, 4, "context")]
    assert _table_rows(
        data_dir / "escalations.db", "escalations", "id, message_id, status"
    ) == [(2, "exact", "closed"), (3, "new", "responded")]

    candidates = _table_rows(
        data_dir / "unified_training.db",
        "unified_faq_candidates",
        "id, source_event_id, question_text",
    )
    assert candidates == [
        (2, "exact", "question"),
        (3, "new", "question"),
        (4, "retained:4", ""),
        (6, "retained:6", ""),
    ]
    assert _table_rows(
        data_dir / "unified_training.db",
        "knowledge_update_proposals",
        "id, candidate_id, preview_markdown",
    ) == [(1, 4, "private proposal")]
    assert _table_rows(
        data_dir / "unified_training.db",
        "thread_messages",
        "id, thread_id, content",
    ) == [(1, 1, "private")]
    assert _table_rows(
        data_dir / "unified_training.db",
        "conversation_threads",
        "id, thread_key, room_id",
    ) == [(1, "retained:1", None), (3, "exact", "room")]

    with _connect(data_dir / "unified_training.db") as connection:
        state = connection.execute(
            "SELECT review_history, threshold_history FROM learning_state"
        ).fetchone()
    history = json.loads(state[0])
    assert [row["question_id"] for row in history] == [
        "exact",
        "new",
        "malformed",
    ]
    assert json.loads(state[1]) == [{"timestamp": _iso(OLD), "auto_send": 0.9}]

    assert _table_rows(
        data_dir / "translation_cache.db", "translations", "cache_key"
    ) == [("exact",), ("new",)]
    retained_jsonl = (
        (data_dir / "conversations.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert [json.loads(line)["id"] for line in retained_jsonl[:2]] == [
        "exact",
        "new",
    ]
    assert retained_jsonl[2] == "not-json"
    with (data_dir / "support_chat_export.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        assert [row["id"] for row in csv.DictReader(handle)] == [
            "exact",
            "new",
            "unknown",
        ]

    assert _table_rows(
        data_dir / "faq_candidates.db",
        "candidates",
        "id, content, created_at",
    ) == [
        (2, "private", _iso(EXACT)),
        (3, "private", None),
    ]
    assert _table_rows(
        data_dir / "feedback.db",
        "trust_findings",
        "id, channel_id, space_id, suspect_actor_id",
    ) == [
        (1, "", "", ""),
        (2, "channel", "space", "actor"),
    ]

    matrix_state = json.loads(
        (data_dir / "matrix_polling_state.json").read_text(encoding="utf-8")
    )
    assert matrix_state["processed_ids"] == ["exact", "new"]
    assert matrix_state["since_token"] == "current-cursor"
    assert matrix_state["room_tokens"] == {"room": "current-room-cursor"}
    assert not (data_dir / "matrix_session.json").exists()
    assert not (data_dir / "matrix_session_store").exists()
    assert "reviewed_by: support-admin" in (
        data_dir / "knowledge/llm_wiki/pages/old.md"
    ).read_text(encoding="utf-8")
    assert "reviewed_by: reviewer-exact" in (
        data_dir / "knowledge/llm_wiki/pages/exact.md"
    ).read_text(encoding="utf-8")
    assert set(report.vacuumed_databases) == {
        "feedback.db",
        "escalations.db",
        "translation_cache.db",
        "unified_training.db",
        "faq_candidates.db",
    }

    second = service.run(now=NOW)
    assert second.deleted_rows == 0
    assert second.vacuumed_databases == []


def test_store_failure_is_reported_and_other_groups_continue(
    retention_fixture: tuple[PrivacyRetentionService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, data_dir = retention_fixture
    original: Any = service._cleanup_text_table

    def fail_feedback_table(
        connection: sqlite3.Connection,
        **kwargs: object,
    ):
        result = original(connection, **kwargs)
        if kwargs["table"] == "feedback_metadata":
            raise RuntimeError("fixture failure")
        return result

    monkeypatch.setattr(service, "_cleanup_text_table", fail_feedback_table)

    with pytest.raises(PrivacyRetentionError) as error:
        service.run(now=NOW)

    assert error.value.report.failed_store_groups == ["feedback"]
    assert _table_rows(data_dir / "feedback.db", "conversation_messages", "id") == [
        (1,),
        (2,),
    ]
    assert _table_rows(data_dir / "escalations.db", "escalations", "message_id") == [
        ("exact",),
        ("new",),
    ]


def test_success_invalidates_only_live_personal_data_caches(
    retention_fixture: tuple[PrivacyRetentionService, Path],
) -> None:
    service, _ = retention_fixture
    translation_cache = SimpleNamespace(l1=MagicMock())
    feedback_service = MagicMock()

    service.run(
        now=NOW,
        translation_cache=translation_cache,
        feedback_service=feedback_service,
    )

    translation_cache.l1.clear.assert_called_once_with()
    feedback_service.invalidate_retention_caches.assert_called_once_with()


@pytest.mark.parametrize(
    ("failing_hook", "failed_group"),
    [
        ("feedback", "feedback"),
        ("training", "training"),
        ("translations", "translations"),
    ],
)
def test_post_cleanup_hook_failures_use_store_group_accounting(
    retention_fixture: tuple[PrivacyRetentionService, Path],
    monkeypatch: pytest.MonkeyPatch,
    failing_hook: str,
    failed_group: str,
) -> None:
    service, _ = retention_fixture
    translation_cache = SimpleNamespace(l1=MagicMock())
    feedback_service = MagicMock()
    learning_engine = MagicMock()
    learning_engine.prune_review_history_before.return_value = 0
    if failing_hook == "feedback":
        feedback_service.invalidate_retention_caches.side_effect = RuntimeError(
            "fixture failure"
        )
    elif failing_hook == "training":
        learning_engine.prune_review_history_before.side_effect = RuntimeError(
            "fixture failure"
        )
    else:
        translation_cache.l1.clear.side_effect = RuntimeError("fixture failure")
    record_run = MagicMock()
    record_failure = MagicMock()
    monkeypatch.setattr(
        "app.services.privacy_retention_service.record_privacy_retention_run",
        record_run,
    )
    monkeypatch.setattr(
        "app.services.privacy_retention_service.record_privacy_retention_failure",
        record_failure,
    )

    with pytest.raises(PrivacyRetentionError) as error:
        service.run(
            now=NOW,
            translation_cache=translation_cache,
            feedback_service=feedback_service,
            learning_engine=learning_engine,
        )

    assert error.value.report.failed_store_groups == [failed_group]
    successful_groups = record_run.call_args.kwargs["successful_store_groups"]
    assert failed_group not in successful_groups
    assert set(successful_groups) == set(service.STORE_GROUPS) - {failed_group}
    record_failure.assert_called_once_with(failed_store_groups=[failed_group])


def test_dry_run_training_hook_failure_is_recorded_without_success_metrics(
    retention_fixture: tuple[PrivacyRetentionService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = retention_fixture
    learning_engine = MagicMock()
    learning_engine.prune_review_history_before.side_effect = RuntimeError(
        "fixture failure"
    )
    record_run = MagicMock()
    record_failure = MagicMock()
    monkeypatch.setattr(
        "app.services.privacy_retention_service.record_privacy_retention_run",
        record_run,
    )
    monkeypatch.setattr(
        "app.services.privacy_retention_service.record_privacy_retention_failure",
        record_failure,
    )

    with pytest.raises(PrivacyRetentionError):
        service.run(dry_run=True, now=NOW, learning_engine=learning_engine)

    record_run.assert_not_called()
    record_failure.assert_called_once_with(failed_store_groups=["training"])


def test_learning_hook_handles_absent_persisted_history_result(
    retention_fixture: tuple[PrivacyRetentionService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = retention_fixture
    monkeypatch.setattr(
        service,
        "_cleanup_training_database",
        MagicMock(),
    )
    learning_engine = MagicMock()
    learning_engine.prune_review_history_before.return_value = 2

    report = service.run(dry_run=True, now=NOW, learning_engine=learning_engine)

    assert report.stores["training_learning_history"].deleted_rows == 2


def test_failed_vacuum_is_retried_after_deletions_are_committed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "retention.db"
    with _connect(path) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO records VALUES (1)")

    connection = _connect(path)
    connection.execute("DELETE FROM records")

    class FailingVacuumConnection:
        def commit(self) -> None:
            connection.commit()

        def execute(self, statement: str):
            if statement == "VACUUM":
                raise sqlite3.OperationalError("fixture vacuum failure")
            return connection.execute(statement)

    report = PrivacyRetentionReport(
        dry_run=False,
        cutoff=CUTOFF,
        completed_at=NOW,
    )
    with pytest.raises(sqlite3.OperationalError, match="fixture vacuum failure"):
        PrivacyRetentionService._vacuum(
            FailingVacuumConnection(),  # type: ignore[arg-type]
            path=path,
            changed=1,
            dry_run=False,
            report=report,
        )
    connection.close()

    marker = tmp_path / ".retention.db.retention-vacuum-pending"
    assert marker.is_file()
    assert _table_rows(path, "records", "id") == []

    retry_connection = _connect(path)
    try:
        PrivacyRetentionService._vacuum(
            retry_connection,
            path=path,
            changed=0,
            dry_run=False,
            report=report,
        )
    finally:
        retry_connection.close()

    assert not marker.exists()
    assert report.vacuumed_databases == ["retention.db"]


def test_vacuum_fsyncs_pending_marker_and_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "retention.db"
    with _connect(path) as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO records VALUES (1)")

    connection = _connect(path)
    connection.execute("DELETE FROM records")
    fsync = MagicMock()
    monkeypatch.setattr(os, "fsync", fsync)
    report = PrivacyRetentionReport(
        dry_run=False,
        cutoff=CUTOFF,
        completed_at=NOW,
    )
    try:
        PrivacyRetentionService._vacuum(
            connection,
            path=path,
            changed=1,
            dry_run=False,
            report=report,
        )
    finally:
        connection.close()

    assert fsync.call_count == 3
    assert not (tmp_path / ".retention.db.retention-vacuum-pending").exists()
