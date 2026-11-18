"""Synthetic offline checks for replay admission, provenance and reporting."""

import argparse
import json
from types import SimpleNamespace

import pytest
from app.channels.staff_assist.public_context import PublicContextRequest, StaffEvidence
from app.scripts import replay_staff_context as replay

pytestmark = pytest.mark.unit
BASE = 1_800_000_000_000


def saved_event(event_id, at, text="A synthetic question", **content):
    return {
        "event_id": event_id,
        "sender": "requester",
        "role": "requester",
        "origin_server_ts": at,
        "text": text,
        "original_sanitized_event": {
            "type": "m.room.message",
            "event_id": event_id,
            "sender": "requester",
            "origin_server_ts": at,
            "content": {"msgtype": "m.text", "body": text, **content},
        },
    }


def fixture_inputs(tmp_path):
    room = "!synthetic:example.org"
    cases = [
        {
            "id": 1,
            "channel_metadata": {
                "room_id": room,
                "source_event_id": "$question",
                "evidence_snapshot": [],
            },
        }
    ]
    threads = [{"case_id": 1, "messages": [saved_event("$question", BASE)]}]
    references = {
        "cases": [
            {
                "case_id": 1,
                "comparison_role": "staff",
                "action_summary": "A synthetic action",
            }
        ],
        "focus_case_ids": [1],
        "reference_request_ids": [1],
        "reference_non_request_ids": [2],
        "baseline": {
            "cases": 1,
            "sessions": 1,
            "non_request_model_calls": 0,
            "real_model_calls": 1,
            "limitation_openings": 0,
            "notes_written": 1,
            "provenance": "Synthetic reference",
        },
    }
    for name, data in (("cases", cases), ("threads", threads)):
        (tmp_path / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(row) for row in data) + "\n"
        )
    index = {
        "source_hashes": {
            f"{name}.jsonl": replay.digest_bytes(
                (tmp_path / f"{name}.jsonl").read_bytes()
            )
            for name in ("cases", "threads")
        },
        "natural_case_count": 1,
        "distinct_room_requester_pairs": 1,
        "sessions": [
            {
                "session_id": "synthetic-session",
                "room_id": room,
                "requester_id": "requester",
                "case_ids": [1],
                "first_anchor_ms": BASE,
                "last_anchor_ms": BASE,
                "anchors": [
                    {"case_id": 1, "event_id": "$question", "origin_server_ts": BASE}
                ],
                "candidate_events": [{"event_id": "$question"}],
                "case_window_coverage": {"status": "partial"},
            }
        ],
    }
    (tmp_path / "sessions.json").write_text(json.dumps(index))
    (tmp_path / "references.json").write_text(json.dumps(references))
    (tmp_path / "staff-context-examples.json").write_text(
        json.dumps([{"reply": "Which version are you using?"}])
    )
    return argparse.Namespace(
        cases=tmp_path / "cases.jsonl",
        threads=tmp_path / "threads.jsonl",
        sessions=tmp_path / "sessions.json",
        comparisons=tmp_path / "references.json",
        data_dir=tmp_path,
        output=tmp_path / "prepared",
        model="openai:synthetic-model",
        reasoning_effort="low",
        max_output_tokens=1000,
        input_usd_per_million="10",
        output_usd_per_million="20",
        budget_usd="10",
        daily_budget_usd="10",
        max_model_calls=10,
        maximum_elapsed_seconds=600,
        first_response_delay_seconds=10,
    )


def test_prepare_is_offline_hash_bound_private_and_has_no_after_claim(
    tmp_path, monkeypatch
):
    args = fixture_inputs(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Offline preparation invoked a model")

    monkeypatch.setattr(replay.RequestGateService, "classify", forbidden)
    monkeypatch.setattr(replay.StaffContextService, "preview", forbidden)
    result = replay.prepare(args)
    assert result["paid_calls"] == 0
    plan, _ = replay.approved_plan(args.output / "plan.json", result["plan_sha256"])
    assert plan["estimate"]["absolute_per_call_cost_ceiling_usd"] == "1.02"
    report = json.loads((args.output / "prepared-report.json").read_text())
    assert report["after"]["cases_formed"] is None
    assert report["action_comparisons"][0]["after_action_present"] is None
    assert (args.output / "plan.json").stat().st_mode & 0o777 == 0o600
    assert args.output.stat().st_mode & 0o777 == 0o700
    args.threads.write_text("changed")
    with pytest.raises(ValueError, match="Frozen replay input changed"):
        replay.approved_plan(args.output / "plan.json", result["plan_sha256"])


def test_preparation_never_replaces_existing_plan(tmp_path):
    args = fixture_inputs(tmp_path)
    replay.prepare(args)
    with pytest.raises(FileExistsError):
        replay.prepare(args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("budget_usd", "NaN"),
        ("input_usd_per_million", "0"),
        ("max_model_calls", 0),
        ("maximum_elapsed_seconds", 0),
        ("max_output_tokens", 50000),
        ("first_response_delay_seconds", 0),
    ],
)
def test_invalid_paid_limits_fail_before_writing(tmp_path, field, value):
    args = fixture_inputs(tmp_path)
    setattr(args, field, value)
    with pytest.raises(ValueError):
        replay.prepare(args)
    assert not args.output.exists()


