"""Real nio/Olm restart coverage with synthetic stores and an in-memory transport.

No homeserver is contacted. Run with the project's pinned E2EE dependencies;
environments without python-olm skip this file rather than simulate encryption.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("olm", reason="real matrix-nio E2EE dependencies required")

from app.channels.plugins.matrix.channel import MatrixChannel  # noqa: E402
from app.channels.plugins.matrix.client.connection_manager import (  # noqa: E402
    ConnectionManager,
    MatrixRoomStateError,
)
from app.channels.plugins.matrix.client.session_manager import (  # noqa: E402
    SessionManager,
)
from app.channels.plugins.matrix.message_handler import (  # noqa: E402
    MatrixMessageHandler,
)
from app.channels.runtime import ChannelRuntime  # noqa: E402
from app.services.channel_autoresponse_policy_service import (  # noqa: E402
    ChannelAutoResponsePolicyService,
)
from nio import (  # noqa: E402
    AsyncClient,
    AsyncClientConfig,
    JoinedMembersResponse,
    KeysQueryResponse,
    KeysUploadResponse,
    MegolmEvent,
    RoomMessageText,
    RoomSendResponse,
    SyncResponse,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

USER = "@synthetic-bot:example.invalid"
DEVICE = "SYNTHETIC_DEVICE"
TOKEN = "synthetic-not-a-real-token"
STAFF = "!synthetic-staff:example.invalid"
SOURCE = "!synthetic-source:example.invalid"
SAVED_CURSOR = "synthetic-saved-cursor"


def _room_state(room_id):
    return {
        "state": {
            "events": [
                {
                    "type": "m.room.encryption",
                    "state_key": "",
                    "event_id": f"$encryption-{room_id}",
                    "sender": USER,
                    "origin_server_ts": 1,
                    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                },
                {
                    "type": "m.room.member",
                    "state_key": USER,
                    "event_id": f"$membership-{room_id}",
                    "sender": USER,
                    "origin_server_ts": 2,
                    "content": {"membership": "join"},
                },
            ]
        },
        "summary": {"m.joined_member_count": 1, "m.invited_member_count": 0},
        "timeline": {"events": [], "limited": False, "prev_batch": "old"},
        "ephemeral": {"events": []},
        "account_data": {"events": []},
    }


def _sync_response(cursor, rooms):
    response = SyncResponse.from_dict(
        {
            "next_batch": cursor,
            "rooms": {"join": rooms},
            "device_lists": {"changed": [], "left": []},
            "device_one_time_keys_count": {},
        }
    )
    assert isinstance(response, SyncResponse)
    return response


def _client(store_dir):
    return AsyncClient(
        "https://example.invalid",
        USER,
        store_path=str(store_dir),
        config=AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True),
    )


def _event(content, event_id):
    event = MegolmEvent.from_dict(
        {
            "type": "m.room.encrypted",
            "room_id": STAFF,
            "event_id": event_id,
            "sender": USER,
            "origin_server_ts": 100,
            "content": content,
        }
    )
    assert isinstance(event, MegolmEvent)
    return event


async def _restart_with_real_store(tmp_path):
    """Initialize an isolated account, close it, restore it using production code."""
    store_dir = tmp_path / "synthetic-store"
    store_dir.mkdir()
    session_path = tmp_path / "synthetic-session.json"
    session_path.write_text(
        json.dumps({"user_id": USER, "device_id": DEVICE, "access_token": TOKEN})
    )
    original = _client(store_dir)
    original.restore_login(USER, DEVICE, TOKEN)
    await original.receive_response(
        _sync_response(SAVED_CURSOR, {STAFF: _room_state(STAFF)})
    )
    await original.receive_response(
        JoinedMembersResponse.from_dict({"joined": {USER: {}}}, STAFF)
    )
    assert original.olm is not None
    assert original.store is not None
    identity_keys = dict(original.olm.account.identity_keys)
    original.olm.create_outbound_group_session(STAFF)
    original.olm.outbound_group_sessions[STAFF].shared = True
    _, old_ciphertext = original.encrypt(
        STAFF, "m.room.message", {"msgtype": "m.text", "body": "Before restart"}
    )
    await original.close()
    original.store.database.close()

    restored = _client(store_dir)
    manager = SessionManager(
        client=restored,
        password="",
        session_file=str(session_path),
        restore_only=True,
    )
    assert manager._load_session()
    assert restored.olm is not None
    assert restored.store is not None
    assert restored.user_id == USER
    assert restored.device_id == DEVICE
    assert restored.access_token == TOKEN
    assert restored.olm.account.identity_keys == identity_keys
    assert restored.loaded_sync_token == SAVED_CURSOR
    assert STAFF in restored.encrypted_rooms
    assert restored.rooms == {}
    # Real persisted inbound Megolm key is usable after closing/reopening the DB.
    old_event = restored.decrypt_event(_event(old_ciphertext, "$before-restart"))
    assert isinstance(old_event, RoomMessageText)
    assert old_event.body == "Before restart"
    return restored, identity_keys


class SyntheticTransport:
    """Replace only nio's HTTP boundary; parse and apply its real responses."""

    def __init__(self, client, *, staff_present=True, timeline_events=None):
        self.client = client
        self.staff_present = staff_present
        self.timeline_events = timeline_events or []
        self.requests = []
        self.sent_events = []

    async def __call__(
        self, response_class, method, path, data=None, response_data=(), **kwargs
    ):
        self.requests.append((response_class, method, path))
        if response_class is SyncResponse:
            query = parse_qs(urlparse(path).query)
            assert query["since"] == [SAVED_CURSOR]
            assert query["full_state"] == ["true"]
            rooms = {SOURCE: _room_state(SOURCE)}
            rooms[SOURCE]["timeline"]["events"] = self.timeline_events
            if self.staff_present:
                rooms[STAFF] = _room_state(STAFF)
            response = _sync_response("synthetic-resumed-cursor", rooms)
        elif response_class is JoinedMembersResponse:
            assert response_data == (STAFF,)
            response = JoinedMembersResponse.from_dict({"joined": {USER: {}}}, STAFF)
        elif response_class is KeysQueryResponse:
            device_keys = self.client.olm.share_keys()["device_keys"]
            response = KeysQueryResponse.from_dict(
                {"device_keys": {USER: {DEVICE: device_keys}}, "failures": {}}
            )
        elif response_class is KeysUploadResponse:
            response = KeysUploadResponse.from_dict(
                {"one_time_key_counts": {"signed_curve25519": 50}}
            )
        elif response_class is RoomSendResponse:
            assert method == "PUT"
            assert "/send/m.room.encrypted/" in path
            content = json.loads(data)
            assert content["algorithm"] == "m.megolm.v1.aes-sha2"
            assert "body" not in content
            event_id = f"$synthetic-sent-{len(self.sent_events) + 1}"
            self.sent_events.append((event_id, content, path))
            response = RoomSendResponse.from_dict({"event_id": event_id}, STAFF)
        else:
            raise AssertionError(f"Unexpected transport operation: {response_class}")
        await self.client.receive_response(response)
        return response


