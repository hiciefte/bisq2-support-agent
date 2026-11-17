"""Offline independent replay chronology and accounting regressions."""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace as NS

import pytest
from app.scripts.replay_staff_context import replay

pytestmark = pytest.mark.unit
ROOM = "!synthetic:example.org"
USER = "@requester:example.org"
STAFF = "@staff:example.org"


def message(event_id, text, timestamp, *, staff=False, replaces=None):
    content = {"body": text, "msgtype": "m.text"}
    if replaces:
        content["m.relates_to"] = {"rel_type": "m.replace", "event_id": replaces}
        content["m.new_content"] = {"body": text, "msgtype": "m.text"}
    return {
        "event_id": event_id,
        "sender": STAFF if staff else USER,
        "origin_server_ts": timestamp,
        "role": "staff" if staff else "requester",
        "text": text,
        "original_sanitized_event": {"content": content, "type": "m.room.message"},
    }


def inputs():
    rows = [
        message("$root", "The application does not start", 1000),
        message("$staff", "Try the documented connection check", 21000, staff=True),
        message(
            "$edit", "A different startup error now appears", 31000, replaces="$root"
        ),
        message("$follow", "The startup error still happens", 40000),
    ]
    return {
        "cases": {
            101: {"id": 101, "channel_metadata": {}},
            102: {"id": 102, "channel_metadata": {}},
        },
        "threads": {},
        "index": {
            "sessions": [
                {
                    "session_id": "synthetic-session",
                    "room_id": ROOM,
                    "requester_id": USER,
                    "first_anchor_ms": 1000,
                    "last_anchor_ms": 40000,
                    "case_ids": [101, 102],
                    "candidate_events": [{"event_id": row["event_id"]} for row in rows],
                    "anchors": [
                        {"case_id": 101, "event_id": "$root", "origin_server_ts": 1000},
                        {
                            "case_id": 102,
                            "event_id": "$follow",
                            "origin_server_ts": 40000,
                        },
                    ],
                }
            ],
        },
        "events": {(ROOM, row["event_id"]): row for row in rows},
        "conflicts": set(),
        "comparisons": {
            "cases": [{"case_id": 101, "staff_answer": "FUTURE_REFERENCE_ONLY"}],
            "focus_case_ids": [101, 102],
            "reference_request_ids": [101, 102],
            "reference_non_request_ids": [],
            "baseline": {"cases": 2},
        },
    }


class FakeCalls:
    """An in-process test adapter with no provider or Matrix dependency."""

    def __init__(self, path, *, fail=False):
        self.store = NS(
            db_path=str(path),
            trial=NS(trial_id="synthetic-replay", reason=lambda: None),
        )
        self.calls = 0
        self.requests = []
        self.fail = fail

    def adapter(self, snapshot, *, kind, virtual_time_ms):
        def invoke(prompt, system_content):
            self.calls += 1
            payload = json.loads(prompt)
            self.requests.append((kind, virtual_time_ms, payload))
            if self.fail:
                raise RuntimeError("Synthetic uncertain provider outcome")
            if "candidate_event_ids" in payload:
                body = {
                    "relation": "same_request",
                    "new_request_event_ids": [],
                    "reason": "The requester supplies a follow-up to the same issue.",
                }
            elif kind == "gate":
                staff_seen = any(row["role"] == "staff" for row in payload["messages"])
                body = {
                    "category": (
                        "already_answered"
                        if staff_seen
                        else "unanswered_support_request"
                    ),
                    "selected_event_ids": [
                        row["event_id"]
                        for row in payload["messages"]
                        if row["role"] == "requester"
                    ],
                    "request_summary": "Synthetic request",
                    "material_change": True,
                    "request_resolved": False,
                    "reason": "Synthetic classification",
                }
            else:
                body = {
                    "action": "silence",
                    "reply": "",
                    "staff_note": "",
                    "source_ids": [],
                    "reason": "knowledge_gap: startup troubleshooting",
                }
            return NS(
                content=json.dumps(body),
                usage={"input_tokens": 10, "output_tokens": 10},
            )

        return NS(invoke=invoke, reason=None, before_call=None, started=True)


def plan(tmp_path):
    return {
        "first_response_delay_seconds": 10,
        "data_dir": str(tmp_path),
        "estimate": {},
        "assumptions": [],
    }


@pytest.mark.asyncio
async def test_replay_excludes_later_staff_edits_and_report_reference(tmp_path):
    calls = FakeCalls(tmp_path / "replay.db")
    report = await replay(plan(tmp_path), inputs(), tmp_path, calls)
    assert report["stopped_reason"] is None
    first_gate = next(row for row in calls.requests if row[0] == "gate")
    assert first_gate[1] == 11000
    assert [row["event_id"] for row in first_gate[2]["messages"]] == ["$root"]
    assert first_gate[2]["messages"][0]["text"] == "The application does not start"
    assert "FUTURE_REFERENCE_ONLY" not in json.dumps(calls.requests)
    later_gates = [
        row for row in calls.requests if row[0] == "gate" and row[1] >= 40000
    ]
    assert later_gates
    assert any(
        message["event_id"] == "$edit" for message in later_gates[-1][2]["messages"]
    )


@pytest.mark.asyncio
async def test_model_silence_is_a_note_generation_but_not_a_rendered_reply(tmp_path):
    calls = FakeCalls(tmp_path / "replay.db")
    report = await replay(plan(tmp_path), inputs(), tmp_path, calls)
    assert report["after"]["model_note_generations"] == 1
    assert report["after"]["rendered_replies"] == 0
    assert report["after"]["limitation_opening_share"] is None
    assert report["after"]["staff_verdicts"] is None
    assert report["provider_invocations_started_or_uncertain"] == calls.calls


@pytest.mark.asyncio
async def test_final_quiet_deadline_drains_same_request_admission_and_update(tmp_path):
    data = inputs()
    for event_id in ("$staff", "$edit"):
        del data["events"][(ROOM, event_id)]
    calls = FakeCalls(tmp_path / "replay.db")
    report = await replay(plan(tmp_path), data, tmp_path, calls)
    assert report["stopped_reason"] is None
    assert [kind for kind, _, _ in calls.requests] == [
        "gate",
        "note",
        "gate",
        "gate",
        "update",
    ]
    assert [at for _, at, _ in calls.requests[-3:]] == [50000, 50000, 50000]
    with closing(sqlite3.connect(calls.store.db_path)) as db:
        rows = db.execute("SELECT channel_metadata FROM escalations").fetchall()
    assert len(rows) == 1
    metadata = json.loads(rows[0][0])
    assert metadata["conversation_generation_count"] == 2
    assert (
        metadata["conversation_admission_history"][0]["decision"]["relation"]
        == "same_request"
    )


@pytest.mark.asyncio
async def test_failed_replay_preserves_uncertainty_in_its_case(tmp_path):
    calls = FakeCalls(tmp_path / "replay.db", fail=True)
    report = await replay(plan(tmp_path), inputs(), tmp_path, calls)
    assert report["stopped_reason"]
    assert calls.calls == 1
    with closing(sqlite3.connect(calls.store.db_path)) as db:
        rows = db.execute("SELECT channel_metadata FROM escalations").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0])["conversation_delivery_uncertain"] is True
