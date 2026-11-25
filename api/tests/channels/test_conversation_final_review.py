"""Synthetic final-review regressions for attribution and worker continuations."""

import asyncio
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.context_conversation import (
    RequestSnapshot,
    conversation_turn,
    selected_staff_request,
)
from app.channels.staff_assist.context_gate import RequestGateError, RequestGateService

from tests.channels.test_context_conversation_independent import (
    HELPER,
    REQUESTER,
    ROOM,
)
from tests.channels.test_context_conversation_independent import (
    coordinator as base_coordinator,
)
from tests.channels.test_context_conversation_independent import (
    decision,
    turn,
)
from tests.channels.test_context_conversation_runtime import (
    draft,
    event,
    gate,
    incoming,
)
from tests.channels.test_context_conversation_runtime import (
    runtime_case as base_runtime_case,
)
from tests.channels.test_context_conversation_runtime import (
    setup,
)
from tests.channels.test_context_runtime_integration import SOURCE_ROOM
from tests.channels.test_request_admission import admission, old_request

coordinator = base_coordinator
runtime_case = base_runtime_case
pytestmark = pytest.mark.unit


async def image_context(coordinator):
    """Capture an attachment and its author-valid correction without intake."""
    original = turn("$image", "[Image contents unavailable]", 2000, non_text="m.image")
    edit = turn(
        "$image-edit",
        "[Edited image contents unavailable]",
        2100,
        non_text="m.image",
        replaces_event_id="$image",
    )
    await coordinator.ingest(original, now_ms=2000, allow_new=False)
    await coordinator.ingest(edit, now_ms=2100, allow_new=False)
    return original, edit


async def test_effective_attachment_edit_covers_original_parent(coordinator):
    await image_context(coordinator)
    result = await coordinator.ingest(
        turn(
            "$question", "Why does this icon differ?", 2200, reply_to_event_id="$image"
        ),
        now_ms=2200,
    )
    snapshot = await coordinator.snapshot(result.case_id, now_ms=12200)
    request = selected_staff_request(snapshot, decision(["$question"]), [])
    assert request.conversation_coverage.attachment_event_ids == ["$image-edit"]
    assert request.conversation_coverage.missing_parent_event_ids == []
    assert request.question == "Why does this icon differ?"


async def test_promotion_preserves_attachment_original_and_edit_as_context(coordinator):
    old = await old_request(coordinator)
    await image_context(coordinator)
    await coordinator.ingest(
        turn("$new", "Why does this icon differ?", 2200, reply_to_event_id="$image"),
        now_ms=2200,
    )
    snapshot = await coordinator.snapshot(old, now_ms=12200)
    assert snapshot.kind == "admission"
    assert await coordinator.claim(snapshot)
    result = await coordinator.record_admission(snapshot, admission())
    child = await coordinator.service.repository.get_by_id(result.case_id)
    assert {t["event_id"] for t in child.channel_metadata["incident_messages"]} == {
        "$new"
    }
    assert {t["event_id"] for t in child.channel_metadata["conversation_exchange"]} == {
        "$new",
        "$image",
        "$image-edit",
    }
    child_snapshot = await coordinator.snapshot(child.id, now_ms=12200)
    assert {t.event_id for t in child_snapshot.turns} == {"$new", "$image-edit"}
    request = selected_staff_request(child_snapshot, decision(["$new"]), [])
    assert request.question == "Why does this icon differ?"
    assert request.conversation_coverage.attachment_event_ids == ["$image-edit"]
    assert request.conversation_coverage.missing_parent_event_ids == []
    assert not child_snapshot.valid_new_request_evidence(["$image-edit"])


@pytest.mark.parametrize("with_edit", [False, True])
async def test_captured_redaction_scrubs_previous_prompt_not_audit(
    coordinator, with_edit
):
    first = await coordinator.ingest(
        turn("$secret", "Private old diagnostic", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$kept", "The client is offline", 1100, reply_to_event_id="$secret"),
        now_ms=1100,
    )
    if with_edit:
        await coordinator.ingest(
            turn(
                "$edit",
                "Corrected private diagnostic",
                1200,
                replaces_event_id="$secret",
            ),
            now_ms=1200,
        )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11200)
    await coordinator.record_draft(
        snapshot, NS(model_called=True, rendered_note="synthetic")
    )
    before = (
        await coordinator.service.repository.get_by_id(first.case_id)
    ).channel_metadata["conversation_generated_snapshot"]
    assert any("private" in m["text"].lower() for m in before["messages"])
    await coordinator.ingest(
        turn("$redact", "", 13000, redacts_event_id="$secret"), now_ms=13000
    )
    await coordinator.ingest(
        turn(
            "$facts",
            "It now shows a connection error",
            14000,
            reply_to_event_id="$kept",
        ),
        now_ms=14000,
    )
    current = await coordinator.snapshot(first.case_id, now_ms=24000)
    payload = current.prompt_payload()
    assert {
        m["event_id"] for m in payload["previous_generated_request"]["messages"]
    } == {"$kept"}
    assert "private" not in json.dumps(payload).lower()
    after = (
        await coordinator.service.repository.get_by_id(first.case_id)
    ).channel_metadata["conversation_generated_snapshot"]
    assert after == before