def _channel(tmp_path, client):
    policy = ChannelAutoResponsePolicyService(str(tmp_path / "synthetic-policy.db"))
    policy.set_policy(
        "matrix",
        generation_enabled=True,
        enabled=False,
        ai_response_mode="hitl",
        response_kind="public_context",
        delivery_audience="staff_room",
    )
    settings = SimpleNamespace(
        MATRIX_SYNC_ENABLED=True,
        MATRIX_CONTEXT_SOURCE_ROOMS=[SOURCE],
        MATRIX_STAFF_ROOM=STAFF,
        MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES=True,
    )
    runtime = ChannelRuntime(settings=settings, rag_service=MagicMock())
    runtime.register("matrix_client", client)
    runtime.register("channel_autoresponse_policy_service", policy)
    channel = MatrixChannel(runtime)
    channel._is_connected = True
    return channel


async def test_real_crypto_store_restore_full_state_and_encrypted_staff_thread(
    tmp_path,
):
    client, identity_keys = await _restart_with_real_store(tmp_path)
    source_event = {
        "type": "m.room.message",
        "event_id": "$new-synthetic-source",
        "sender": "@synthetic-participant:example.invalid",
        "origin_server_ts": 101,
        "content": {"msgtype": "m.text", "body": "Synthetic question"},
    }
    transport = SyntheticTransport(client, timeline_events=[source_event])
    client._send = transport
    manager = ConnectionManager(client, SimpleNamespace(login=AsyncMock()))
    # Restore-only local loading ran above; live authentication is outside this test.
    manager.connected = True
    channel = _channel(tmp_path, client)
    handler = MatrixMessageHandler(
        client=client,
        connection_manager=manager,
        channel=channel,
        autoresponse_policy_service=channel.runtime.resolve_optional(
            "channel_autoresponse_policy_service"
        ),
        allowed_room_ids=[SOURCE],
    )
    handler._record_trust_event = AsyncMock()
    handler._is_staff_sender = MagicMock(return_value=False)
    observed_before_staff_state = []
    delivered = []

    async def before_message(room, event):
        # Nio parses rooms in response order; the source callback runs first.
        observed_before_staff_state.append(
            (STAFF in client.rooms, manager.room_state_ready)
        )

    async def process(incoming):
        assert incoming.message_id == "$new-synthetic-source"
        assert manager.room_state_ready
        assert client.rooms[STAFF].encrypted
        root = await channel.send_staff_context(
            incoming.question,
            transaction_id="synthetic-root",
            expected_room_id=STAFF,
        )
        assert root.sent
        note = await channel.send_staff_context(
            "AI context · Synthetic fact.",
            transaction_id="synthetic-note",
            expected_room_id=STAFF,
            thread_root_event_id=root.external_message_id,
        )
        assert note.sent
        delivered.append((root, note))

    async def stop_after_first_response(response):
        manager.stop_sync()
        client.stop_sync_forever()

    process_mock = AsyncMock(side_effect=process)
    handler._get_orchestrator = MagicMock(
        return_value=SimpleNamespace(process_incoming=process_mock)
    )
    client.add_event_callback(before_message, RoomMessageText)
    client.add_event_callback(handler._on_message, RoomMessageText)
    client.add_response_callback(stop_after_first_response, SyncResponse)
    try:
        await asyncio.wait_for(manager.sync_forever(timeout=0), timeout=5)
        assert observed_before_staff_state == [(False, False)]
        process_mock.assert_awaited_once()
        manager.session_manager.login.assert_not_awaited()
        assert manager.room_state_error is None
        assert len(delivered) == 1
        root, note = delivered[0]
        assert client.rooms[STAFF].encrypted
        assert client.store.load_sync_token() == "synthetic-resumed-cursor"
        assert client.olm.account.identity_keys == identity_keys
        assert len(transport.sent_events) == 2
        assert sum(request[0] is SyncResponse for request in transport.requests) == 1
        plaintext = [
            client.decrypt_event(_event(content, event_id))
            for event_id, content, _ in transport.sent_events
        ]
        assert plaintext[0].body == "Synthetic question"
        assert plaintext[1].body == "AI context · Synthetic fact."
        relation = {
            "rel_type": "m.thread",
            "event_id": root.external_message_id,
            "is_falling_back": True,
            "m.in_reply_to": {"event_id": root.external_message_id},
        }
        assert plaintext[1].source["content"]["m.relates_to"] == relation
        assert transport.sent_events[1][1]["m.relates_to"] == relation
        assert transport.sent_events[0][2].split("?")[0].endswith("/synthetic-root")
        assert transport.sent_events[1][2].split("?")[0].endswith("/synthetic-note")
    finally:
        await client.close()
        client.store.database.close()


