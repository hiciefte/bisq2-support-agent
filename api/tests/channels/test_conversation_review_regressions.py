"""Offline counterexamples from the bounded release review."""

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
    REQUESTER,
    ROOM,
    STAFF,
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


async def test_selected_staff_reply_to_another_request_never_takes_ownership(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$one", "How do I connect?", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$other", "Where are settings?", 1001, sender=HELPER), now_ms=1001
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "Which version?",
            1002,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$other",
        ),
        now_ms=1002,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    assert snapshot.staff_reply_event_ids(["$one", "$staff"]) == ()
    assert await coordinator.claim(snapshot)
    assert await coordinator.record_gate(snapshot, decision(["$one", "$staff"]))
    assert not (
        await coordinator.service.repository.get_by_id(first.case_id)
    ).channel_metadata.get("conversation_staff_replied")


async def test_staff_native_reply_through_helper_persists_ownership(coordinator):
    first = await coordinator.ingest(
        turn("$one", "How do I connect?", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$helper",
            "Which operating system?",
            1001,
            sender=HELPER,
            reply_to_event_id="$one",
        ),
        now_ms=1001,
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "Please include the exact release.",
            1002,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$helper",
        ),
        now_ms=1002,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    assert snapshot.staff_reply_event_ids(["$one"]) == ("$staff",)
    assert snapshot.staff_replied and await coordinator.due(now_ms=12000) == []


async def test_observation_only_owner_question_waits_for_subscription_admission(
    coordinator,
):
    old = await old_request(coordinator)
    question = turn("$new", "How do I change the application language?", 3000)
    await coordinator.ingest(question, now_ms=3000, allow_new=False)
    before = await coordinator.service.repository.get_by_id(old)
    assert "$new" not in {
        item["event_id"] for item in before.channel_metadata["incident_messages"]
    }
    observed = await coordinator.ingest(question, now_ms=3000)
    assert observed.changed
    snapshot = await coordinator.snapshot(old, now_ms=13000)
    assert snapshot.kind == "admission" and snapshot.admission_event_ids == ("$new",)


async def test_unassigned_admission_events_have_explicit_staff_review_reason(
    coordinator,
):
    old = await old_request(coordinator)
    await coordinator.ingest(
        turn("$first", "How do maker fees work?", 3000), now_ms=3000
    )
    await coordinator.ingest(
        turn("$second", "Where is the language setting?", 3001), now_ms=3001
    )
    snapshot = await coordinator.snapshot(old, now_ms=13001)
    assert await coordinator.claim(snapshot)
    result = await coordinator.record_admission(snapshot, admission(ids=["$first"]))
    assert result.created
    parent = await coordinator.service.repository.get_by_id(old)
    assert parent.channel_metadata["conversation_unassigned_candidates"] == ["$second"]
    assert (
        parent.channel_metadata["context_reason"]
        == "unassigned_request_candidates_review_required"
    )
    assert parent.channel_metadata["context_status"] == "needs_human"
    child = await coordinator.service.repository.get_by_id(result.case_id)
    assert {row["event_id"] for row in child.channel_metadata["incident_messages"]} == {
        "$first"
    }