@pytest.mark.parametrize(
    "relation,selected", [(True, True), (True, False), (False, True), (False, False)]
)
def test_later_requester_state_supersedes_resolution(relation, selected):
    resolved = turn("$fixed", "It works now", 1000)
    later = turn(
        "$recurrence",
        "The same error is back",
        2000,
        reply_to_event_id="$fixed" if relation else None,
    )
    snapshot = RequestSnapshot(1, ROOM, REQUESTER, 1, (resolved, later), 2000)
    result = decision(
        ["$fixed", *(["$recurrence"] if selected else [])],
        category="already_answered",
        resolved=True,
    ).model_copy(update={"resolution_event_id": "$fixed"})
    service = RequestGateService(
        NS(invoke=Mock(return_value=NS(content=result.model_dump_json())))
    )
    with pytest.raises(RequestGateError, match="invalid_conversation_gate"):
        service.classify(snapshot)


@pytest.mark.parametrize("later", [None, "Thanks!", "It is working now"])
def test_standalone_or_reaffirmed_resolution_remains_valid(later):
    turns = [turn("$fixed", "It works now", 1000)]
    if later:
        turns.append(turn("$later", later, 2000, reply_to_event_id="$fixed"))
    snapshot = RequestSnapshot(1, ROOM, REQUESTER, 1, tuple(turns), 2000)
    result = decision(
        [t.event_id for t in turns], category="already_answered", resolved=True
    ).model_copy(update={"resolution_event_id": "$fixed"})
    service = RequestGateService(
        NS(invoke=Mock(return_value=NS(content=result.model_dump_json())))
    )
    assert service.classify(snapshot).request_resolved


def test_other_participant_cannot_supersede_requester_resolution():
    turns = (
        turn("$fixed", "It works now", 1000),
        turn(
            "$peer",
            "Mine is still broken",
            2000,
            sender=HELPER,
            reply_to_event_id="$fixed",
        ),
    )
    snapshot = RequestSnapshot(1, ROOM, REQUESTER, 1, turns, 2000)
    result = decision(
        ["$fixed", "$peer"], category="already_answered", resolved=True
    ).model_copy(update={"resolution_event_id": "$fixed"})
    service = RequestGateService(
        NS(invoke=Mock(return_value=NS(content=result.model_dump_json())))
    )
    assert service.classify(snapshot).request_resolved


