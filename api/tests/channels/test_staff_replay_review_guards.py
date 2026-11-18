"""Offline adverse-path tests for approved replay bytes and continuation ownership."""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from app.channels.staff_assist.context_trial import ContextTrialStore
from app.channels.staff_assist.staff_context import StaffContextService
from app.scripts import replay_staff_context as replay
from app.scripts import replay_staff_context_continuation as recovery

from tests.channels.test_context_spend import wrapper
from tests.channels.test_staff_replay import fixture_inputs
from tests.channels.test_staff_replay_continuation import make_parent
from tests.channels.test_staff_replay_independent import (
    ROOM,
    FakeCalls,
    inputs,
    message,
    plan,
)

pytestmark = pytest.mark.unit


def prepared(tmp_path):
    args = fixture_inputs(tmp_path)
    result = replay.prepare(args)
    plan, inputs = replay.approved_plan(
        args.output / "plan.json", result["plan_sha256"]
    )
    return args, result, plan, inputs


def test_jsonl_roundtrip_keeps_unicode_line_separator_in_one_record(tmp_path):
    path = tmp_path / "events.jsonl"
    record = {"reason": "part one\u2028part two"}
    replay.append_private(path, record)
    replay.append_private(path, {"reason": "next"})
    assert replay.read_jsonl(path) == [record, {"reason": "next"}]


def test_inputs_parse_exact_verified_buffers_even_if_export_is_replaced(
    tmp_path, monkeypatch
):
    args, _, plan, _ = prepared(tmp_path)
    original = Path.read_bytes
    seen = []

    def swap_after_read(path):
        data = original(path)
        seen.append(path)
        if path == args.threads:
            path.write_text('{"case_id":1,"messages":[]}\n')
        return data

    monkeypatch.setattr(Path, "read_bytes", swap_after_read)
    verified = replay.load_inputs(plan["sources"])
    assert len(verified["threads"][1]["messages"]) == 1
    assert seen.count(args.threads) == 1


def test_verified_examples_survive_file_change_after_approval(tmp_path):
    args, _, _, inputs = prepared(tmp_path)
    (args.data_dir / "staff-context-examples.json").write_text(
        '[{"reply":"REPLACEMENT"}]'
    )
    service = StaffContextService(
        None, data_dir=args.data_dir, verified_examples=inputs["examples_snapshot"]
    )
    assert service.examples == [{"reply": "Which version are you using?"}]
    assert "REPLACEMENT" not in json.dumps(service.examples)
    calls = FakeCalls(tmp_path / "verified-replay.db")
    result = asyncio.run(replay.replay(plan(tmp_path), inputs, tmp_path, calls))
    assert result["stopped_reason"] is None
    note = next(payload for kind, _, payload in calls.requests if kind == "note")
    assert note["style_examples"] == service.examples


@pytest.mark.parametrize(
    "field,value",
    [("input_usd_per_million", "10.0001"), ("budget_usd", "1.0000000001")],
)
def test_unrepresentable_ledger_amount_refused_before_plan(tmp_path, field, value):
    args = fixture_inputs(tmp_path)
    setattr(args, field, value)
    with pytest.raises(ValueError, match="decimal amounts"):
        replay.prepare(args)
    assert not args.output.exists()


def test_representable_rate_and_runtime_policy_are_pinned(tmp_path):
    args = fixture_inputs(tmp_path)
    args.input_usd_per_million = "10.000"
    replay.prepare(args)
    plan = json.loads((args.output / "plan.json").read_text())
    assert "prompts/runtime_policy.py" in plan["code_sha256"]


def test_manifest_is_parsed_from_the_single_approved_read(tmp_path, monkeypatch):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    result = recovery.prepare(args)
    manifest_path = args.output / "manifest.json"
    original = Path.read_text
    original_bytes = Path.read_bytes
    reads = 0

    def read_bytes_once(path):
        nonlocal reads
        if path == manifest_path:
            reads += 1
            assert reads == 1, "manifest bytes were read again after approval check"
        return original_bytes(path)

    def refuse_second_parse(path, *a, **k):
        if path == manifest_path:
            pytest.fail("manifest was read again after its digest check")
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "read_text", refuse_second_parse)
    monkeypatch.setattr(Path, "read_bytes", read_bytes_once)
    recovery.approved_manifest(manifest_path, result["manifest_sha256"])
    assert reads == 1


def test_execution_copy_is_verified_and_claim_survives_copied_manifest(
    tmp_path, monkeypatch
):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    result = recovery.prepare(args)
    import openai

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **k: pytest.fail("provider constructed before exact DB verification"),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-never-used")
    original = shutil.copyfile

    def corrupted_copy(source, target, *a, **k):
        value = original(source, target, *a, **k)
        if Path(target).name == "replay.db":
            with Path(target).open("ab") as stream:
                stream.write(b"different copied ledger")
        return value

    monkeypatch.setattr(shutil, "copyfile", corrupted_copy)
    execute_args = NS(
        owner_approved=True,
        approve_manifest_sha256=result["manifest_sha256"],
        manifest=args.output / "manifest.json",
    )
    with pytest.raises(ValueError, match="Copied continuation ledger changed"):
        recovery.execute(execute_args)
    moved = tmp_path / "copied-approval"
    moved.mkdir()
    original(execute_args.manifest, moved / "manifest.json")
    execute_args.manifest = moved / "manifest.json"
    with pytest.raises(FileExistsError):
        recovery.execute(execute_args)
    assert not (moved / "execution").exists()


