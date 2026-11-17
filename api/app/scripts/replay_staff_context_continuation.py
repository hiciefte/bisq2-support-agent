"""Prepare an explicitly approved suffix of a stopped private replay.

Original receipts are immutable. Offline preparation verifies the completed
failure, reconciles its saved response in a copy and binds the exact remaining
stream. Execution requires a separate owner-approved manifest; no old call is
retried and neither the original budget nor its absolute cutoff is reset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.channels.staff_assist.context_conversation import StaffConversationCoordinator
from app.channels.staff_assist.context_gate import RequestGateService
from app.channels.staff_assist.context_trial import ContextTrial, ContextTrialStore
from app.scripts.replay_staff_context import (
    ReplayCalls,
    append_private,
    digest_bytes,
    json_bytes,
    load_inputs,
    model_code_hashes,
    ordered_turns,
    read_jsonl,
    render_report,
    replay,
    write_private,
)
from app.services.escalation.escalation_repository import EscalationRepository
from app.services.escalation.escalation_service import EscalationService

PARENT_FILES = (
    "replay.db",
    "gates.jsonl",
    "drafts.jsonl",
    "call-intents.jsonl",
    "failures.jsonl",
    "execution-intent.json",
    "result.json",
)


def file_pin(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": digest_bytes(path.read_bytes())}


def verify_pins(pins: dict[str, dict[str, str]]) -> None:
    for pin in pins.values():
        if digest_bytes(Path(pin["path"]).read_bytes()) != pin["sha256"]:
            raise ValueError("Continuation input changed")


def continuation_code_hashes() -> dict[str, str]:
    return {
        **model_code_hashes(),
        "scripts/replay_staff_context_continuation.py": digest_bytes(
            Path(__file__).read_bytes()
        ),
    }


def restore_trial(descriptor: dict[str, Any]) -> ContextTrial:
    values = dict(descriptor)
    if values.pop("version", None) != 2:
        raise ValueError("Continuation requires the original spend-bound descriptor")
    values["max_cases"] = 0
    values["source_rooms"] = tuple(values["source_rooms"])
    for key in ("start_at", "end_at"):
        values[key] = datetime.fromisoformat(values[key])
    trial = ContextTrial(**values)
    if json.loads(trial.descriptor()) != descriptor:
        raise ValueError("Original trial descriptor cannot be preserved")
    return trial


def receipts(database: Path) -> list[dict[str, Any]]:
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM matrix_context_trial_spend ORDER BY started_at,escalation_id,kind,call_id"
            )
        ]


def validate_parent(
    parent_plan: Path, parent_execution: Path, original_code_root: Path
) -> dict[str, Any]:
    plan = json.loads(parent_plan.read_text())
    inputs = load_inputs(plan["sources"])
    for relative, expected in plan["code_sha256"].items():
        if digest_bytes((original_code_root / relative).read_bytes()) != expected:
            raise ValueError("Original approved source no longer matches its plan")
    pins = {name: file_pin(parent_execution / name) for name in PARENT_FILES}
    pins["parent_plan"] = file_pin(parent_plan)
    for suffix in ("-wal", "-journal"):
        path = Path(str(parent_execution / "replay.db") + suffix)
        if path.exists() and path.stat().st_size:
            raise ValueError("Parent database has an active or unreconciled journal")
    intent = json.loads((parent_execution / "execution-intent.json").read_text())
    if intent["approved_plan_sha256"] != pins["parent_plan"]["sha256"]:
        raise ValueError("Parent approval receipt does not match plan")
    trial = restore_trial(intent["trial_descriptor"])
    rows = receipts(parent_execution / "replay.db")
    if not rows or any(
        row["status"] != "settled" or row["trial_id"] != trial.trial_id for row in rows
    ):
        raise ValueError("Parent has uncertain, overrun or unrelated model receipts")
    calls = read_jsonl(parent_execution / "call-intents.jsonl")

    def keys(values: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
        return [
            (
                row["case_id"] if "case_id" in row else row["escalation_id"],
                row["kind"],
                row["call_id"],
            )
            for row in values
        ]

    if len(set(keys(calls))) != len(calls) or set(keys(calls)) != set(keys(rows)):
        raise ValueError("Parent call intents and settled receipts do not reconcile")
    gate_rows = read_jsonl(parent_execution / "gates.jsonl")
    draft_rows = read_jsonl(parent_execution / "drafts.jsonl")
    completed_keys = {
        (row["case_id"], "gate", row["snapshot_version"]) for row in gate_rows
    }
    completed_keys.update(
        (row["case_id"], row["kind"], row["snapshot_version"])
        for row in draft_rows
        if row.get("model_called")
    )
    if completed_keys != set(keys(rows)) - {keys([calls[-1]])[0]}:
        raise ValueError(
            "Parent completed-output records do not reconcile with receipts"
        )
    result = json.loads((parent_execution / "result.json").read_text())
    if (
        result.get("status") != "stopped"
        or result.get("stopped_reason") != "invalid_conversation_gate"
    ):
        raise ValueError(
            "Parent terminal result is not the approved gate-validation stop"
        )
    if result["provider_invocations_started_or_uncertain"] != len(rows):
        raise ValueError("Parent call count does not reconcile")
    failures = read_jsonl(parent_execution / "failures.jsonl")
    if len(failures) != 1 or failures[0]["reason"] != "invalid_conversation_gate":
        raise ValueError("Only one known completed gate-validation stop is supported")
    failure = failures[0]
    last = calls[-1]
    if (
        last["kind"] != "gate"
        or last["case_id"] != failure["case_id"]
        or last["virtual_time_ms"] != failure["virtual_time_ms"]
    ):
        raise ValueError("Saved failure is not the exact last gate attempt")
    receipt = next(row for row in rows if keys([row])[0] == keys([last])[0])
    usage = failure.get("usage") or {}
    if (
        usage.get("prompt_tokens") != receipt["input_tokens"]
        or usage.get("completion_tokens") != receipt["output_tokens"]
    ):
        raise ValueError("Saved response usage differs from settled receipt")
    ordered, end_ms, _ = ordered_turns(
        inputs, int(plan["first_response_delay_seconds"] * 1000)
    )
    coverage = result["chronological_coverage"]
    cursor = coverage["processed_observed_events"]
    if (
        type(cursor) is not int
        or not 0 < cursor < len(ordered)
        or coverage["planned_observed_events"] != len(ordered)
        or coverage["planned_final_virtual_time_ms"] != end_ms
    ):
        raise ValueError("Invalid parent chronological boundary")
    if (
        ordered[cursor - 1].timestamp_ms != coverage["last_processed_virtual_time_ms"]
        or not ordered[cursor - 1].timestamp_ms
        < failure["virtual_time_ms"]
        < ordered[cursor].timestamp_ms
    ):
        raise ValueError("Parent did not stop between the verified event groups")
    with closing(
        sqlite3.connect(
            (parent_execution / "replay.db").resolve().as_uri() + "?mode=ro", uri=True
        )
    ) as db:
        descriptor = db.execute(
            "SELECT descriptor FROM matrix_context_trials WHERE trial_id=?",
            (trial.trial_id,),
        ).fetchone()
        if not descriptor or descriptor[0] != trial.descriptor():
            raise ValueError("Stored descriptor differs from execution receipt")
        uncertain = [
            row[0]
            for row in db.execute(
                "SELECT id FROM escalations WHERE json_extract(channel_metadata,'$.conversation_delivery_uncertain')=1"
            )
        ]
        if uncertain != [failure["case_id"]]:
            raise ValueError(
                "Other case uncertainty requires independent reconciliation"
            )
    return {
        "plan": plan,
        "inputs": inputs,
        "pins": pins,
        "trial": trial,
        "receipts": rows,
        "calls": calls,
        "result": result,
        "failure": failure,
        "last_call": last,
        "cursor": cursor,
        "prefix_sha256": digest_bytes(
            json_bytes([asdict(turn) for turn in ordered[:cursor]])
        ),
        "remaining_stream_sha256": digest_bytes(
            json_bytes([asdict(turn) for turn in ordered[cursor:]])
        ),
        "intent": intent,
    }


async def reconcile_saved_gate(
    database: Path, parent: dict[str, Any]
) -> dict[str, Any]:
    repository = EscalationRepository(str(database))
    service = EscalationService(
        repository, None, None, None, SimpleNamespace(ESCALATION_CLAIM_TTL_MINUTES=30)
    )
    coordinator = StaffConversationCoordinator(
        service,
        parent["trial"].trial_id,
        first_response_delay_seconds=parent["plan"]["first_response_delay_seconds"],
    )
    failure = parent["failure"]
    snapshot = await coordinator.snapshot(
        failure["case_id"], now_ms=failure["virtual_time_ms"]
    )
    if snapshot.version != parent["last_call"]["call_id"]:
        raise ValueError("Saved failure snapshot no longer matches exact paid receipt")

    class SavedOnly:
        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(
                content=failure["raw_output"], usage=failure["usage"]
            )

    decision = RequestGateService(SavedOnly()).classify(snapshot)
    if (
        decision.category != "already_answered"
        or decision.request_resolved
        or snapshot.should_draft(decision)
    ):
        raise ValueError("Saved decision would require broader recovery authority")
    if not await coordinator.record_gate(snapshot, decision):
        raise ValueError("Saved decision could not reconcile exact copied revision")
    await coordinator.finish(snapshot, uncertain=False)
    linkage = {
        "kind": "saved_completed_gate_reconciliation",
        "case_id": snapshot.case_id,
        "snapshot_version": snapshot.version,
        "virtual_time_ms": failure["virtual_time_ms"],
        "input_event_ids": [turn.event_id for turn in snapshot.turns],
        "decision": decision.model_dump(),
        "usage": failure["usage"],
        "provider_calls": 0,
        "parent_failure_sha256": parent["pins"]["failures.jsonl"]["sha256"],
        "raw_response_sha256": digest_bytes(failure["raw_output"].encode()),
        "parent_call_id": parent["last_call"]["call_id"],
    }
    await coordinator._change(snapshot.case_id, conversation_gate_recovery=linkage)
    return linkage


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    parent = validate_parent(
        args.parent_plan, args.parent_execution, args.original_code_root
    )
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    database = args.output / "prepared-state.db"
    shutil.copyfile(args.parent_execution / "replay.db", database)
    os.chmod(database, 0o600)
    linkage = asyncio.run(reconcile_saved_gate(database, parent))
    if receipts(database) != parent["receipts"]:
        raise ValueError("Offline reconciliation altered spend receipts")
    state = {
        "processed_event_count": parent["cursor"],
        "last_time": parent["result"]["chronological_coverage"][
            "last_processed_virtual_time_ms"
        ],
        "formed_cases": parent["result"]["formed_cases"],
        "drafts": read_jsonl(args.parent_execution / "drafts.jsonl"),
        "gates": [*read_jsonl(args.parent_execution / "gates.jsonl"), linkage],
        "capacity_limited_snapshots": parent["result"].get(
            "capacity_limited_snapshots", []
        ),
        "invalid_gate_outcomes": parent["result"].get("invalid_gate_outcomes", []),
    }
    write_private(args.output / "continuation-state.json", state)
    write_private(args.output / "reconciled-gate.json", linkage)
    used = sum(row["actual_nanodollars"] for row in parent["receipts"])
    if (
        used >= parent["trial"].budget_nanodollars
        or len(parent["receipts"]) >= parent["plan"]["max_model_calls"]
    ):
        raise ValueError(
            "Original cumulative budget or call cap leaves no continuation allowance"
        )
    manifest = {
        "schema_version": 1,
        "status": "prepared_pending_new_owner_approval",
        "parent_plan": str(args.parent_plan.resolve()),
        "parent_execution": str(args.parent_execution.resolve()),
        "original_code_root": str(args.original_code_root.resolve()),
        "parent_pins": parent["pins"],
        "prepared_pins": {
            name: file_pin(args.output / name)
            for name in (
                "prepared-state.db",
                "continuation-state.json",
                "reconciled-gate.json",
            )
        },
        "code_sha256": continuation_code_hashes(),
        "trial_descriptor": json.loads(parent["trial"].descriptor()),
        "parent_call_ids": sorted({row["call_id"] for row in parent["receipts"]}),
        "parent_call_count": len(parent["receipts"]),
        "cumulative_call_cap": parent["plan"]["max_model_calls"],
        "accounted_nanodollars_before_continuation": used,
        "remaining_budget_nanodollars": parent["trial"].budget_nanodollars - used,
        "processed_event_count": parent["cursor"],
        "prefix_sha256": parent["prefix_sha256"],
        "remaining_stream_sha256": parent["remaining_stream_sha256"],
        "original_absolute_cutoff": parent["trial"].end_at.isoformat(),
        "no_existing_provider_call_retry": True,
        "provider_calls_during_preparation": 0,
    }
    verify_pins(parent["pins"])
    write_private(args.output / "manifest.json", manifest)
    return {
        "manifest": str(args.output / "manifest.json"),
        "manifest_sha256": digest_bytes((args.output / "manifest.json").read_bytes()),
        "parent_calls": len(parent["receipts"]),
        "remaining_calls": parent["plan"]["max_model_calls"] - len(parent["receipts"]),
        "remaining_budget_nanodollars": manifest["remaining_budget_nanodollars"],
        "original_absolute_cutoff": manifest["original_absolute_cutoff"],
        "provider_calls": 0,
    }


class ContinuationCalls(ReplayCalls):
    def __init__(
        self,
        plan: dict[str, Any],
        llm: Any,
        store: ContextTrialStore,
        output: Path,
        manifest: dict[str, Any],
        original_started_at: str,
    ):
        super().__init__(plan, llm, store, output)
        self.calls = manifest["parent_call_count"]
        self.parent_call_ids = set(manifest["parent_call_ids"])
        elapsed = (
            datetime.now(timezone.utc) - datetime.fromisoformat(original_started_at)
        ).total_seconds()
        self.started = time.monotonic() - max(0, elapsed)

    def adapter(self, snapshot: Any, *, kind: str, virtual_time_ms: int):
        if snapshot.version in self.parent_call_ids:
            raise RuntimeError("parent_provider_call_must_not_be_retried")
        return super().adapter(snapshot, kind=kind, virtual_time_ms=virtual_time_ms)


def approved_manifest(
    path: Path, expected: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if digest_bytes(path.read_bytes()) != expected:
        raise ValueError("New continuation approval hash does not match")
    manifest = json.loads(path.read_text())
    if continuation_code_hashes() != manifest["code_sha256"]:
        raise ValueError("Continuation source changed")
    verify_pins(manifest["parent_pins"])
    verify_pins(manifest["prepared_pins"])
    parent = validate_parent(
        Path(manifest["parent_plan"]),
        Path(manifest["parent_execution"]),
        Path(manifest["original_code_root"]),
    )
    for field in ("prefix_sha256", "remaining_stream_sha256"):
        if manifest[field] != parent[field]:
            raise ValueError("Frozen chronological suffix changed")
    if manifest["trial_descriptor"] != json.loads(
        parent["trial"].descriptor()
    ) or manifest["parent_call_count"] != len(parent["receipts"]):
        raise ValueError("Cumulative continuation limits changed")
    derived = {
        "parent_call_ids": sorted({row["call_id"] for row in parent["receipts"]}),
        "cumulative_call_cap": parent["plan"]["max_model_calls"],
        "processed_event_count": parent["cursor"],
        "accounted_nanodollars_before_continuation": sum(
            row["actual_nanodollars"] for row in parent["receipts"]
        ),
        "original_absolute_cutoff": parent["trial"].end_at.isoformat(),
    }
    derived["remaining_budget_nanodollars"] = (
        parent["trial"].budget_nanodollars
        - derived["accounted_nanodollars_before_continuation"]
    )
    if any(manifest[key] != value for key, value in derived.items()):
        raise ValueError("Derived continuation scope does not match parent")
    if (
        receipts(Path(manifest["prepared_pins"]["prepared-state.db"]["path"]))
        != parent["receipts"]
    ):
        raise ValueError("Prepared continuation changed parent spend ledger")
    state = json.loads(
        Path(manifest["prepared_pins"]["continuation-state.json"]["path"]).read_text()
    )
    if (
        state["processed_event_count"] != parent["cursor"]
        or state["last_time"]
        != parent["result"]["chronological_coverage"]["last_processed_virtual_time_ms"]
    ):
        raise ValueError("Prepared state changed chronological boundary")
    return manifest, parent


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if not args.owner_approved or not args.approve_manifest_sha256:
        raise ValueError(
            "Continuation requires NEW owner approval and exact manifest hash"
        )
    manifest, parent = approved_manifest(args.manifest, args.approve_manifest_sha256)
    trial = parent["trial"]
    if trial.reason():
        raise ValueError("Original replay window has ended or is not active")
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Existing secret environment must provide OPENAI_API_KEY")
    output = args.manifest.parent / "execution"
    output.mkdir(exist_ok=False, mode=0o700)
    write_private(
        output / "continuation-intent.json",
        {
            "manifest_sha256": args.approve_manifest_sha256,
            "parent_plan_sha256": parent["pins"]["parent_plan"]["sha256"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "original_cutoff": trial.end_at.isoformat(),
            "no_retry_or_second_suffix": True,
        },
    )
    shutil.copyfile(
        manifest["prepared_pins"]["prepared-state.db"]["path"], output / "replay.db"
    )
    os.chmod(output / "replay.db", 0o600)
    for name in ("gates.jsonl", "drafts.jsonl", "call-intents.jsonl"):
        shutil.copyfile(parent["pins"][name]["path"], output / name)
        os.chmod(output / name, 0o600)
    linkage = json.loads(
        Path(manifest["prepared_pins"]["reconciled-gate.json"]["path"]).read_text()
    )
    append_private(output / "gates.jsonl", linkage)
    state = json.loads(
        Path(manifest["prepared_pins"]["continuation-state.json"]["path"]).read_text()
    )
    from app.services.rag.openai_responses import OpenAIResponsesLLMWrapper
    from openai import OpenAI

    plan = parent["plan"]
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url="https://api.openai.com/v1",
        max_retries=0,
        timeout=90.0,
    )
    rate = float(Decimal(plan["input_usd_per_million_ceiling"]) / 1000000)
    llm = OpenAIResponsesLLMWrapper(
        client=client,
        model=plan["model"],
        max_tokens=plan["max_output_tokens"],
        reasoning_effort=plan["reasoning_effort"],
        mcp_url="",
        input_cost_per_token=rate,
        cached_input_cost_per_token=rate,
        cache_write_cost_per_token=rate,
        output_cost_per_token=float(
            Decimal(plan["output_usd_per_million_ceiling"]) / 1000000
        ),
    )
    try:
        store = ContextTrialStore(str(output / "replay.db"), trial)
        calls = ContinuationCalls(
            plan, llm, store, output, manifest, parent["intent"]["started_at"]
        )
        result = asyncio.run(
            replay(plan, parent["inputs"], output, calls, continuation=state)
        )
    finally:
        client.close()
    result["continuation_manifest_sha256"] = args.approve_manifest_sha256
    result["parent_execution_sha256"] = parent["pins"]["result.json"]["sha256"]
    result["saved_response_reconciliation"] = linkage
    from app.scripts.summarize_staff_context import summarize

    result["model_usage_by_kind"] = next(
        (
            row["model_usage_by_kind"]
            for row in summarize(output / "replay.db")
            if row["trial_id"] == trial.trial_id
        ),
        None,
    )
    write_private(output / "result.json", result)
    (output / "REPORT.md").write_text(render_report(result))
    os.chmod(output / "REPORT.md", 0o600)
    return {
        "result": str(output / "result.json"),
        "status": result["status"],
        "cumulative_calls": calls.calls,
        "new_calls": calls.calls - manifest["parent_call_count"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Offline only")
    for name in ("parent-plan", "parent-execution", "original-code-root", "output"):
        prep.add_argument("--" + name, type=Path, required=True)
    run = commands.add_parser(
        "execute", help="New explicitly approved paid suffix only"
    )
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--approve-manifest-sha256")
    run.add_argument("--owner-approved", action="store_true")
    args = parser.parse_args()
    try:
        result = prepare(args) if args.command == "prepare" else execute(args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
