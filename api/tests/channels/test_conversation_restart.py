"""Recover eligible saved requests using live lifecycle and synthetic Matrix events."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from app.channels.staff_assist import context_runtime
from app.channels.staff_assist.context_conversation import conversation_turn
from app.channels.staff_assist.context_runtime import MatrixContextRuntime

from tests.channels.test_context_conversation_runtime import (
    draft,
    event,
    gate,
)
from tests.channels.test_context_conversation_runtime import (
    runtime_case as base_runtime_case,
)
from tests.channels.test_context_conversation_runtime import (
    setup,
)
from tests.channels.test_context_runtime_integration import SOURCE_ROOM
from tests.channels.test_request_admission_runtime import submit

runtime_case = base_runtime_case
pytestmark = pytest.mark.unit


async def test_restart_recovers_after_quiet_delay_without_another_event(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    responses = [gate(["$source"], category="not_a_request")]
    await setup(bundle, responses)
    bundle.policy.first_response_delay_seconds = 60
    e = event(
        bundle, "$waiting", "How do I open mediation?", sender="@other:example.org"
    )
    clock = datetime.fromtimestamp(e.server_timestamp / 1000, timezone.utc)
    monkeypatch.setattr(context_runtime, "utc_now", lambda: clock)
    turn = conversation_turn(SOURCE_ROOM, e, is_staff=False)
    await bundle.engine._ingest_conversation(turn, bundle.channel)
    await bundle.engine.close()
    engine = bundle.engine = MatrixContextRuntime(bundle.runtime)
    bundle.services["matrix_message_handler"] = NS(channel=bundle.channel)
    bundle.channel.is_connected = True
    bundle.runtime.settings.MATRIX_SYNC_ENABLED = True
    monkeypatch.setattr(engine, "RECOVERY_INTERVAL_SECONDS", 0.01, raising=False)
    coordinator = engine._conversation_coordinator()
    first_scan = asyncio.Event()
    original_due = coordinator.due

    async def due(**kwargs):
        snapshots = await original_due(**kwargs)
        first_scan.set()
        return snapshots

    monkeypatch.setattr(coordinator, "due", due)
    responses.append(gate(["$waiting"], category="not_a_request"))
    bundle.llm.invoke.reset_mock()
    engine.start()
    await asyncio.wait_for(first_scan.wait(), timeout=1)
    bundle.llm.invoke.assert_not_called()
    clock += timedelta(seconds=61)
    async with asyncio.timeout(2):
        while not bundle.llm.invoke.called:
            await asyncio.sleep(0.01)
    await engine.drain()
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_not_awaited()


async def test_invalidated_admission_rechecks_pending_candidate(runtime_case):
    bundle = runtime_case
    old = await setup(bundle, [gate(["$source"]), draft()])
    read = bundle.client.room_context.side_effect

    def changed(room, event_id, **kwargs):
        response = read(room, event_id, **kwargs)
        if event_id == "$new":
            response.event = NS(
                **{**vars(response.event), "body": "Changed after capture"}
            )
            response.event.source = {"content": {"body": response.event.body}}
        return response

    bundle.client.room_context.side_effect = changed
    await submit(bundle)
    current = await bundle.repository.get_by_id(old.id)
    meta = current.channel_metadata
    assert not meta["conversation_admission_pending"]
    assert (
        meta["conversation_admission_history"][-1]["failure"]["reason"]
        == "conversation_no_text_anchor"
    )
    assert bundle.llm.invoke.call_count == 2


async def test_recovery_skips_request_claimed_by_live_worker(runtime_case, monkeypatch):
    bundle = runtime_case
    responses = [gate(["$source"], category="not_a_request")]
    await setup(bundle, responses)
    bundle.services["matrix_message_handler"] = NS(channel=bundle.channel)
    bundle.runtime.settings.MATRIX_SYNC_ENABLED = True
    bundle.channel.is_connected = True
    entered, release = asyncio.Event(), asyncio.Event()
    verify = bundle.engine._verify_conversation_anchor

    async def pause(snapshot):
        entered.set()
        await release.wait()
        return await verify(snapshot)

    monkeypatch.setattr(bundle.engine, "_verify_conversation_anchor", pause)
    e = event(bundle, "$claimed", "Where is the trade?", sender="@other:example.org")
    responses.append(gate(["$claimed"], category="not_a_request"))
    await bundle.engine._ingest_conversation(
        conversation_turn(SOURCE_ROOM, e, is_staff=False), bundle.channel
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    other = MatrixContextRuntime(bundle.runtime)
    start_worker = AsyncMock(wraps=other._start_conversation_worker)
    monkeypatch.setattr(other, "_start_conversation_worker", start_worker)
    try:
        await other._recover_due_conversations()
        start_worker.assert_not_awaited()
    finally:
        release.set()
        await bundle.engine.drain()
        await other.close()
    assert bundle.llm.invoke.call_count == 2