def test_real_replay_first_gate_failure_has_optional_empty_logs_and_stop_clock(
    tmp_path,
):
    args, _, trial = asyncio.run(make_parent(tmp_path))
    plan = json.loads(args.parent_plan.read_text())
    actual = tmp_path / "actual-parent"
    actual.mkdir()
    store = ContextTrialStore(str(actual / "replay.db"), trial)
    llm = wrapper(store).llm
    llm.invoke.return_value = NS(
        content=json.dumps(
            {
                "category": "invalid_category",
                "selected_event_ids": ["$question"],
                "request_summary": "Synthetic",
                "material_change": False,
                "reason": "Invalid result",
            }
        ),
        usage={"prompt_tokens": 10, "completion_tokens": 2},
    )
    calls = replay.ReplayCalls(plan, llm, store, actual)
    result = asyncio.run(
        replay.replay(plan, replay.load_inputs(plan["sources"]), actual, calls)
    )
    assert result["stopped_reason"] == "invalid_conversation_gate"
    assert not (actual / "gates.jsonl").exists()
    assert not (actual / "drafts.jsonl").exists()
    replay.write_private(actual / "result.json", result)
    shutil.copyfile(
        args.parent_execution / "execution-intent.json",
        actual / "execution-intent.json",
    )
    parent = recovery.validate_parent(args.parent_plan, actual, args.original_code_root)
    assert parent["pins"]["gates.jsonl"]["sha256"] is None
    assert parent["pins"]["drafts.jsonl"]["sha256"] is None
    assert parent["cursor"] == 1
    assert (
        result["chronological_coverage"]["last_processed_virtual_time_ms"]
        == parent["failure"]["virtual_time_ms"]
    )


@pytest.mark.asyncio
async def test_changed_admission_is_drained_before_later_due_request(tmp_path):
    data = inputs()
    first = data["index"]["sessions"][0]
    first.update(
        last_anchor_ms=21000,
        candidate_events=[{"event_id": "$root"}, {"event_id": "$follow"}],
    )
    first["anchors"][1]["origin_server_ts"] = 21000
    data["events"][(ROOM, "$follow")] = message(
        "$follow", "The startup error still happens", 21000
    )
    second_event = message("$other", "The network connection fails", 26000)
    second_event["sender"] = "other-requester"
    data["events"][(ROOM, "$other")] = second_event
    data["cases"][103] = {"id": 103, "channel_metadata": {}}
    data["index"]["sessions"].append(
        {
            **first,
            "session_id": "other",
            "requester_id": "other-requester",
            "case_ids": [103],
            "first_anchor_ms": 26000,
            "last_anchor_ms": 26000,
            "candidate_events": [{"event_id": "$other"}],
            "anchors": [
                {"case_id": 103, "event_id": "$other", "origin_server_ts": 26000}
            ],
        }
    )
    calls = FakeCalls(tmp_path / "replay.db")
    result = await replay.replay(plan(tmp_path), data, tmp_path, calls)
    assert result["stopped_reason"] is None
    gate_times = [at for kind, at, _ in calls.requests if kind == "gate"]
    assert gate_times == [11000, 31000, 31000, 36000]


def test_copied_original_plan_cannot_reset_its_execution_claim(tmp_path, monkeypatch):
    args, prepared_result, frozen, _ = prepared(tmp_path)
    replay.write_private(
        Path(frozen["execution_claim"]), {"status": "already_attempted"}
    )
    copied = tmp_path / "copied-plan"
    copied.mkdir()
    shutil.copyfile(args.output / "plan.json", copied / "plan.json")
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-never-used")
    monkeypatch.setattr(
        openai, "OpenAI", lambda **kw: pytest.fail("Repeated approval reached provider")
    )
    with pytest.raises(FileExistsError):
        replay.execute(
            NS(
                owner_approved=True,
                approve_plan_sha256=prepared_result["plan_sha256"],
                plan=copied / "plan.json",
            )
        )
    assert not (copied / "execution").exists()


def test_private_jsonl_writer_explicitly_uses_utf8(tmp_path, monkeypatch):
    original = replay.os.fdopen
    seen = []

    def check_encoding(*args, **kwargs):
        seen.append(kwargs.get("encoding"))
        return original(*args, **kwargs)

    monkeypatch.setattr(replay.os, "fdopen", check_encoding)
    record = {"reason": "café\u2028next"}
    replay.append_private(tmp_path / "unicode.jsonl", record)
    assert seen == ["utf-8"]
    assert replay.read_jsonl(tmp_path / "unicode.jsonl") == [record]


