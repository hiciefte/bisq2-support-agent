"""Synthetic offline progress reports, helper advice and reservation boundaries."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from app.channels.models import ClassificationDecision
from app.channels.staff_assist import context_incidents
from app.channels.staff_assist.context_runtime import MatrixContextRuntime
from app.models.escalation import EscalationFilters

from tests.channels.test_context_conversations_acceptance import reservations
from tests.channels.test_context_discussion import (
    change_after_generation_or_root,
    event,
    source,
)
from tests.channels.test_context_incidents import hold_worker, incoming, server_events
from tests.channels.test_context_runtime_integration import (
    runtime_case as existing_runtime_case,
)
from tests.channels.test_context_runtime_integration import (
    saved_case,
)
from tests.channels.test_context_trial import enable_trial

pytestmark = pytest.mark.unit
ROOT = "My payout is stuck after the trade period."
STATUS = "I checked the deposit transaction and it is confirmed."
COUNT = "The transaction has 47 confirmations."
MENU = "Settings > Network information > Resync SPV"


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in existing_runtime_case.__wrapped__(tmp_path):
        enable_trial(bundle)
        yield bundle


@pytest.mark.parametrize(
    "text",
    [
        "47 confirmations",
        "Confirmations: 47",
        "I see 47 confirmations.",
        COUNT,
        STATUS,
        "I checked the payout transaction in an explorer; it has 47 confirmations.",
        "The payout transaction is still pending.",
        "My Bisq 1 payout transaction is confirmed.",
        "The Bisq 2 transaction has 47 confirmations.",
        "My Bisq Easy payout is still pending.",
    ],
)
def test_progress_is_substantive_without_being_a_new_question(text):
    assert context_incidents.diagnostic_progress(text)
    assert not context_incidents.context_only(text)


@pytest.mark.parametrize(
    "text",
    [
        "Thanks",
        "47 times",
        "How many confirmations are needed?",
        "The transaction has 47 confirmations. How can I open mediation?",
        "New issue: the transaction has 47 confirmations.",
        "My transaction is missing.",
        "The transaction is confirmed but my wallet still fails.",
        "You should wait for 47 confirmations.",
    ],
)
def test_progress_does_not_absorb_new_requests_advice_or_unknown_details(text):
    assert not context_incidents.diagnostic_progress(text)


@pytest.mark.asyncio
async def test_status_and_count_join_one_requester_incident_and_reservation(
    runtime_case,
):
    bundle = runtime_case
    release = hold_worker(bundle)
    messages = [
        incoming(bundle, "$root", ROOT),
        incoming(bundle, "$status", STATUS),
        incoming(bundle, "$count", COUNT),
    ]
    server_events(bundle, messages)
    for message in messages:
        await bundle.engine.process(message, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert len(case.channel_metadata["incident_messages"]) == 3
    assert STATUS in case.channel_metadata["incident_generation_question"]
    assert COUNT in case.channel_metadata["incident_generation_question"]
    bundle.llm.invoke.assert_called_once()
    assert reservations(bundle) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["Bisq 1", "Bisq 2"])
async def test_qualified_progress_keeps_product_ownership(runtime_case, product):
    bundle = runtime_case
    hold_worker(bundle)
    await bundle.engine.process(
        incoming(bundle, "$root", "My Bisq 1 payout is stuck."), bundle.channel
    )
    await bundle.engine.process(
        incoming(bundle, "$progress", f"My {product} payout transaction is confirmed."),
        bundle.channel,
    )
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == (1 if product == "Bisq 1" else 2)
    if product == "Bisq 1":
        assert len(cases[0].channel_metadata["incident_messages"]) == 2
    else:
        assert all(
            len(case.channel_metadata["incident_messages"]) == 1 for case in cases
        )
    await bundle.engine.close()
    assert reservations(bundle) == 0


@pytest.mark.parametrize(
    "failure", ["Connection refused", "Not responding", "Not working", "Timed out"]
)
def test_navigation_failure_is_not_helper_advice(failure):
    assert not context_incidents.helper_turn(f"Settings > Network > {failure}")
    assert context_incidents.helper_turn(MENU)


@pytest.mark.asyncio
@pytest.mark.parametrize("filtered", [False, True])
async def test_unmatched_progress_is_retained_without_reservation(
    runtime_case, filtered
):
    bundle = runtime_case
    message = incoming(bundle, "$count", COUNT)
    if filtered:
        message.classification = ClassificationDecision(should_process=False)
    await bundle.engine.process(message, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.question == COUNT
    assert case.channel_metadata["conversation_membership"] == "provisional"
    assert "conversation_requester_id" not in case.channel_metadata
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["model_called"] is False
    assert reservations(bundle) == 0
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.client.room_context.assert_not_awaited()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_two_same_requester_incidents_keep_ambiguous_count_for_admin(
    runtime_case,
):
    bundle = runtime_case
    hold_worker(bundle)
    for event_id, text in [
        ("$first", ROOT),
        ("$second", "Separate issue: my other trade has a locked deposit."),
    ]:
        await bundle.engine.process(incoming(bundle, event_id, text), bundle.channel)
    roots, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 3
    held = next(case for case in cases if case.question == COUNT)
    assert set(held.channel_metadata["candidate_conversation_ids"]) == {
        case.id for case in roots
    }
    assert held.channel_metadata["conversation_membership"] == "provisional"
    assert held.channel_metadata["model_called"] is False
    assert all(len(case.channel_metadata["incident_messages"]) == 1 for case in cases)
    for case in cases:
        if case.id != held.id:
            assert case.channel_metadata["conversation_pending_candidate_ids"] == [
                held.id
            ]
    assert reservations(bundle) == 0
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_orphan_status_and_count_share_review_queue_without_confirming_membership(
    runtime_case,
):
    bundle = runtime_case
    await bundle.engine.process(incoming(bundle, "$status", STATUS), bundle.channel)
    original = await saved_case(bundle)
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    followup = await saved_case(bundle)
    assert followup.id == original.id
    assert followup.channel_metadata["progress_review_queue"] is True
    assert followup.channel_metadata["conversation_membership"] == "provisional"
    assert "conversation_requester_id" not in followup.channel_metadata
    assert len(followup.channel_metadata["incident_messages"]) == 2
    assert not followup.channel_metadata.get("candidate_conversation_ids")
    assert reservations(bundle) == 0
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["speaker", "topic", "idle", "age", "closed"])
async def test_progress_cannot_borrow_ineligible_incidents(runtime_case, boundary):
    bundle = runtime_case
    hold_worker(bundle)
    root = incoming(
        bundle,
        "$root",
        "My profile is missing." if boundary == "topic" else ROOT,
        user="@other:example.org" if boundary == "speaker" else None,
    )
    await bundle.engine.process(root, bundle.channel)
    original = await saved_case(bundle)
    if boundary in {"idle", "age"}:
        metadata = original.channel_metadata
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(minutes=61 if boundary == "age" else 16)
        metadata["incident_last_meaningful_at"] = (
            now if boundary == "age" else created_at
        ).isoformat()
        with closing(sqlite3.connect(bundle.repository.db_path)) as db:
            db.execute(
                "UPDATE escalations SET created_at=?, channel_metadata=? WHERE id=?",
                (created_at.isoformat(), json.dumps(metadata), original.id),
            )
            db.commit()
    elif boundary == "closed":
        await bundle.service.close_escalation(original.id)
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    held = next(case for case in cases if case.question == COUNT)
    assert held.channel_metadata["conversation_membership"] == "provisional"
    assert not held.channel_metadata.get("candidate_conversation_ids")
    assert all(len(case.channel_metadata["incident_messages"]) == 1 for case in cases)
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_native_root_cannot_fall_back_to_unique_progress_case(
    runtime_case,
):
    bundle = runtime_case
    hold_worker(bundle)
    await bundle.engine.process(incoming(bundle, "$root", ROOT), bundle.channel)
    await bundle.engine.process(
        incoming(
            bundle,
            "$count",
            COUNT,
            thread_root_event_id="$uncaptured",
            reply_to_event_id="$root",
        ),
        bundle.channel,
    )
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    held = next(case for case in cases if case.question == COUNT)
    assert held.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert not held.channel_metadata.get("candidate_conversation_ids")
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_late_progress_after_restart_preserves_generation_and_call_count(
    runtime_case,
):
    bundle = runtime_case
    root = incoming(bundle, "$root", ROOT)
    server_events(bundle, [root])
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.drain()
    original = await saved_case(bundle)
    frozen = original.channel_metadata["incident_generation_question"]
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    enable_trial(bundle)
    late = incoming(bundle, "$count", COUNT)
    await bundle.engine.process(late, bundle.channel)
    await bundle.engine.process(late, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.id == original.id
    assert len(case.channel_metadata["incident_messages"]) == 2
    assert case.channel_metadata["incident_generation_question"] == frozen
    assert case.channel_metadata["incident_late_meaningful_update"] is True
    assert case.channel_metadata["incident_late_update_status"] == (
        "needs_review_no_additional_generation"
    )
    bundle.llm.invoke.assert_called_once()
    assert reservations(bundle) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("relationship", ["reply", "thread", "edit", "quote"])
async def test_explicit_progress_relation_wins_over_multiple_candidates(
    runtime_case, relationship
):
    bundle = runtime_case
    hold_worker(bundle)
    first = incoming(bundle, "$first", "How do I recover a stuck payout?")
    second = incoming(
        bundle, "$second", "Separate issue: my other trade has a locked deposit."
    )
    await bundle.engine.process(first, bundle.channel)
    original = await saved_case(bundle)
    await bundle.engine.process(second, bundle.channel)
    relations = {}
    text = COUNT
    if relationship == "reply":
        relations = {"reply_to_event_id": first.message_id}
    elif relationship == "thread":
        relations = {
            "thread_root_event_id": first.message_id,
            "reply_to_event_id": second.message_id,
        }
    elif relationship == "edit":
        relations = {
            "replaces_event_id": first.message_id,
            "thread_root_event_id": second.message_id,
        }
    else:
        text = f'You asked "{first.question}". {COUNT}'
    await bundle.engine.process(
        incoming(bundle, "$count", text, **relations), bundle.channel
    )
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    updated = next(case for case in cases if case.id == original.id)
    assert updated.channel_metadata["incident_messages"][-1]["text"] == text
    assert len(updated.channel_metadata["incident_messages"]) == 2
    assert all(
        len(case.channel_metadata["incident_messages"]) == 1
        for case in cases
        if case.id != original.id
    )
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "New issue: the transaction has 47 confirmations.",
        "The transaction has 47 confirmations. How do I recover my backup?",
        "Bisq 2: the transaction has 47 confirmations.",
        "Using version 1.9.18: the transaction has 47 confirmations.",
    ],
)
async def test_new_request_or_conflicting_product_version_is_never_merged(
    runtime_case, text
):
    bundle = runtime_case
    hold_worker(bundle)
    root = incoming(bundle, "$root", "My Bisq 1 v1.9.17 payout is stuck.")
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(incoming(bundle, "$different", text), bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    assert all(len(case.channel_metadata["incident_messages"]) == 1 for case in cases)
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_menu_only_helper_and_personal_question_keep_distinct_roles(runtime_case):
    bundle = runtime_case
    hold_worker(bundle)
    helper = incoming(bundle, "$helper", MENU, user="@helper:example.org")
    await bundle.engine.process(helper, bundle.channel)
    advice = await saved_case(bundle)
    assert advice.channel_metadata["conversation_membership"] == "provisional"
    assert advice.channel_metadata["context_reason"] == "conversation_helper_only"
    assert "conversation_requester_id" not in advice.channel_metadata
    personal = incoming(
        bundle,
        "$personal",
        "How can I recover my missing wallet backup?",
        user="@helper:example.org",
    )
    await bundle.engine.process(personal, bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    request = next(case for case in cases if case.id != advice.id)
    assert request.channel_metadata["conversation_membership"] == "confirmed"
    assert (
        request.channel_metadata["conversation_requester_id"] == personal.user.user_id
    )
    assert reservations(bundle) == 0
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_linked_navigation_remains_attributed_helper_context(runtime_case):
    bundle = runtime_case
    hold_worker(bundle)
    root = incoming(bundle, "$root", ROOT)
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(
        incoming(
            bundle,
            "$advice",
            MENU,
            user="@helper:example.org",
            reply_to_event_id=root.message_id,
        ),
        bundle.channel,
    )
    case = await saved_case(bundle)
    assert case.channel_metadata["conversation_requester_id"] == root.user.user_id
    assert case.channel_metadata["incident_messages"][-1]["sender_id"] == (
        "@helper:example.org"
    )
    question, _, _ = await context_incidents.ContextIncidentStore(
        bundle.repository.db_path
    ).freeze(case.id)
    assert question == ROOT
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        "Settings > Network information > Resync SPV. My wallet fails to open.",
        "Settings > Network > I cannot connect",
        "Settings > Network > How do I restore my backup?",
        "2026/11/06",
        "deposit/payout/status",
        "The log says: Settings > Network > Failed",
    ],
)
def test_navigation_rule_does_not_hide_requests_logs_or_slash_data(text):
    assert not context_incidents.helper_turn(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize(
    "arrival", ["count", "status", "other_speaker", "other_topic", "ambiguous"]
)
async def test_server_progress_before_intake_withholds_only_unique_requester_case(
    runtime_case, phase, arrival
):
    bundle = runtime_case
    if arrival == "ambiguous":
        # Leave another eligible requester incident active without letting its
        # worker run. The current case must not claim an unthreaded count.
        original_run_case = bundle.engine._run_case
        hold_worker(bundle)
        await bundle.engine.process(
            incoming(
                bundle,
                "$other-incident",
                "Separate issue: my other trade has a locked deposit.",
            ),
            bundle.channel,
        )
        bundle.engine._run_case = original_run_case
    question = "My profile is missing." if arrival == "other_topic" else ROOT
    response = source(bundle, question)

    def change():
        response.events_after = [
            event(
                "$progress",
                STATUS if arrival == "status" else COUNT,
                sender=(
                    "@other:example.org"
                    if arrival == "other_speaker"
                    else bundle.incoming.user.user_id
                ),
            )
        ]

    change_after_generation_or_root(bundle, phase, change)
    previous_tasks = set(bundle.engine._tasks)
    await bundle.engine.process(bundle.incoming, bundle.channel)
    # drain() would also await the intentionally held other-case worker.
    for task in set(bundle.engine._tasks) - previous_tasks:
        await task
    cases, _ = await bundle.repository.list_escalations(EscalationFilters())
    case = next(case for case in cases if case.question == question)
    assert len(case.channel_metadata["incident_messages"]) == 1
    assert case.channel_metadata["incident_generation_question"] == question
    assert not case.channel_metadata.get("incident_late_meaningful_update")
    bundle.llm.invoke.assert_called_once()
    assert reservations(bundle) == 1
    if arrival in {"count", "status"}:
        assert case.channel_metadata["context_reason"] == (
            "incident_updated_after_generation"
        )
        assert case.channel_metadata["context_status"] == "deferred"
        assert "staff_note_event_id" not in case.channel_metadata
        assert bundle.sender.await_count == (1 if phase == "root" else 0)
    else:
        assert case.channel_metadata["context_status"] == "delivered"
        assert bundle.sender.await_count == 2
