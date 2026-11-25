"""Synthetic regressions for native context and reviewed lifecycle boundaries."""

import asyncio
import json
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
    ROOM,
    STAFF,
)
from tests.channels.test_context_conversation_independent import coordinator as base
from tests.channels.test_context_conversation_independent import (
    decision,
    turn,
)
from tests.channels.test_context_conversation_runtime import (
    draft,
    event,
    gate,
)
from tests.channels.test_context_conversation_runtime import (
    runtime_case as runtime_base,
)
from tests.channels.test_context_conversation_runtime import (
    setup,
)
from tests.channels.test_context_runtime_integration import SOURCE_ROOM
from tests.channels.test_request_admission import admission, old_request

pytestmark = pytest.mark.unit
coordinator = base
runtime_case = runtime_base


async def test_native_image_parent_before_intake_is_context_not_question(coordinator):
    parent = turn(
        "$image",
        "[Attachment: m.image; contents unavailable]",
        1000,
        non_text="m.image",
    )
    unrelated = turn(
        "$other-image",
        "[Attachment: m.image; contents unavailable]",
        1001,
        non_text="m.image",
    )
    assert not (await coordinator.ingest(parent, now_ms=1000)).created
    await coordinator.ingest(unrelated, now_ms=1001)
    first = await coordinator.ingest(
        turn(
            "$question",
            "Why do the two icons differ?",
            1500,
            reply_to_event_id="$image",
        ),
        now_ms=1500,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11500)
    assert {t.event_id for t in snapshot.turns} == {"$image", "$question"}
    request = selected_staff_request(snapshot, decision(["$question"]), [])
    assert request.question == "Why do the two icons differ?"
    assert request.conversation_coverage.attachment_event_ids == ["$image"]
    assert request.conversation_coverage.missing_parent_event_ids == []
    assert any("contents unavailable" in m.content for m in request.recent_messages)
    assert (
        await coordinator.service.repository.get_by_id(first.case_id)
    ).channel_metadata["incident_messages"][0]["event_id"] == "$question"
    assert snapshot.anchor.event_id == "$question"


@pytest.mark.parametrize("mutation", ["redact", "invalidate"])
async def test_unavailable_native_parent_does_not_reappear(coordinator, mutation):
    await coordinator.ingest(
        turn(
            "$image",
            "[Attachment: m.image; contents unavailable]",
            1000,
            non_text="m.image",
        ),
        now_ms=1000,
    )
    first = await coordinator.ingest(
        turn("$question", "Why this icon?", 1100, reply_to_event_id="$image"),
        now_ms=1100,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11100)
    if mutation == "redact":
        await coordinator.ingest(
            turn("$redact", "", 12000, redacts_event_id="$image"), now_ms=12000
        )
    else:
        await coordinator.invalidate_visible_event(snapshot, "$image")
    current = await coordinator.snapshot(first.case_id, now_ms=22000)
    assert "$image" not in {t.event_id for t in current.turns}
    assert current.version != snapshot.version
    request = selected_staff_request(current, decision(["$question"]), [])
    assert request.conversation_coverage.missing_parent_event_ids == ["$image"]


async def test_required_native_parent_still_respects_input_capacity(coordinator):
    await coordinator.ingest(
        turn("$parent", "x" * 33000, 1000), now_ms=1000, allow_new=False
    )
    first = await coordinator.ingest(
        turn("$question", "What does that mean?", 1001, reply_to_event_id="$parent"),
        now_ms=1001,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11001)
    assert snapshot.overflow


async def test_edited_helper_alias_preserves_native_staff_hold_on_promotion(
    coordinator,
):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn("$new", "Where is the language setting?", 3000), now_ms=3000
    )
    await coordinator.ingest(
        turn("$helper", "Which screen?", 3001, sender=HELPER, reply_to_event_id="$new"),
        now_ms=3001,
    )
    await coordinator.ingest(
        turn(
            "$edit",
            "Which application screen?",
            3002,
            sender=HELPER,
            replaces_event_id="$helper",
        ),
        now_ms=3002,
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "I can help with that screen.",
            3003,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$helper",
        ),
        now_ms=3003,
    )
    snapshot = await coordinator.snapshot(old, now_ms=13003)
    assert await coordinator.claim(snapshot)
    promoted = await coordinator.record_admission(snapshot, admission())
    child = await coordinator.service.repository.get_by_id(promoted.case_id)
    assert child.channel_metadata["conversation_staff_replied"]
    assert "$staff" in child.channel_metadata["conversation_staff_reply_event_ids"]
    assert not await coordinator.claim(
        await coordinator.snapshot(child.id, now_ms=23003)
    )


