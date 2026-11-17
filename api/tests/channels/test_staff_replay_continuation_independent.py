"""Independent no-provider checks of the explicitly approved replay suffix."""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest
from app.channels.staff_assist import context_trial
from app.channels.staff_assist.context_conversation import StaffConversationCoordinator
from app.channels.staff_assist.context_trial import ContextTrialStore
from app.scripts import replay_staff_context as replay
from app.scripts import replay_staff_context_continuation as recovery

from tests.channels.test_context_spend import wrapper
from tests.channels.test_staff_replay import BASE
from tests.channels.test_staff_replay_continuation import make_parent
from tests.channels.test_staff_replay_independent import FakeCalls

pytestmark = pytest.mark.unit


def prepared_parent(tmp_path):
    args, snapshot, trial = asyncio.run(make_parent(tmp_path))
    result = recovery.prepare(args)
    manifest, parent = recovery.approved_manifest(
        args.output / "manifest.json", result["manifest_sha256"]
    )
    return args, snapshot, trial, result, manifest, parent


def test_suffix_ingests_only_remaining_observed_events(tmp_path, monkeypatch):
    args, _, trial, _, _, parent = prepared_parent(tmp_path)
    state = json.loads((args.output / "continuation-state.json").read_text())
    parent_before = recovery.file_pin(args.parent_execution / "replay.db")
    ingested = []
    original = StaffConversationCoordinator.ingest

    async def observe(self, turn, **kwargs):
        ingested.append((turn.event_id, kwargs["now_ms"]))
        return await original(self, turn, **kwargs)

    monkeypatch.setattr(StaffConversationCoordinator, "ingest", observe)
    calls = FakeCalls(args.output / "prepared-state.db")
    assert calls.store.trial.trial_id == trial.trial_id
    result = asyncio.run(
        replay.replay(
            parent["plan"], parent["inputs"], args.output, calls, continuation=state
        )
    )
    assert result["stopped_reason"] is None
    assert ingested == [("$later", BASE + 20000)]
    assert len(result["formed_cases"]) == 1
    assert result["chronological_coverage"]["processed_observed_events"] == 2
    assert result["chronological_coverage"]["reached_final_quiet_deadline"] is True
    assert calls.calls == 2
    gate = calls.requests[0]
    assert gate[0:2] == ("gate", BASE + 30000)
    assert [item["event_id"] for item in gate[2]["messages"]] == [
        "$question",
        "$later",
    ]
    assert recovery.file_pin(args.parent_execution / "replay.db") == parent_before


def test_exact_saved_call_id_must_match_reconstructed_snapshot(tmp_path):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    path = args.parent_execution / "call-intents.jsonl"
    intent = json.loads(path.read_text())
    old_id = intent["call_id"]
    intent["call_id"] = "different-synthetic-call-id"
    path.write_text(json.dumps(intent) + "\n")
    with closing(sqlite3.connect(args.parent_execution / "replay.db")) as db, db:
        db.execute(
            "UPDATE matrix_context_trial_spend SET call_id=? WHERE call_id=?",
            (intent["call_id"], old_id),
        )
    with pytest.raises(ValueError, match="exact paid receipt"):
        recovery.prepare(args)
    assert not (args.output / "manifest.json").exists()


def test_parent_success_cannot_be_treated_as_a_stopped_run(tmp_path):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    path = args.parent_execution / "result.json"
    result = json.loads(path.read_text())
    result.update(status="executed_pending_agent_and_staff_review", stopped_reason=None)
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="stop|stopped"):
        recovery.prepare(args)
    assert not args.output.exists()


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("parent_call_ids", []),
        ("cumulative_call_cap", 999999),
        ("remaining_budget_nanodollars", 999999999999),
        ("processed_event_count", 0),
    ],
)
def test_derived_manifest_fields_cannot_override_parent(tmp_path, field, replacement):
    args, _, _, _, manifest, _ = prepared_parent(tmp_path)
    path = args.output / "manifest.json"
    manifest[field] = replacement
    path.write_bytes(replay.json_bytes(manifest))
    with pytest.raises(ValueError):
        recovery.approved_manifest(path, replay.digest_bytes(path.read_bytes()))


def test_changed_prepared_copy_is_rejected_before_execution(tmp_path):
    args, _, _, result, _, _ = prepared_parent(tmp_path)
    with closing(sqlite3.connect(args.output / "prepared-state.db")) as db, db:
        db.execute("UPDATE matrix_context_trial_spend SET actual_nanodollars=0")
    with pytest.raises(ValueError, match="input changed"):
        recovery.approved_manifest(
            args.output / "manifest.json", result["manifest_sha256"]
        )


def test_original_cutoff_blocks_suffix_before_client_or_execution_intent(
    tmp_path, monkeypatch
):
    args, _, trial, result, manifest, _ = prepared_parent(tmp_path)
    assert manifest["original_absolute_cutoff"] == trial.end_at.isoformat()
    monkeypatch.setattr(
        context_trial, "utc_now", lambda: trial.end_at + timedelta(seconds=1)
    )
    with pytest.raises(ValueError, match="Original replay window"):
        recovery.execute(
            NS(
                owner_approved=True,
                approve_manifest_sha256=result["manifest_sha256"],
                manifest=args.output / "manifest.json",
            )
        )
    assert not (args.output / "execution").exists()


def test_cumulative_call_cap_does_not_reset_for_suffix(tmp_path):
    args, _, trial, _, manifest, parent = prepared_parent(tmp_path)
    store = ContextTrialStore(str(args.output / "prepared-state.db"), trial)
    llm = wrapper(store).llm
    plan = {**parent["plan"], "max_model_calls": manifest["parent_call_count"]}
    calls = recovery.ContinuationCalls(
        plan, llm, store, args.output, manifest, parent["intent"]["started_at"]
    )
    adapter = calls.adapter(
        NS(case_id=99, version="synthetic-unstarted-suffix"),
        kind="gate",
        virtual_time_ms=BASE + 30000,
    )
    with pytest.raises(RuntimeError, match="replay_model_call_cap_reached"):
        adapter.invoke("Synthetic prompt", system_content="Synthetic system")
    llm.invoke.assert_not_called()
    assert calls.calls == manifest["parent_call_count"]
    records = recovery.receipts(args.output / "prepared-state.db")
    new = next(row for row in records if row["escalation_id"] == 99)
    assert new["status"] == "not_started"
    assert new["actual_nanodollars"] == 0


def test_elapsed_limit_uses_original_start_time(tmp_path):
    args, _, trial, _, manifest, parent = prepared_parent(tmp_path)
    store = ContextTrialStore(str(args.output / "prepared-state.db"), trial)
    llm = wrapper(store).llm
    plan = {**parent["plan"], "maximum_elapsed_seconds": 1}
    original_start = (trial.start_at - timedelta(minutes=1)).isoformat()
    calls = recovery.ContinuationCalls(
        plan, llm, store, args.output, manifest, original_start
    )
    adapter = calls.adapter(
        NS(case_id=99, version="synthetic-expired-suffix"),
        kind="gate",
        virtual_time_ms=BASE + 30000,
    )
    with pytest.raises(RuntimeError, match="replay_elapsed_limit_reached"):
        adapter.invoke("Synthetic prompt", system_content="Synthetic system")
    llm.invoke.assert_not_called()
    assert calls.calls == manifest["parent_call_count"]
