"""Unit tests for Matrix ConnectionManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from nio import AsyncClient

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    pytestmark = pytest.mark.skip(reason="matrix-nio not installed")

if NIO_AVAILABLE:
    from app.channels.plugins.matrix.client.connection_manager import ConnectionManager


@pytest.fixture
def mock_client():
    """Create mock AsyncClient."""
    client = MagicMock(spec=AsyncClient)
    client.homeserver = "https://matrix.org"
    client.user_id = "@test:matrix.org"
    client.access_token = None
    client.device_id = None
    client.next_batch = None
    client.loaded_sync_token = None
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_session_manager():
    """Create mock SessionManager."""
    manager = MagicMock()
    manager.login = AsyncMock()
    return manager


@pytest.fixture
def connection_manager(mock_client, mock_session_manager):
    """Create ConnectionManager instance with test configuration."""
    return ConnectionManager(client=mock_client, session_manager=mock_session_manager)


class TestConnectionManagerInit:
    """Test ConnectionManager initialization."""

    def test_init_success(self, mock_client, mock_session_manager):
        """Test successful initialization."""
        manager = ConnectionManager(
            client=mock_client, session_manager=mock_session_manager
        )

        assert manager.client == mock_client
        assert manager.session_manager == mock_session_manager
        assert manager.connected is False

    def test_init_without_nio_available(self, mock_client, mock_session_manager):
        """Test initialization fails when matrix-nio not available."""
        with patch(
            "app.channels.plugins.matrix.client.connection_manager.NIO_AVAILABLE", False
        ):
            with pytest.raises(ImportError, match="matrix-nio is not installed"):
                ConnectionManager(
                    client=mock_client, session_manager=mock_session_manager
                )


class TestConnect:
    """Test connection establishment."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test successful connection establishment."""

        # Setup: Make client authenticated after login
        async def mock_login():
            mock_client.access_token = "test_token"
            mock_client.device_id = "TEST_DEVICE"

        mock_session_manager.login = AsyncMock(side_effect=mock_login)

        # Execute
        await connection_manager.connect()

        # Verify
        mock_session_manager.login.assert_called_once()
        assert connection_manager.connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test connection failure handling."""
        # Setup: Make login fail
        mock_session_manager.login = AsyncMock(
            side_effect=Exception("Authentication failed")
        )

        # Execute & Verify
        with pytest.raises(Exception, match="Authentication failed"):
            await connection_manager.connect()

        # Verify: Connection flag should be False
        assert connection_manager.connected is False


class TestDisconnect:
    """Test connection shutdown."""

    @pytest.mark.asyncio
    async def test_disconnect_success(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test successful disconnection."""

        # Setup: Establish connection first
        async def mock_login():
            mock_client.access_token = "test_token"
            mock_client.device_id = "TEST_DEVICE"

        mock_session_manager.login = AsyncMock(side_effect=mock_login)
        await connection_manager.connect()

        # Execute
        await connection_manager.disconnect()

        # Verify
        mock_client.close.assert_called_once()
        assert connection_manager.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_without_connection(self, connection_manager, mock_client):
        """Test disconnection when not connected."""
        # Execute (without prior connect)
        await connection_manager.disconnect()

        # Verify: Should still call close() safely
        mock_client.close.assert_called_once()
        assert connection_manager.connected is False