async def test_invalidated_text_absent_from_all_admission_payloads(coordinator):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn("$new", "Where is the language setting?", 3000), now_ms=3000
    )
    await coordinator.ingest(
        turn("$helper", "DISPROVED_HELPER", 3001, sender=HELPER),
        now_ms=3001,
        allow_new=False,
    )
    snapshot = await coordinator.snapshot(old, now_ms=13001)
    await coordinator.invalidate_visible_event(snapshot, "$old")
    await coordinator.invalidate_visible_event(snapshot, "$helper")
    fresh = await coordinator.snapshot(old, now_ms=13001)
    payload = json.dumps(fresh.prompt_payload())
    assert "DISPROVED_HELPER" not in payload
    assert "The application cannot connect" not in payload
    assert "Where is the language setting?" in payload


async def test_previous_generated_copy_filters_invalidated_text_without_rewriting_history(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$one", "DISPROVED_OLD_TEXT", 1000), now_ms=1000
    )
    previous = {
        "messages": [
            {"event_id": "$one", "role": "requester", "text": "DISPROVED_OLD_TEXT"}
        ]
    }
    await coordinator._change(first.case_id, conversation_generated_snapshot=previous)
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    await coordinator.invalidate_visible_event(snapshot, "$one")
    await coordinator.ingest(
        turn("$new", "Where are language settings?", 12000), now_ms=12000
    )
    fresh = await coordinator.snapshot(first.case_id, now_ms=22000)
    assert "DISPROVED_OLD_TEXT" not in json.dumps(fresh.prompt_payload())
    case = await coordinator.service.repository.get_by_id(first.case_id)
    assert case.channel_metadata["conversation_generated_snapshot"] == previous


async def test_pending_admission_invalidates_inflight_ordinary_work(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The application cannot connect", 1000), now_ms=1000
    )
    await coordinator._change(first.case_id, conversation_generation_count=1)
    await coordinator.ingest(
        turn("$facts", "It fails on this release too", 2000, reply_to_event_id="$one"),
        now_ms=2000,
    )
    ordinary = await coordinator.snapshot(first.case_id, now_ms=12000)
    assert await coordinator.claim(ordinary)
    await coordinator.ingest(
        turn("$new", "Where is the language setting?", 12001), now_ms=12001
    )
    assert not await coordinator.is_current(ordinary)
    assert coordinator.request_call_guard(ordinary) == "conversation_changed"
    assert not await coordinator.record_gate(ordinary, decision(["$facts"]))
    await coordinator.finish(ordinary)
    current = await coordinator.snapshot(first.case_id, now_ms=22001)
    assert current.kind == "admission"
    assert await coordinator.claim(current)
    await coordinator.record_admission(current, admission("same_request"))
    await coordinator.finish(current)
    assert (await coordinator.due(now_ms=22001))[0].kind == "update"


async def test_all_selected_edit_history_belongs_only_to_promoted_case(coordinator):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn("$new", "Where is the language setting?", 3000), now_ms=3000
    )
    await coordinator.ingest(
        turn("$edit1", "Where is language?", 3001, replaces_event_id="$new"),
        now_ms=3001,
    )
    await coordinator.ingest(
        turn(
            "$edit2",
            "Where is the display language setting?",
            3002,
            replaces_event_id="$new",
        ),
        now_ms=3002,
    )
    snapshot = await coordinator.snapshot(old, now_ms=13002)
    assert await coordinator.claim(snapshot)
    promoted = await coordinator.record_admission(snapshot, admission(ids=["$edit2"]))
    child = await coordinator.service.repository.get_by_id(promoted.case_id)
    assert {i["event_id"] for i in child.channel_metadata["incident_messages"]} == {
        "$new",
        "$edit1",
        "$edit2",
    }
    parent = await coordinator.service.repository.get_by_id(old)
    assert not parent.channel_metadata.get("conversation_unassigned_candidates")


@pytest.mark.parametrize(
    "text",
    [
        "No, it still fails",
        "It is not resolved",
        "This is not resolved",
        "This is resolved but the payment is still missing",
        "It isn't fixed",
        "It works now but payment is still missing",
        "Is the problem resolved?",
        "Thanks",
        "Maybe it works now",
    ],
)
def test_nonaffirmative_resolution_never_closes_request(text):
    snap = RequestSnapshot(
        1, ROOM, turn("$x", text, 1).sender_id, 1, (turn("$x", text, 1),), 1, "note"
    )
    choice = decision(["$x"], category="already_answered", resolved=True).model_copy(
        update={"resolution_event_id": "$x"}
    )
    with pytest.raises(RequestGateError):
        RequestGateService(
            Mock(invoke=Mock(return_value=NS(content=choice.model_dump_json())))
        ).classify(snap)


