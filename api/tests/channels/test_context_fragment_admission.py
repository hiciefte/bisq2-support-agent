"""Generic offline fixtures for explicit Matrix referent boundaries."""

import json
import sqlite3
from contextlib import closing

import pytest
from app.channels.staff_assist.context_runtime import MatrixContextRuntime
from app.models.escalation import EscalationFilters

from tests.channels.test_context_incidents import (
    hold_worker,
    incoming,
    server_events,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as existing_runtime_case,
)
from tests.channels.test_context_runtime_integration import (
    saved_case,
)
from tests.channels.test_context_trial import enable_trial

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in existing_runtime_case.__wrapped__(tmp_path):
        yield bundle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "relations",
    [
        {"reply_to_event_id": "$uncaptured"},
        {"thread_root_event_id": "$uncaptured"},
    ],
)
async def test_uncaptured_referent_is_deferred_before_model_work(
    runtime_case, relations
):
    bundle = runtime_case
    enable_trial(bundle)
    followup = incoming(
        bundle, "$followup", "Does that apply after restarting?", **relations
    )
    server_events(bundle, [followup])
    await bundle.engine.process(followup, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert case.channel_metadata["model_called"] is False
    assert case.channel_metadata["model_call_status"] == "not_started"
    bundle.client.room_context.assert_not_awaited()
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        for table in ("matrix_context_attempts", "matrix_context_trial_cases"):
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert (
                not exists
                or db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )


@pytest.mark.asyncio
async def test_captured_same_author_reply_keeps_referent_for_retrieval_and_prompt(
    runtime_case,
):
    bundle = runtime_case
    enable_trial(bundle)
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", "My wallet will not open after an update.")
    unrelated = incoming(
        bundle,
        "$other",
        "My profile disappeared.",
        user="@someone-else:example.org",
    )
    followup = incoming(
        bundle,
        "$followup",
        "Does that apply after restarting?",
        reply_to_event_id="$root",
    )
    server_events(bundle, [root, unrelated, followup])
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    release.set()
    await bundle.engine.drain()
    case = await saved_case(bundle)
    combined = root.question + "\n---\n" + followup.question
    assert case.channel_metadata["incident_generation_question"] == combined
    bundle.retrieve.assert_called_once_with(combined)
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert prompt["question"] == combined
    assert prompt["recent_messages"] == [{"role": "user", "content": root.question}]
    assert unrelated.question not in json.dumps(prompt)
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_unresolved_thread_root_cannot_borrow_reply_fallback(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    root = incoming(bundle, "$root", "My wallet will not open after an update.")
    followup = incoming(
        bundle,
        "$followup",
        "Does that apply after restarting?",
        thread_root_event_id="$uncaptured-thread",
        reply_to_event_id="$root",
    )
    await bundle.engine.process(root, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    detached = next(case for case in cases if case.question == followup.question)
    assert detached.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert all(len(case.channel_metadata["incident_messages"]) == 1 for case in cases)
    await bundle.engine.close()
    release.set()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_reply_to_other_author_does_not_inherit_their_question(runtime_case):
    bundle = runtime_case
    release = hold_worker(bundle)
    other = incoming(
        bundle,
        "$other",
        "My wallet will not open after an update.",
        user="@someone-else:example.org",
    )
    followup = incoming(
        bundle,
        "$followup",
        "Does that apply after restarting?",
        reply_to_event_id="$other",
    )
    await bundle.engine.process(other, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    own = next(case for case in cases if case.user_id == followup.user.user_id)
    assert own.question == followup.question
    assert own.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert own.channel_metadata["incident_unresolved_relation"] == "$other"
    assert len(bundle.engine._active_cases) == 1
    await bundle.engine.close()
    release.set()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_deferred_chain_stays_held_across_duplicate_and_restart(runtime_case):
    bundle = runtime_case
    enable_trial(bundle)
    detached = incoming(
        bundle,
        "$detached",
        "Does that apply after restarting?",
        reply_to_event_id="$uncaptured",
    )
    followup = incoming(
        bundle,
        "$followup",
        "The wallet still fails to open.",
        reply_to_event_id="$detached",
    )
    await bundle.engine.process(detached, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    await bundle.engine.process(followup, bundle.channel)
    await bundle.engine.drain()
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    late = incoming(
        bundle,
        "$late",
        "It also fails after an update.",
        reply_to_event_id="$followup",
    )
    await bundle.engine.process(late, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert case.channel_metadata["incident_unresolved_relation"] == "$uncaptured"
    assert len(case.channel_metadata["incident_messages"]) == 3
    assert case.channel_metadata["incident_late_update_status"] == (
        "needs_review_no_additional_generation"
    )
    assert case.channel_metadata["model_called"] is False
    bundle.client.room_context.assert_not_awaited()
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_new_issue_preserves_existing_standalone_contract(runtime_case):
    bundle = runtime_case
    enable_trial(bundle)
    question = incoming(
        bundle,
        "$new",
        "New issue: where can I open mediation after the trade period?",
        reply_to_event_id="$uncaptured",
    )
    server_events(bundle, [question])
    await bundle.engine.process(question, bundle.channel)
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    assert "incident_unresolved_relation" not in case.channel_metadata
    bundle.retrieve.assert_called_once_with(question.question)
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_deferred_chain_cannot_move_to_a_newer_heuristic_candidate(runtime_case):
    bundle = runtime_case
    enable_trial(bundle)
    detached = incoming(
        bundle, "$detached", "Does that apply?", reply_to_event_id="$uncaptured"
    )
    await bundle.engine.process(detached, bundle.channel)
    release = hold_worker(bundle)
    standalone = incoming(bundle, "$standalone", "My wallet will not open.")
    await bundle.engine.process(standalone, bundle.channel)
    followup = incoming(
        bundle,
        "$followup",
        "I also have a wallet error.",
        reply_to_event_id="$detached",
    )
    await bundle.engine.process(followup, bundle.channel)
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    held = next(
        case
        for case in cases
        if case.channel_metadata["source_event_id"] == "$detached"
    )
    other = next(
        case
        for case in cases
        if case.channel_metadata["source_event_id"] == "$standalone"
    )
    assert held.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert [
        message["event_id"] for message in held.channel_metadata["incident_messages"]
    ] == [
        "$detached",
        "$followup",
    ]
    assert len(other.channel_metadata["incident_messages"]) == 1
    assert len(bundle.engine._active_cases) == 1
    await bundle.engine.close()
    release.set()
    bundle.llm.invoke.assert_not_called()