class TestHealthCheck:
    """Test connection health checking."""

    def test_health_check_healthy(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test health check when connection is healthy."""
        # Setup: Simulate healthy connection
        connection_manager.connected = True
        mock_client.access_token = "test_token"
        mock_client.device_id = "TEST_DEVICE"

        # Execute
        result = connection_manager.health_check()

        # Verify
        assert result is True

    def test_health_check_not_connected(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test health check when not connected."""
        # Setup: Not connected
        connection_manager.connected = False
        mock_client.access_token = "test_token"
        mock_client.device_id = "TEST_DEVICE"

        # Execute
        result = connection_manager.health_check()

        # Verify
        assert result is False

    def test_health_check_missing_token(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test health check when access token is missing."""
        # Setup: Connected but no token
        connection_manager.connected = True
        mock_client.access_token = None
        mock_client.device_id = "TEST_DEVICE"

        # Execute
        result = connection_manager.health_check()

        # Verify
        assert result is False

    def test_health_check_missing_device_id(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test health check when device ID is missing."""
        # Setup: Connected but no device ID
        connection_manager.connected = True
        mock_client.access_token = "test_token"
        mock_client.device_id = None

        # Execute
        result = connection_manager.health_check()

        # Verify
        assert result is False

    def test_health_check_all_conditions_required(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test that all three conditions (connected, token, device) are required."""
        # Setup: All conditions false
        connection_manager.connected = False
        mock_client.access_token = None
        mock_client.device_id = None

        # Execute
        result = connection_manager.health_check()

        # Verify
        assert result is False


class TestSessionPersistence:
    """Test session file preservation during disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_preserves_session_file(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test that disconnect does NOT delete session file."""
        # Note: This is a documentation test - session file deletion
        # is intentionally NOT implemented to enable automatic reconnection

        # Setup: Establish connection
        async def mock_login():
            mock_client.access_token = "test_token"
            mock_client.device_id = "TEST_DEVICE"

        mock_session_manager.login = AsyncMock(side_effect=mock_login)
        await connection_manager.connect()

        # Execute
        await connection_manager.disconnect()

        # Verify: Session file is preserved (no explicit delete should happen)
        # We verify the disconnect happened successfully and connection is closed
        assert connection_manager.connected is False
        # The mock_client.close() should have been called
        mock_client.close.assert_called_once()


class TestContainerRestartScenario:
    """Test container restart resilience."""

    @pytest.mark.asyncio
    async def test_reconnect_after_restart(
        self, connection_manager, mock_client, mock_session_manager
    ):
        """Test reconnection scenario after container restart."""

        # Track connection count to verify reconnection behavior
        connection_count = 0

        async def mock_login():
            nonlocal connection_count
            connection_count += 1
            mock_client.access_token = "test_token"
            mock_client.device_id = "TEST_DEVICE"

        # Scenario 1: Initial connection
        mock_session_manager.login = AsyncMock(side_effect=mock_login)
        await connection_manager.connect()
        assert connection_manager.connected is True
        assert connection_count == 1

        # Scenario 2: Container shutdown (disconnect)
        await connection_manager.disconnect()
        assert connection_manager.connected is False

        # Scenario 3: Container restart (reconnect)
        # SessionManager should restore session from file (simulated here)
        await connection_manager.connect()
        assert connection_manager.connected is True

        # Verify: Login called twice (initial + after restart)
        assert connection_count == 2


class TestRoomStateInitialization:
    """Restore nio room objects before admitting the first delta's messages."""

    @pytest.mark.asyncio
    async def test_full_state_preserves_cursor_and_releases_callbacks_in_order(
        self, connection_manager, mock_client
    ):
        from nio import SyncResponse

        connection_manager.connected = True
        mock_client.loaded_sync_token = "saved-cursor"
        mock_client.next_batch = ""
        mock_client.rooms = {}
        dispatched = []

        async def on_message(room, event):
            assert connection_manager.room_state_ready is True
            assert "!staff:example.org" in mock_client.rooms
            dispatched.append(event)

        async def sync_forever(**kwargs):
            assert kwargs == {"timeout": 30000, "full_state": True}
            assert mock_client.loaded_sync_token == "saved-cursor"
            assert mock_client.next_batch == ""
            assert not connection_manager.health_check()
            assert connection_manager.defer_until_room_state_ready(
                on_message, "!source:example.org", "first"
            )
            assert connection_manager.defer_until_room_state_ready(
                on_message, "!source:example.org", "second"
            )
            assert dispatched == []
            mock_client.rooms["!staff:example.org"] = object()
            response = SyncResponse.from_dict({"next_batch": "after-delta"})
            await connection_manager._on_sync_response(response)
            await connection_manager._on_sync_response(response)
            connection_manager.stop_sync()

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        await connection_manager.sync_forever()

        assert dispatched == ["first", "second"]
        assert not connection_manager.defer_until_room_state_ready(
            on_message, "!source:example.org", "later"
        )
        mock_client.sync_forever.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initial_sync_error_requests_full_state_again(
        self, connection_manager, mock_client
    ):
        from nio import SyncError, SyncResponse

        connection_manager.connected = True
        calls = 0

        async def sync_forever(**kwargs):
            nonlocal calls
            calls += 1
            assert kwargs["full_state"] is True
            assert connection_manager.room_state_ready is False
            if calls == 1:
                await connection_manager._on_sync_response(
                    SyncError("fixture sync failure", "M_UNKNOWN")
                )
            else:
                await connection_manager._on_sync_response(
                    SyncResponse.from_dict({"next_batch": "after-delta"})
                )
                connection_manager.stop_sync()

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with patch(
            "app.channels.plugins.matrix.client.connection_manager.asyncio.sleep",
            new=AsyncMock(),
        ):
            await connection_manager.sync_forever()
        assert calls == 2
        assert connection_manager.room_state_ready is True

    @pytest.mark.asyncio
    async def test_partial_response_failure_does_not_dispatch_or_reconnect(
        self, connection_manager, mock_client
    ):
        from app.channels.plugins.matrix.client.connection_manager import (
            MatrixRoomStateError,
        )

        callback = AsyncMock()
        connection_manager.connected = True

        async def sync_forever(**kwargs):
            connection_manager.defer_until_room_state_ready(
                callback, object(), object()
            )
            raise ValueError("fixture parsing failed after an earlier room")

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with pytest.raises(
            MatrixRoomStateError, match="initial_sync_processing_failed"
        ):
            await connection_manager.sync_forever()
        callback.assert_not_awaited()
        assert not connection_manager.room_state_ready
        assert not connection_manager.health_check()
        assert len(connection_manager._initial_events) == 1
        with pytest.raises(MatrixRoomStateError):
            await connection_manager.sync_forever()
        mock_client.sync_forever.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cancelled", [False, True])
    async def test_cursor_advance_before_first_callback_requires_reconciliation(
        self, connection_manager, mock_client, cancelled
    ):
        import asyncio

        from app.channels.plugins.matrix.client.connection_manager import (
            MatrixRoomStateError,
        )

        connection_manager.connected = True
        mock_client.loaded_sync_token = "saved-cursor"

        async def sync_forever(**kwargs):
            # Nio persists this before parsing the first room's state/events.
            mock_client.next_batch = "partially-processed-delta"
            if cancelled:
                raise asyncio.CancelledError()
            raise ValueError("fixture processing failed before first callback")

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        expected = asyncio.CancelledError if cancelled else MatrixRoomStateError
        with pytest.raises(expected):
            await connection_manager.sync_forever()
        assert not connection_manager._initial_events
        assert connection_manager.room_state_error is not None
        assert not connection_manager.health_check()
        assert mock_client.next_batch == "partially-processed-delta"
        with pytest.raises(MatrixRoomStateError):
            await connection_manager.sync_forever()
        mock_client.sync_forever.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_dispatch_failure_never_replays_callbacks(
        self, connection_manager, mock_client
    ):
        from app.channels.plugins.matrix.client.connection_manager import (
            MatrixRoomStateError,
        )
        from nio import SyncResponse

        first = AsyncMock()
        second = AsyncMock(side_effect=RuntimeError("fixture callback failed"))
        third = AsyncMock()
        connection_manager.connected = True

        async def sync_forever(**kwargs):
            for callback in (first, second, third):
                connection_manager.defer_until_room_state_ready(
                    callback, object(), object()
                )
            await connection_manager._on_sync_response(
                SyncResponse.from_dict({"next_batch": "after-delta"})
            )

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with pytest.raises(
            MatrixRoomStateError, match="initial_message_dispatch_interrupted"
        ):
            await connection_manager.sync_forever()
        first.assert_awaited_once()
        second.assert_awaited_once()
        third.assert_not_awaited()
        assert len(connection_manager._initial_events) == 1
        assert not connection_manager.room_state_ready
        assert not connection_manager.health_check()
        mock_client.sync_forever.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initial_buffer_limit_fails_closed(
        self, connection_manager, mock_client
    ):
        from app.channels.plugins.matrix.client.connection_manager import (
            MatrixRoomStateError,
        )

        connection_manager.connected = True
        connection_manager._MAX_INITIAL_EVENTS = 2
        callback = AsyncMock()

        async def sync_forever(**kwargs):
            for event in range(3):
                connection_manager.defer_until_room_state_ready(
                    callback, object(), event
                )

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with pytest.raises(MatrixRoomStateError, match="initial_event_buffer_limit"):
            await connection_manager.sync_forever()
        assert len(connection_manager._initial_events) == 2
        callback.assert_not_awaited()
        assert not connection_manager.health_check()

    @pytest.mark.asyncio
    async def test_cancellation_retains_pending_callback_and_stops(
        self, connection_manager, mock_client
    ):
        import asyncio

        callback = AsyncMock()
        connection_manager.connected = True

        async def sync_forever(**kwargs):
            connection_manager.defer_until_room_state_ready(
                callback, object(), object()
            )
            raise asyncio.CancelledError()

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with pytest.raises(asyncio.CancelledError):
            await connection_manager.sync_forever()
        assert connection_manager.room_state_error == "initial_sync_interrupted"
        assert not connection_manager.room_state_ready
        assert not connection_manager.health_check()
        assert len(connection_manager._initial_events) == 1
        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normal_cancellation_after_bootstrap_needs_no_reconciliation(
        self, connection_manager, mock_client
    ):
        import asyncio

        from nio import SyncResponse

        connection_manager.connected = True
        mock_client.loaded_sync_token = "saved-cursor"

        async def sync_forever(**kwargs):
            mock_client.next_batch = "after-delta"
            await connection_manager._on_sync_response(
                SyncResponse.from_dict({"next_batch": "after-delta"})
            )
            raise asyncio.CancelledError()

        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with pytest.raises(asyncio.CancelledError):
            await connection_manager.sync_forever()
        assert connection_manager.room_state_error is None
        assert not connection_manager.health_check()

    @pytest.mark.asyncio
    async def test_stop_during_bootstrap_dispatch_preserves_remaining_callbacks(
        self, connection_manager, mock_client
    ):
        from app.channels.plugins.matrix.client.connection_manager import (
            MatrixRoomStateError,
        )
        from nio import SyncResponse

        first = AsyncMock(side_effect=connection_manager.stop_sync)
        second = AsyncMock()
        connection_manager.connected = True

        async def sync_forever(**kwargs):
            connection_manager.defer_until_room_state_ready(first, object(), object())
            connection_manager.defer_until_room_state_ready(second, object(), object())
            await connection_manager._on_sync_response(
                SyncResponse.from_dict({"next_batch": "after-delta"})
            )

        # Ignore the callback arguments when simulating a local shutdown signal.
        first.side_effect = lambda *args: connection_manager.stop_sync()
        mock_client.sync_forever = AsyncMock(side_effect=sync_forever)
        with pytest.raises(
            MatrixRoomStateError, match="initial_message_dispatch_interrupted"
        ):
            await connection_manager.sync_forever()
        first.assert_awaited_once()
        second.assert_not_awaited()
        assert len(connection_manager._initial_events) == 1
        assert not connection_manager.health_check()
