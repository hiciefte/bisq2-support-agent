"""Configured retention expires resolved receipts, never unresolved retry guards."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.services.knowledge.candidate_repository import KnowledgeCandidateRepository
from app.services.privacy_retention_service import (
    PrivacyRetentionReport,
    PrivacyRetentionService,
)


@pytest.mark.parametrize("dry_run", [True, False])
def test_completed_receipts_follow_configured_window(tmp_path, dry_run):
    path = tmp_path / "unified_training.db"
    KnowledgeCandidateRepository(str(path))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=2)
    with closing(sqlite3.connect(path)) as conn, conn:
        for digest, state, timestamp in [
            ("old", "completed", now - timedelta(days=3)),
            ("new", "completed", now - timedelta(days=1)),
            ("held", "uncertain", now - timedelta(days=40)),
        ]:
            conn.execute(
                "INSERT INTO knowledge_extraction_attempts "
                "(input_digest, scope_digest, source, state, created_at, updated_at) "
                "VALUES (?, ?, 'matrix', ?, ?, ?)",
                (digest, digest, state, timestamp.isoformat(), timestamp.isoformat()),
            )
    service = PrivacyRetentionService(
        SimpleNamespace(
            DATA_DIR=str(tmp_path),
            DATA_RETENTION_DAYS=2,
        )
    )
    report = PrivacyRetentionReport(dry_run=dry_run, cutoff=cutoff, completed_at=now)
    service._cleanup_training_database(
        cutoff=cutoff, now=now, dry_run=dry_run, report=report
    )
    result = report.stores["knowledge_extraction_completed"]
    assert result.deleted_rows == 1
    assert result.window_seconds == 2 * 86400
    with closing(sqlite3.connect(path)) as conn, conn:
        retained = {
            row[0]
            for row in conn.execute(
                "SELECT input_digest FROM knowledge_extraction_attempts"
            )
        }
    assert retained == ({"old", "new", "held"} if dry_run else {"new", "held"})