async def test_real_restored_client_does_not_send_without_staff_room(tmp_path):
    client, _ = await _restart_with_real_store(tmp_path)
    transport = SyntheticTransport(client, staff_present=False)
    client._send = transport
    try:
        await client.sync(timeout=0, full_state=True)
        channel = _channel(tmp_path, client)
        result = await channel.send_staff_context(
            "Synthetic question",
            transaction_id="synthetic-root",
            expected_room_id=STAFF,
        )
        assert not result.sent
        assert result.error == "staff_context_room_state_unavailable"
        assert transport.sent_events == []
        assert [request[0] for request in transport.requests] == [SyncResponse]
    finally:
        await client.close()
        client.store.database.close()


async def test_real_saved_cursor_partial_sync_failure_never_reconnects(tmp_path):
    client, identity_keys = await _restart_with_real_store(tmp_path)
    transport = SyntheticTransport(client)
    client._send = transport
    manager = ConnectionManager(client, SimpleNamespace(login=AsyncMock()))
    manager.connected = True
    # Nio has persisted next_batch before entering this room-processing phase.
    client._handle_joined_rooms = AsyncMock(
        side_effect=ValueError("synthetic room processing fault")
    )
    try:
        with pytest.raises(
            MatrixRoomStateError, match="initial_sync_processing_failed"
        ):
            await asyncio.wait_for(manager.sync_forever(timeout=0), timeout=5)
        assert manager.room_state_ready is False
        assert manager.health_check() is False
        assert not manager._initial_events
        assert client.store.load_sync_token() == "synthetic-resumed-cursor"
        assert client.olm.account.identity_keys == identity_keys
        assert transport.sent_events == []
        assert [request[0] for request in transport.requests] == [SyncResponse]
        with pytest.raises(MatrixRoomStateError):
            await manager.sync_forever(timeout=0)
        assert len(transport.requests) == 1
    finally:
        await client.close()
        client.store.database.close()