@pytest.mark.parametrize(
    "text",
    [
        "It works now",
        "No need, synchronization is working again",
        "The issue is resolved",
        "That fixed the connection; this is resolved",
        "It is fixed",
    ],
)
def test_affirmative_resolution_remains_accepted(text):
    snap = RequestSnapshot(
        1, ROOM, turn("$x", text, 1).sender_id, 1, (turn("$x", text, 1),), 1, "note"
    )
    choice = decision(["$x"], category="already_answered", resolved=True).model_copy(
        update={"resolution_event_id": "$x"}
    )
    assert (
        RequestGateService(
            Mock(invoke=Mock(return_value=NS(content=choice.model_dump_json())))
        )
        .classify(snap)
        .request_resolved
    )


def test_attachment_cannot_be_only_selected_request_or_new_fact():
    image = turn(
        "$image", "[Attachment: m.image; contents unavailable]", 2, non_text="m.image"
    )
    question = turn("$question", "Why this warning?", 1)
    snap = RequestSnapshot(
        1,
        ROOM,
        question.sender_id,
        1,
        (question, image),
        2,
        "update",
        {"messages": [{"event_id": "$question", "role": "requester"}]},
    )
    choice = decision(["$image"])
    assert not snap.has_new_requester_facts
    with pytest.raises(RequestGateError):
        RequestGateService(
            Mock(invoke=Mock(return_value=NS(content=choice.model_dump_json())))
        ).classify(snap)


async def test_confirmed_anchor_mismatch_is_durable_but_timeout_is_not(runtime_case):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])
    coordinator = bundle.engine._conversation_coordinator()
    snap = await coordinator.snapshot(
        old.id, now_ms=int(bundle.source_events[0].server_timestamp) + 100000
    )
    bundle.client.room_context.side_effect = asyncio.TimeoutError
    assert (
        await bundle.engine._verify_conversation_anchor(snap)
        == "source_context_timeout"
    )
    assert not (await bundle.repository.get_by_id(old.id)).channel_metadata.get(
        "conversation_invalidated_event_ids"
    )
    changed = event(bundle, "$source", "Changed source text")
    changed.server_timestamp = snap.anchor.timestamp_ms
    bundle.client.room_context.side_effect = lambda *a, **k: NS(
        event=changed, events_before=[], events_after=[]
    )
    assert (
        await bundle.engine._verify_conversation_anchor(snap)
        == "source_changed_or_redacted"
    )
    assert (
        "$source"
        in (await bundle.repository.get_by_id(old.id)).channel_metadata[
            "conversation_invalidated_event_ids"
        ]
    )


async def test_worker_capacity_defers_persisted_case_without_new_task(runtime_case):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])
    markers = {object() for _ in range(100)}
    bundle.engine._tasks.update(markers)
    try:
        await bundle.engine._start_conversation_worker(old.id, bundle.channel)
        assert old.id not in bundle.engine._active_cases
        case = await bundle.repository.get_by_id(old.id)
        assert case.channel_metadata["context_reason"] == "context_capacity_reached"
    finally:
        bundle.engine._tasks.difference_update(markers)


@pytest.mark.parametrize("newer", [True, False])
async def test_admission_claim_race_only_rechecks_a_newer_unclaimed_revision(
    runtime_case, monkeypatch, newer
):
    bundle = runtime_case
    responses = [gate(["$source"]), draft()]
    old = await setup(bundle, responses)
    coordinator = bundle.engine._conversation_coordinator()
    fresh = event(bundle, "$new", "It fails on this operating system too")
    await coordinator.ingest(
        conversation_turn(SOURCE_ROOM, fresh, is_staff=False),
        now_ms=fresh.server_timestamp,
    )
    original = coordinator.claim
    claim_count = 0

    async def claim(snapshot):
        nonlocal claim_count
        claim_count += 1
        if claim_count == 1:
            if newer:
                latest = event(bundle, "$later", "The exact release is version 2")
                await coordinator.ingest(
                    conversation_turn(SOURCE_ROOM, latest, is_staff=False),
                    now_ms=latest.server_timestamp,
                )
            else:
                await original(snapshot)  # A competing worker owns the same revision.
            return False
        return await original(snapshot)

    monkeypatch.setattr(coordinator, "claim", claim)
    responses.append(
        {
            "relation": "same_request",
            "new_request_event_ids": [],
            "reason": "Additional diagnostic facts",
        }
    )
    before = bundle.llm.invoke.call_count
    result = await bundle.engine._run_request_admission(old.id, bundle.channel)
    assert result is newer
    assert claim_count == (2 if newer else 1)
    assert bundle.llm.invoke.call_count == before + (1 if newer else 0)


