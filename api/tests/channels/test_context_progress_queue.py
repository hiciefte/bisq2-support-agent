"""Bound unresolved progress intake without claiming incident membership."""

from unittest.mock import AsyncMock

import pytest
from app.channels.staff_assist.context_incidents import ContextIncidentStore
from app.channels.staff_assist.context_runtime import (
    ContextReviewStore,
    MatrixContextRuntime,
)
from app.models.escalation import EscalationFilters

from tests.channels.test_context_conversations_acceptance import reservations
from tests.channels.test_context_incidents import hold_worker, incoming
from tests.channels.test_context_progress_updates import (
    COUNT,
    ROOT,
    STATUS,
)
from tests.channels.test_context_progress_updates import (
    runtime_case as existing_progress_case,
)
from tests.channels.test_context_runtime_integration import saved_case

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in existing_progress_case.__wrapped__(tmp_path):
        yield bundle


@pytest.mark.asyncio
async def test_progress_burst_reuses_durable_bounded_queue_after_restart(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    candidates = AsyncMock(wraps=ContextIncidentStore.candidate_links)

    async def candidate_links(store, *args):
        return await candidates(store, *args)

    monkeypatch.setattr(ContextIncidentStore, "candidate_links", candidate_links)
    await bundle.engine.process(incoming(bundle, "$first", STATUS), bundle.channel)
    original = await saved_case(bundle)
    for number in range(35):
        await bundle.engine.process(
            incoming(bundle, f"$progress-{number}", f"{number} confirmations"),
            bundle.channel,
        )
    await bundle.engine.close()
    restarted = MatrixContextRuntime(bundle.runtime)
    try:
        await restarted.process(incoming(bundle, "$latest", COUNT), bundle.channel)
    finally:
        await restarted.close()
    case = await saved_case(bundle)
    metadata = case.channel_metadata
    assert case.id == original.id
    assert len(metadata["incident_messages"]) == 10
    assert metadata["incident_messages"][0]["event_id"] == "$first"
    assert metadata["incident_messages"][-1]["event_id"] == "$latest"
    assert metadata["incident_context_overflow"] is True
    assert metadata["conversation_membership"] == "provisional"
    assert metadata["model_call_status"] == "not_started"
    assert metadata["context_status"] == "deferred"
    candidates.assert_awaited_once()
    assert reservations(bundle) == 0
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.client.room_context.assert_not_awaited()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_progress_caps_candidate_backlinks_once(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    hold_worker(bundle)
    for number in range(12):
        await bundle.engine.process(
            incoming(
                bundle,
                f"$root-{number}",
                f"Separate issue: my payout is stuck for trade {number}.",
            ),
            bundle.channel,
        )
    roots, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 12
    updates = AsyncMock(wraps=ContextReviewStore.update)

    async def update(store, *args, **kwargs):
        return await updates(store, *args, **kwargs)

    monkeypatch.setattr(ContextReviewStore, "update", update)
    for number in range(20):
        await bundle.engine.process(
            incoming(bundle, f"$count-{number}", COUNT), bundle.channel
        )
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 13
    queue = next(
        case for case in cases if case.channel_metadata.get("progress_review_queue")
    )
    assert len(queue.channel_metadata["candidate_conversation_ids"]) == 8
    assert queue.channel_metadata["candidate_conversation_overflow"] is True
    backlinks = [
        case
        for case in cases
        if case.channel_metadata.get("conversation_pending_candidate_ids")
    ]
    assert len(backlinks) == 8
    assert all(
        case.channel_metadata["conversation_pending_candidate_ids"] == [queue.id]
        for case in backlinks
    )
    assert set(queue.channel_metadata["candidate_conversation_ids"]) <= {
        case.id for case in roots
    }
    assert (
        sum(
            "conversation_pending_candidate_ids" in call.kwargs
            for call in updates.await_args_list
        )
        == 8
    )
    assert reservations(bundle) == 0
    await bundle.engine.close()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_existing_backlink_bound_preserves_saved_links(runtime_case):
    bundle = runtime_case
    hold_worker(bundle)
    for number in range(2):
        await bundle.engine.process(
            incoming(bundle, f"$root-{number}", f"Separate issue: {ROOT}"),
            bundle.channel,
        )
    roots, _ = await bundle.repository.list_escalations(EscalationFilters())
    store = ContextReviewStore(bundle.repository.db_path)
    previous = list(range(100, 108))
    for root in roots:
        await store.update(root.id, conversation_pending_candidate_ids=previous)
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    for root in roots:
        saved = await bundle.repository.get_by_id(root.id)
        assert saved.channel_metadata["conversation_pending_candidate_ids"] == previous
        assert saved.channel_metadata["conversation_pending_candidate_overflow"] is True
    await bundle.engine.close()


@pytest.mark.asyncio
async def test_native_orphans_share_queue_but_never_become_an_incident_anchor(
    runtime_case,
):
    bundle = runtime_case
    for number in range(3):
        await bundle.engine.process(
            incoming(
                bundle,
                f"$count-{number}",
                COUNT,
                reply_to_event_id=f"$missing-{number}",
            ),
            bundle.channel,
        )
    queue = await saved_case(bundle)
    assert queue.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert [
        message["reply_to_event_id"]
        for message in queue.channel_metadata["incident_messages"]
    ] == [f"$missing-{number}" for number in range(3)]
    store = ContextIncidentStore(bundle.repository.db_path)
    trial_id = bundle.engine._trial.trial_id
    for message in (
        incoming(
            bundle,
            "$reply",
            "How can I unlock the wallet?",
            reply_to_event_id="$count-1",
        ),
        incoming(bundle, "$quote", f'"{COUNT}" How can I unlock the wallet?'),
        incoming(bundle, "$unthreaded", COUNT),
    ):
        assert await store.find(message, trial_id) == (None, False)
        assert await store.candidate_links(message, trial_id) == []
    await bundle.engine.process(
        incoming(
            bundle,
            "$reply",
            "How can I unlock the wallet?",
            reply_to_event_id="$count-1",
        ),
        bundle.channel,
    )
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    reply = next(case for case in cases if case.id != queue.id)
    assert reply.channel_metadata["context_reason"] == "incident_relation_unresolved"
    assert len(reply.channel_metadata["incident_messages"]) == 1
    assert reservations(bundle) == 0
    bundle.llm.invoke.assert_not_called()
    bundle.client.room_context.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_duplicate_edits_and_genuine_question_preserve_ownership(
    runtime_case,
):
    bundle = runtime_case
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    queue = await saved_case(bundle)
    store = ContextIncidentStore(bundle.repository.db_path)
    trial_id = bundle.engine._trial.trial_id
    assert await store.find(incoming(bundle, "$count", COUNT), trial_id) == (
        queue.id,
        True,
    )
    edit = incoming(bundle, "$edit", "48 confirmations", replaces_event_id="$count")
    assert await store.find(edit, trial_id) == (queue.id, False)
    assert await store.find(
        incoming(
            bundle,
            "$forged",
            "49 confirmations",
            user="@other:example.org",
            replaces_event_id="$count",
        ),
        trial_id,
    ) == (None, False)
    await bundle.engine.process(edit, bundle.channel)
    updated = await saved_case(bundle)
    assert len(updated.channel_metadata["incident_messages"]) == 2
    assert updated.channel_metadata["conversation_membership"] == "provisional"
    hold_worker(bundle)
    await bundle.engine.process(
        incoming(bundle, "$question", "How can I unlock my wallet?"), bundle.channel
    )
    cases, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    question = next(case for case in cases if case.id != queue.id)
    assert question.channel_metadata["conversation_membership"] == "confirmed"
    await bundle.engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary",
    ["sender", "room", "trial", "closed", "confirmed", "attempted", "frozen"],
)
async def test_queue_reuse_requires_open_unattempted_same_scope(runtime_case, boundary):
    bundle = runtime_case
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    queue = await saved_case(bundle)
    message = incoming(
        bundle,
        "$next",
        STATUS,
        user="@other:example.org" if boundary == "sender" else None,
    )
    trial_id = bundle.engine._trial.trial_id
    if boundary == "room":
        message.channel_metadata["room_id"] = "!other:example.org"
    elif boundary == "trial":
        trial_id = "another-trial"
    elif boundary == "closed":
        await bundle.service.close_escalation(queue.id)
    elif boundary in {"confirmed", "attempted", "frozen"}:
        field, value = {
            "confirmed": ("conversation_membership", "confirmed"),
            "attempted": ("model_call_status", "completed"),
            "frozen": ("incident_frozen", True),
        }[boundary]
        await ContextReviewStore(bundle.repository.db_path).update(
            queue.id, **{field: value}
        )
    store = ContextIncidentStore(bundle.repository.db_path)
    assert await store.progress_review_case(message, trial_id) is None


@pytest.mark.asyncio
async def test_queue_cannot_activate_even_if_helper_reason_is_assigned(runtime_case):
    bundle = runtime_case
    await bundle.engine.process(incoming(bundle, "$count", COUNT), bundle.channel)
    queue = await saved_case(bundle)
    await ContextReviewStore(bundle.repository.db_path).update(
        queue.id, reason="conversation_helper_only"
    )
    store = ContextIncidentStore(bundle.repository.db_path)
    assert not await store.append(
        queue.id, incoming(bundle, "$other", ROOT, user="@other:example.org"), ROOT
    )
    updated = await saved_case(bundle)
    assert updated.channel_metadata["conversation_membership"] == "provisional"
    assert "conversation_requester_id" not in updated.channel_metadata
