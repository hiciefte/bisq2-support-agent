"""Tests for Matrix alert service.

TDD tests for the Matrix alerting functionality that sends
Prometheus Alertmanager alerts to a dedicated Matrix room.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMatrixAlertSettingsProtocol:
    """Test suite for MatrixAlertSettings Protocol type safety."""

    def test_protocol_can_be_imported(self):
        """Test that MatrixAlertSettings Protocol can be imported."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertSettings,
        )

        assert MatrixAlertSettings is not None

    def test_protocol_defines_required_attributes(self):
        """Test that Protocol defines all required Matrix settings attributes."""
        from typing import get_type_hints

        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertSettings,
        )

        # Protocol should define these attributes
        hints = get_type_hints(MatrixAlertSettings)
        assert "MATRIX_HOMESERVER_URL" in hints
        assert "MATRIX_USER" in hints
        assert "MATRIX_ALERT_ROOM" in hints

    def test_settings_class_satisfies_protocol(self):
        """Test that Settings class satisfies MatrixAlertSettings Protocol."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertSettings,
        )
        from app.core.config import Settings

        # Settings should have all required attributes
        settings = Settings()
        assert hasattr(settings, "MATRIX_HOMESERVER_URL")
        assert hasattr(settings, "MATRIX_USER")
        assert hasattr(settings, "MATRIX_ALERT_ROOM")

        # Should be usable where MatrixAlertSettings is expected (duck typing)
        # This verifies structural subtyping works
        def accepts_settings(s: MatrixAlertSettings) -> str:
            return s.MATRIX_HOMESERVER_URL

        result = accepts_settings(settings)
        assert isinstance(result, str)


class TestMatrixAlertServiceSessionPath:
    """Test suite for session path portability."""

    def test_uses_explicit_alert_session_file_when_set(self):
        """Test that MATRIX_ALERT_SESSION_FILE takes precedence when set."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        settings.MATRIX_ALERT_SESSION_FILE = "/custom/path/alert_session.json"
        settings.MATRIX_SYNC_SESSION_FILE = "/data/matrix_session.json"

        service = MatrixAlertService(settings)
        session_path = service._get_session_path()

        assert session_path == "/custom/path/alert_session.json"

    def test_derives_path_from_sync_session_file_directory(self):
        """Test that path is derived from MATRIX_SYNC_SESSION_FILE directory."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        # No explicit alert session path
        del settings.MATRIX_ALERT_SESSION_FILE
        settings.MATRIX_SYNC_SESSION_FILE = "/data/matrix_session.json"

        service = MatrixAlertService(settings)
        session_path = service._get_session_path()

        # Should derive from same directory as MATRIX_SYNC_SESSION_FILE
        assert session_path == "/data/matrix_alert_session.json"

    def test_uses_default_when_no_paths_configured(self):
        """Test fallback to default path when nothing is configured."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        # No paths configured
        del settings.MATRIX_ALERT_SESSION_FILE
        del settings.MATRIX_SYNC_SESSION_FILE

        service = MatrixAlertService(settings)
        session_path = service._get_session_path()

        # Should use sensible default
        assert session_path == "/data/matrix_alert_session.json"


class TestMatrixAlertServiceConcurrency:
    """Test suite for concurrent initialization safety."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for tests."""
        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        settings.MATRIX_SYNC_SESSION_FILE = "/data/matrix_session.json"
        return settings

    @pytest.mark.asyncio
    async def test_concurrent_get_client_calls_only_init_once(self, mock_settings):
        """Test that concurrent _get_client calls only initialize once."""
        import asyncio

        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        service = MatrixAlertService(mock_settings)
        init_count = 0

        async def mock_connect():
            nonlocal init_count
            init_count += 1
            await asyncio.sleep(0.1)  # Simulate slow connection

        with patch("app.channels.plugins.matrix.services.alert_service.AsyncClient"):
            with patch(
                "app.channels.plugins.matrix.client.connection_manager.ConnectionManager"
            ) as mock_cm:
                with patch(
                    "app.channels.plugins.matrix.client.session_manager.SessionManager"
                ):
                    mock_cm.return_value.connect = mock_connect

                    # Launch multiple concurrent calls
                    tasks = [service._get_client() for _ in range(5)]
                    await asyncio.gather(*tasks)

                    # Should only have initialized once despite 5 concurrent calls
                    assert init_count == 1

    @pytest.mark.asyncio
    async def test_failed_connect_cleans_up_state(self, mock_settings):
        """Test that failed connection attempt cleans up partial state."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        service = MatrixAlertService(mock_settings)

        with patch("app.channels.plugins.matrix.services.alert_service.AsyncClient"):
            with patch(
                "app.channels.plugins.matrix.client.connection_manager.ConnectionManager"
            ) as mock_cm:
                with patch(
                    "app.channels.plugins.matrix.client.session_manager.SessionManager"
                ):
                    mock_cm.return_value.connect = AsyncMock(
                        side_effect=Exception("Connection failed")
                    )

                    # Should raise the exception
                    with pytest.raises(Exception, match="Connection failed"):
                        await service._get_client()

                    # State should be cleaned up
                    assert service._client is None
                    assert service._connection_manager is None
                    assert service._session_manager is None


class TestMatrixAlertServiceConfig:
    """Test suite for Matrix alert service configuration."""

    def test_matrix_alert_room_setting_exists(self):
        """Test that MATRIX_ALERT_ROOM setting exists in config."""
        from app.core.config import Settings

        settings = Settings()
        assert hasattr(settings, "MATRIX_ALERT_ROOM")

    def test_matrix_alert_room_default_empty(self):
        """Test that MATRIX_ALERT_ROOM defaults to empty string."""
        from app.core.config import Settings

        settings = Settings()
        assert settings.MATRIX_ALERT_ROOM == ""

    def test_matrix_alert_room_can_be_set(self):
        """Test that MATRIX_ALERT_ROOM can be set via environment."""
        with patch.dict("os.environ", {"MATRIX_ALERT_ROOM": "!test123:matrix.org"}):
            from app.core.config import Settings

            settings = Settings()
            assert settings.MATRIX_ALERT_ROOM == "!test123:matrix.org"


class TestMatrixAlertServiceInitialization:
    """Test suite for Matrix alert service initialization."""

    def test_service_can_be_imported(self):
        """Test that MatrixAlertService can be imported."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        assert MatrixAlertService is not None

    def test_service_init_with_settings(self):
        """Test service initialization with settings."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"

        service = MatrixAlertService(settings)
        assert service is not None
        assert service.settings == settings

    def test_service_is_configured_returns_false_when_missing_homeserver(self):
        """Test is_configured returns False when homeserver is missing."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = ""
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"

        service = MatrixAlertService(settings)
        assert service.is_configured() is False

    def test_service_is_configured_returns_false_when_missing_room(self):
        """Test is_configured returns False when alert room is missing."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_ALERT_ROOM = ""

        service = MatrixAlertService(settings)
        assert service.is_configured() is False

    def test_service_is_configured_returns_true_when_properly_configured(self):
        """Test is_configured returns True when all required settings present."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"

        service = MatrixAlertService(settings)
        assert service.is_configured() is True


