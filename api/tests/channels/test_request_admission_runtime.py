"""Admission uses the real budget wrapper and live adapter without network calls."""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.models import SendResult
from app.channels.staff_assist.context_conversation import conversation_turn
from app.channels.staff_assist.context_gate import RequestAdmissionService

from tests.channels.test_context_conversation_runtime import draft, event, gate, setup
from tests.channels.test_context_runtime_integration import (
    SOURCE_ROOM,
    no_public_delivery,
)
from tests.channels.test_context_runtime_integration import runtime_case as base

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in base.__wrapped__(tmp_path):
        yield bundle


def boundary(relation="new_request"):
    return {
        "relation": relation,
        "new_request_event_ids": ["$new"] if relation == "new_request" else [],
        "reason": "A distinct requester question",
    }


async def submit(
    bundle,
    text="How do maker fees use the available balance?",
    *,
    event_id="$new",
    drain=True
):
    source = event(bundle, event_id, text)
    turn = conversation_turn(SOURCE_ROOM, source, is_staff=False)
    message = bundle.incoming.model_copy(
        update={
            "message_id": source.event_id,
            "question": source.body,
            "channel_metadata": {
                "room_id": SOURCE_ROOM,
                "conversation_turn": asdict(turn),
            },
        }
    )
    await bundle.engine.process(message, bundle.channel)
    if drain:
        await bundle.engine.drain()


def receipts(bundle):
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        return db.execute(
            "SELECT escalation_id, kind, status FROM matrix_context_trial_spend ORDER BY started_at"
        ).fetchall()


async def test_new_question_after_one_draft_gets_independent_case_and_receipts(
    runtime_case,
):
    bundle = runtime_case
    responses = [gate(["$source"]), draft()]
    old = await setup(bundle, responses)
    responses.extend([boundary(), gate(["$new"]), draft()])
    bundle.sender.side_effect = [
        SendResult(True, "$new-root"),
        SendResult(True, "$new-note"),
    ]
    await submit(bundle)
    old_after = await bundle.repository.get_by_id(old.id)
    new = await bundle.repository.get_by_id(old.id + 1)
    assert new.channel_metadata["conversation_admitted_from_case_id"] == old.id
    assert new.channel_metadata["staff_root_event_id"] == "$new-root"
    assert old_after.channel_metadata["staff_root_event_id"] == "$staff-root"
    assert old_after.channel_metadata["conversation_generation_count"] == 1
    assert new.channel_metadata["conversation_generation_count"] == 1
    assert receipts(bundle) == [
        (1, "gate", "settled"),
        (1, "note", "settled"),
        (1, "gate", "settled"),
        (2, "gate", "settled"),
        (2, "note", "settled"),
    ]
    no_public_delivery(bundle)


async def test_true_unthreaded_followup_keeps_only_existing_update_allowance(
    runtime_case,
):
    bundle = runtime_case
    responses = [gate(["$source"]), draft()]
    old = await setup(bundle, responses)
    responses.extend([boundary("same_request"), gate(["$source", "$new"]), draft()])
    bundle.sender.side_effect = [SendResult(True, "$update")]
    await submit(bundle, "The trade period has now expired")
    assert await bundle.repository.get_by_id(old.id + 1) is None
    current = await bundle.repository.get_by_id(old.id)
    assert current.channel_metadata["conversation_generation_count"] == 2
    assert current.channel_metadata["staff_root_event_id"] == "$staff-root"
    assert bundle.sender.await_args.kwargs["thread_root_event_id"] == "$staff-root"
    assert [row[1] for row in receipts(bundle)] == [
        "gate",
        "note",
        "gate",
        "gate",
        "update",
    ]
    no_public_delivery(bundle)


@pytest.mark.parametrize("change", ["policy", "cutoff"])
async def test_policy_or_cutoff_during_classification_prevents_promotion(
    runtime_case, change
):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])

    def classify(*args, **kwargs):
        if change == "policy":
            bundle.policy.generation_enabled = False
        else:
            bundle.engine._trial_reason = AsyncMock(
                return_value="context_trial_expired"
            )
        return NS(
            content=json.dumps(boundary()),
            usage={"input_tokens": 100, "output_tokens": 30},
        )

    bundle.llm.invoke = Mock(side_effect=classify)
    await submit(bundle)
    assert await bundle.repository.get_by_id(old.id + 1) is None
    current = await bundle.repository.get_by_id(old.id)
    failure = current.channel_metadata["conversation_admission_history"][-1]["failure"]
    assert failure["completed_decision"]["relation"] == "new_request"
    assert failure["reason"] in {"review_or_policy_changed", "context_trial_expired"}
    assert current.channel_metadata["conversation_generation_count"] == 1
    bundle.llm.invoke.assert_called_once()
    assert len(receipts(bundle)) == 3
    no_public_delivery(bundle)


async def test_admission_refusal_calls_no_provider_and_creates_no_case(runtime_case):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])
    calls_before = bundle.llm.invoke.call_count
    bundle.llm.max_tokens = 513
    await submit(bundle)
    assert bundle.llm.invoke.call_count == calls_before
    assert len(receipts(bundle)) == 2
    assert await bundle.repository.get_by_id(old.id + 1) is None
    current = await bundle.repository.get_by_id(old.id)
    assert (
        current.channel_metadata["conversation_admission_history"][-1]["failure"][
            "model_called"
        ]
        is False
    )


async def test_uncertain_admission_does_not_retry_or_reset_old_case(runtime_case):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])
    bundle.llm.invoke = Mock(side_effect=TimeoutError("Unknown provider outcome"))
    await submit(bundle)
    assert receipts(bundle)[-1] == (old.id, "gate", "uncertain")
    await submit(bundle, "Another question about balances", event_id="$later")
    bundle.llm.invoke.assert_called_once()
    assert await bundle.repository.get_by_id(old.id + 1) is None
    current = await bundle.repository.get_by_id(old.id)
    assert current.channel_metadata["conversation_admission_uncertain"]
    assert current.channel_metadata["conversation_generation_count"] == 1


async def test_dispatched_worker_cancellation_preserves_uncertainty_before_start(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = RequestAdmissionService.classify

    def delayed(service, snapshot):
        entered.set()
        release.wait(timeout=3)
        try:
            return original(service, snapshot)
        finally:
            finished.set()

    monkeypatch.setattr(RequestAdmissionService, "classify", delayed)
    await submit(bundle, drain=False)
    assert await asyncio.to_thread(entered.wait, 2)
    tasks = [task for task in bundle.engine._tasks if not task.done()]
    assert len(tasks) == 1
    tasks[0].cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    current = await bundle.repository.get_by_id(old.id)
    assert current.channel_metadata["conversation_admission_uncertain"]
    release.set()
    assert await asyncio.to_thread(finished.wait, 2)
    assert receipts(bundle)[-1] == (old.id, "gate", "not_started")
    assert bundle.llm.invoke.call_count == 2
    await submit(bundle, "Another question about balances", event_id="$later")
    assert bundle.llm.invoke.call_count == 2
    assert await bundle.repository.get_by_id(old.id + 1) is None
