"""Independent synthetic checks for request identity and chronology boundaries."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.context_conversation import (
    ConversationTurn,
    StaffConversationCoordinator,
    effective_turns,
    selected_staff_request,
)
from app.channels.staff_assist.context_gate import (
    RequestGateDecision,
    RequestGateError,
    RequestGateService,
)
from app.services.escalation.escalation_repository import EscalationRepository
from app.services.escalation.escalation_service import EscalationService

pytestmark = pytest.mark.unit

ROOM = "!synthetic-support:example.org"
REQUESTER = "@requester:example.org"
HELPER = "@helper:example.org"
STAFF = "@staff:example.org"


def turn(event_id, text, at, *, sender=REQUESTER, **kwargs):
    return ConversationTurn(ROOM, event_id, sender, at, text, **kwargs)


def decision(
    ids, *, category="unanswered_support_request", material=True, resolved=False
):
    return RequestGateDecision(
        category=category,
        selected_event_ids=ids,
        request_summary="A synthetic request",
        material_change=material,
        request_resolved=resolved,
        reason="Synthetic classification",
    )


@pytest.fixture
async def coordinator(tmp_path):
    repository = EscalationRepository(str(tmp_path / "escalations.db"))
    await repository.initialize()
    service = EscalationService(
        repository, None, None, None, NS(ESCALATION_CLAIM_TTL_MINUTES=30)
    )
    return StaffConversationCoordinator(
        service, "synthetic-conversations", first_response_delay_seconds=10
    )


@pytest.mark.asyncio
async def test_fragment_and_product_followup_share_request_and_restart_quiet_time(
    coordinator,
):
    first = await coordinator.ingest(
        turn("$one", "my trade is stuck", 1000), now_ms=1000
    )
    followup = await coordinator.ingest(
        turn("$two", "bisq 1, deposit confirmed but nothing happens", 9000), now_ms=9000
    )
    assert followup.case_id == first.case_id
    assert not followup.created
    assert await coordinator.due(now_ms=18000) == []
    snapshots = await coordinator.due(now_ms=19000)
    assert len(snapshots) == 1
    assert [item.event_id for item in snapshots[0].turns] == ["$one", "$two"]


@pytest.mark.asyncio
async def test_native_helper_keeps_requester_identity_and_attributed_text(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    helper = await coordinator.ingest(
        turn(
            "$help",
            "Which network is selected?",
            2000,
            sender=HELPER,
            reply_to_event_id="$one",
        ),
        now_ms=2000,
    )
    assert helper.case_id == first.case_id and not helper.created
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    request = selected_staff_request(snapshot, decision(["$one", "$help"]), [])
    assert snapshot.requester_id == REQUESTER
    assert request.question == "The client does not connect"
    assert request.recent_messages[0].role == "user"
    assert request.recent_messages[0].speaker == "requester"
    assert request.recent_messages[1].role == "participant"
    helper_alias = next(
        row["speaker"]
        for row in snapshot.prompt_payload()["messages"]
        if row["event_id"] == "$help"
    )
    assert helper_alias != "requester"
    assert request.recent_messages[1].speaker == helper_alias


@pytest.mark.asyncio
async def test_speaker_alias_remains_stable_when_neighborhood_changes(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$helper", "Which release?", 3000, sender=HELPER, reply_to_event_id="$one"
        ),
        now_ms=3000,
    )
    before = await coordinator.snapshot(first.case_id, now_ms=12000)
    another = turn(
        "$neighbor", "Separate discussion", 2000, sender="@another:example.org"
    )
    after = replace(
        before,
        turns=tuple(
            sorted([*before.turns, another], key=lambda item: item.timestamp_ms)
        ),
    )
    labels = []
    for snapshot in (before, after):
        labels.append(
            next(
                row["speaker"]
                for row in snapshot.prompt_payload()["messages"]
                if row["event_id"] == "$helper"
            )
        )
    assert labels[0] == labels[1]


@pytest.mark.asyncio
async def test_unrelated_staff_is_context_and_does_not_resolve_request(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    staff = await coordinator.ingest(
        turn(
            "$staff",
            "The weekly meeting starts tomorrow",
            3000,
            sender=STAFF,
            is_staff=True,
        ),
        now_ms=3000,
    )
    assert not staff.created
    snapshot = (await coordinator.due(now_ms=11000))[0]
    assert snapshot.case_id == first.case_id
    assert any(item.is_staff for item in snapshot.turns)
    await coordinator.record_gate(snapshot, decision(["$one"]))
    assert await coordinator.is_current(snapshot)


@pytest.mark.asyncio
async def test_forged_edit_cannot_change_requester_text(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$forged",
            "Everything is now solved",
            2000,
            sender=HELPER,
            replaces_event_id="$one",
        ),
        now_ms=2000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=3000)
    assert [item.text for item in snapshot.turns if item.sender_id == REQUESTER] == [
        "The client does not connect"
    ]
    assert "Everything is now solved" not in json.dumps(snapshot.prompt_payload())


def test_author_edit_preserves_original_native_relationship():
    original = turn(
        "$answer",
        "First observation",
        1000,
        reply_to_event_id="$root",
        thread_root_event_id="$root",
    )
    edit = turn("$edit", "Corrected observation", 2000, replaces_event_id="$answer")
    projected = effective_turns([original, edit])
    assert len(projected) == 1 and projected[0].text == "Corrected observation"
    assert projected[0].reply_to_event_id == "$root"
    assert projected[0].thread_root_event_id == "$root"


@pytest.mark.asyncio
async def test_future_turn_is_rejected_and_snapshot_never_peeks_ahead(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    with pytest.raises(ValueError, match="Future"):
        await coordinator.ingest(turn("$future", "The fix worked", 3000), now_ms=2000)
    await coordinator.ingest(turn("$later", "The fix worked", 3000), now_ms=3000)
    earlier = await coordinator.snapshot(first.case_id, now_ms=2000)
    assert [item.event_id for item in earlier.turns] == ["$one"]


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [["$forged"], ["$one", "$one"], ["$helper"]])
async def test_gate_rejects_forged_duplicate_or_nonrequester_only_selection(
    coordinator, selected
):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$helper", "My application is working", 2000, sender=HELPER), now_ms=2000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    llm = NS(invoke=Mock(return_value=NS(content=decision(selected).model_dump_json())))
    with pytest.raises(RequestGateError, match="invalid_conversation_gate"):
        RequestGateService(llm).classify(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,selected",
    [
        ("unanswered_support_request", ["$one"]),
        ("already_answered", ["$staff"]),
    ],
)
async def test_gate_resolution_needs_consistent_category_and_requester_evidence(
    coordinator, category, selected
):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn("$staff", "Try reconnecting", 2000, sender=STAFF, is_staff=True),
        now_ms=2000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=12000)
    llm = NS(
        invoke=Mock(
            return_value=NS(
                content=decision(
                    selected, category=category, resolved=True
                ).model_dump_json()
            )
        )
    )
    with pytest.raises(RequestGateError, match="invalid_conversation_gate"):
        RequestGateService(llm).classify(snapshot)


@pytest.mark.asyncio
async def test_duplicate_after_restart_does_not_change_revision(coordinator):
    event = turn("$one", "The client does not connect", 1000)
    first = await coordinator.ingest(event, now_ms=1000)
    before = await coordinator.snapshot(first.case_id, now_ms=11000)
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    duplicate = await restarted.ingest(event, now_ms=12000)
    after = await restarted.snapshot(first.case_id, now_ms=12000)
    assert not duplicate.created and not duplicate.changed
    assert before.version == after.version


@pytest.mark.asyncio
async def test_observed_neighbor_can_later_enter_as_real_request(coordinator):
    await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    neighbor = turn(
        "$other-request", "My application has a startup error", 2000, sender=HELPER
    )
    context_only = await coordinator.ingest(neighbor, now_ms=3000, allow_new=False)
    assert not context_only.created
    subscription = await coordinator.ingest(neighbor, now_ms=3000)
    assert subscription.created and subscription.case_id is not None
    snapshot = await coordinator.snapshot(subscription.case_id, now_ms=13000)
    assert snapshot.requester_id == HELPER
    assert [item.event_id for item in snapshot.turns if item.sender_id == HELPER] == [
        "$other-request"
    ]


@pytest.mark.asyncio
async def test_cross_coordinator_claim_has_one_winner(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    other = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    winners = await asyncio.gather(coordinator.claim(snapshot), other.claim(snapshot))
    assert sum(winners) == 1


@pytest.mark.asyncio
async def test_closed_case_cannot_claim_a_previously_due_snapshot(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    await coordinator.service.close_escalation(first.case_id)
    assert not await coordinator.claim(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_restart_never_retries_claimed_or_uncertain_work(coordinator, uncertain):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert await coordinator.claim(snapshot)
    if uncertain:
        await coordinator.finish(snapshot, uncertain=True)
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    assert await restarted.due(now_ms=100000) == []
    assert not await restarted.claim(snapshot)


@pytest.mark.asyncio
async def test_stale_gate_result_cannot_resolve_new_requester_facts(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The client does not connect", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert await coordinator.claim(snapshot)
    await coordinator.ingest(
        turn("$new", "Now it shows an error after login", 12000), now_ms=12000
    )
    await coordinator.record_gate(
        snapshot, decision(["$one"], category="already_answered")
    )
    await coordinator.finish(snapshot)
    assert not await coordinator.is_current(snapshot)
    due = await coordinator.due(now_ms=22000)
    assert len(due) == 1 and due[0].case_id == first.case_id


@pytest.mark.asyncio
async def test_resolved_request_facts_do_not_leak_into_new_request(coordinator):
    first = await coordinator.ingest(
        turn("$old", "The application did not start", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    await coordinator.record_gate(
        snapshot, decision(["$old"], category="already_answered", resolved=True)
    )
    second = await coordinator.ingest(
        turn("$new", "How can I change the display language?", 20000), now_ms=20000
    )
    assert second.created and second.case_id != first.case_id
    current = await coordinator.snapshot(second.case_id, now_ms=30000)
    assert [item.event_id for item in current.turns if item.sender_id == REQUESTER] == [
        "$new"
    ]


@pytest.mark.asyncio
async def test_staff_answer_is_not_requester_resolution(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The application does not start", 1000), now_ms=1000
    )
    await coordinator.ingest(
        turn(
            "$staff",
            "Which release is installed?",
            2000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$one",
        ),
        now_ms=2000,
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    await coordinator.record_gate(
        snapshot, decision(["$one", "$staff"], category="already_answered")
    )
    followup = await coordinator.ingest(
        turn("$two", "Version 2.1.9; the startup error still happens", 12000),
        now_ms=12000,
    )
    assert followup.case_id == first.case_id and not followup.created
    due = await coordinator.due(now_ms=22000)
    assert len(due) == 1 and due[0].case_id == first.case_id


@pytest.mark.asyncio
async def test_obvious_thanks_attaches_without_scheduling_a_new_gate(coordinator):
    first = await coordinator.ingest(
        turn("$one", "The application does not start", 1000), now_ms=1000
    )
    snapshot = await coordinator.snapshot(first.case_id, now_ms=11000)
    assert await coordinator.claim(snapshot)
    await coordinator.record_gate(snapshot, decision(["$one"]))
    await coordinator.record_draft(snapshot, NS(model_called=True))
    await coordinator.finish(snapshot)
    thanks = await coordinator.ingest(turn("$thanks", "Thanks!", 12000), now_ms=12000)
    assert thanks.case_id == first.case_id and not thanks.created
    current = await coordinator.snapshot(first.case_id, now_ms=22000)
    assert any(item.event_id == "$thanks" for item in current.turns)
    assert await coordinator.due(now_ms=22000) == []