class TestMatrixAlertServiceSendMessage:
    """Test suite for send_alert_message functionality."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for tests."""
        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        settings.MATRIX_ALERT_SESSION_FILE = "/tmp/test_alert_session.json"
        return settings

    @pytest.mark.asyncio
    async def test_send_alert_message_when_not_configured(self, mock_settings):
        """Test that send_alert_message does nothing when not configured."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        mock_settings.MATRIX_ALERT_ROOM = ""  # Not configured
        service = MatrixAlertService(mock_settings)

        # Should not raise, just log warning
        await service.send_alert_message("Test alert")

    @pytest.mark.asyncio
    async def test_send_alert_message_connects_and_sends(self, mock_settings):
        """Test that send_alert_message connects and sends message."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        # Need to mock RoomSendResponse for the isinstance check
        with patch(
            "app.channels.plugins.matrix.services.alert_service.RoomSendResponse"
        ) as mock_response_class:
            service = MatrixAlertService(mock_settings)

            # Mock the Matrix client
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response_class.return_value = mock_response
            # Make isinstance check pass
            mock_client.room_send = AsyncMock(return_value=mock_response)

            with patch.object(service, "_get_client", return_value=mock_client):
                with patch(
                    "app.channels.plugins.matrix.services.alert_service.isinstance",
                    return_value=True,
                ):
                    await service.send_alert_message("🔥 Test alert")

                    # Verify room_send was called with correct arguments
                    mock_client.room_send.assert_called_once()
                    call_kwargs = mock_client.room_send.call_args.kwargs
                    assert call_kwargs["room_id"] == "!alert:matrix.org"
                    assert call_kwargs["message_type"] == "m.room.message"

    @pytest.mark.asyncio
    async def test_send_alert_message_handles_connection_error(self, mock_settings):
        """Test that send_alert_message handles connection errors gracefully."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        service = MatrixAlertService(mock_settings)

        with patch.object(
            service, "_get_client", side_effect=Exception("Connection failed")
        ):
            # Should not raise, just log error
            await service.send_alert_message("Test alert")


class TestAlertmanagerIntegration:
    """Test suite for alertmanager webhook integration."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for tests."""
        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_USER = "@bot:matrix.org"
        settings.MATRIX_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        return settings

    def test_alertmanager_route_uses_matrix_alert_service(self):
        """Test that alertmanager route references matrix_alert_service."""
        from app.routes.alertmanager import receive_alerts

        # The route should exist and be async
        assert receive_alerts is not None
        assert hasattr(receive_alerts, "__wrapped__") or callable(receive_alerts)

    @pytest.mark.asyncio
    async def test_alertmanager_processes_alerts_with_service(self, mock_settings):
        """Test alertmanager endpoint processes alerts using the service."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )
        from app.routes.alertmanager import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router, prefix="/alertmanager")

        # Create and configure the service
        service = MatrixAlertService(mock_settings)
        service.send_alert_message = AsyncMock()
        app.state.matrix_alert_service = service

        client = TestClient(app)
        response = client.post(
            "/alertmanager/alerts",
            json={
                "receiver": "test",
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "TestAlert", "severity": "warning"},
                        "annotations": {"summary": "Test summary"},
                    }
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["alerts_processed"] == 1
        service.send_alert_message.assert_called_once()
