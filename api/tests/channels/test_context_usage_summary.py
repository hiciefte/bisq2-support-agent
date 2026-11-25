"""Model accounting stays distinct from Staff judgments and delivery."""

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from app.channels.staff_assist.context_trial import ContextTrial, ContextTrialStore
from app.scripts.summarize_staff_context import summarize
from app.services.escalation.escalation_repository import EscalationRepository

pytestmark = pytest.mark.unit


async def test_summary_separates_gate_unknown_note_and_unstarted_update(tmp_path):
    path = tmp_path / "cases.db"
    await EscalationRepository(str(path)).initialize()
    now = datetime.now(timezone.utc)
    trial = ContextTrial(
        "summary-trial",
        ("!source:example.org",),
        "!staff:example.org",
        now - timedelta(hours=1),
        now + timedelta(hours=1),
        0,
        budget_nanodollars=10**9,
        daily_budget_nanodollars=10**9,
        input_nanodollars_per_token=10000,
        output_nanodollars_per_token=50000,
        model="openai:test",
        max_output_tokens=256,
    )
    store = ContextTrialStore(str(path), trial)
    for kind in ("gate", "note", "update"):
        assert (
            store.reserve_call(1, kind=kind, call_id="first", input_tokens_bound=1000)
            is None
        )
    assert store.settle_call(
        1,
        kind="gate",
        call_id="first",
        usage={"prompt_tokens": 100, "completion_tokens": 20},
    )
    store.cancel_unstarted_call(1, kind="update", call_id="first")

    result = summarize(path)[0]
    gate, note, update = (
        result["model_usage_by_kind"][kind] for kind in ("gate", "note", "update")
    )
    assert gate["usage_observed"] == 1
    assert gate["observed_input_tokens"] == 100
    assert gate["accounted_nanodollars"] == 2000000
    assert note["uncertain"] == 1
    assert note["usage_observed"] == 0
    assert note["accounted_nanodollars"] == 22800000
    assert update["started_or_uncertain"] == 0
    assert update["cancelled_before_start"] == 1
    assert update["accounted_nanodollars"] == 0
    assert result["version_diagnostics"]["notes_posted"] == 0
    assert result["version_diagnostics"]["share_of_posted_notes_with_verdict"] is None


async def test_no_spend_receipts_does_not_invent_zero_measured_cost(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    await EscalationRepository(str(path)).initialize()
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE matrix_context_trials (trial_id TEXT, descriptor TEXT)"
        )
        db.execute("INSERT INTO matrix_context_trials VALUES ('legacy', '{}')")
    result = summarize(path)[0]
    assert result["model_usage_by_kind"] is None
    assert result["version_diagnostics"]["share_of_posted_notes_with_verdict"] is None


def test_legacy_summary_reads_only_report_columns_and_separates_proposals(
    tmp_path, monkeypatch
):
    import json
    import sqlite3

    path = tmp_path / "legacy-columns.db"
    metadata = {
        "delivery_audience": "staff_room",
        "response_kind": "public_context",
        "context_trial_id": "legacy",
    }
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE escalations (id INTEGER, channel TEXT, channel_metadata TEXT, routing_reason TEXT, question TEXT, staff_answer TEXT)"
        )
        db.execute(
            "INSERT INTO escalations VALUES (1, 'matrix', ?, '', 'private question', NULL)",
            (
                json.dumps(
                    {
                        **metadata,
                        "staff_context_proposed_answer": {"answer": "Proposed only"},
                    }
                ),
            ),
        )
        db.execute(
            "INSERT INTO escalations VALUES (2, 'matrix', ?, '', 'private question', 'Existing Admin response')",
            (json.dumps(metadata),),
        )
    connect = sqlite3.connect

    def report_connection(*args, **kwargs):
        db = connect(*args, **kwargs)

        def authorizer(action, table, column, *_):
            if (
                action == sqlite3.SQLITE_READ
                and table == "escalations"
                and column in {"question", "staff_answer"}
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(authorizer)
        return db

    monkeypatch.setattr(sqlite3, "connect", report_connection)
    result = summarize(path)[0]
    assert result["cases"] == 2
    assert result["requests_with_thread_activity"] == 1
    assert result["drafts_with_verdict"] == 0
    assert result["version_diagnostics"]["notes_posted"] == 0


def test_request_results_keep_latest_version_disagreement_and_exclusions(tmp_path):
    import json
    import sqlite3

    path = tmp_path / "requests.db"
    metadata = {
        "context_trial_id": "synthetic",
        "delivery_audience": "staff_room",
        "response_kind": "public_context",
    }
    votes = [
        {
            "reviewer": "a",
            "target_event_id": "$old",
            "event_id": "$v3",
            "at": "2026-01-03T00:00:00+00:00",
            "verdict": "not_needed",
        },
        {
            "reviewer": "a",
            "target_event_id": "$new",
            "event_id": "$v1",
            "at": "2026-01-01T00:00:00+00:00",
            "verdict": "wrong",
        },
        {
            "reviewer": "b",
            "target_event_id": "$new",
            "event_id": "$v2",
            "at": "2026-01-02T00:00:00+00:00",
            "verdict": "would_send_after_edit",
        },
    ]
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE escalations (id INTEGER, channel TEXT, channel_metadata TEXT, routing_reason TEXT, staff_context_verdicts TEXT)"
        )
        for case_id, (extra, records) in enumerate(
            [
                (
                    {
                        "context_status": "delivered",
                        "staff_note_event_id": "$new",
                        "staff_note_history": [
                            {"event_id": "$old"},
                            {"event_id": "$new"},
                        ],
                    },
                    votes,
                ),
                ({"context_status": "delivery_uncertain"}, []),
                (
                    {
                        "context_reason": "invalid_model_output",
                        "validation_diagnostic": "unsafe_reply",
                    },
                    [],
                ),
            ],
            1,
        ):
            db.execute(
                "INSERT INTO escalations VALUES (?, 'matrix', ?, '', ?)",
                (case_id, json.dumps({**metadata, **extra}), json.dumps(records)),
            )
    trial = summarize(path)[0]
    assert [r["request_id"] for r in trial["requests"]] == [1, 2, 3]
    assert trial["requests_drafted"] == trial["drafts_with_verdict"] == 1
    assert sum(trial["headline_verdict_counts"].values()) == 1
    assert trial["headline_verdict_counts"]["would_send_after_edit"] == 1
    assert trial["drafts_with_any_reviewer_verdict"]["wrong"] == 1
    assert trial["drafts_with_any_reviewer_verdict"]["would_send_after_edit"] == 1
    assert trial["drafts_with_any_reviewer_verdict"]["not_needed"] == 0
    assert list(trial["requests"][0]["reviewer_verdicts"].values()) == [
        "wrong",
        "would_send_after_edit",
    ]
    assert (
        trial["requests_with_delivery_uncertain"]
        == trial["requests_with_safety_withhold"]
        == 1
    )
    assert trial["draft_verdict_coverage"] == 1.0
