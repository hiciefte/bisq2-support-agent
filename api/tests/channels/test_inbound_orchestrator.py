from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.coordination import InMemoryCoordinationStore
from app.channels.events import thread_lock_key
from app.channels.inbound_orchestrator import InboundMessageOrchestrator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_processes_when_generation_policy_is_disabled_elsewhere():
    policy_service = MagicMock()
    policy_service.get_policy.return_value = SimpleNamespace(
        enabled=True,
        generation_enabled=False,
    )

    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )

    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = MagicMock()
    channel.runtime.resolve_optional = MagicMock(return_value=None)
    channel.handle_incoming = AsyncMock(return_value=response)

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    incoming = SimpleNamespace(
        message_id="$evt1",
        channel_metadata={"room_id": "!room:server"},
        user=SimpleNamespace(user_id="@user:server"),
    )

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=policy_service,
        coordination_store=InMemoryCoordinationStore(),
    )

    processed = await orchestrator.process_incoming(incoming)

    assert processed is True
    channel.handle_incoming.assert_awaited_once()
    dispatcher.dispatch.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_consumes_followup_before_rag():
    followup = MagicMock()
    followup.consume_if_pending = AsyncMock(return_value=True)

    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=followup)

    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    incoming = SimpleNamespace(
        message_id="$evt1",
        channel_metadata={"room_id": "!room:server"},
        user=SimpleNamespace(user_id="@user:server"),
    )

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=InMemoryCoordinationStore(),
    )

    processed = await orchestrator.process_incoming(incoming)

    assert processed is True
    channel.handle_incoming.assert_not_called()
    dispatcher.dispatch.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_deduplicates_events():
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)

    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )

    channel = MagicMock()
    channel.channel_id = "bisq2"
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock(return_value=response)

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    incoming = SimpleNamespace(
        message_id="msg-1",
        channel_metadata={"conversation_id": "support.support"},
        user=SimpleNamespace(user_id="user-1"),
    )

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="bisq2",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=InMemoryCoordinationStore(),
    )

    first = await orchestrator.process_incoming(incoming)
    second = await orchestrator.process_incoming(incoming)

    assert first is True
    assert second is False
    channel.handle_incoming.assert_awaited_once_with(incoming)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_updates_thread_state_after_dispatch():
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)

    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )

    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock(return_value=response)

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    incoming = SimpleNamespace(
        message_id="$evt1",
        channel_metadata={"room_id": "!room:server"},
        user=SimpleNamespace(user_id="@user:server"),
    )

    store = InMemoryCoordinationStore()
    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=store,
        thread_state_ttl_seconds=60.0,
    )

    processed = await orchestrator.process_incoming(incoming)

    assert processed is True
    state = await store.get_thread_state("thread:matrix:!room:server")
    assert state is not None
    assert state.get("last_event_id") == "$evt1"
    assert state.get("last_user_id") == "@user:server"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_does_not_dedup_when_lock_is_unavailable():
    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)

    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )

    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock(return_value=response)

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    incoming = SimpleNamespace(
        message_id="$evt1",
        channel_metadata={"room_id": "!room:server"},
        user=SimpleNamespace(user_id="@user:server"),
    )

    store = InMemoryCoordinationStore()
    lock_key = thread_lock_key("matrix", "!room:server")
    lock_token = await store.acquire_lock(lock_key, ttl_seconds=1.0)
    assert lock_token is not None

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=store,
    )

    first = await orchestrator.process_incoming(incoming)
    await store.release_lock(lock_key, lock_token)
    second = await orchestrator.process_incoming(incoming)

    assert first is False
    assert second is True
    channel.handle_incoming.assert_awaited_once_with(incoming)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_handles_missing_runtime_resolve_optional():
    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )

    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = SimpleNamespace()
    channel.handle_incoming = AsyncMock(return_value=response)

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    incoming = SimpleNamespace(
        message_id="$evt1",
        channel_metadata={"room_id": "!room:server"},
        user=SimpleNamespace(user_id="@user:server"),
    )

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=InMemoryCoordinationStore(),
    )

    processed = await orchestrator.process_incoming(incoming)

    assert processed is True
    channel.handle_incoming.assert_awaited_once_with(incoming)
