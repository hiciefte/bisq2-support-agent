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
