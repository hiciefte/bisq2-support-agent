"""Synthetic role boundaries through real intake, SQLite and frozen delivery."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from app.channels.models import SendResult
from app.channels.staff_assist.context_runtime import MatrixContextRuntime
from app.models.escalation import EscalationStatus

from tests.channels.test_context_conversations_acceptance import (
    HELPER,
    OTHER,
    REQUESTER,
    all_cases,
    assert_no_paid_work,
    assert_single_delivery,
    authoritative_timeline,
)
from tests.channels.test_context_conversations_acceptance import (
    conversation as existing_conversation,
)
from tests.channels.test_context_conversations_acceptance import (
    hold_worker,
    incoming,
    no_public_delivery,
    process_all,
    reservations,
)

pytestmark = pytest.mark.unit

QUESTION = "What does LedgerSyncError mean for my wallet connection?"
HELP = "Check the wallet connection panel for the LedgerSyncError status."


@pytest.fixture
async def conversation(tmp_path):
    async for bundle in existing_conversation.__wrapped__(tmp_path):
        yield bundle


def requester_and_helper(bundle):
    return [
        incoming(bundle, "$request", QUESTION),
        incoming(
            bundle, "$helper-answer", HELP, user=HELPER, reply_to_event_id="$request"
        ),
    ]


@pytest.mark.asyncio
async def test_helper_in_two_conversations_keeps_both_candidates_without_merging(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    initial = requester_and_helper(bundle)
    initial.extend(
        [
            incoming(
                bundle,
                "$other-request",
                "My wallet also reports LedgerSyncError. How can I reconnect it?",
                user=OTHER,
            ),
            incoming(
                bundle,
                "$other-helper-answer",
                HELP,
                user=HELPER,
                reply_to_event_id="$other-request",
            ),
        ]
    )
    advice = incoming(
        bundle,
        "$ambiguous-advice",
        "Also check the wallet connection panel before trying another connection.",
        user=HELPER,
    )
    authoritative_timeline(bundle, [*initial, advice])
    bundle.sender.side_effect = lambda *args, **kwargs: SendResult(
        True, f"$staff-{bundle.sender.await_count}"
    )
    await process_all(bundle, initial)
    release.set()
    await bundle.engine.drain()
    originals = await all_cases(bundle)
    assert len(originals) == 2
    assert all(
        case.channel_metadata["context_status"] == "delivered" for case in originals
    )
    snapshots = {case.id: case.channel_metadata for case in originals}

    await process_all(bundle, [advice, advice])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 3
    held = next(case for case in cases if case.id not in snapshots)
    assert held.channel_metadata["conversation_membership"] == "provisional"
    assert (
        held.channel_metadata["context_reason"] == "conversation_membership_unresolved"
    )
    assert set(held.channel_metadata["candidate_conversation_ids"]) == set(snapshots)
    assert not held.channel_metadata.get("conversation_requester_id")
    assert not held.channel_metadata["model_called"]
    assert not held.channel_metadata.get("staff_root_event_id")
    assert [
        message["event_id"] for message in held.channel_metadata["incident_messages"]
    ] == [advice.message_id]
    for case in cases:
        if case.id not in snapshots:
            continue
        assert (
            case.channel_metadata["incident_messages"]
            == snapshots[case.id]["incident_messages"]
        )
        assert (
            case.channel_metadata["incident_generation_event_ids"]
            == snapshots[case.id]["incident_generation_event_ids"]
        )
        assert held.id in case.channel_metadata["conversation_pending_candidate_ids"]
    assert reservations(bundle) == bundle.llm.invoke.call_count == 2
    assert bundle.sender.await_count == 4
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_second_helper_advice_and_own_edit_cannot_activate_provisional_case(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = [
        incoming(
            bundle,
            "$diagnostic-question",
            "Have you checked the wallet connection panel?",
            user=HELPER,
        ),
        incoming(
            bundle,
            "$second-helper-advice",
            "Try reconnecting the wallet before checking the connection panel.",
            user=OTHER,
            reply_to_event_id="$diagnostic-question",
        ),
        incoming(
            bundle,
            "$second-helper-edit",
            "My wallet still reports LedgerSyncError.",
            user=OTHER,
            replaces_event_id="$second-helper-advice",
        ),
        incoming(
            bundle,
            "$second-helper-statement",
            "My wallet now reports LedgerSyncError after reconnecting.",
            user=OTHER,
            reply_to_event_id="$diagnostic-question",
        ),
        incoming(
            bundle,
            "$actual-request",
            "My wallet reports LedgerSyncError and cannot connect. How can I recover?",
            reply_to_event_id="$diagnostic-question",
        ),
    ]
    authoritative_timeline(bundle, messages)
    for message in messages[:-1]:
        await process_all(bundle, [message])
        cases = await all_cases(bundle)
        assert len(cases) == 1
        held = cases[0]
        assert held.channel_metadata["conversation_membership"] == "provisional"
        assert not held.channel_metadata.get("conversation_requester_id")
        assert not held.channel_metadata.get("incident_frozen")
        assert_no_paid_work(bundle)

    original_id = held.id
    await process_all(bundle, [messages[-1], messages[-1]])
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    case = cases[0]
    assert case.id == original_id
    assert case.user_id == HELPER
    assert_single_delivery(bundle, case)
    assert [
        message["sender_id"] for message in case.channel_metadata["incident_messages"]
    ] == [
        HELPER,
        OTHER,
        OTHER,
        OTHER,
        REQUESTER,
    ]
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert prompt["question"] == messages[-1].question
    for context in prompt["recent_messages"]:
        if context["content"] in (messages[2].question, messages[3].question):
            assert context["role"] == "participant"
            assert context["speaker"] != "requester"


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["room", "trial", "idle", "hard_age", "closed"])
async def test_prior_helper_role_does_not_leak_outside_eligible_conversation(
    conversation, boundary
):
    bundle = conversation
    release = hold_worker(bundle)
    initial = requester_and_helper(bundle)
    # A neutral standalone statement is not itself positive advisory syntax.
    # Only a live conversation-local helper role could turn it into a hold.
    neutral = incoming(
        bundle,
        "$neutral",
        "The wallet status is described in the connection panel.",
        user=HELPER,
    )
    authoritative_timeline(bundle, [*initial, neutral])
    bundle.sender.side_effect = lambda *args, **kwargs: SendResult(
        True, f"$staff-{bundle.sender.await_count}"
    )
    await process_all(bundle, initial)
    release.set()
    await bundle.engine.drain()
    original = (await all_cases(bundle))[0]
    assert original.channel_metadata["context_status"] == "delivered"

    metadata = dict(original.channel_metadata)
    now = datetime.now(timezone.utc)
    created_at = original.created_at.isoformat()
    if boundary == "room":
        metadata["room_id"] = "!another-room:example.org"
    elif boundary == "trial":
        metadata["context_trial_id"] = "another-trial"
    elif boundary == "idle":
        created_at = (now - timedelta(minutes=30)).isoformat()
        metadata["incident_last_meaningful_at"] = (
            now - timedelta(minutes=16)
        ).isoformat()
    elif boundary == "hard_age":
        created_at = (now - timedelta(hours=1, minutes=1)).isoformat()
        metadata["incident_last_meaningful_at"] = now.isoformat()
    else:
        await bundle.service.close_escalation(original.id)
    with closing(sqlite3.connect(bundle.repository.db_path)) as connection:
        connection.execute(
            "UPDATE escalations SET channel_metadata=?, created_at=? WHERE id=?",
            (json.dumps(metadata), created_at, original.id),
        )
        connection.commit()

    await process_all(bundle, [neutral])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 2
    old = next(case for case in cases if case.id == original.id)
    current = next(case for case in cases if case.id != original.id)
    assert old.channel_metadata["incident_messages"] == metadata["incident_messages"]
    assert not old.channel_metadata.get("conversation_pending_candidate_ids")
    if boundary == "closed":
        assert old.status == EscalationStatus.CLOSED
    assert current.channel_metadata["conversation_membership"] == "confirmed"
    assert current.channel_metadata["conversation_requester_id"] == HELPER
    assert not current.channel_metadata.get("candidate_conversation_ids")
    assert current.channel_metadata["context_status"] == "delivered"
    assert reservations(bundle) == bundle.llm.invoke.call_count == 2
    assert bundle.sender.await_count == 4
    no_public_delivery(bundle)


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["native", "unique_quote"])
async def test_late_linked_helper_advice_and_ack_keep_one_frozen_delivery(
    conversation, link
):
    bundle = conversation
    release = hold_worker(bundle)
    initial = requester_and_helper(bundle)
    advice = "Check the wallet connection panel before retrying."
    late = incoming(
        bundle,
        "$late-helper",
        f'You asked "{QUESTION}". {advice}' if link == "unique_quote" else advice,
        user=HELPER,
        **({"reply_to_event_id": "$request"} if link == "native" else {}),
    )
    thanks = incoming(bundle, "$helper-thanks", "Thanks again", user=HELPER)
    authoritative_timeline(bundle, [*initial, late, thanks])
    await process_all(bundle, initial)
    release.set()
    await bundle.engine.drain()
    original = (await all_cases(bundle))[0]
    assert_single_delivery(bundle, original)

    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    await process_all(bundle, [late, late])
    after_late = (await all_cases(bundle))[0]
    await process_all(bundle, [thanks, thanks])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    case = cases[0]
    assert case.id == original.id
    assert_single_delivery(bundle, case)
    assert case.channel_metadata["incident_generation_event_ids"] == (
        original.channel_metadata["incident_generation_event_ids"]
    )
    assert case.channel_metadata["incident_generation_question"] == QUESTION
    assert case.channel_metadata["incident_late_update_status"] == (
        "needs_review_no_additional_generation"
    )
    assert case.channel_metadata["incident_last_meaningful_at"] == (
        after_late.channel_metadata["incident_last_meaningful_at"]
    )
    assert case.channel_metadata["incident_messages"][-1]["sender_id"] == HELPER
    assert [
        message["event_id"] for message in case.channel_metadata["incident_messages"]
    ] == [
        "$request",
        "$helper-answer",
        "$late-helper",
        "$helper-thanks",
    ]
