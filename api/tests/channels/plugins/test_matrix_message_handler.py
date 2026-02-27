"""Tests for Matrix message push handler."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.plugins.matrix import message_handler as matrix_message_handler_module
from app.channels.plugins.matrix.message_handler import MatrixMessageHandler


def _matrix_event(
    *,
    room_id: str = "!room:server",
    sender: str = "@user:server",
    event_id: str = "$evt:server",
    body: str = "Need help with Bisq Easy",
) -> tuple[MagicMock, MagicMock]:
    room = MagicMock()
    room.room_id = room_id
    event = MagicMock()
    event.sender = sender
    event.event_id = event_id
    event.body = body
    event.source = {"content": {"body": body}}
    return room, event


def _outgoing_response(*, routing_action: str = "auto_send") -> MagicMock:
    outgoing = MagicMock()
    outgoing.metadata = MagicMock()
    outgoing.metadata.routing_action = routing_action
    outgoing.metadata.routing_reason = None
    outgoing.metadata.confidence_score = 0.82
    outgoing.requires_human = False
    outgoing.sources = []
    outgoing.answer = "Answer"
    outgoing.original_question = "Need help with Bisq Easy"
    return outgoing


def _enabled_policy_service() -> MagicMock:
    svc = MagicMock()
    svc.get_policy.return_value = MagicMock(enabled=True, generation_enabled=True)
    return svc


@pytest.mark.asyncio
async def test_start_registers_callback_and_starts_sync_loop() -> None:
    client = MagicMock()
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        allowed_room_ids=["!room:server"],
        sync_timeout_ms=12345,
    )

    await handler.start()
    await asyncio.sleep(0)

    registered_event_types = [
        call.args[1] for call in client.add_event_callback.call_args_list
    ]
    assert matrix_message_handler_module.RoomMessageText in registered_event_types
    assert matrix_message_handler_module.MegolmEvent in registered_event_types
    connection_manager.sync_forever.assert_called_once_with(timeout=12345)


@pytest.mark.asyncio
async def test_stop_removes_callback_and_stops_sync_loop() -> None:
    client = MagicMock()
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()
    connection_manager.stop_sync = MagicMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        allowed_room_ids=["!room:server"],
    )
    await handler.start()
    await handler.stop()

    client.remove_event_callback.assert_called_once_with(handler._on_message)
    connection_manager.stop_sync.assert_called_once()


@pytest.mark.asyncio
async def test_on_message_skips_when_generation_disabled() -> None:
    client = MagicMock()
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()
    policy_service = MagicMock()
    policy_service.get_policy.return_value = MagicMock(
        enabled=False, generation_enabled=False
    )
    channel = MagicMock()
    channel.handle_incoming = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        autoresponse_policy_service=policy_service,
        allowed_room_ids=["!room:server"],
        channel_id="matrix",
    )

    room, event = _matrix_event()
    await handler._on_message(room, event)

    channel.handle_incoming.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_skips_when_channel_not_attached() -> None:
    client = MagicMock()
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=None,
        allowed_room_ids=["!room:server"],
    )

    room, event = _matrix_event()
    await handler._on_message(room, event)


@pytest.mark.asyncio
async def test_on_message_dispatches_to_channel() -> None:
    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    outgoing = _outgoing_response(routing_action="auto_send")
    runtime = MagicMock()

    def resolve_optional(name: str):
        if name == "feedback_followup_coordinator":
            return None
        if name == "staff_resolver":
            resolver = MagicMock()
            resolver.is_staff.return_value = False
            return resolver
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="!room:server")
    channel.send_message = AsyncMock(return_value=True)

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        autoresponse_policy_service=_enabled_policy_service(),
        allowed_room_ids=["!room:server"],
        channel_id="matrix",
    )

    room, event = _matrix_event(sender="@user:server")
    await handler._on_message(room, event)

    channel.handle_incoming.assert_called_once()
    channel.send_message.assert_called_once_with("!room:server", outgoing)


@pytest.mark.asyncio
async def test_on_message_decrypts_encrypted_event_before_dispatch(monkeypatch) -> None:
    class DummyMegolmEvent:
        pass

    monkeypatch.setattr(matrix_message_handler_module, "MegolmEvent", DummyMegolmEvent)

    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    outgoing = _outgoing_response(routing_action="auto_send")
    runtime = MagicMock()

    def resolve_optional(name: str):
        if name == "feedback_followup_coordinator":
            return None
        if name == "staff_resolver":
            resolver = MagicMock()
            resolver.is_staff.return_value = False
            return resolver
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="!room:server")
    channel.send_message = AsyncMock(return_value=True)

    decrypted_event = MagicMock()
    decrypted_event.sender = "@user:server"
    decrypted_event.event_id = "$decrypted:server"
    decrypted_event.body = "Need help with Bisq Easy"
    decrypted_event.source = {"content": {"body": "Need help with Bisq Easy"}}
    client.decrypt_event = MagicMock(return_value=decrypted_event)
    client.request_room_key = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        autoresponse_policy_service=_enabled_policy_service(),
        allowed_room_ids=["!room:server"],
        channel_id="matrix",
    )

    room = MagicMock()
    room.room_id = "!room:server"
    encrypted_event = DummyMegolmEvent()
    encrypted_event.event_id = "$encrypted:server"

    await handler._on_message(room, encrypted_event)

    client.decrypt_event.assert_called_once_with(encrypted_event)
    client.request_room_key.assert_not_awaited()
    channel.handle_incoming.assert_awaited_once()
    channel.send_message.assert_awaited_once_with("!room:server", outgoing)


@pytest.mark.asyncio
async def test_on_message_skips_on_encrypted_decrypt_error(monkeypatch) -> None:
    class DummyMegolmEvent:
        pass

    monkeypatch.setattr(matrix_message_handler_module, "MegolmEvent", DummyMegolmEvent)

    client = MagicMock()
    client.user_id = "@agent:server"
    client.decrypt_event = MagicMock(side_effect=ValueError("cannot decrypt"))
    client.request_room_key = AsyncMock()
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        autoresponse_policy_service=_enabled_policy_service(),
        allowed_room_ids=["!room:server"],
    )

    room = MagicMock()
    room.room_id = "!room:server"
    encrypted_event = DummyMegolmEvent()
    encrypted_event.event_id = "$encrypted:server"

    await handler._on_message(room, encrypted_event)

    client.request_room_key.assert_awaited_once_with(encrypted_event)
    channel.handle_incoming.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_queues_when_autosend_disabled() -> None:
    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()
    policy_service = MagicMock()
    policy_service.get_policy.return_value = MagicMock(
        enabled=False, generation_enabled=True
    )

    outgoing = _outgoing_response(routing_action="auto_send")
    escalation_service = MagicMock()
    escalation_service.create_escalation = AsyncMock(return_value=MagicMock(id=77))

    runtime = MagicMock()

    def resolve_optional(name: str):
        if name == "feedback_followup_coordinator":
            return None
        if name == "staff_resolver":
            resolver = MagicMock()
            resolver.is_staff.return_value = False
            return resolver
        if name == "escalation_service":
            return escalation_service
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    channel = MagicMock()
    channel.runtime = runtime
    channel.format_escalation_message = MagicMock(
        return_value="Escalated to support. (Reference: #77)"
    )
    channel.handle_incoming = AsyncMock(return_value=outgoing)
    channel.get_delivery_target = MagicMock(return_value="!room:server")
    channel.send_message = AsyncMock(return_value=True)

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        autoresponse_policy_service=policy_service,
        allowed_room_ids=["!room:server"],
        channel_id="matrix",
    )

    room, event = _matrix_event(sender="@user:server")
    await handler._on_message(room, event)

    channel.send_message.assert_called_once()
    queued_notification = channel.send_message.call_args.args[1]
    assert queued_notification.requires_human is True
    escalation_service.create_escalation.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_message_consumes_feedback_followup_before_processing() -> None:
    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()
    followup_coordinator = MagicMock()
    followup_coordinator.consume_if_pending = AsyncMock(return_value=True)

    runtime = MagicMock()

    def resolve_optional(name: str):
        if name == "feedback_followup_coordinator":
            return followup_coordinator
        if name == "staff_resolver":
            resolver = MagicMock()
            resolver.is_staff.return_value = False
            return resolver
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        autoresponse_policy_service=_enabled_policy_service(),
        allowed_room_ids=["!room:server"],
    )

    room, event = _matrix_event(sender="@user:server")
    await handler._on_message(room, event)

    followup_coordinator.consume_if_pending.assert_awaited_once()
    channel.handle_incoming.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_ignores_sender_when_same_as_matrix_user() -> None:
    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        allowed_room_ids=["!room:server"],
    )

    room, event = _matrix_event(sender="@agent:server")
    await handler._on_message(room, event)

    channel.handle_incoming.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_ignores_staff_sender() -> None:
    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    staff_resolver = MagicMock()
    staff_resolver.is_staff.return_value = True

    runtime = MagicMock()

    def resolve_optional(name: str):
        if name == "staff_resolver":
            return staff_resolver
        if name == "feedback_followup_coordinator":
            return None
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        allowed_room_ids=["!room:server"],
    )

    room, event = _matrix_event(sender="@support:server")
    await handler._on_message(room, event)

    channel.handle_incoming.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_message_ignores_non_sync_room() -> None:
    client = MagicMock()
    client.user_id = "@agent:server"
    connection_manager = MagicMock()
    connection_manager.sync_forever = AsyncMock()

    runtime = MagicMock()
    runtime.resolve_optional = MagicMock(return_value=None)

    channel = MagicMock()
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    handler = MatrixMessageHandler(
        client=client,
        connection_manager=connection_manager,
        channel=channel,
        allowed_room_ids=["!sync:server"],
    )

    room, event = _matrix_event(room_id="!other:server", sender="@user:server")
    await handler._on_message(room, event)

    channel.handle_incoming.assert_not_awaited()