def test_execution_needs_both_explicit_approval_and_hash(tmp_path):
    with pytest.raises(ValueError, match="explicit owner approval"):
        replay.execute(
            SimpleNamespace(
                owner_approved=False, approve_plan_sha256=None, plan=tmp_path / "absent"
            )
        )


def test_evidence_excludes_future_anchors_and_unproved_live_data():
    def source(source_id, kind="faq", **provenance):
        return {
            "id": source_id,
            "title": "Synthetic source",
            "content": "A documented step",
            "kind": kind,
            "url": "http://[REDACTED:private_host]/faq/1",
            "provenance": provenance,
        }

    session = {
        "anchors": [
            {"case_id": 1, "origin_server_ts": BASE},
            {"case_id": 2, "origin_server_ts": BASE + 10000},
        ]
    }
    inputs = {
        "cases": {
            1: {
                "channel_metadata": {
                    "evidence_snapshot": [
                        source(
                            "document",
                            protocol="bisq1",
                            staff_applicability={
                                "status": "explicit_conflict",
                                "requester_product": "bisq2",
                            },
                        ),
                        source("missing_time", kind="live_tool"),
                        source(
                            "future_observation",
                            kind="live_tool",
                            observed_at=BASE + 9000,
                        ),
                    ]
                }
            },
            2: {"channel_metadata": {"evidence_snapshot": [source("future_anchor")]}},
        }
    }
    evidence, coverage = replay.evidence_at(session, BASE + 5000, inputs)
    assert [item.id for item in evidence] == ["document"]
    assert evidence[0].kind == "saved_excerpt"
    assert evidence[0].source_refs == []
    assert evidence[0].provenance["original_kind"] == "faq"
    assert evidence[0].provenance["protocol"] == "bisq1"
    assert (
        evidence[0].provenance["staff_applicability"]["status"] == "explicit_conflict"
    )
    assert coverage["source_case_id"] == 1
    assert len(coverage["excluded"]) == 2


def test_replay_saved_excerpt_cannot_enter_public_audience():
    evidence = StaffEvidence(
        id="saved",
        title="Private saved excerpt",
        content="Synthetic text",
        kind="saved_excerpt",
    )
    with pytest.raises(ValueError, match="staff-only"):
        PublicContextRequest(question="Synthetic question", evidence=[evidence])


def test_native_edit_arrives_as_edit_not_rewritten_historical_message():
    message = saved_event(
        "$edit",
        BASE + 1000,
        text="* changed",
        **{
            "m.new_content": {"body": "changed", "msgtype": "m.text"},
            "m.relates_to": {"rel_type": "m.replace", "event_id": "$original"},
        },
    )
    turn = replay.saved_turn("!synthetic:example.org", message)
    assert turn.timestamp_ms == BASE + 1000
    assert turn.replaces_event_id == "$original"
    assert turn.text == "changed"


def test_gate_predictions_are_not_reference_labels_and_silence_counts(tmp_path):
    args = fixture_inputs(tmp_path)
    prepared = replay.prepare(args)
    plan, inputs = replay.approved_plan(
        args.output / "plan.json", prepared["plan_sha256"]
    )
    references = inputs["comparisons"]
    assert replay._reference_category([2], references) == "non_request"
    assert replay._reference_category([2, 3], references) == "unassessed"
    assert replay._reference_category([1, 3], references) == "request"
    rows = [
        {
            "reference_category": "non_request",
            "model_called": True,
            "rendered": False,
            "reply": "",
            "source_case_ids": [2],
        },
        {
            "reference_category": "unassessed",
            "model_called": True,
            "rendered": True,
            "reply": "Which version are you using?",
            "source_case_ids": [3],
        },
    ]
    report = replay.report_data(plan, inputs, rows, [], pending=False)
    assert report["after"]["model_note_generations"] == 2
    assert report["after"]["non_request_generations"] == 1
    assert report["after"]["reference_assessed_generations"] == 1
    assert report["after"]["reference_unassessed_generations"] == 1
    assert report["after"]["non_request_share_on_assessed_subset"] == 1
    assert report["after"]["staff_verdicts"] is None