async def test_trimmed_high_numbered_alias_does_not_block_request(coordinator):
    first = await coordinator.ingest(
        turn("$one", "How do I connect?", 1000), now_ms=1000
    )
    await coordinator._change(
        first.case_id,
        conversation_speaker_aliases={
            REQUESTER: "requester",
            "@trimmed:example.org": "participant-100",
        },
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert not snapshot.overflow
    assert (
        selected_staff_request(snapshot, decision(["$one"]), []).question
        == "How do I connect?"
    )


@pytest.mark.parametrize("last_length,overflow", [(15999, False), (16000, True)])
async def test_question_capacity_counts_join_separator(
    coordinator, last_length, overflow
):
    first = await coordinator.ingest(turn("$one", "a" * 16000, 1000), now_ms=1000)
    await coordinator.ingest(
        turn("$two", "b" * last_length, 1001, reply_to_event_id="$one"), now_ms=1001
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11001)
    assert snapshot.overflow is overflow
    if not overflow:
        assert (
            len(
                selected_staff_request(
                    snapshot, decision(["$one", "$two"]), []
                ).question
            )
            == 32000
        )


@pytest.mark.parametrize(
    "text,valid",
    [("Thanks!", False), ("Okay!", False), ("Thanks, that fixed it", True)],
)
def test_resolution_requires_more_than_acknowledgement(text, valid):
    snapshot = RequestSnapshot(1, ROOM, REQUESTER, 1, (turn("$one", text, 1000),), 1000)
    response = decision(
        ["$one"], category="already_answered", resolved=True
    ).model_copy(update={"resolution_event_id": "$one"})
    service = RequestGateService(
        NS(invoke=Mock(return_value=NS(content=response.model_dump_json())))
    )
    if valid:
        assert service.classify(snapshot).request_resolved
    else:
        with pytest.raises(RequestGateError, match="invalid_conversation_gate"):
            service.classify(snapshot)


async def test_quiet_deadline_rechecked_inside_claim_even_when_revision_unchanged(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$one", "How do I connect?", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    await coordinator.ingest(turn("$ack", "Thanks!", 10999), now_ms=10999)
    after_ack = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert after_ack.revision == snapshot.revision
    assert after_ack.last_requester_at_ms == 10999 > snapshot.last_requester_at_ms
    assert not await coordinator.claim(snapshot)
    fresh = await coordinator.snapshot(first.case_id, now_ms=20999)
    assert await coordinator.claim(fresh)


async def test_attachment_only_intake_is_context_not_request_or_anchor(coordinator):
    result = await coordinator.ingest(
        turn("$image", "[Attachment unavailable]", 1000, non_text="m.image"),
        now_ms=1000,
    )
    assert result.case_id is None and await coordinator.due(now_ms=11000) == []
    request = await coordinator.ingest(
        turn("$one", "How do I connect?", 2000), now_ms=2000
    )
    await coordinator.ingest(
        turn(
            "$image2",
            "[Attachment unavailable]",
            2001,
            non_text="m.image",
            reply_to_event_id="$one",
        ),
        now_ms=2001,
    )
    snapshot = await coordinator.snapshot(request.case_id, now_ms=12001)
    assert snapshot.anchor.event_id == "$one"
    assert (
        "$image2"
        in selected_staff_request(
            snapshot, decision(["$one", "$image2"]), []
        ).conversation_coverage.attachment_event_ids
    )


async def test_fresh_bounded_page_invalidates_changed_older_selected_turn(runtime_case):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    coordinator = bundle.engine._conversation_coordinator()
    source = event(
        bundle, "$latest", "The application now shows an error", relation="$source"
    )
    source.server_timestamp += 1
    await bundle.engine._capture_conversation_turn(
        conversation_turn(SOURCE_ROOM, source, is_staff=False)
    )
    snapshot = await coordinator.snapshot(1, now_ms=source.server_timestamp + 1000)
    original = bundle.client.room_context.side_effect

    def read(*args, **kwargs):
        result = original(*args, **kwargs)
        result.events_after = [
            (
                NS(**{**vars(item), "body": "", "source": {"content": {}}})
                if item.event_id == "$source"
                else item
            )
            for item in result.events_after
        ]
        return result

    bundle.client.room_context.side_effect = read
    assert (
        await bundle.engine._verify_conversation_anchor(snapshot)
        == "source_changed_or_redacted"
    )
    refreshed = await coordinator.snapshot(1, now_ms=source.server_timestamp + 1000)
    assert "$source" not in {turn.event_id for turn in refreshed.turns}
    assert "$source" in refreshed.omitted_event_ids
    assert bundle.llm.invoke.call_count == 1


async def test_staff_hold_at_queued_draft_boundary_prevents_provider_and_slot(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    import app.channels.staff_assist.context_runtime as module

    real_to_thread = asyncio.to_thread
    intercepted = False

    async def to_thread(fn, *args, **kwargs):
        nonlocal intercepted
        if fn.__name__ == "generate_preview" and not intercepted:
            intercepted = True
            staff = event(
                bundle,
                "$staff",
                "Which release?",
                sender="@staff:example.org",
                relation="$source",
            )
            await bundle.engine._capture_conversation_turn(
                conversation_turn(SOURCE_ROOM, staff, is_staff=True)
            )
        return await real_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    bundle.llm.invoke = Mock(
        return_value=NS(
            content=json.dumps(gate(["$source", "$facts"])),
            usage={"input_tokens": 10, "output_tokens": 10},
        )
    )
    current = await incoming(
        bundle,
        event(
            bundle, "$facts", "The error appeared after updating", relation="$source"
        ),
    )
    assert intercepted and bundle.llm.invoke.call_count == 1
    assert current.channel_metadata.get("conversation_generation_count", 0) == 0
    assert current.channel_metadata["context_reason"] == "conversation_changed"
    bundle.sender.assert_not_awaited()


async def test_note_history_always_has_acknowledgement_time(runtime_case):
    current = await setup(runtime_case, [gate(["$source"]), draft()])
    history = current.channel_metadata["staff_note_history"]
    assert history[0]["event_id"] == "$staff-note"
    assert type(history[0]["acknowledged_at_ms"]) is int
    assert history[0]["acknowledged_at_ms"] > 0


async def test_pii_in_public_citation_blocks_complete_outbound_note(runtime_case):
    from tests.channels.test_context_runtime_integration import public_doc

    document = public_doc()
    document.metadata["url"] = "https://bisq.wiki/Mediation?contact=person@example.org"
    runtime_case.retrieve.return_value = ([document], [0.9])
    current = await setup(runtime_case, [gate(["$source"]), draft()])
    assert current.channel_metadata["context_reason"] == "context_pii_detected"
    assert current.channel_metadata["context_status"] == "needs_human"
    runtime_case.sender.assert_not_awaited()


async def test_promoted_worker_is_registered_before_staff_intake_and_owned_cleanup(
    runtime_case, monkeypatch
):
    from app.channels.models import SendResult

    from tests.channels.test_request_admission_runtime import boundary, submit

    bundle = runtime_case
    responses = [gate(["$source"]), draft()]
    old = await setup(bundle, responses)
    responses.extend([boundary(), gate(["$new"]), draft()])
    bundle.sender.side_effect = [
        SendResult(True, "$new-root"),
        SendResult(True, "$new-note"),
    ]
    original = bundle.engine._run_conversation
    observed = []

    async def worker(case_id, channel):
        if case_id != old.id:
            observed.append(
                (
                    case_id in bundle.engine._active_cases,
                    bundle.engine._conversation_workers.get(case_id)
                    is asyncio.current_task(),
                )
            )
        await original(case_id, channel)

    monkeypatch.setattr(bundle.engine, "_run_conversation", worker)
    await submit(bundle)
    assert observed == [(True, True)]
    new = await bundle.repository.get_by_id(old.id + 1)
    assert new.channel_metadata["context_status"] == "delivered"
    assert new.id not in bundle.engine._active_cases


async def test_stale_admission_guard_continues_new_unstarted_revision(
    runtime_case, monkeypatch
):
    import app.channels.staff_assist.context_runtime as module
    from app.channels.models import SendResult

    from tests.channels.test_request_admission_runtime import boundary, submit

    bundle = runtime_case
    responses = [gate(["$source"]), draft()]
    old = await setup(bundle, responses)
    responses.extend(
        [
            {**boundary(), "new_request_event_ids": ["$new", "$more"]},
            gate(["$new", "$more"]),
            draft(),
        ]
    )
    bundle.sender.side_effect = [
        SendResult(True, "$new-root"),
        SendResult(True, "$new-note"),
    ]
    original_thread = asyncio.to_thread
    changed = False

    async def dispatch(fn, *args, **kwargs):
        nonlocal changed
        if (
            isinstance(getattr(fn, "__self__", None), module.RequestAdmissionService)
            and not changed
        ):
            changed = True
            newer = event(bundle, "$more", "I mean the fee balance", relation="$new")
            await bundle.engine._capture_conversation_turn(
                conversation_turn(SOURCE_ROOM, newer, is_staff=False)
            )
        return await original_thread(fn, *args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", dispatch)
    await submit(bundle)
    assert changed
    new = await bundle.repository.get_by_id(old.id + 1)
    assert new.channel_metadata["context_status"] == "delivered"
    history = (await bundle.repository.get_by_id(old.id)).channel_metadata[
        "conversation_admission_history"
    ]
    assert len(history) == 2
    assert history[0]["failure"]["reason"] == "request_admission_changed"
    assert history[0]["failure"]["model_called"] is False
    assert history[1]["decision"]["relation"] == "new_request"
    assert bundle.llm.invoke.call_count == 5


async def test_snapshot_kind_race_uses_admission_classifier_not_request_gate(
    runtime_case, monkeypatch
):
    from app.channels.models import SendResult

    from tests.channels.test_request_admission_runtime import boundary

    bundle = runtime_case
    responses = [gate(["$source"]), draft()]
    old = await setup(bundle, responses)

    def respond(prompt, system_content):
        payload = json.loads(prompt)
        if "Decide whether a later requester" in system_content:
            response = boundary()
        elif "Classify a support-room conversation" in system_content:
            ids = [
                item["event_id"]
                for item in payload["messages"]
                if item["role"] == "requester"
            ]
            # The original follow-up also resumes after the separate admission.
            response = gate(
                ids,
                category=(
                    "already_answered"
                    if "$source" in ids
                    else "unanswered_support_request"
                ),
            )
        else:
            response = draft()
        return NS(
            content=json.dumps(response),
            usage={"input_tokens": 100, "output_tokens": 30},
        )

    bundle.llm.invoke.side_effect = respond
    bundle.sender.side_effect = [
        SendResult(True, "$new-root"),
        SendResult(True, "$new-note"),
    ]
    coordinator = bundle.engine._conversation_coordinator()
    original = coordinator.snapshot
    injected = False

    async def snapshot(case_id, *, now_ms):
        nonlocal injected
        if not injected and case_id == old.id:
            injected = True
            newer = event(
                bundle, "$new", "How do maker fees use the available balance?"
            )
            await bundle.engine._capture_conversation_turn(
                conversation_turn(SOURCE_ROOM, newer, is_staff=False)
            )
        return await original(case_id, now_ms=now_ms)

    monkeypatch.setattr(coordinator, "snapshot", snapshot)
    from tests.channels.test_context_conversation_live_independent import message

    await bundle.engine.process(
        message(
            bundle, event(bundle, "$followup", "It has now expired", relation="$source")
        ),
        bundle.channel,
    )
    await bundle.engine.drain()
    assert injected
    assert (
        "Decide whether a later requester"
        in bundle.llm.invoke.call_args_list[2].kwargs["system_content"]
    )
    new = await bundle.repository.get_by_id(old.id + 1)
    assert new.channel_metadata["context_status"] == "delivered"