def test_preparation_state_uses_validated_parent_rows_not_second_path_read(
    tmp_path, monkeypatch
):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    original_validate = recovery.validate_parent
    original_verify = recovery.verify_pins
    path = args.parent_execution / "gates.jsonl"
    original = path.read_bytes()

    def swap_after_validation(*a, **k):
        parent = original_validate(*a, **k)
        path.write_text('{"reply":"UNAPPROVED REPLACEMENT"}\n')
        return parent

    def restore_before_final_verification(pins):
        path.write_bytes(original)
        return original_verify(pins)

    monkeypatch.setattr(recovery, "validate_parent", swap_after_validation)
    monkeypatch.setattr(recovery, "verify_pins", restore_before_final_verification)
    recovery.prepare(args)
    state = json.loads((args.output / "continuation-state.json").read_bytes())
    assert len(state["gates"]) == 1  # only the saved-response reconciliation
    assert "UNAPPROVED" not in json.dumps(state)


def test_parent_drift_between_manifest_check_and_validation_refuses(
    tmp_path, monkeypatch
):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    result = recovery.prepare(args)
    original = recovery.validate_parent

    def replace_after_manifest_check(*a, **kwargs):
        assert kwargs["expected_pins"]
        (args.parent_execution / "gates.jsonl").write_bytes(b"\n")
        return original(*a, **kwargs)

    monkeypatch.setattr(recovery, "validate_parent", replace_after_manifest_check)
    with pytest.raises(ValueError, match="Continuation input changed"):
        recovery.approved_manifest(
            args.output / "manifest.json", result["manifest_sha256"]
        )


def test_copied_parent_directories_share_original_execution_claim(
    tmp_path, monkeypatch
):
    args, _, _ = asyncio.run(make_parent(tmp_path))
    first = recovery.prepare(args)
    copied_parent = tmp_path / "copied-parent"
    shutil.copytree(args.parent_execution, copied_parent)
    copied_args = NS(**vars(args))
    copied_args.parent_execution = copied_parent
    copied_args.output = tmp_path / "second-preparation"
    second = recovery.prepare(copied_args)
    first_manifest = json.loads((args.output / "manifest.json").read_bytes())
    second_manifest = json.loads((copied_args.output / "manifest.json").read_bytes())
    assert (
        first_manifest["original_execution_identity"]
        == second_manifest["original_execution_identity"]
    )
    assert first_manifest["continuation_claim"] == second_manifest["continuation_claim"]
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-never-used")
    import openai

    monkeypatch.setattr(
        openai, "OpenAI", lambda **kw: pytest.fail("provider was constructed")
    )
    original_copy = shutil.copyfile

    def corrupt_ledger(src, dst, *a, **k):
        result = original_copy(src, dst, *a, **k)
        if Path(dst).name == "replay.db":
            with Path(dst).open("ab") as stream:
                stream.write(b"changed")
        return result

    monkeypatch.setattr(shutil, "copyfile", corrupt_ledger)
    with pytest.raises(ValueError, match="Copied continuation ledger changed"):
        recovery.execute(
            NS(
                owner_approved=True,
                approve_manifest_sha256=first["manifest_sha256"],
                manifest=args.output / "manifest.json",
            )
        )
    with pytest.raises(FileExistsError):
        recovery.execute(
            NS(
                owner_approved=True,
                approve_manifest_sha256=second["manifest_sha256"],
                manifest=copied_args.output / "manifest.json",
            )
        )
    assert not (copied_args.output / "execution").exists()


@pytest.mark.asyncio
async def test_many_changed_admissions_drain_iteratively_without_stack_growth(
    tmp_path, monkeypatch
):
    total = 1100
    state = {"count": 0, "finished": 0}
    snapshot = NS(
        case_id=1,
        version="v",
        kind="admission",
        turns=[],
        room_id=ROOM,
        requester_id="requester",
        last_requester_at_ms=0,
    )

    class Coordinator:
        def __init__(self, *a, **k):
            pass

        async def due(self, **k):
            assert state["finished"] == state["count"]
            return [snapshot] if state["count"] < total else []

        async def snapshot(self, *a, **k):
            return snapshot

        async def claim(self, *a):
            return True

        def admission_call_guard(self, *a):
            return None

        async def record_admission(self, *a, **k):
            state["count"] += 1
            return NS(changed=True, created=False)

        async def finish(self, *a, **k):
            state["finished"] += 1

    class Gate:
        def __init__(self, *a):
            self.usage = {}

        def classify(self, *a):
            return NS(model_dump=lambda: {"relation": "same_request"})

    monkeypatch.setattr(replay, "StaffConversationCoordinator", Coordinator)
    monkeypatch.setattr(replay, "RequestAdmissionService", Gate)
    monkeypatch.setattr(replay, "ordered_turns", lambda *a: ([], 1000000, []))
    monkeypatch.setattr(replay, "append_private", lambda *a: None)
    calls = FakeCalls(tmp_path / "many.db")
    result = await replay.replay(plan(tmp_path), inputs(), tmp_path, calls)
    assert result["stopped_reason"] is None
    assert result["gate_calls_recorded"] == total
    assert state == {"count": total, "finished": total}
