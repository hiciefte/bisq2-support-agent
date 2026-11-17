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
    assert result["notes_posted"] == 0
    assert result["share_of_posted_notes_with_verdict"] is None


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
    assert result["share_of_posted_notes_with_verdict"] is None
