"""A Staff reply owns the request, even without resolution or an AI draft."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.context_conversation import StaffConversationCoordinator
from app.channels.staff_assist.context_gate import (
    RequestAdmissionDecision,
    RequestGateService,
)

from tests.channels.test_context_conversation_independent import (
    HELPER,
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
    setup,
)
from tests.channels.test_context_runtime_integration import (
    SOURCE_ROOM,
    no_public_delivery,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as base_runtime_case,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def coordinator(tmp_path):
    return await base_coordinator.__wrapped__(tmp_path)


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in base_runtime_case.__wrapped__(tmp_path):
        yield bundle


def classify(snapshot, ids, **kwargs):
    llm = NS(
        invoke=Mock(return_value=NS(content=decision(ids, **kwargs).model_dump_json()))
    )
    return RequestGateService(llm).classify(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", ["reply_to_event_id", "thread_root_event_id"])
async def test_native_staff_reply_before_first_gate_is_a_durable_hold(
    coordinator, relation
):
    first = await coordinator.ingest(
        turn("$request", "The application cannot connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "Which network is selected?",
            2000,
            sender=STAFF,
            is_staff=True,
            **{relation: "$request"},
        ),
        now_ms=2000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    assert snapshot.staff_replied
    assert snapshot.staff_reply_event_ids() == ("$staff",)
    assert not await coordinator.claim(snapshot)
    assert await coordinator.due(now_ms=12000) == []
    case = await coordinator.service.repository.get_by_id(first.case_id)
    assert not case.channel_metadata.get("conversation_resolved")
    assert not case.channel_metadata.get("conversation_generation_count")
    assert case.channel_metadata["conversation_staff_reply_event_ids"] == ["$staff"]
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    followup = await restarted.ingest(
        turn(
            "$facts",
            "The normal network; the error persists",
            13000,
            reply_to_event_id="$staff",
        ),
        now_ms=13000,
    )
    assert followup.case_id == first.case_id and not followup.created
    assert await restarted.due(now_ms=24000) == []


@pytest.mark.asyncio
async def test_unthreaded_selected_staff_assistance_prevents_initial_draft(coordinator):
    first = await coordinator.ingest(
        turn("$request", "How do I move my account to another computer?", 1000),
        now_ms=1000,
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "I am finding the migration guide for you",
            2000,
            sender=STAFF,
            is_staff=True,
        ),
        now_ms=2000,
    )
    snapshot = (await coordinator.due(now_ms=12000))[0]
    assert await coordinator.claim(snapshot)
    result = classify(snapshot, ["$request", "$staff"])
    assert result.category == "already_answered"
    assert result.reason == "staff_replied_to_request"
    assert not result.request_resolved
    assert not snapshot.should_draft(result)
    assert await coordinator.record_gate(snapshot, result)
    await coordinator.finish(snapshot)
    case = await coordinator.service.repository.get_by_id(first.case_id)
    assert case.channel_metadata["conversation_staff_replied"]
    assert not case.channel_metadata["conversation_resolved"]
    assert await coordinator.due(now_ms=22000) == []


@pytest.mark.asyncio
async def test_staff_who_replied_before_first_generation_also_blocks_update(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$request", "The trade confirmation failed", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$staff", "Which step is shown?", 2000, sender=STAFF, is_staff=True),
        now_ms=2000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    snapshot = replace(
        snapshot, kind="update", previous_generated_snapshot={"observed_at_ms": 10000}
    )
    result = classify(snapshot, ["$request", "$staff"])
    assert result.category == "already_answered"
    assert not snapshot.should_draft(result)


@pytest.mark.asyncio
async def test_unrelated_staff_presence_and_nonstaff_help_do_not_hold(coordinator):
    first = await coordinator.ingest(
        turn("$request", "The client cannot connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "I am helping a different user",
            2000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$somebody-else",
        ),
        now_ms=2000,
    )
    await coordinator.ingest(
        turn(
            "$helper",
            "Which network is selected?",
            3000,
            sender=HELPER,
            reply_to_event_id="$request",
        ),
        now_ms=3000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=13000)
    result = classify(snapshot, ["$request", "$helper"])
    assert result.category == "unanswered_support_request"
    assert snapshot.should_draft(result)
    assert await coordinator.claim(snapshot)


@pytest.mark.asyncio
async def test_old_staff_context_does_not_hold_an_explicit_distinct_request(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$old", "The application cannot connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "Which network is selected?",
            2000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$old",
        ),
        now_ms=2000,
    )
    second = await coordinator.ingest(
        turn("$new", "Different question: how do I change the display language?", 3000),
        now_ms=3000,
    )
    assert not second.created and second.case_id == first.case_id
    pending = await coordinator.snapshot(first.case_id, now_ms=13000)
    assert await coordinator.claim(pending)
    promoted = await coordinator.record_admission(
        pending,
        RequestAdmissionDecision(
            relation="new_request",
            new_request_event_ids=["$new"],
            reason="Distinct display question",
        ),
    )
    await coordinator.finish(pending)
    snapshot = await coordinator.snapshot(promoted.case_id, now_ms=13000)
    assert "$staff" not in {item.event_id for item in snapshot.turns}
    result = classify(snapshot, ["$new"])
    assert result.category == "unanswered_support_request"
    assert snapshot.should_draft(result)
    assert await coordinator.claim(snapshot)


@pytest.mark.asyncio
async def test_requester_edit_does_not_move_request_boundary_past_staff_reply(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$request", "The application cannot connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$staff", "Which network is selected?", 2000, sender=STAFF, is_staff=True),
        now_ms=2000,
    )
    await coordinator.ingest(
        turn(
            "$edit",
            "The application cannot connect on the normal network",
            3000,
            replaces_event_id="$request",
        ),
        now_ms=3000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=13000)
    assert snapshot.request_started_at_ms == 1000
    result = classify(snapshot, ["$edit", "$staff"])
    assert result.category == "already_answered"
    assert not snapshot.should_draft(result)


@pytest.mark.asyncio
async def test_staff_reply_between_snapshot_and_claim_blocks_stale_gate(coordinator):
    first = await coordinator.ingest(
        turn("$request", "The application cannot connect", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    await coordinator.ingest(
        turn(
            "$staff",
            "Please check the network",
            12000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$request",
        ),
        now_ms=12000,
    )
    assert not await coordinator.claim(snapshot)
    assert not await coordinator.is_current(snapshot)
    assert not await coordinator.record_gate(snapshot, decision(["$request"]))


@pytest.mark.asyncio
async def test_out_of_order_native_staff_reply_survives_trimming_and_restart(
    coordinator,
):
    await coordinator.ingest(
        turn(
            "$staff",
            "Which network is selected?",
            2000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$request",
        ),
        now_ms=3000,
    )
    first = await coordinator.ingest(
        turn("$request", "The application cannot connect", 1000), now_ms=3000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=13000)
    assert snapshot.staff_reply_event_ids() == ("$staff",)
    assert snapshot.staff_replied
    assert not await coordinator.claim(snapshot)
    assert await coordinator.due(now_ms=13000) == []
    for index in range(130):
        await coordinator.ingest(
            turn(
                f"$neighbor-{index}",
                "An unrelated room discussion",
                14000 + index,
                sender=STAFF,
                is_staff=True,
                reply_to_event_id="$other-request",
            ),
            now_ms=14000 + index,
        )
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    trimmed = await restarted.snapshot(first.case_id, now_ms=30000)
    assert "$staff" not in {item.event_id for item in trimmed.turns}
    assert trimmed.staff_replied
    assert not await restarted.claim(trimmed)
    assert await restarted.due(now_ms=30000) == []
    case = await restarted.service.repository.get_by_id(first.case_id)
    assert case.channel_metadata["conversation_staff_reply_event_ids"] == ["$staff"]
    assert not case.channel_metadata.get("conversation_resolved")


@pytest.mark.asyncio
async def test_gate_keeps_valid_explicit_requester_resolution(coordinator):
    first = await coordinator.ingest(
        turn("$request", "The application cannot connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$staff", "Please check the network", 2000, sender=STAFF, is_staff=True),
        now_ms=2000,
    )
    await coordinator.ingest(
        turn("$fixed", "That fixed the connection; this is resolved", 3000), now_ms=3000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=13000)
    raw = decision(
        ["$request", "$staff", "$fixed"], category="already_answered", resolved=True
    ).model_copy(update={"resolution_event_id": "$fixed"})
    service = RequestGateService(
        NS(invoke=Mock(return_value=NS(content=raw.model_dump_json())))
    )
    result = service.classify(snapshot)
    assert result.request_resolved and result.resolution_event_id == "$fixed"
    assert await coordinator.record_gate(snapshot, result)
    case = await coordinator.service.repository.get_by_id(first.case_id)
    assert case.channel_metadata["conversation_resolved"]


@pytest.mark.asyncio
async def test_live_native_staff_reply_prevents_first_note_and_additional_gate(
    runtime_case,
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    staff = event(
        bundle,
        "$staff-answer",
        "Which network is selected?",
        sender="@staff:example.org",
        relation="$source",
    )
    await bundle.engine.observe_source_event(
        SOURCE_ROOM, staff, bundle.channel, is_staff=True
    )
    case = await incoming(
        bundle,
        event(bundle, "$facts", "The normal network is selected", relation="$source"),
    )
    assert case.channel_metadata["conversation_staff_replied"]
    assert not case.channel_metadata.get("conversation_generation_count")
    assert bundle.llm.invoke.call_count == 1
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_live_selected_unthreaded_staff_prevents_first_note(runtime_case):
    bundle = runtime_case
    responses = [gate(["$source"], category="already_answered")]
    await setup(bundle, responses)
    staff = event(
        bundle,
        "$staff-answer",
        "I am looking up the procedure for you",
        sender="@staff:example.org",
    )
    await bundle.engine.observe_source_event(
        SOURCE_ROOM, staff, bundle.channel, is_staff=True
    )
    responses.append(gate(["$source", "$staff-answer", "$facts"]))
    case = await incoming(
        bundle, event(bundle, "$facts", "The installed version is current")
    )
    assert case.channel_metadata["conversation_staff_replied"]
    assert case.channel_metadata["conversation_gate"]["category"] == "already_answered"
    assert not case.channel_metadata.get("conversation_generation_count")
    assert not case.channel_metadata["conversation_resolved"]
    assert bundle.llm.invoke.call_count == 2
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_staff_reply_during_initial_draft_stops_publication(runtime_case):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    loop = asyncio.get_running_loop()

    def generate(_prompt, system_content):
        if "Classify a support-room conversation" in system_content:
            body = gate(["$source", "$facts"])
        else:
            staff = event(
                bundle,
                "$staff-answer",
                "I will help with this trade",
                sender="@staff:example.org",
                relation="$facts",
            )
            asyncio.run_coroutine_threadsafe(
                bundle.engine.observe_source_event(
                    SOURCE_ROOM, staff, bundle.channel, is_staff=True
                ),
                loop,
            ).result(timeout=3)
            body = draft()
        return NS(
            content=json.dumps(body), usage={"input_tokens": 100, "output_tokens": 30}
        )

    bundle.llm.invoke = Mock(side_effect=generate)
    case = await incoming(bundle, event(bundle, "$facts", "The trade period expired"))
    assert case.channel_metadata["conversation_staff_replied"]
    assert case.channel_metadata["conversation_generation_count"] == 1
    bundle.sender.assert_not_awaited()
    assert bundle.llm.invoke.call_count == 2
    await incoming(
        bundle,
        event(bundle, "$more", "The payment is now confirmed", relation="$facts"),
    )
    assert bundle.llm.invoke.call_count == 2
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)
