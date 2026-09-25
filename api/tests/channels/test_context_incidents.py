"""Offline incident admission, accumulation and durable no-retry boundaries."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from app.channels.models import ClassificationDecision, UserContext
from app.channels.staff_assist.context_runtime import MatrixContextRuntime
from app.models.escalation import EscalationFilters

from tests.channels.test_context_runtime_integration import (
    SOURCE_ROOM,
    run,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as existing_runtime_case,
)
from tests.channels.test_context_runtime_integration import (
    saved_case,
)
from tests.channels.test_context_trial import enable_trial

pytestmark = pytest.mark.unit

ROOT = "My trade deposit is locked. SignMediatedPayoutTx: sellerPayoutAddressString must not be null."
FOLLOWUP = "i already updated bisq multiple times in the meantime, and also resynced spv 5 times"


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in existing_runtime_case.__wrapped__(tmp_path):
        yield bundle


def incoming(bundle, event_id, text, *, user=None, **relations):
    return bundle.incoming.model_copy(
        update={
            "message_id": event_id,
            "question": text,
            "user": UserContext(user_id=user or bundle.incoming.user.user_id),
            "channel_metadata": {"room_id": SOURCE_ROOM, **relations},
        }
    )


def server_events(bundle, messages):
    by_id = {message.message_id: message for message in messages}

    async def read(room, event_id, **kwargs):
        message = by_id[event_id]

        def event(entry):
            return NS(
                event_id=entry.message_id,
                body=entry.question,
                sender=entry.user.user_id,
                server_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
            )

        index = messages.index(message)
        return NS(
            event=event(message),
            events_before=[event(entry) for entry in reversed(messages[:index])],
            events_after=[],
        )

    bundle.client.room_context.side_effect = read


def hold_worker(bundle):
    release = asyncio.Event()
    original = bundle.engine._run_case

    async def held(*args):
        await release.wait()
        return await original(*args)

    bundle.engine._run_case = held
    return release


@pytest.mark.asyncio
async def test_actual_split_diagnostics_use_one_case_call_and_thread(runtime_case):
    bundle = runtime_case
    enable_trial(bundle)
    release = hold_worker(bundle)
    messages = [
        incoming(bundle, "$root", ROOT),
        incoming(bundle, "$update", FOLLOWUP),
        incoming(bundle, "$logs", "I can also provide the chat log"),
        incoming(bundle, "$count", "2 times"),
        incoming(bundle, "$ack", "Thanks"),
    ]
    server_events(bundle, messages)
    for message in messages:
        await bundle.engine.process(message, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    assert ROOT in bundle.retrieve.call_args.args[0]
    assert FOLLOWUP in bundle.retrieve.call_args.args[0]
    assert "2 times" not in bundle.retrieve.call_args.args[0]
    assert "provide the chat log" not in bundle.retrieve.call_args.args[0]
    assert len(case.channel_metadata["incident_messages"]) == 5
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2
    assert "/$root" in bundle.sender.await_args_list[0].args[0]
    assert (
        bundle.sender.await_args_list[1].kwargs["thread_root_event_id"] == "$staff-root"
    )
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        assert (
            db.execute("SELECT COUNT(*) FROM matrix_context_trial_cases").fetchone()[0]
            == 1
        )


@pytest.mark.asyncio
async def test_restart_late_followup_keeps_case_thread_and_no_additional_call(
    runtime_case,
):
    bundle = runtime_case
    bundle.incoming = incoming(bundle, "$root", ROOT)
    late = incoming(bundle, "$late", FOLLOWUP, reply_to_event_id="$root")
    server_events(bundle, [bundle.incoming, late])
    original = await run(bundle)
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    await bundle.engine.process(late, bundle.channel)
    await bundle.engine.process(late, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.id == original.id
    assert len(case.channel_metadata["incident_messages"]) == 2
    assert (
        case.channel_metadata["incident_late_update_status"]
        == "needs_review_no_additional_generation"
    )
    assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2


@pytest.mark.asyncio
async def test_uncertain_attempt_stays_held_when_new_context_arrives(runtime_case):
    bundle = runtime_case
    bundle.incoming = incoming(bundle, "$root", ROOT)
    server_events(bundle, [bundle.incoming])
    bundle.sender.side_effect = TimeoutError("ambiguous")
    await run(bundle)
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    await bundle.engine.process(
        incoming(bundle, "$late", FOLLOWUP, reply_to_event_id="$root"), bundle.channel
    )
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "delivery_uncertain"
    assert (
        case.channel_metadata["incident_late_update_status"]
        == "needs_review_no_additional_generation"
    )
    assert bundle.sender.await_count == 1
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_different_owner_or_new_problem_does_not_merge(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    messages = [
        incoming(bundle, "$root", ROOT),
        incoming(
            bundle,
            "$other",
            "How do I configure Bisq 2 notifications?",
            user="@other:example.org",
            reply_to_event_id="$root",
        ),
        incoming(
            bundle,
            "$new",
            "Different issue: how can I change the Bisq 2 profile?",
            reply_to_event_id="$root",
        ),
    ]
    server_events(bundle, messages)
    for message in messages:
        await bundle.engine.process(message, bundle.channel)
    rows, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 3
    assert all(len(row.channel_metadata["incident_messages"]) == 1 for row in rows)
    # Do not run three model calls merely to test local grouping.
    await bundle.engine.close()
    release.set()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_edit_replaces_original_text_without_new_case(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", "Bisq 1 gives me an error opening my profile.")
    edit = incoming(
        bundle,
        "$edit",
        "Bisq 2 gives me an error opening my profile.",
        replaces_event_id="$root",
    )
    server_events(bundle, [root, edit])
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(edit, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.question == edit.question
    assert "Bisq 1" not in bundle.retrieve.call_args.args[0]
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_detached_fragments_and_edits_have_no_admission(runtime_case):
    bundle = runtime_case
    for index, text in enumerate(
        [
            "2 times",
            "Thanks",
            "I can also provide the chat log",
            "How many times did you rebuild the DAO?",
        ]
    ):
        await bundle.engine.process(
            incoming(bundle, f"$fragment{index}", text), bundle.channel
        )
    await bundle.engine.process(
        incoming(bundle, "$edit", "Corrected question", replaces_event_id="$unknown"),
        bundle.channel,
    )
    _, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 0
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_prefiltered_linked_followup_still_enriches_incident(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", ROOT)
    answer = incoming(bundle, "$count", "2 times", reply_to_event_id="$root")
    answer.classification = ClassificationDecision(should_process=False)
    server_events(bundle, [root, answer])
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(answer, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert "2 times" in case.question
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_missing_or_changed_original_defers_whole_incident(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", ROOT)
    followup = incoming(bundle, "$followup", FOLLOWUP)
    server_events(bundle, [followup])  # Original fell outside bounded context.
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert (
        case.channel_metadata["context_reason"] == "incident_source_context_incomplete"
    )
    bundle.llm.invoke.assert_not_called()
    bundle.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_high_risk_linked_followup_does_not_lower_original_risk(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", ROOT)
    followup = incoming(
        bundle, "$followup", "I also suspect stolen funds", reply_to_event_id="$root"
    )
    followup.classification = ClassificationDecision(topic_risk="high")
    server_events(bundle, [root, followup])
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_reason"] == "high_risk_action"
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_same_time_unrelated_question_starts_another_case(runtime_case):
    bundle = runtime_case
    hold_worker(bundle)
    await bundle.engine.process(incoming(bundle, "$root", ROOT), bundle.channel)
    await bundle.engine.process(
        incoming(bundle, "$other", "Where can I change my payment account?"),
        bundle.channel,
    )
    _, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_restart_before_generation_does_not_resume_reserved_attempt(runtime_case):
    bundle = runtime_case
    hold_worker(bundle)
    await bundle.engine.process(incoming(bundle, "$root", ROOT), bundle.channel)
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    await bundle.engine.process(
        incoming(bundle, "$followup", FOLLOWUP, reply_to_event_id="$root"),
        bundle.channel,
    )
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert (
        case.channel_metadata["incident_late_update_status"]
        == "needs_review_no_additional_generation"
    )
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_followup_cannot_admit_pre_activation_root(runtime_case):
    bundle = runtime_case
    trial = enable_trial(bundle)
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", ROOT)
    followup = incoming(bundle, "$followup", FOLLOWUP)
    server_events(bundle, [root, followup])
    read = bundle.client.room_context.side_effect

    async def stale_root(*args, **kwargs):
        result = await read(*args, **kwargs)
        result.events_before[0].server_timestamp = (
            int(trial.start_at.timestamp() * 1000) - 1000
        )
        return result

    bundle.client.room_context.side_effect = stale_root
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_before_activation"
    bundle.llm.invoke.assert_not_called()
    bundle.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_oversized_context_defers_instead_of_losing_original_error(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", ROOT + " Diagnostic detail." * 160)
    followup = incoming(
        bundle,
        "$followup",
        FOLLOWUP + " Followup detail." * 100,
        reply_to_event_id="$root",
    )
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert (
        case.channel_metadata["context_reason"] == "incident_context_capacity_reached"
    )
    assert case.channel_metadata["incident_messages"][0]["text"] == root.question
    bundle.llm.invoke.assert_not_called()
    bundle.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_polite_support_request_is_not_dropped_as_chatter(runtime_case):
    bundle = runtime_case
    bundle.incoming = incoming(
        bundle,
        "$root",
        "I hope you can help: Bisq 2 fails to start with a profile error.",
    )
    server_events(bundle, [bundle.incoming])
    await run(bundle)
    case = await saved_case(bundle)
    assert case.question == bundle.incoming.question
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "followup",
    [
        "I already updated Bisq 2 but my profile still fails to open.",
        "I also have a profile error when opening the identity settings.",
        "I already updated the application and the notifications still fail.",
    ],
)
async def test_unlinked_other_product_or_topic_is_a_separate_incident(
    runtime_case, followup
):
    bundle = runtime_case
    hold_worker(bundle)
    await bundle.engine.process(
        incoming(bundle, "$root", "Bisq 1: " + ROOT), bundle.channel
    )
    await bundle.engine.process(incoming(bundle, "$other", followup), bundle.channel)
    _, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "late_text",
    [
        "Actually resolved now; the funds arrived.",
        "I can send logs. The trade shows as completed but my BTC balance is zero.",
        "How many times did you resync? My BTC balance is zero after completion.",
    ],
)
async def test_resolution_during_generation_withholds_stale_note(
    runtime_case, late_text
):
    import threading

    bundle = runtime_case
    bundle.incoming = incoming(bundle, "$root", ROOT)
    late = incoming(
        bundle,
        "$resolved",
        late_text,
        reply_to_event_id="$root",
    )
    server_events(bundle, [bundle.incoming, late])
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    result = bundle.llm.invoke.return_value

    def generate(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return result

    bundle.llm.invoke.side_effect = generate
    await bundle.engine.process(bundle.incoming, bundle.channel)
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        await bundle.engine.process(late, bundle.channel)
    finally:
        release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert (
        case.channel_metadata["context_reason"] == "incident_updated_after_generation"
    )
    assert (
        case.channel_metadata["incident_late_update_status"]
        == "needs_review_no_additional_generation"
    )
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_offer_with_diagnostic_fact_is_admitted(runtime_case):
    bundle = runtime_case
    hold_worker(bundle)
    await bundle.engine.process(
        incoming(
            bundle,
            "$question",
            "I can send logs. The trade shows as completed but my BTC balance is zero.",
        ),
        bundle.channel,
    )
    _, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 1
    await bundle.engine.close()


@pytest.mark.asyncio
async def test_late_update_during_final_trial_check_blocks_note(runtime_case):
    bundle = runtime_case
    bundle.incoming = incoming(bundle, "$root", ROOT)
    late = incoming(
        bundle,
        "$late",
        "Actually resolved now; the funds arrived.",
        reply_to_event_id="$root",
    )
    server_events(bundle, [bundle.incoming, late])
    original = bundle.engine.check_trial_delivery

    async def check(transaction_id):
        reason = await original(transaction_id)
        if transaction_id.endswith("-note"):
            await bundle.engine.process(late, bundle.channel)
        return reason

    bundle.engine.check_trial_delivery = check
    await bundle.engine.process(bundle.incoming, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["incident_late_meaningful_update"] is True
    assert bundle.sender.await_count == 1
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "staff_context_case_changed"
