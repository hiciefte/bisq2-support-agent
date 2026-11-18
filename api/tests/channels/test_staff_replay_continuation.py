"""Synthetic preparation and cumulative-bound tests; no provider or Matrix client."""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from app.channels.staff_assist.context_conversation import (
    ConversationTurn,
    StaffConversationCoordinator,
)
from app.channels.staff_assist.context_trial import ContextTrial, ContextTrialStore
from app.scripts import replay_staff_context as replay
from app.scripts import replay_staff_context_continuation as recovery
from app.services.escalation.escalation_repository import EscalationRepository
from app.services.escalation.escalation_service import EscalationService

from tests.channels.test_staff_replay import BASE, fixture_inputs, saved_event

pytestmark = pytest.mark.unit


async def make_parent(tmp_path):
    args = fixture_inputs(tmp_path)
    threads = json.loads(args.threads.read_text())
    threads["messages"].append(saved_event("$later", BASE + 20000, text="A later fact"))
    args.threads.write_text(json.dumps(threads) + "\n")
    index = json.loads(args.sessions.read_text())
    index["source_hashes"]["threads.jsonl"] = replay.digest_bytes(
        args.threads.read_bytes()
    )
    session = index["sessions"][0]
    session["candidate_events"].append({"event_id": "$later"})
    session["last_anchor_ms"] = BASE + 20000
    args.sessions.write_text(json.dumps(index))
    prepared = replay.prepare(args)
    plan = json.loads((args.output / "plan.json").read_text())
    output = tmp_path / "parent-execution"
    output.mkdir()
    repository = EscalationRepository(str(output / "replay.db"))
    await repository.initialize()
    service = EscalationService(
        repository, None, None, None, NS(ESCALATION_CLAIM_TTL_MINUTES=30)
    )
    now = datetime.now(timezone.utc)
    trial = ContextTrial(
        "synthetic-replay",
        ("!synthetic:example.org",),
        "!staff:example.org",
        now - timedelta(minutes=1),
        now + timedelta(hours=1),
        0,
        budget_nanodollars=10_000_000_000,
        daily_budget_nanodollars=10_000_000_000,
        input_nanodollars_per_token=10000,
        output_nanodollars_per_token=20000,
        model=plan["model"],
        max_output_tokens=1000,
    )
    coordinator = StaffConversationCoordinator(
        service, trial.trial_id, first_response_delay_seconds=10
    )
    turn = ConversationTurn(
        "!synthetic:example.org", "$question", "requester", BASE, "A synthetic question"
    )
    intake = await coordinator.ingest(turn, now_ms=BASE)
    snapshot = await coordinator.snapshot(intake.case_id, now_ms=BASE + 10000)
    await coordinator.claim(snapshot)
    store = ContextTrialStore(str(output / "replay.db"), trial)
    assert (
        store.reserve_call(
            intake.case_id,
            kind="gate",
            call_id=snapshot.version,
            input_tokens_bound=1000,
        )
        is None
    )
    usage = {"prompt_tokens": 10, "completion_tokens": 2}
    assert store.settle_call(
        intake.case_id, kind="gate", call_id=snapshot.version, usage=usage
    )
    await coordinator.finish(snapshot, uncertain=True)
    raw = {
        "category": "already_answered",
        "selected_event_ids": ["$question"],
        "request_summary": "Synthetic answered request",
        "material_change": False,
        "request_resolved": False,
        "resolution_event_id": None,
        "reason": "x" * 503,
    }
    call = {
        "case_id": intake.case_id,
        "kind": "gate",
        "call_id": snapshot.version,
        "virtual_time_ms": BASE + 10000,
        "status": "started_or_uncertain",
        "model": plan["model"],
    }
    failure = {
        "case_id": intake.case_id,
        "virtual_time_ms": BASE + 10000,
        "kind": "gate_or_draft",
        "reason": "invalid_conversation_gate",
        "raw_output": json.dumps(raw),
        "usage": usage,
    }
    for name, rows in (
        ("call-intents.jsonl", [call]),
        ("gates.jsonl", []),
        ("drafts.jsonl", []),
        ("failures.jsonl", [failure]),
    ):
        (output / name).write_text("".join(json.dumps(row) + "\n" for row in rows))
    replay.write_private(
        output / "execution-intent.json",
        {
            "approved_plan_sha256": prepared["plan_sha256"],
            "started_at": now.isoformat(),
            "trial_descriptor": json.loads(trial.descriptor()),
        },
    )
    replay.write_private(
        output / "result.json",
        {
            "status": "stopped",
            "stopped_reason": "invalid_conversation_gate",
            "provider_invocations_started_or_uncertain": 1,
            "formed_cases": [{"case_id": intake.case_id}],
            "capacity_limited_snapshots": [],
            "chronological_coverage": {
                "processed_observed_events": 1,
                "planned_observed_events": 2,
                "planned_final_virtual_time_ms": BASE + 30000,
                "last_processed_virtual_time_ms": BASE + 10000,
            },
        },
    )
    return (
        NS(
            parent_plan=args.output / "plan.json",
            parent_execution=output,
            original_code_root=Path(replay.__file__).resolve().parents[1],
            output=tmp_path / "continuation",
        ),
        snapshot,
        trial,
    )