@pytest.mark.parametrize("mutation", ["ack_edit", "redact"])
async def test_no_text_anchor_is_known_no_call_and_later_revision_runs(
    runtime_case, mutation
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    original_calls = bundle.llm.invoke.call_count
    source = event(bundle, "$change", "Thanks!")
    source.server_timestamp += 1
    if mutation == "ack_edit":
        source.source["content"] = {
            "body": "* Thanks!",
            "m.relates_to": {"rel_type": "m.replace", "event_id": "$source"},
            "m.new_content": {"msgtype": "m.text", "body": "Thanks!"},
        }
    else:
        source.body = ""
        source.source["content"] = {"redacts": "$source"}
    current = await incoming(bundle, source)
    assert current.channel_metadata["context_reason"] == "conversation_no_text_anchor"
    assert current.channel_metadata["context_status"] == "deferred"
    assert not current.channel_metadata.get("conversation_delivery_uncertain")
    assert current.channel_metadata["conversation_running_revision"] is None
    assert bundle.llm.invoke.call_count == original_calls
    bundle.sender.assert_not_awaited()
    bundle.llm.invoke = Mock(
        return_value=NS(
            content=json.dumps(gate(["$later"], category="already_answered")),
            usage={"input_tokens": 100, "output_tokens": 30},
        )
    )
    later = event(bundle, "$later", "How do I reconnect?", relation="$source")
    later.server_timestamp += 1
    current = await incoming(bundle, later)
    bundle.llm.invoke.assert_called_once()
    assert not current.channel_metadata.get("conversation_delivery_uncertain")
    assert current.channel_metadata["conversation_gate"]["selected_event_ids"] == [
        "$later"
    ]


@pytest.mark.parametrize("redacted", [False, True])
async def test_visible_original_behind_retained_edit_is_verified(
    runtime_case, redacted
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    coordinator = bundle.engine._conversation_coordinator()
    edit = event(bundle, "$edit", "The corrected original request")
    edit.server_timestamp += 1
    edit.source["content"] = {
        "body": "* The corrected original request",
        "m.relates_to": {"rel_type": "m.replace", "event_id": "$source"},
        "m.new_content": {
            "msgtype": "m.text",
            "body": "The corrected original request",
        },
    }
    await bundle.engine._capture_conversation_turn(
        conversation_turn(SOURCE_ROOM, edit, is_staff=False)
    )
    later = event(
        bundle, "$later", "The application now shows an error", relation="$source"
    )
    later.server_timestamp += 1
    await bundle.engine._capture_conversation_turn(
        conversation_turn(SOURCE_ROOM, later, is_staff=False)
    )
    snapshot = await coordinator.snapshot(1, now_ms=later.server_timestamp + 1000)
    assert "$source" not in {t.event_id for t in snapshot.turns}
    assert "$edit" in {t.event_id for t in snapshot.turns}
    if redacted:
        original = bundle.source_events[0]
        original.body = ""
        original.source = {
            "content": {},
            "unsigned": {"redacted_because": {"type": "m.room.redaction"}},
        }
    result = await bundle.engine._verify_conversation_anchor(snapshot)
    assert result == ("source_changed_or_redacted" if redacted else None)
    fresh = await coordinator.snapshot(1, now_ms=later.server_timestamp + 1000)
    assert ("$edit" in {t.event_id for t in fresh.turns}) is not redacted
    assert bundle.llm.invoke.call_count == 1


async def test_original_worker_continues_when_separate_request_is_promoted(
    runtime_case,
):
    from tests.channels.test_request_admission_runtime import boundary, submit

    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"], category="already_answered")])
    coordinator = bundle.engine._conversation_coordinator()
    await coordinator._change(
        old.id,
        conversation_last_gate_revision=-1,
        context_status="preparing",
        context_reason="request_waiting",
    )
    observed = []

    def classify(prompt, system_content):
        data = json.loads(prompt)
        if "Decide whether a later requester" in system_content:
            response = boundary()
        else:
            ids = [m["event_id"] for m in data["messages"] if m["role"] == "requester"]
            observed.append(ids)
            response = gate(ids, category="already_answered")
        return NS(
            content=json.dumps(response),
            usage={"input_tokens": 100, "output_tokens": 30},
        )

    bundle.llm.invoke = Mock(side_effect=classify)
    await submit(bundle, "Separate question: where is the language setting?")
    parent = await bundle.repository.get_by_id(old.id)
    child = await bundle.repository.get_by_id(old.id + 1)
    assert (
        parent.channel_metadata["conversation_last_gate_revision"]
        == parent.channel_metadata["conversation_revision"]
    )
    assert parent.channel_metadata["context_status"] == "needs_human"
    assert parent.channel_metadata["conversation_gate"]["selected_event_ids"] == [
        "$source"
    ]
    assert child.channel_metadata["conversation_gate"]["selected_event_ids"] == ["$new"]
    assert sorted(observed) == [["$new"], ["$source"]]
    bundle.sender.assert_not_awaited()


async def test_quiet_restart_after_claim_reschedules_without_spend_receipt(
    runtime_case, monkeypatch
):
    from datetime import timedelta

    import app.channels.staff_assist.context_runtime as module

    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    bundle.policy.first_response_delay_seconds = 1
    clock = module.utc_now() + timedelta(seconds=2)
    monkeypatch.setattr(module, "utc_now", lambda: clock)
    later = event(
        bundle, "$facts", "It now shows a connection error", relation="$source"
    )
    await bundle.engine._capture_conversation_turn(
        conversation_turn(SOURCE_ROOM, later, is_staff=False)
    )
    bundle.llm.invoke = Mock(
        return_value=NS(
            content=json.dumps(
                gate(["$source", "$facts"], category="already_answered")
            ),
            usage={"input_tokens": 100, "output_tokens": 30},
        )
    )
    original_verify = bundle.engine._verify_conversation_anchor
    injected = False
    waited = []
    original_sleep = asyncio.sleep

    async def verify(snapshot):
        nonlocal injected
        result = await original_verify(snapshot)
        if not injected:
            injected = True
            ack = event(bundle, "$ack", "Thanks!", relation="$facts")
            ack.server_timestamp = int(clock.timestamp() * 1000)
            await bundle.engine._capture_conversation_turn(
                conversation_turn(SOURCE_ROOM, ack, is_staff=False)
            )
        return result

    async def sleep(seconds):
        nonlocal clock
        if seconds > 0:
            with closing(sqlite3.connect(bundle.repository.db_path)) as db:
                rows = db.execute(
                    "SELECT status FROM matrix_context_trial_spend"
                ).fetchall()
            assert rows == [("settled",)]
            current = await bundle.repository.get_by_id(1)
            assert (
                current.channel_metadata["conversation_last_gate_revision"]
                < current.channel_metadata["conversation_revision"]
            )
            assert current.channel_metadata["conversation_running_revision"] is None
            waited.append(seconds)
            clock += timedelta(seconds=seconds + 0.001)
        await original_sleep(0)

    monkeypatch.setattr(bundle.engine, "_verify_conversation_anchor", verify)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    await bundle.engine._run_conversation(1, bundle.channel)
    assert injected and len(waited) == 1
    bundle.llm.invoke.assert_called_once()
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        rows = db.execute("SELECT status FROM matrix_context_trial_spend").fetchall()
    assert rows == [("settled",), ("settled",)]
    current = await bundle.repository.get_by_id(1)
    assert not current.channel_metadata.get("conversation_delivery_uncertain")


@pytest.mark.parametrize("reconciliation_fails", [False, True])
async def test_note_receipt_reconciles_early_answers_without_reclassifying_delivery(
    runtime_case, monkeypatch, reconciliation_fails
):
    from app.channels.models import SendResult
    from app.channels.staff_assist.context_feedback import ContextFeedbackStore

    bundle = runtime_case
    observed = []

    async def reconcile(_store, case_id):
        case = await bundle.repository.get_by_id(case_id)
        history = case.channel_metadata["staff_note_history"]
        assert case.channel_metadata["context_status"] == "delivered"
        observed.append([item["event_id"] for item in history])
        if reconciliation_fails:
            raise sqlite3.OperationalError("synthetic storage failure")

    monkeypatch.setattr(ContextFeedbackStore, "reconcile_answers", reconcile)
    case = await setup(
        bundle, [gate(["$source"]), draft(), gate(["$source", "$facts"]), draft()]
    )
    assert case.channel_metadata["context_status"] == "delivered"
    bundle.sender.side_effect = [SendResult(True, "$staff-update")]
    case = await incoming(
        bundle,
        event(
            bundle,
            "$facts",
            "The trade period expired and the payment was sent.",
            relation="$source",
        ),
    )
    assert case.channel_metadata["context_status"] == "delivered"
    assert observed == [["$staff-note"], ["$staff-note", "$staff-update"]]
    assert bundle.sender.await_count == 3


async def test_quiet_guard_is_gate_only_and_clears_at_actual_deadline(coordinator):
    """A late acknowledgement delays eligibility, not an already produced draft."""
    first = await coordinator.ingest(
        turn("$request", "How do I connect?", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert await coordinator.claim(snapshot)
    await coordinator.ingest(
        turn("$ack", "Thanks!", 11001, reply_to_event_id="$request"), now_ms=11001
    )
    assert coordinator.request_call_guard(snapshot) is None
    assert (
        coordinator.request_call_guard(snapshot, now_ms=11001)
        == "conversation_quiet_period_restarted"
    )
    assert coordinator.request_call_guard(snapshot, now_ms=21001) is None


@pytest.mark.parametrize("withheld", [False, True])
async def test_promotion_does_not_consume_pending_draft_or_bounded_replacement(
    coordinator, withheld
):
    """A completed eligibility gate alone does not settle the original draft."""
    first = await coordinator.ingest(
        turn("$first", "How do I reconnect?", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert await coordinator.claim(snapshot)
    assert await coordinator.record_gate(snapshot, decision(["$first"]))
    if withheld:
        # Even an earlier handled flag cannot override a later saved replacement.
        await coordinator.record_draft(
            snapshot, NS(model_called=True, rendered_note="synthetic"), presented=False
        )
        await coordinator._change(first.case_id, context_status="deferred")
    await coordinator.ingest(
        turn("$new", "Separate question: where is the language setting?", 12000),
        now_ms=12000,
    )
    if withheld:
        await coordinator._change(
            first.case_id, conversation_admission_request_pending=False
        )
        await coordinator.record_withheld(snapshot)
    await coordinator.finish(snapshot)
    boundary_snapshot = await coordinator.snapshot(first.case_id, now_ms=22000)
    assert await coordinator.claim(boundary_snapshot)
    result = await coordinator.record_admission(boundary_snapshot, admission())
    await coordinator.finish(boundary_snapshot)
    parent = await coordinator.service.repository.get_by_id(first.case_id)
    assert (
        parent.channel_metadata["conversation_last_gate_revision"]
        < parent.channel_metadata["conversation_revision"]
    )
    due = await coordinator.due(now_ms=22000)
    assert {item.case_id for item in due} == {first.case_id, result.case_id}
    if withheld:
        assert parent.channel_metadata["conversation_replacement_allowed"]
        assert parent.channel_metadata["conversation_generation_count"] == 1
    else:
        assert not parent.channel_metadata.get("conversation_generation_count")
