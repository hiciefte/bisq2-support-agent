"""Independent final-read and concurrent-intake tests for the live adapter."""

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.models import SendResult
from app.channels.plugins.matrix.message_handler import MatrixMessageHandler
from app.channels.staff_assist.context_conversation import (
    ConversationTurn,
    conversation_turn,
)
from app.channels.staff_assist.context_runtime import ContextReviewStore

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
from tests.channels.test_context_runtime_integration import (
    saved_case,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in base_runtime_case.__wrapped__(tmp_path):
        try:
            yield bundle
        finally:
            await bundle.engine.close()


def message(bundle, source):
    turn = conversation_turn(SOURCE_ROOM, source, is_staff=False)
    return bundle.incoming.model_copy(
        update={
            "message_id": turn.event_id,
            "question": turn.text,
            "channel_metadata": {
                "room_id": SOURCE_ROOM,
                "conversation_turn": asdict(turn),
            },
        }
    )


@pytest.mark.parametrize("field", ["sender", "body", "server_timestamp"])
async def test_anchor_identity_or_content_change_stops_before_next_gate(
    runtime_case, field
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    original_read = bundle.client.room_context.side_effect
    source = event(bundle, "$zzz-facts", "The error now appears after login")
    source.server_timestamp += 1

    def changed_read(room, event_id, **kwargs):
        result = original_read(room, event_id, **kwargs)
        if event_id == source.event_id:
            altered = NS(**vars(result.event))
            setattr(
                altered,
                field,
                (
                    altered.server_timestamp + 1
                    if field == "server_timestamp"
                    else "different"
                ),
            )
            result.event = altered
        return result

    bundle.client.room_context.side_effect = changed_read
    case = await incoming(bundle, source)
    assert case.channel_metadata["context_reason"] == "source_changed_or_redacted"
    assert bundle.llm.invoke.call_count == 1
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)


async def test_requester_change_during_draft_suppresses_stale_publication(runtime_case):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    loop = asyncio.get_running_loop()
    draft_count = 0

    def generate(prompt, system_content):
        nonlocal draft_count
        payload = json.loads(prompt)
        if "Classify a support-room conversation" in system_content:
            body = gate(
                [
                    row["event_id"]
                    for row in payload["messages"]
                    if row["role"] == "requester"
                ]
            )
        else:
            draft_count += 1
            body = draft()
            if draft_count == 1:
                update = event(
                    bundle,
                    "$zzz-more",
                    "The payment is now confirmed and the period expired",
                )
                update.server_timestamp += 1
                asyncio.run_coroutine_threadsafe(
                    bundle.engine.process(message(bundle, update), bundle.channel), loop
                ).result(timeout=3)
                body["reply"] = "The earlier state suggests checking the trade screen."
            else:
                body["reply"] = (
                    "The latest update supports opening mediation after expiry."
                )
        return NS(
            content=json.dumps(body), usage={"input_tokens": 100, "output_tokens": 30}
        )

    bundle.llm.invoke = Mock(side_effect=generate)
    case = await incoming(bundle, event(bundle, "$facts", "The trade period expired"))
    assert draft_count == 2
    assert case.channel_metadata["conversation_generation_count"] == 2
    assert case.channel_metadata["context_status"] == "delivered"
    assert bundle.sender.await_count == 2
    assert "earlier state" not in " ".join(
        call.args[0] for call in bundle.sender.await_args_list
    )
    assert "latest update" in bundle.sender.await_args_list[-1].args[0]
    no_public_delivery(bundle)


async def test_unrelated_chatter_during_first_draft_does_not_lose_that_draft(
    runtime_case,
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    loop = asyncio.get_running_loop()
    draft_count = 0
    gate_count = 0

    def generate(prompt, system_content):
        nonlocal draft_count, gate_count
        payload = json.loads(prompt)
        if "Classify a support-room conversation" in system_content:
            gate_count += 1
            body = gate(
                [
                    row["event_id"]
                    for row in payload["messages"]
                    if row["role"] == "requester"
                ],
                material=gate_count == 1,
            )
        else:
            draft_count += 1
            body = draft()
            if draft_count == 1:
                neighbor = event(
                    bundle,
                    "$neighbor",
                    "A separate discussion about translations",
                    sender="@other:example.org",
                )
                observed = ConversationTurn(
                    SOURCE_ROOM,
                    neighbor.event_id,
                    neighbor.sender,
                    neighbor.server_timestamp,
                    neighbor.body,
                )
                asyncio.run_coroutine_threadsafe(
                    bundle.engine._capture_conversation_turn(observed, allow_new=False),
                    loop,
                ).result(timeout=3)
        return NS(
            content=json.dumps(body), usage={"input_tokens": 100, "output_tokens": 30}
        )

    bundle.llm.invoke = Mock(side_effect=generate)
    case = await incoming(bundle, event(bundle, "$facts", "The trade period expired"))
    assert 1 <= draft_count <= 2
    assert case.channel_metadata["context_status"] == "delivered"
    assert bundle.sender.await_count == 2
    assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    assert len(case.channel_metadata["staff_note_history"]) == 1
    no_public_delivery(bundle)


async def test_final_delivery_lock_orders_concurrent_intake(runtime_case, monkeypatch):
    bundle = runtime_case
    await setup(
        bundle, [gate(["$source"]), draft(), gate(["$source", "$facts"]), draft()]
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(*args, **kwargs):
        entered.set()
        await release.wait()
        return SendResult(True, "$staff-update")

    bundle.sender.side_effect = send
    update_task = asyncio.create_task(
        incoming(
            bundle,
            event(bundle, "$facts", "The trade period expired", relation="$source"),
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=3)
    late = event(
        bundle, "$late", "A new confirmation just appeared", relation="$source"
    )
    reached_lock = asyncio.Event()
    original_acquire = bundle.service._acquire_delivery_lock

    async def acquire(case_id):
        reached_lock.set()
        return await original_acquire(case_id)

    monkeypatch.setattr(bundle.service, "_acquire_delivery_lock", acquire)
    intake = asyncio.create_task(
        bundle.engine.process(message(bundle, late), bundle.channel)
    )
    await asyncio.wait_for(reached_lock.wait(), timeout=3)
    before = await saved_case(bundle)
    assert "$late" not in {
        row["event_id"] for row in before.channel_metadata["incident_messages"]
    }
    assert not intake.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(update_task, intake), timeout=3)
    await bundle.engine.drain()
    after = await saved_case(bundle)
    assert "$late" in {
        row["event_id"] for row in after.channel_metadata["incident_messages"]
    }
    assert after.channel_metadata["staff_note_event_id"] == "$staff-update"
    assert bundle.llm.invoke.call_count == 4
    assert bundle.sender.await_count == 3
    no_public_delivery(bundle)


async def test_acknowledged_root_is_reused_after_facts_arrive_before_note(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    await setup(bundle, [gate(["$source"], category="already_answered")])
    original_update = ContextReviewStore.update
    injected = False

    async def update(store, case_id, **kwargs):
        nonlocal injected
        await original_update(store, case_id, **kwargs)
        if kwargs.get("reason") == "staff_note_reserved" and not injected:
            injected = True
            late = event(bundle, "$zzz-more", "The payment just became confirmed")
            late.server_timestamp += 1
            await bundle.engine.process(message(bundle, late), bundle.channel)

    monkeypatch.setattr(ContextReviewStore, "update", update)

    def generate(prompt, system_content):
        payload = json.loads(prompt)
        body = (
            gate(
                [
                    row["event_id"]
                    for row in payload["messages"]
                    if row["role"] == "requester"
                ]
            )
            if "Classify a support-room conversation" in system_content
            else draft()
        )
        return NS(
            content=json.dumps(body), usage={"input_tokens": 100, "output_tokens": 30}
        )

    ordinary_generate = generate

    def generate_with_admission(prompt, system_content):
        if "Decide whether a later requester exchange" in system_content:
            return NS(
                content=json.dumps(
                    {
                        "relation": "same_request",
                        "new_request_event_ids": [],
                        "reason": "The new payment confirmation continues this trade.",
                    }
                ),
                usage={"input_tokens": 100, "output_tokens": 30},
            )
        return ordinary_generate(prompt, system_content)

    bundle.llm.invoke = Mock(side_effect=generate_with_admission)
    case = await incoming(bundle, event(bundle, "$facts", "The trade period expired"))
    assert injected
    assert case.channel_metadata["context_status"] == "delivered"
    assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    assert bundle.sender.await_count == 2
    assert [
        call.kwargs["transaction_id"] for call in bundle.sender.await_args_list
    ] == ["context-1-root", "context-1-note"]
    assert (
        bundle.sender.await_args_list[-1].kwargs["thread_root_event_id"]
        == "$staff-root"
    )
    no_public_delivery(bundle)


async def test_source_staff_identity_cannot_be_spoofed_by_display_name(runtime_case):
    bundle = runtime_case
    observation = AsyncMock()
    bundle.services["matrix_context_runtime"] = NS(observe_source_event=observation)
    handler = MatrixMessageHandler(
        client=bundle.client,
        connection_manager=NS(room_state_ready=True),
        channel=bundle.channel,
        autoresponse_policy_service=bundle.services[
            "channel_autoresponse_policy_service"
        ],
    )
    process = AsyncMock()
    handler._get_orchestrator = Mock(return_value=NS(process_incoming=process))
    handler._record_trust_event = AsyncMock()
    handler._record_staff_activity = AsyncMock()
    handler._maybe_handle_staff_command = AsyncMock()
    room = NS(room_id=SOURCE_ROOM, user_name=lambda _: "@staff:example.org")
    source = NS(
        event_id="$spoofed-display-name",
        sender="@outsider:example.org",
        server_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        body="My application does not start",
        source={
            "content": {"body": "My application does not start", "msgtype": "m.text"}
        },
    )
    await handler._on_message(room, source)
    observation.assert_not_awaited()
    handler._record_staff_activity.assert_not_awaited()
    process.assert_awaited_once()
    captured = process.await_args.args[0]
    assert captured.user.user_id == "@outsider:example.org"
    assert captured.channel_metadata["conversation_turn"]["is_staff"] is False
