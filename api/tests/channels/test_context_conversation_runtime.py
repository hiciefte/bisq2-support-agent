"""Exercise the live v3 adapter with the real coordinator/gate/draft services."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.models import SendResult
from app.channels.staff_assist.context_conversation import conversation_turn
from app.channels.staff_assist.context_runtime import MatrixContextRuntime
from app.services.rag.openai_responses import OpenAIResponsesLLMWrapper

from tests.channels.test_context_runtime_integration import (
    SOURCE_ROOM,
    context,
    no_public_delivery,
)
from tests.channels.test_context_runtime_integration import (  # noqa: F401
    runtime_case as shared_runtime_case,
)
from tests.channels.test_context_runtime_integration import (
    saved_case,
)


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in shared_runtime_case.__wrapped__(tmp_path):
        try:
            yield bundle
        finally:
            await bundle.engine.close()


pytestmark = pytest.mark.unit


def gate(ids, *, category="unanswered_support_request", material=True):
    return {
        "category": category,
        "selected_event_ids": ids,
        "request_summary": "A request",
        "material_change": material,
        "reason": "observed_request",
    }


def draft():
    return {
        "action": "reply",
        "reply": "Open mediation from the trade screen after the trade period expires.",
        "staff_note": "The supplied guide documents this action.",
        "source_ids": ["e1"],
        "reason": "documented_action",
    }


async def setup(bundle, responses):
    await bundle.engine.close()
    settings = bundle.runtime.settings
    for key, value in dict(
        MATRIX_CONTEXT_TRIAL_ID="conversation-fixture",
        MATRIX_CONTEXT_TRIAL_BUDGET_USD="10",
        MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="10",
        MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION="1",
        MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION="2",
        MAX_TOKENS=512,
    ).items():
        setattr(settings, key, value)
    llm = OpenAIResponsesLLMWrapper(
        client=NS(max_retries=0),
        model=settings.OPENAI_MODEL,
        max_tokens=512,
        reasoning_effort="low",
        mcp_url="",
        input_cost_per_token=0.000001,
        cached_input_cost_per_token=0.0000001,
        cache_write_cost_per_token=0.000001,
        output_cost_per_token=0.000002,
    )
    llm.invoke = Mock(
        side_effect=lambda *a, **kw: NS(
            content=json.dumps(responses.pop(0)),
            usage={"input_tokens": 100, "output_tokens": 30},
        )
    )
    bundle.rag.llm = llm
    bundle.llm = llm
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    source = context().event
    bundle.source_events = [source]

    def read(_room, event_id, **kwargs):
        event = next(
            event for event in bundle.source_events if event.event_id == event_id
        )
        return NS(
            event=event,
            events_before=[],
            events_after=[
                item for item in bundle.source_events if item.event_id != event_id
            ],
        )

    bundle.client.room_context.side_effect = read
    return await incoming(bundle, source)


async def incoming(bundle, event):
    turn = conversation_turn(SOURCE_ROOM, event, is_staff=False)
    message = bundle.incoming.model_copy(
        update={
            "message_id": turn.event_id,
            "question": turn.text,
            "channel_metadata": {
                "room_id": SOURCE_ROOM,
                "conversation_turn": asdict(turn),
            },
        }
    )
    await bundle.engine.process(message, bundle.channel)
    await bundle.engine.drain()
    return await saved_case(bundle)


def event(bundle, event_id, body, *, sender="@user:example.org", relation=None):
    value = NS(
        event_id=event_id,
        body=body,
        sender=sender,
        server_timestamp=bundle.source_events[-1].server_timestamp,
        source={"content": {"body": body}},
    )
    if relation:
        value.source["content"]["m.relates_to"] = {
            "m.in_reply_to": {"event_id": relation}
        }
    bundle.source_events.append(value)
    return value


async def test_live_groups_update_under_same_root_and_ack_is_free(runtime_case):
    bundle = runtime_case
    case = await setup(
        bundle, [gate(["$source"]), draft(), gate(["$source", "$facts"]), draft()]
    )
    assert case.channel_metadata["context_status"] == "delivered"
    assert case.channel_metadata["conversation_generation_count"] == 1
    bundle.sender.side_effect = [SendResult(True, "$staff-update")]
    case = await incoming(
        bundle,
        event(
            bundle,
            "$facts",
            "The trade period expired and the payment was sent.",
            relation="$source",
        ),
    )
    assert case.channel_metadata["conversation_generation_count"] == 2
    assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    assert [
        item["event_id"] for item in case.channel_metadata["staff_note_history"]
    ] == ["$staff-note", "$staff-update"]
    assert bundle.sender.await_args.kwargs["thread_root_event_id"] == "$staff-root"
    assert bundle.sender.await_args.kwargs["transaction_id"] == "context-1-update"
    case = await incoming(bundle, event(bundle, "$thanks", "thanks"))
    assert len(case.channel_metadata["incident_messages"]) == 3
    assert bundle.llm.invoke.call_count == 4
    assert bundle.sender.await_count == 3
    no_public_delivery(bundle)


async def test_live_gate_blocks_nonrequest_without_note_slot(runtime_case):
    bundle = runtime_case
    case = await setup(bundle, [gate(["$source"], category="helping_another")])
    assert case.channel_metadata["conversation_gate"]["category"] == "helping_another"
    assert case.channel_metadata.get("conversation_generation_count", 0) == 0
    bundle.sender.assert_not_awaited()
    assert bundle.llm.invoke.call_count == 1
    no_public_delivery(bundle)


@pytest.mark.parametrize("category", ["not_a_request", "helping_another"])
async def test_live_later_question_after_nonrequest_reaches_eligibility(
    runtime_case, category
):
    bundle = runtime_case
    case = await setup(
        bundle,
        [gate(["$source"], category=category), gate(["$question"]), draft()],
    )
    original_id = case.id
    assert not case.channel_metadata.get("conversation_resolved")
    bundle.sender.assert_not_awaited()
    case = await incoming(
        bundle,
        event(bundle, "$question", "How do I open mediation after the trade period?"),
    )
    assert case.id == original_id
    assert case.channel_metadata["conversation_generation_count"] == 1
    assert not case.channel_metadata.get("conversation_admission_history")
    assert bundle.llm.invoke.call_count == 3
    assert case.channel_metadata["context_status"] == "delivered"
    no_public_delivery(bundle)


async def test_live_neighbor_staff_does_not_suppress_request(runtime_case):
    bundle = runtime_case
    case = await setup(bundle, [gate(["$source"]), draft()])
    assert case.channel_metadata["context_status"] == "delivered"
    staff = event(
        bundle,
        "$unrelated",
        "I am helping somebody else.",
        sender="@staff:example.org",
        relation="$other-user",
    )
    await bundle.engine.observe_source_event(
        SOURCE_ROOM, staff, bundle.channel, is_staff=True
    )
    await bundle.engine.drain()
    assert bundle.llm.invoke.call_count == 2
    assert not (await saved_case(bundle)).channel_metadata.get(
        "conversation_staff_replied_after_draft"
    )


async def test_live_reply_after_draft_prevents_update(runtime_case):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"]), draft()])
    staff = event(
        bundle,
        "$staff-answer",
        "Please use the trade screen.",
        sender="@staff:example.org",
        relation="$source",
    )
    await bundle.engine.observe_source_event(
        SOURCE_ROOM, staff, bundle.channel, is_staff=True
    )
    await bundle.engine.drain()
    case = await incoming(
        bundle,
        event(bundle, "$facts", "The payment is now confirmed.", relation="$source"),
    )
    assert case.channel_metadata["conversation_staff_replied_after_draft"]
    assert bundle.llm.invoke.call_count == 2
    assert bundle.sender.await_count == 2


async def test_live_uncertain_update_never_retries_on_restart(runtime_case):
    bundle = runtime_case
    await setup(
        bundle, [gate(["$source"]), draft(), gate(["$source", "$facts"]), draft()]
    )
    bundle.sender.side_effect = RuntimeError("transport outcome unknown")
    case = await incoming(
        bundle,
        event(bundle, "$facts", "The payment is now confirmed.", relation="$source"),
    )
    assert case.channel_metadata["conversation_delivery_uncertain"]
    assert case.channel_metadata["conversation_update_delivery_attempted"]
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    await incoming(bundle, event(bundle, "$later", "I still need help."))
    assert bundle.llm.invoke.call_count == 4
    assert bundle.sender.await_count == 3


async def test_live_budget_refusal_spends_no_note_slot(runtime_case):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    # Refuse at the exact note boundary without mutating the stored descriptor.
    original = bundle.llm.invoke

    def result(*args, **kwargs):
        response = original(*args, **kwargs)
        bundle.llm.max_tokens = 513
        return response

    bundle.llm.invoke = Mock(side_effect=result)
    original.side_effect = lambda *args, **kwargs: NS(
        content=json.dumps(gate(["$source", "$facts"])),
        usage={"input_tokens": 100, "output_tokens": 30},
    )
    case = await incoming(
        bundle,
        event(bundle, "$facts", "It is still unresolved after the trade expired."),
    )
    bundle.llm.invoke.assert_called_once()
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert "$facts" in {row["event_id"] for row in prompt["messages"]}
    assert case.channel_metadata["context_reason"] == "context_trial_unbounded_model"
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        note_rows = db.execute(
            "SELECT status, COALESCE(actual_nanodollars, reserved_nanodollars) "
            "FROM matrix_context_trial_spend WHERE escalation_id=? AND kind='note'",
            (case.id,),
        ).fetchall()
        assert note_rows == []
        assert (
            db.execute(
                "SELECT COUNT(*) FROM matrix_context_trial_cases WHERE escalation_id=?",
                (case.id,),
            ).fetchone()[0]
            == 0
        )
    assert case.channel_metadata.get("conversation_generation_count", 0) == 0
    assert case.channel_metadata["model_called"] is False
    bundle.sender.assert_not_awaited()