def test_preparation_reconciles_copy_without_changing_parent_or_spend(tmp_path):
    args, snapshot, trial = asyncio.run(make_parent(tmp_path))
    before = replay.digest_bytes((args.parent_execution / "replay.db").read_bytes())
    result = recovery.prepare(args)
    assert result["provider_calls"] == 0
    assert result["original_absolute_cutoff"] == trial.end_at.isoformat()
    assert (
        replay.digest_bytes((args.parent_execution / "replay.db").read_bytes())
        == before
    )
    assert recovery.receipts(args.output / "prepared-state.db") == recovery.receipts(
        args.parent_execution / "replay.db"
    )
    manifest, parent = recovery.approved_manifest(
        args.output / "manifest.json", result["manifest_sha256"]
    )
    assert manifest["parent_call_ids"] == [snapshot.version]
    with closing(sqlite3.connect(args.output / "prepared-state.db")) as db:
        md = json.loads(
            db.execute("SELECT channel_metadata FROM escalations").fetchone()[0]
        )
    assert md["conversation_gate"]["category"] == "already_answered"
    assert md["conversation_gate"]["reason"] == "x" * 503
    assert md["conversation_delivery_uncertain"] is False
    assert md["conversation_last_gate_revision"] == snapshot.revision
    assert md["conversation_gate_recovery"]["provider_calls"] == 0


def test_parent_uncertain_receipt_refuses_preparation(tmp_path):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    with closing(sqlite3.connect(args.parent_execution / "replay.db")) as db, db:
        db.execute("UPDATE matrix_context_trial_spend SET status='uncertain'")
    with pytest.raises(ValueError, match="uncertain"):
        recovery.prepare(args)
    assert not args.output.exists()


def test_continuation_rejects_prior_call_id_before_any_adapter_or_provider(tmp_path):
    args, snapshot, trial = asyncio.run(make_parent(tmp_path))
    prepared = recovery.prepare(args)
    manifest, parent = recovery.approved_manifest(
        args.output / "manifest.json", prepared["manifest_sha256"]
    )
    calls = recovery.ContinuationCalls(
        parent["plan"],
        None,
        ContextTrialStore(str(args.output / "prepared-state.db"), trial),
        args.output,
        manifest,
        parent["intent"]["started_at"],
    )
    assert calls.calls == 1
    with pytest.raises(RuntimeError, match="must_not_be_retried"):
        calls.adapter(snapshot, kind="gate", virtual_time_ms=BASE + 10000)
    assert calls.calls == 1


def test_new_explicit_approval_required_before_reading_or_client_creation(tmp_path):
    with pytest.raises(ValueError, match="NEW owner approval"):
        recovery.execute(
            NS(
                owner_approved=False,
                approve_manifest_sha256=None,
                manifest=tmp_path / "absent",
            )
        )