@pytest.mark.parametrize(
    "message",
    [
        "He said it works now",
        "I hope it works now",
        "If it works now I will send it",
        'The error says "issue resolved"',
    ],
)
def test_reported_or_conditional_success_does_not_prove_resolution(message):
    snapshot = RequestSnapshot(
        1, ROOM, turn("$x", message, 1).sender_id, 1, (turn("$x", message, 1),), 1
    )
    choice = decision(["$x"], category="already_answered", resolved=True).model_copy(
        update={"resolution_event_id": "$x"}
    )
    with pytest.raises(RequestGateError):
        RequestGateService(
            Mock(invoke=Mock(return_value=NS(content=choice.model_dump_json())))
        ).classify(snapshot)


async def test_invalidated_original_cannot_leak_through_previous_edit_copy(coordinator):
    first = await coordinator.ingest(
        turn("$one", "Original private fact", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$edit", "DISPROVED_EDIT_TEXT", 1001, replaces_event_id="$one"),
        now_ms=1001,
    )
    previous = {
        "messages": [
            {"event_id": "$edit", "role": "requester", "text": "DISPROVED_EDIT_TEXT"}
        ]
    }
    await coordinator._change(first.case_id, conversation_generated_snapshot=previous)
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11001)
    await coordinator.invalidate_visible_event(snapshot, "$one")
    await coordinator.ingest(turn("$fresh", "A new exact symptom", 12000), now_ms=12000)
    current = await coordinator.snapshot(first.case_id, now_ms=22000)
    assert "DISPROVED_EDIT_TEXT" not in json.dumps(current.prompt_payload())


async def test_unrelated_edited_chain_never_takes_new_request_ownership(coordinator):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn("$new", "Where is the language setting?", 3000), now_ms=3000
    )
    await coordinator.ingest(
        turn(
            "$helper",
            "Another unrelated question",
            3001,
            sender=HELPER,
            reply_to_event_id="$unseen-other",
        ),
        now_ms=3001,
        allow_new=False,
    )
    await coordinator.ingest(
        turn(
            "$edit",
            "Correcting unrelated question",
            3002,
            sender=HELPER,
            replaces_event_id="$helper",
        ),
        now_ms=3002,
        allow_new=False,
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "I can help that other person",
            3003,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$helper",
        ),
        now_ms=3003,
        allow_new=False,
    )
    snapshot = await coordinator.snapshot(old, now_ms=13003)
    assert await coordinator.claim(snapshot)
    promoted = await coordinator.record_admission(snapshot, admission())
    child = await coordinator.service.repository.get_by_id(promoted.case_id)
    assert not child.channel_metadata.get("conversation_staff_replied")


async def test_native_image_parent_survives_new_request_admission_without_new_slot(
    coordinator,
):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn(
            "$image",
            "[Attachment: m.image; contents unavailable]",
            3000,
            non_text="m.image",
        ),
        now_ms=3000,
    )
    await coordinator.ingest(
        turn(
            "$new", "Why are these icons different?", 3001, reply_to_event_id="$image"
        ),
        now_ms=3001,
    )
    snapshot = await coordinator.snapshot(old, now_ms=13001)
    assert snapshot.kind == "admission"
    assert "$image" in {t.event_id for t in snapshot.turns}
    assert snapshot.admission_event_ids == ("$new",)
    assert await coordinator.claim(snapshot)
    promoted = await coordinator.record_admission(snapshot, admission())
    child = await coordinator.snapshot(promoted.case_id, now_ms=23001)
    request = selected_staff_request(child, decision(["$new"]), [])
    assert request.conversation_coverage.attachment_event_ids == ["$image"]
    assert request.question == "Why are these icons different?"
    assert (await coordinator.service.repository.get_by_id(old)).channel_metadata[
        "conversation_generation_count"
    ] == 2
    assert (
        await coordinator.service.repository.get_by_id(promoted.case_id)
    ).channel_metadata.get("conversation_generation_count", 0) == 0


async def test_admission_native_parent_redaction_is_not_lost_by_neighbor_window(
    coordinator,
):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn(
            "$image",
            "[Attachment: m.image; contents unavailable]",
            3000,
            non_text="m.image",
        ),
        now_ms=3000,
    )
    await coordinator.ingest(
        turn("$redact", "", 3001, redacts_event_id="$image"), now_ms=3001
    )
    await coordinator.ingest(
        turn(
            "$new", "Why are these icons different?", 3002, reply_to_event_id="$image"
        ),
        now_ms=3002,
    )
    snapshot = await coordinator.snapshot(old, now_ms=13002)
    assert snapshot.kind == "admission"
    assert "$image" not in {t.event_id for t in snapshot.turns}
