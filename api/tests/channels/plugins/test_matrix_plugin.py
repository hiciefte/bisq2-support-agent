"""Tests for Matrix Channel Plugin.

TDD tests for the Matrix channel plugin that wraps existing matrix integration.

Note: Matrix channel wraps the existing Matrix integration components:
- ConnectionManager for connection lifecycle
- SessionManager for authentication
- Matrix nio AsyncClient for room operations
"""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    IncomingMessage,
    OutgoingMessage,
    SendResult,
    UserContext,
)
from app.channels.plugins.matrix.channel import MatrixChannel
from app.channels.runtime import ChannelRuntime
from app.channels.trust_monitor.publisher import CompositeTrustAlertPublisher


class TestMatrixChannelProperties:
    """Test MatrixChannel properties and identification."""

    @pytest.mark.unit
    def test_channel_id_is_matrix(self):
        """MatrixChannel has channel_id 'matrix'."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert channel.channel_id == "matrix"

    @pytest.mark.unit
    def test_capabilities_include_text_messages(self):
        """MatrixChannel supports text message capability."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.TEXT_MESSAGES in channel.capabilities

    @pytest.mark.unit
    def test_capabilities_include_persistent_connection(self):
        """MatrixChannel supports persistent connection capability."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        assert ChannelCapability.PERSISTENT_CONNECTION in channel.capabilities

    @pytest.mark.unit
    def test_staff_notification_target_prefers_matrix_staff_room(self):
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_STAFF_ROOM="!staff:matrix.org",
            MATRIX_ALERT_ROOM="!alert:matrix.org",
        )
        channel = MatrixChannel(runtime)

        target = channel.get_staff_notification_target({})

        assert target == "!staff:matrix.org"

    @pytest.mark.unit
    def test_staff_notification_target_falls_back_to_alert_room(self):
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_STAFF_ROOM="",
            MATRIX_ALERT_ROOM="!alert:matrix.org",
        )
        channel = MatrixChannel(runtime)

        target = channel.get_staff_notification_target({})

        assert target == "!alert:matrix.org"


class TestMatrixChannelLifecycle:
    """Test MatrixChannel lifecycle methods."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_succeeds_with_connection_manager(self):
        """MatrixChannel starts successfully when ConnectionManager is available."""

        # Create mock ConnectionManager
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_conn_manager)

        channel = MatrixChannel(runtime)
        await channel.start()

        assert channel.is_connected is True
        mock_conn_manager.connect.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_wires_trust_alerts_before_message_handler(self):
        order: list[str] = []
        mock_conn_manager = SimpleNamespace(
            connect=AsyncMock(),
        )
        message_handler = SimpleNamespace(
            channel=None,
            start=AsyncMock(side_effect=lambda: order.append("message_handler")),
        )
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace()
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "matrix_connection_manager": mock_conn_manager,
                "matrix_message_handler": message_handler,
            }.get(name)
        )
        channel = MatrixChannel(runtime)
        channel._wire_trust_monitor_alerts = AsyncMock(
            side_effect=lambda: order.append("trust_alerts")
        )

        await channel.start()

        assert order[:2] == ["trust_alerts", "message_handler"]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wire_trust_monitor_binds_matrix_owner_loop(self):
        publisher = SimpleNamespace(
            matrix_notifier=None,
            bind_loop=MagicMock(),
        )
        trust_monitor_service = SimpleNamespace(publisher=publisher)
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(MATRIX_STAFF_ROOM="!staff:matrix.org")
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                trust_monitor_service if name == "trust_monitor_service" else None
            )
        )
        channel = MatrixChannel(runtime)

        await channel._wire_trust_monitor_alerts()

        publisher.bind_loop.assert_called_once_with(asyncio.get_running_loop())

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_trust_monitor_notifier_reports_transport_failure(self, monkeypatch):
        publisher = SimpleNamespace(matrix_notifier=None, bind_loop=MagicMock())
        trust_monitor_service = SimpleNamespace(publisher=publisher)
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(MATRIX_STAFF_ROOM="!staff:matrix.org")
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                trust_monitor_service if name == "trust_monitor_service" else None
            )
        )
        channel = MatrixChannel(runtime)
        channel.send_message = AsyncMock(
            return_value=SendResult(sent=False, error="transport down")
        )
        monkeypatch.setattr(
            "app.channels.trust_monitor.alert_formatting.format_trust_alert_for_matrix",
            lambda _finding: "trust alert",
        )

        await channel._wire_trust_monitor_alerts()
        delivered = await publisher.matrix_notifier(SimpleNamespace(id=1))

        assert delivered is False

    def test_trust_publisher_timeout_covers_missing_room_recovery_budget(self):
        assert (
            CompositeTrustAlertPublisher.DEFAULT_DELIVERY_TIMEOUT_SECONDS
            > MatrixChannel.MATRIX_OP_TIMEOUT_SECONDS * 4
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_joins_trust_monitor_rooms(self):
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock()
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                mock_conn_manager if name == "matrix_connection_manager" else None
            )
        )
        runtime.settings = SimpleNamespace(
            MATRIX_SYNC_ROOMS=["!sync:matrix.org"],
            TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=["!trust:matrix.org"],
            TRUST_MONITOR_MATRIX_STAFF_ROOM="!staff:matrix.org",
        )

        channel = MatrixChannel(runtime)
        channel.join_room = AsyncMock(return_value=True)

        await channel.start()

        joined = {call.args[0] for call in channel.join_room.call_args_list}
        assert joined == {"!sync:matrix.org", "!trust:matrix.org", "!staff:matrix.org"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_joins_matrix_chatops_rooms(self):
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock()
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                mock_conn_manager if name == "matrix_connection_manager" else None
            )
        )
        runtime.settings = SimpleNamespace(
            MATRIX_SYNC_ROOMS=["!sync:matrix.org"],
            TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=[],
            TRUST_MONITOR_MATRIX_STAFF_ROOM="",
            MATRIX_CHATOPS_ROOM_IDS=["!private-chatops:matrix.org"],
        )

        channel = MatrixChannel(runtime)
        channel.join_room = AsyncMock(return_value=True)

        await channel.start()

        joined = {call.args[0] for call in channel.join_room.call_args_list}
        assert joined == {"!sync:matrix.org", "!private-chatops:matrix.org"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_degraded_without_connection_manager(self):
        """MatrixChannel starts in degraded mode when ConnectionManager not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        await channel.start()

        # Channel starts but is not connected
        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_handles_connection_failure(self):
        """MatrixChannel handles connection failure gracefully."""

        # Create mock ConnectionManager that fails
        mock_conn_manager = MagicMock()
        mock_conn_manager.connect = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_conn_manager)

        channel = MatrixChannel(runtime)
        await channel.start()

        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds_with_connection_manager(self):
        """MatrixChannel stops successfully when ConnectionManager is available."""

        # Create mock ConnectionManager
        mock_conn_manager = MagicMock()
        mock_conn_manager.disconnect = AsyncMock()

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_conn_manager)

        channel = MatrixChannel(runtime)
        channel._is_connected = True

        await channel.stop()

        assert channel.is_connected is False
        mock_conn_manager.disconnect.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_succeeds_without_connection_manager(self):
        """MatrixChannel stops gracefully when ConnectionManager not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        channel._is_connected = True

        await channel.stop()

        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_unregisters_stopped_proactive_scanner(self):
        """Stopped proactive scanner is removed so a restart can create a fresh one."""

        proactive_scanner = MagicMock()
        proactive_scanner.stop = AsyncMock()
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                proactive_scanner if name == "proactive_scanner" else None
            )
        )

        channel = MatrixChannel(runtime)
        channel._is_connected = True

        await channel.stop()

        proactive_scanner.stop.assert_awaited_once()
        runtime.unregister.assert_called_once_with("proactive_scanner")
        assert channel.is_connected is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_expired_session_rotation_stops_and_rebuilds_live_client(
        self,
        tmp_path,
        monkeypatch,
    ):
        from app.services.privacy_retention_service import RetentionStoreResult

        session_path = tmp_path / "matrix-session.json"
        connection_manager = SimpleNamespace(disconnect=AsyncMock())
        client = SimpleNamespace(access_token="token", device_id="device")
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_SYNC_SESSION_PATH=str(session_path),
            DATA_RETENTION_DAYS=7,
        )
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "matrix_connection_manager": connection_manager,
                "matrix_client": client,
            }.get(name)
        )
        channel = MatrixChannel(runtime)

        async def reconnect() -> None:
            channel._is_connected = True

        channel.start = AsyncMock(side_effect=reconnect)
        expired = RetentionStoreResult(2, None, 7 * 86400.0)
        prune = MagicMock(return_value=expired)
        monkeypatch.setattr(
            "app.services.privacy_retention_service.prune_matrix_session_artifacts",
            prune,
        )
        setup_dependencies = MagicMock()
        monkeypatch.setattr(MatrixChannel, "setup_dependencies", setup_dependencies)

        result = await channel.rotate_expired_session()

        assert result is expired
        connection_manager.disconnect.assert_awaited_once_with()
        channel.start.assert_awaited_once_with()
        setup_dependencies.assert_called_once_with(runtime, runtime.settings)
        assert client.access_token is None
        assert client.device_id is None
        assert prune.call_count == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_expired_session_rotation_keeps_files_when_disconnect_fails(
        self,
        tmp_path,
    ):
        session_path = tmp_path / "matrix-session.json"
        session_path.write_text("session", encoding="utf-8")
        old_timestamp = session_path.stat().st_mtime - 2 * 86400
        os.utime(session_path, (old_timestamp, old_timestamp))
        connection_manager = SimpleNamespace(
            disconnect=AsyncMock(side_effect=RuntimeError("close failed"))
        )
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_SYNC_SESSION_PATH=str(session_path),
            DATA_RETENTION_DAYS=1,
        )
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: (
                connection_manager if name == "matrix_connection_manager" else None
            )
        )
        channel = MatrixChannel(runtime)

        with pytest.raises(RuntimeError, match="did not close cleanly"):
            await channel.rotate_expired_session()

        assert session_path.exists()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_expired_session_rotation_fails_when_reconnect_is_unhealthy(
        self,
        tmp_path,
        monkeypatch,
    ):
        from app.services.privacy_retention_service import RetentionStoreResult

        session_path = tmp_path / "matrix-session.json"
        connection_manager = SimpleNamespace(disconnect=AsyncMock())
        client = SimpleNamespace(access_token="token", device_id="device")
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(
            MATRIX_SYNC_SESSION_PATH=str(session_path),
            DATA_RETENTION_DAYS=7,
        )
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "matrix_connection_manager": connection_manager,
                "matrix_client": client,
            }.get(name)
        )
        channel = MatrixChannel(runtime)
        channel.start = AsyncMock()
        expired = RetentionStoreResult(1, None, 7 * 86400.0)
        monkeypatch.setattr(
            "app.services.privacy_retention_service.prune_matrix_session_artifacts",
            MagicMock(return_value=expired),
        )
        monkeypatch.setattr(MatrixChannel, "setup_dependencies", MagicMock())

        with pytest.raises(RuntimeError, match="did not reconnect"):
            await channel.rotate_expired_session()

        connection_manager.disconnect.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_waits_for_in_flight_send(self):
        send_started = asyncio.Event()
        release_send = asyncio.Event()

        async def room_send(**_kwargs):
            send_started.set()
            await release_send.wait()
            return SimpleNamespace(event_id="$sent")

        client = SimpleNamespace(room_send=room_send)
        connection_manager = SimpleNamespace(disconnect=AsyncMock())
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.settings = SimpleNamespace(MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES=True)
        runtime.resolve_optional = MagicMock(
            side_effect=lambda name: {
                "matrix_client": client,
                "matrix_connection_manager": connection_manager,
            }.get(name)
        )
        channel = MatrixChannel(runtime)
        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "fixture"
        outgoing.in_reply_to = ""
        outgoing.sources = []
        outgoing.metadata = None

        send_task = asyncio.create_task(channel.send_message("!room", outgoing))
        await send_started.wait()
        stop_task = asyncio.create_task(channel.stop())
        await asyncio.sleep(0)

        connection_manager.disconnect.assert_not_awaited()

        release_send.set()
        assert await send_task
        await stop_task
        connection_manager.disconnect.assert_awaited_once_with()

    @pytest.mark.unit
    def test_health_check_returns_healthy_when_connected(self):
        """Health check returns healthy when connected."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        channel._is_connected = True
        status = channel.health_check()
        assert status.healthy is True

    @pytest.mark.unit
    def test_health_check_returns_unhealthy_when_disconnected(self):
        """Health check returns unhealthy when disconnected."""

        runtime = MagicMock(spec=ChannelRuntime)
        channel = MatrixChannel(runtime)
        channel._is_connected = False
        status = channel.health_check()
        assert status.healthy is False


class TestMatrixChannelMessageHandling:
    """Test MatrixChannel message handling."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_calls_rag_service(self, mock_rag_service):
        """handle_incoming delegates to RAG service."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = MatrixChannel(runtime)

        message = IncomingMessage(
            message_id="matrix-msg-001",
            channel=ChannelType.MATRIX,
            question="How do I run a Bisq node?",
            user=UserContext(user_id="@user:matrix.org"),
        )

        await channel.handle_incoming(message)

        mock_rag_service.query.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_handle_incoming_returns_outgoing_message(self, mock_rag_service):
        """handle_incoming returns OutgoingMessage."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.rag_service = mock_rag_service
        channel = MatrixChannel(runtime)

        message = IncomingMessage(
            message_id="matrix-msg-001",
            channel=ChannelType.MATRIX,
            question="How do I run a Bisq node?",
            user=UserContext(user_id="@user:matrix.org"),
        )

        result = await channel.handle_incoming(message)

        assert isinstance(result, OutgoingMessage)
        assert result.in_reply_to == message.message_id
        assert result.channel == ChannelType.MATRIX

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_with_matrix_client(self):
        """send_message uses Matrix client to send to room."""

        # Create mock Matrix client with successful send
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$event123"
        mock_client.room_send = AsyncMock(return_value=mock_response)
        mock_client.rooms = {"!room:matrix.org": MagicMock()}

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        outgoing.in_reply_to = "$question-event"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        mock_client.room_send.assert_called_once()
        sent_content = mock_client.room_send.call_args.kwargs["content"]
        assert sent_content["format"] == "org.matrix.custom.html"
        assert "formatted_body" in sent_content
        assert (
            sent_content["m.relates_to"]["m.in_reply_to"]["event_id"]
            == "$question-event"
        )
        assert (
            mock_client.room_send.call_args.kwargs["ignore_unverified_devices"] is True
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_recovers_missing_room_and_retries(self):
        """send_message retries once after recovering missing local room state."""

        class MockRoomSendError:
            message = "No such room with id !room:matrix.org found."

        mock_client = MagicMock()
        mock_client.rooms = {}
        success = MagicMock()
        success.event_id = "$event456"
        mock_client.room_send = AsyncMock(side_effect=[MockRoomSendError(), success])
        mock_client.sync = AsyncMock(return_value=MagicMock())
        mock_client.join = AsyncMock(return_value=MagicMock(room_id="!room:matrix.org"))

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        assert mock_client.room_send.await_count == 2
        mock_client.sync.assert_called_once()
        mock_client.join.assert_called_once_with("!room:matrix.org")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_honors_ignore_unverified_toggle(self):
        """send_message can enforce verified devices when explicitly configured."""

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$event123"
        mock_client.room_send = AsyncMock(return_value=mock_response)
        mock_client.rooms = {"!room:matrix.org": MagicMock()}

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)
        runtime.settings = MagicMock()
        runtime.settings.MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES = False

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        assert (
            mock_client.room_send.call_args.kwargs["ignore_unverified_devices"] is False
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_uses_notice_msgtype_for_staff_notice(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$event123"
        mock_client.room_send = AsyncMock(return_value=mock_response)
        mock_client.rooms = {"!room:matrix.org": MagicMock()}

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Escalation #123 queued"
        outgoing.in_reply_to = "$question-event"
        outgoing.metadata = MagicMock()
        outgoing.metadata.routing_action = "staff_escalation_notice"

        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is True
        sent_content = mock_client.room_send.call_args.kwargs["content"]
        assert sent_content["msgtype"] == "m.notice"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_returns_false_without_client(self):
        """send_message returns False when Matrix client not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_handles_send_error(self):
        """send_message handles Matrix send errors gracefully."""

        class MockRoomSendError:
            message = "Permission denied"

        # Create mock Matrix client that returns an error-like response
        # without event_id (matching nio error behavior).
        mock_client = MagicMock()
        mock_client.room_send = AsyncMock(return_value=MockRoomSendError())

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        outgoing = MagicMock(spec=OutgoingMessage)
        outgoing.answer = "Test response"
        result = await channel.send_message("!room:matrix.org", outgoing)

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_reaction_sends_matrix_reaction_event(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.event_id = "$reaction123"
        mock_client.room_send = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)

        sent = await channel.send_reaction(
            room_id="!room:matrix.org",
            event_id="$target123",
            key="👀",
        )

        assert bool(sent) is True
        call_kwargs = mock_client.room_send.call_args.kwargs
        assert call_kwargs["room_id"] == "!room:matrix.org"
        assert call_kwargs["message_type"] == "m.reaction"
        assert call_kwargs["content"]["m.relates_to"]["event_id"] == "$target123"
        assert call_kwargs["content"]["m.relates_to"]["key"] == "👀"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_reaction_returns_false_without_matrix_client(self):
        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)

        sent = await channel.send_reaction(
            room_id="!room:matrix.org",
            event_id="$target123",
            key="👀",
        )
        assert sent is False


class TestMatrixChannelRoomManagement:
    """Test MatrixChannel room management."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_with_matrix_client(self):
        """join_room uses Matrix client to join room."""

        # Create mock Matrix client with successful join
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.room_id = "!room:matrix.org"
        mock_client.join = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.join_room("!room:matrix.org")

        assert bool(result) is True
        mock_client.join.assert_called_once_with("!room:matrix.org")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_returns_false_without_client(self):
        """join_room returns False when Matrix client not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        result = await channel.join_room("!room:matrix.org")

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_join_room_handles_join_error(self):
        """join_room handles Matrix join errors gracefully."""

        # Create mock Matrix client that returns error
        mock_client = MagicMock()
        mock_error = MagicMock()
        mock_error.room_id = None  # Error responses don't have room_id
        mock_error.message = "Room not found"
        mock_client.join = AsyncMock(return_value=mock_error)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.join_room("!room:matrix.org")

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_with_matrix_client(self):
        """leave_room uses Matrix client to leave room."""

        # Create mock Matrix client with successful leave
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.room_id = "!room:matrix.org"  # Has room_id on success
        mock_client.room_leave = AsyncMock(return_value=mock_response)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.leave_room("!room:matrix.org")

        assert bool(result) is True
        mock_client.room_leave.assert_called_once_with("!room:matrix.org")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_returns_false_without_client(self):
        """leave_room returns False when Matrix client not available."""

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=None)

        channel = MatrixChannel(runtime)
        result = await channel.leave_room("!room:matrix.org")

        assert bool(result) is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_leave_room_handles_leave_error(self):
        """leave_room handles Matrix leave errors gracefully."""

        # Create mock Matrix client that returns error
        mock_client = MagicMock()
        mock_error = MagicMock()
        mock_error.room_id = None  # Error responses don't have room_id
        mock_error.message = "Not a member"
        mock_client.room_leave = AsyncMock(return_value=mock_error)

        runtime = MagicMock(spec=ChannelRuntime)
        runtime.resolve_optional = MagicMock(return_value=mock_client)

        channel = MatrixChannel(runtime)
        result = await channel.leave_room("!room:matrix.org")

        assert bool(result) is False