@pytest.mark.asyncio
async def test_capacity_limited_case_does_not_stop_other_cases(tmp_path, monkeypatch):
    from app.channels.staff_assist.context_gate import (
        RequestGateDecision,
        RequestGateError,
    )

    args = fixture_inputs(tmp_path)
    prepared = replay.prepare(args)
    plan, inputs = replay.approved_plan(
        args.output / "plan.json", prepared["plan_sha256"]
    )
    first = inputs["index"]["sessions"][0]
    second = {
        **first,
        "session_id": "second-session",
        "requester_id": "second-requester",
        "case_ids": [2],
        "anchors": [{"case_id": 2, "event_id": "$second", "origin_server_ts": BASE}],
        "candidate_events": [{"event_id": "$second"}],
    }
    inputs["index"]["sessions"].append(second)
    inputs["cases"][2] = {"id": 2, "channel_metadata": {}}
    event = saved_event("$second", BASE)
    event["sender"] = "second-requester"
    event["original_sanitized_event"]["sender"] = "second-requester"
    inputs["events"][(second["room_id"], "$second")] = event
    visited = []

    def classify(self, snapshot):
        visited.append(snapshot.requester_id)
        if snapshot.requester_id == "requester":
            raise RequestGateError("conversation_input_capacity_reached")
        return RequestGateDecision(
            category="not_a_request",
            selected_event_ids=["$second"],
            request_summary="A synthetic acknowledgement",
            material_change=False,
            reason="Synthetic classification",
        )

    monkeypatch.setattr(replay.RequestGateService, "classify", classify)
    calls = SimpleNamespace(
        store=SimpleNamespace(
            db_path=str(tmp_path / "replay.db"),
            trial=SimpleNamespace(trial_id="synthetic"),
        ),
        calls=0,
        adapter=lambda *a, **k: SimpleNamespace(reason=None),
    )
    output = tmp_path / "execution"
    output.mkdir()
    result = await replay.replay(plan, inputs, output, calls)
    assert result["stopped_reason"] is None
    assert set(visited) == {"requester", "second-requester"}
    assert len(result["capacity_limited_snapshots"]) == 1
    assert calls.calls == 0


def test_selected_author_edit_preserves_original_anchor_reference():
    from app.channels.staff_assist.context_conversation import ConversationTurn

    snapshot = SimpleNamespace(
        room_id="room",
        requester_id="requester",
        turns=(
            ConversationTurn(
                "room",
                "$edit",
                "requester",
                BASE,
                "Corrected fact",
                replaces_event_id="$original",
            ),
            ConversationTurn(
                "room",
                "$unselected",
                "requester",
                BASE,
                "Other fact",
                replaces_event_id="$other",
            ),
        ),
    )
    inputs = {
        "index": {
            "sessions": [
                {
                    "room_id": "room",
                    "requester_id": "requester",
                    "anchors": [
                        {"case_id": 1, "event_id": "$original"},
                        {"case_id": 2, "event_id": "$other"},
                    ],
                }
            ]
        }
    }
    assert replay._source_cases(snapshot, ["$edit"], inputs) == [1]
    assert replay._source_cases(snapshot, [], inputs) == []


def test_before_after_keeps_initial_silence_and_later_update_explicit(tmp_path):
    args = fixture_inputs(tmp_path)
    prepared = replay.prepare(args)
    plan, inputs = replay.approved_plan(
        args.output / "plan.json", prepared["plan_sha256"]
    )
    rows = [
        {
            "source_case_ids": [1],
            "reference_category": "request",
            "model_called": True,
            "rendered": False,
            "reply": "",
            "kind": "note",
            "virtual_time_ms": BASE,
            "preview": {"decision": {"action": "silence"}},
        },
        {
            "source_case_ids": [1],
            "reference_category": "request",
            "model_called": True,
            "rendered": True,
            "reply": "A later documented step",
            "kind": "update",
            "virtual_time_ms": BASE + 10000,
            "preview": {"decision": {"action": "reply"}},
        },
    ]
    report = replay.report_data(plan, inputs, rows, [], pending=False)
    assert report["before_after"][0]["attempt_summary"][0]["action"] == "silence"
    assert report["action_comparisons"][0]["after_reply"] == "A later documented step"
    rendered = replay.render_report(report)
    assert "Initial attempt (note)" in rendered
    assert "action=silence" in rendered
    assert "Subsequent attempt (update)" in rendered
    assert "not the initial answer" in rendered


def test_historical_cost_reference_excludes_outside_cohort_and_missing_usage(tmp_path):
    args = fixture_inputs(tmp_path)
    inputs = {
        "index": {"sessions": [{"case_ids": [1, 2]}]},
        "cases": {
            1: {
                "channel_metadata": {
                    "model_usage": {"prompt_tokens": 100, "completion_tokens": 20}
                }
            },
            2: {"channel_metadata": {}},
            3: {
                "channel_metadata": {
                    "model_usage": {
                        "prompt_tokens": 100000,
                        "completion_tokens": 100000,
                    }
                }
            },
        },
    }
    reference = replay.recorded_usage_reference(inputs, args)
    assert reference["observed_cohort_calls"] == 1
    assert reference["observed_input_tokens"] == 100
    assert reference["cost_at_proposed_ceiling_rates_usd"] == "0.0014"
    assert reference["illustrative_four_calls_per_cohort_usd"] == "0.0056"
