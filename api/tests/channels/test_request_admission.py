"""Later distinct requests require a bounded, durable semantic admission."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.context_conversation import StaffConversationCoordinator
from app.channels.staff_assist.context_gate import (
    RequestAdmissionDecision,
    RequestAdmissionService,
    RequestGateError,
)
from app.models.escalation import EscalationUpdate

from tests.channels.test_context_conversation_independent import STAFF
from tests.channels.test_context_conversation_independent import coordinator as base
from tests.channels.test_context_conversation_independent import decision, turn

pytestmark = pytest.mark.unit


@pytest.fixture
async def coordinator(tmp_path):
    return await base.__wrapped__(tmp_path)


def admission(relation="new_request", ids=None):
    return RequestAdmissionDecision(
        relation=relation,
        new_request_event_ids=(
            ids if ids is not None else ["$new"] if relation == "new_request" else []
        ),
        reason="The requester asks about a distinct procedure.",
    )


async def old_request(coordinator, condition="capped"):
    intake = await coordinator.ingest(
        turn("$old", "The application cannot connect", 1000), now_ms=1000
    )
    if condition == "capped":
        await coordinator._change(intake.case_id, conversation_generation_count=2)
    elif condition == "staff":
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
    elif condition == "resolved":
        await coordinator._change(intake.case_id, conversation_resolved=True)
    elif condition == "closed":
        await coordinator.service.repository.update(
            intake.case_id, EscalationUpdate(status="closed")
        )
    return intake.case_id


async def candidate(coordinator, at=3000):
    result = await coordinator.ingest(
        turn("$new", "How do maker fees use my wallet balance?", at), now_ms=at
    )
    assert not result.created
    return await coordinator.snapshot(result.case_id, now_ms=at + 10000)


@pytest.mark.parametrize("condition", ["capped", "staff", "resolved", "closed"])
async def test_distinct_request_requires_gate_and_preserves_old_case(
    coordinator, condition
):
    old_id = await old_request(coordinator, condition)
    before = await coordinator.service.repository.get_by_id(old_id)
    snapshot = await candidate(coordinator)
    assert snapshot.kind == "admission"
    assert [
        t.event_id for t in snapshot.turns if t.sender_id == snapshot.requester_id
    ] == ["$new"]
    assert await coordinator.claim(snapshot)
    result = await coordinator.record_admission(snapshot, admission())
    await coordinator.finish(snapshot)
    assert result.created and result.case_id != old_id
    old = await coordinator.service.repository.get_by_id(old_id)
    for key in [
        "incident_messages",
        "conversation_generation_count",
        "conversation_staff_replied",
        "conversation_resolved",
    ]:
        assert old.channel_metadata.get(key) == before.channel_metadata.get(key)
    assert old.status == before.status
    new = await coordinator.service.repository.get_by_id(result.case_id)
    assert new.channel_metadata["conversation_admitted_from_case_id"] == old_id
    assert new.channel_metadata.get("conversation_generation_count", 0) == 0
    current = await coordinator.snapshot(new.id, now_ms=13000)
    assert current.kind == "note" and not current.staff_replied
    assert current.version != snapshot.version
    assert [
        t.event_id for t in current.turns if t.sender_id == current.requester_id
    ] == ["$new"]
    assert await coordinator.claim(current)


async def test_time_gap_and_keyword_never_create_a_case_without_gate(coordinator):
    old_id = await old_request(coordinator)
    result = await coordinator.ingest(
        turn("$new", "New question: is this still stuck?", 1000000000),
        now_ms=1000000000,
    )
    assert not result.created and result.case_id == old_id
    snapshot = await coordinator.snapshot(old_id, now_ms=1000010000)
    assert await coordinator.claim(snapshot)
    await coordinator.record_admission(snapshot, admission("same_request"))
    await coordinator.finish(snapshot)
    assert len(await coordinator._rows()) == 1
    assert await coordinator.due(now_ms=1000020000) == []


@pytest.mark.parametrize(
    "content", ["Thanks!", "Different question: it is still failing"]
)
async def test_native_followup_never_bypasses_staff_or_cap(coordinator, content):
    old_id = await old_request(coordinator, "staff")
    result = await coordinator.ingest(
        turn("$followup", content, 500000000, reply_to_event_id="$old"),
        now_ms=500000000,
    )
    assert not result.created and result.case_id == old_id
    case = await coordinator.service.repository.get_by_id(old_id)
    assert not case.channel_metadata.get("conversation_admission_pending")
    assert await coordinator.due(now_ms=500010000) == []


async def test_unclear_is_settled_without_new_case_or_retry(coordinator):
    old_id = await old_request(coordinator)
    snapshot = await candidate(coordinator)
    assert await coordinator.claim(snapshot)
    await coordinator.record_admission(snapshot, admission("unclear"))
    await coordinator.finish(snapshot)
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    assert await restarted.due(now_ms=30000) == []
    assert not await restarted.claim(snapshot)
    again = await restarted.record_admission(snapshot, admission())
    assert not again.created
    case = await restarted.service.repository.get_by_id(old_id)
    assert (
        case.channel_metadata["conversation_admission_observed"][0]["event_id"]
        == "$new"
    )
    assert len(case.channel_metadata["conversation_admission_history"]) == 1


async def test_parallel_claim_and_promotion_create_only_one_case(coordinator):
    await old_request(coordinator)
    snapshot = await candidate(coordinator)
    other = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    assert sorted(
        await asyncio.gather(coordinator.claim(snapshot), other.claim(snapshot))
    ) == [False, True]
    results = await asyncio.gather(
        coordinator.record_admission(snapshot, admission()),
        other.record_admission(snapshot, admission()),
    )
    assert sum(result.created for result in results) == 1
    assert len(await coordinator._rows()) == 2


async def test_pending_claim_after_restart_never_replays_provider(coordinator):
    await old_request(coordinator)
    snapshot = await candidate(coordinator)
    assert await coordinator.claim(snapshot)
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    assert not await restarted.claim(snapshot)
    assert await restarted.due(now_ms=30000) == []
    await coordinator.record_admission(
        snapshot, failure={"reason": "timeout", "uncertain": True}
    )
    await coordinator.finish(snapshot, uncertain=True)
    await restarted.ingest(
        turn("$later", "Another issue with the display", 40000), now_ms=40000
    )
    assert await restarted.due(now_ms=50000) == []


async def test_pending_boundary_cannot_bypass_old_delivery_uncertainty(coordinator):
    old_id = await old_request(coordinator)
    snapshot = await candidate(coordinator)
    await coordinator._change(old_id, conversation_delivery_uncertain=True)
    assert not await coordinator.claim(snapshot)
    assert await coordinator.due(now_ms=30000) == []


async def test_changed_candidates_cannot_promote_stale_decision(coordinator):
    old_id = await old_request(coordinator)
    snapshot = await candidate(coordinator)
    assert await coordinator.claim(snapshot)
    await coordinator.ingest(
        turn("$correction", "That is a followup to the same failed connection", 14000),
        now_ms=14000,
    )
    assert coordinator.admission_call_guard(snapshot) == "request_admission_changed"
    result = await coordinator.record_admission(snapshot, admission())
    await coordinator.finish(snapshot)
    assert not result.created and len(await coordinator._rows()) == 1
    updated = await coordinator.snapshot(old_id, now_ms=24000)
    assert set(updated.admission_event_ids) == {"$new", "$correction"}
    assert updated.version != snapshot.version


async def test_concurrent_candidate_intake_preserves_both_events(coordinator):
    old_id = await old_request(coordinator)
    other = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    await asyncio.gather(
        coordinator.ingest(turn("$a", "How do maker fees work?", 3000), now_ms=3000),
        other.ingest(turn("$b", "Which balance funds them?", 3000), now_ms=3000),
    )
    snapshot = await coordinator.snapshot(old_id, now_ms=13000)
    assert set(snapshot.admission_event_ids) == {"$a", "$b"}


async def test_acknowledgement_cannot_supply_new_request_proof(coordinator):
    old_id = await old_request(coordinator)
    await candidate(coordinator)
    await coordinator.ingest(turn("$thanks", "Thanks!", 4000), now_ms=4000)
    snapshot = await coordinator.snapshot(old_id, now_ms=14000)
    llm = Mock()
    llm.invoke.return_value = NS(content=admission(ids=["$thanks"]).model_dump_json())
    with pytest.raises(RequestGateError, match="invalid_request_admission"):
        RequestAdmissionService(llm).classify(snapshot)
    assert await coordinator.claim(snapshot)
    with pytest.raises(ValueError, match="invalid_admission_requester_evidence"):
        await coordinator.record_admission(snapshot, admission(ids=["$thanks"]))
    assert len(await coordinator._rows()) == 1


async def test_promoted_request_preserves_native_staff_hold_across_trim(coordinator):
    old_id = await old_request(coordinator)
    await candidate(coordinator)
    await coordinator.ingest(
        turn(
            "$new-staff",
            "Which fee mode?",
            4000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$new",
        ),
        now_ms=4000,
    )
    snapshot = await coordinator.snapshot(old_id, now_ms=14000)
    assert await coordinator.claim(snapshot)
    created = await coordinator.record_admission(snapshot, admission())
    await coordinator.finish(snapshot)
    child = await coordinator.service.repository.get_by_id(created.case_id)
    assert child.channel_metadata["conversation_staff_replied"] is True
    assert child.channel_metadata["conversation_staff_reply_event_ids"] == [
        "$new-staff"
    ]
    await coordinator._change(created.case_id, conversation_exchange=[])
    restarted = StaffConversationCoordinator(
        coordinator.service, coordinator.trial_id, first_response_delay_seconds=10
    )
    assert await restarted.due(now_ms=50000) == []


@pytest.mark.parametrize("native", [False, True])
async def test_edit_retains_intervening_staff_assistance(coordinator, native):
    old_id = await old_request(coordinator)
    await candidate(coordinator)
    await coordinator.ingest(
        turn(
            "$intervening-staff",
            "Which fee mode is selected?",
            4000,
            sender=STAFF,
            is_staff=True,
            reply_to_event_id="$new" if native else None,
        ),
        now_ms=4000,
    )
    await coordinator.ingest(
        turn(
            "$edited",
            "How do maker fees work with this wallet?",
            5000,
            replaces_event_id="$new",
        ),
        now_ms=5000,
    )
    snapshot = await coordinator.snapshot(old_id, now_ms=15000)
    assert snapshot.request_started_at_ms == 3000
    assert "$intervening-staff" in {turn.event_id for turn in snapshot.turns}
    assert await coordinator.claim(snapshot)
    result = await coordinator.record_admission(snapshot, admission(ids=["$edited"]))
    await coordinator.finish(snapshot)
    child = await coordinator.snapshot(result.case_id, now_ms=15000)
    assert child.request_started_at_ms == 3000
    assert child.staff_reply_event_ids(["$edited", "$intervening-staff"]) == (
        "$intervening-staff",
    )
    if native:
        current = await coordinator.service.repository.get_by_id(result.case_id)
        assert current.channel_metadata["conversation_staff_replied"]


@pytest.mark.parametrize("ids", [["$old"], ["$staff"], ["$new", "$new"], []])
async def test_new_request_needs_exact_candidate_requester_proof(coordinator, ids):
    await old_request(coordinator, "staff")
    snapshot = await candidate(coordinator)
    service = RequestAdmissionService(
        NS(invoke=Mock(return_value=NS(content=admission(ids=ids).model_dump_json())))
    )
    with pytest.raises(RequestGateError, match="invalid_request_admission"):
        service.classify(snapshot)


async def test_helper_only_update_has_no_new_requester_facts(coordinator):
    old_id = await old_request(coordinator, "open")
    snapshot = await coordinator.snapshot(old_id, now_ms=11000)
    await coordinator.record_draft(
        snapshot,
        NS(model_called=True, rendered_note="A draft"),
        selected_event_ids=["$old"],
    )
    await coordinator.ingest(
        turn(
            "$helper",
            "I see the same symptom",
            12000,
            sender="@helper:example.org",
            reply_to_event_id="$old",
        ),
        now_ms=12000,
    )
    update = await coordinator.snapshot(old_id, now_ms=22000)
    assert not update.has_new_requester_facts
    assert not update.should_draft(decision(["$old", "$helper"], material=True))
