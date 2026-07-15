"""Tests for Matrix alert service.

TDD tests for the Matrix alerting functionality that sends
Prometheus Alertmanager alerts to a dedicated Matrix room.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
        assert "MATRIX_ALERT_USER" in hints
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
        assert hasattr(settings, "MATRIX_ALERT_USER")
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
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        settings.MATRIX_ALERT_SESSION_FILE = "/custom/path/alert_session.json"
        settings.MATRIX_SYNC_SESSION_FILE = "/data/matrix_session.json"
        del settings.MATRIX_ALERT_SESSION_FILE_PATH

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
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        # No explicit alert session path
        del settings.MATRIX_ALERT_SESSION_FILE
        del settings.MATRIX_ALERT_SESSION_FILE_PATH
        settings.MATRIX_SYNC_SESSION_FILE = "/data/matrix_session.json"

        service = MatrixAlertService(settings)
        session_path = service._get_session_path()

        # Should derive from same directory as MATRIX_SYNC_SESSION_FILE
        assert session_path == "/data/matrix_alert_session.json"

    @pytest.mark.asyncio
    async def test_expired_session_rotation_closes_client_before_deletion(
        self, tmp_path
    ):
        from app.channels.plugins.matrix.services.alert_service import (
            ALERT_RELAY_RETENTION_STORE,
            MatrixAlertService,
        )
        from prometheus_client import REGISTRY

        session_file = tmp_path / "alert-session.json"
        session_file.write_text(
            json.dumps(
                {
                    "access_token": "fixture",
                    "device_id": "fixture",
                    "user_id": "fixture",
                    "created_at": (datetime.now(UTC) - timedelta(days=31)).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        settings = MagicMock()
        settings.MATRIX_ALERT_SESSION_FILE_PATH = str(session_file)
        settings.DATA_RETENTION_DAYS = 30
        service = MatrixAlertService(settings)
        service._close_unlocked = AsyncMock()

        assert await service.rotate_expired_session(dry_run=True) == 1
        assert session_file.exists()
        service._close_unlocked.assert_not_awaited()

        assert await service.rotate_expired_session() == 1
        service._close_unlocked.assert_awaited_once_with(strict=True)
        assert not session_file.exists()
        labels = {"store": ALERT_RELAY_RETENTION_STORE}
        assert REGISTRY.get_sample_value("privacy_retention_deleted_last", labels) == 1
        assert (
            REGISTRY.get_sample_value("privacy_retention_oldest_age_seconds", labels)
            == 0
        )
        assert (
            REGISTRY.get_sample_value("privacy_retention_window_seconds", labels)
            == 30 * 86400
        )

    @pytest.mark.asyncio
    async def test_expired_session_rotation_keeps_files_when_close_fails(
        self, tmp_path
    ):
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        session_file = tmp_path / "alert-session.json"
        session_file.write_text(
            json.dumps(
                {
                    "access_token": "fixture",
                    "device_id": "fixture",
                    "user_id": "fixture",
                    "created_at": (datetime.now(UTC) - timedelta(days=31)).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        settings = MagicMock()
        settings.MATRIX_ALERT_SESSION_FILE_PATH = str(session_file)
        settings.DATA_RETENTION_DAYS = 30
        service = MatrixAlertService(settings)
        service._connection_manager = SimpleNamespace(
            disconnect=AsyncMock(side_effect=RuntimeError("close failed"))
        )

        with pytest.raises(RuntimeError, match="did not close cleanly"):
            await service.rotate_expired_session()

        assert session_file.exists()
        assert service._connection_manager is not None

    @pytest.mark.asyncio
    async def test_retention_metrics_report_age_when_session_is_retained(
        self, tmp_path
    ):
        from app.channels.plugins.matrix.services.alert_service import (
            ALERT_RELAY_RETENTION_STORE,
            MatrixAlertService,
        )
        from prometheus_client import REGISTRY

        session_file = tmp_path / "alert-session.json"
        session_file.write_text(
            json.dumps(
                {
                    "access_token": "fixture",
                    "device_id": "fixture",
                    "user_id": "fixture",
                    "created_at": (datetime.now(UTC) - timedelta(days=29)).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        settings = MagicMock()
        settings.MATRIX_ALERT_SESSION_FILE_PATH = str(session_file)
        settings.DATA_RETENTION_DAYS = 30
        service = MatrixAlertService(settings)

        assert await service.rotate_expired_session() == 0
        assert session_file.exists()
        labels = {"store": ALERT_RELAY_RETENTION_STORE}
        assert REGISTRY.get_sample_value("privacy_retention_deleted_last", labels) == 0
        oldest_age = REGISTRY.get_sample_value(
            "privacy_retention_oldest_age_seconds", labels
        )
        assert oldest_age is not None
        assert 28 * 86400 < oldest_age < 30 * 86400
        assert (
            REGISTRY.get_sample_value("privacy_retention_window_seconds", labels)
            == 30 * 86400
        )

    def test_uses_default_when_no_paths_configured(self):
        """Test fallback to default path when nothing is configured."""
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        # No paths configured
        del settings.MATRIX_ALERT_SESSION_FILE
        del settings.MATRIX_SYNC_SESSION_FILE

        service = MatrixAlertService(settings)
        session_path = service._get_session_path()

        # Should use sensible default
        assert session_path == "/data/matrix_alert_session.json"


class TestMatrixAlertRelayRetentionObservability:
    @pytest.mark.asyncio
    async def test_retention_loop_counts_failures(self):
        import asyncio

        from app.alert_relay import _session_retention_loop

        stop_event = asyncio.Event()
        service = MagicMock()

        async def fail_rotation() -> int:
            stop_event.set()
            raise RuntimeError("fixture failure")

        service.rotate_expired_session = AsyncMock(side_effect=fail_rotation)

        with patch(
            "app.alert_relay.record_privacy_retention_failure"
        ) as record_failure:
            await _session_retention_loop(service, stop_event)

        record_failure.assert_called_once_with(
            failed_store_groups=("matrix_alert_relay_session",)
        )

    @pytest.mark.asyncio
    async def test_retention_stop_is_bounded_when_rotation_ignores_cancellation(
        self, monkeypatch
    ):
        import asyncio

        from app import alert_relay

        started = asyncio.Event()
        release = asyncio.Event()
        service = MagicMock()

        async def stubborn_rotation() -> int:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
            return 0

        service.rotate_expired_session = AsyncMock(side_effect=stubborn_rotation)
        stop_event = asyncio.Event()
        monkeypatch.setattr(
            alert_relay,
            "SESSION_ROTATION_CANCEL_TIMEOUT_SECONDS",
            0.01,
        )
        task = asyncio.create_task(
            alert_relay._rotate_session_or_stop(service, stop_event)
        )
        await started.wait()

        stop_event.set()
        assert await asyncio.wait_for(task, timeout=0.2) is None

        release.set()
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_relay_close_is_bounded_when_client_ignores_cancellation(
        self, monkeypatch
    ):
        import asyncio

        from app import alert_relay

        started = asyncio.Event()
        release = asyncio.Event()
        service = MagicMock()

        async def stubborn_close() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()

        service.close = AsyncMock(side_effect=stubborn_close)
        monkeypatch.setattr(alert_relay, "SESSION_CLOSE_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(
            alert_relay,
            "SESSION_ROTATION_CANCEL_TIMEOUT_SECONDS",
            0.01,
        )

        task = asyncio.create_task(alert_relay._close_service_bounded(service))
        await started.wait()
        await asyncio.wait_for(task, timeout=0.2)

        release.set()
        await asyncio.sleep(0)

    def test_relay_exposes_prometheus_metrics(self):
        from app.alert_relay import app
        from fastapi.testclient import TestClient

        response = TestClient(app).get("/metrics")

        assert response.status_code == 200
        assert "privacy_retention_last_success_timestamp_seconds" in response.text


class TestMatrixAlertServiceConcurrency:
    """Test suite for concurrent initialization safety."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings for tests."""
        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        settings.MATRIX_SYNC_SESSION_FILE = "/data/matrix_session.json"
        return settings

    @pytest.mark.asyncio
    async def test_close_waits_for_in_flight_send(self, mock_settings, monkeypatch):
        import asyncio

        from app.channels.plugins.matrix.services import alert_service

        class FakeRoomSendResponse:
            pass

        started = asyncio.Event()
        release = asyncio.Event()

        async def room_send(**_kwargs):
            started.set()
            await release.wait()
            return FakeRoomSendResponse()

        monkeypatch.setattr(alert_service, "RoomSendResponse", FakeRoomSendResponse)
        service = alert_service.MatrixAlertService(mock_settings)
        service._client = SimpleNamespace(room_send=room_send)
        service._connection_manager = SimpleNamespace(disconnect=AsyncMock())

        send_task = asyncio.create_task(service.send_alert_message("fixture"))
        await started.wait()
        close_task = asyncio.create_task(service.close())
        await asyncio.sleep(0)

        service._connection_manager.disconnect.assert_not_awaited()

        release.set()
        assert await send_task is True
        await close_task
        assert service._client is None

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
        with patch.dict(
            "os.environ",
            {
                "MATRIX_HOMESERVER_URL": "https://matrix.org",
                "MATRIX_ALERT_USER": "@alerts:matrix.org",
                "MATRIX_ALERT_PASSWORD": "secret",
                "MATRIX_ALERT_ROOM": "!test123:matrix.org",
            },
        ):
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
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
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
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
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
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
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
                    content = call_kwargs["content"]
                    assert content["msgtype"] == "m.text"
                    assert content["format"] == "org.matrix.custom.html"
                    assert "formatted_body" in content

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
        settings.MATRIX_ALERT_USER = "@bot:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "password"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"
        settings.ALERTMANAGER_WEBHOOK_SECRET = "test-only-alertmanager-webhook-secret"
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
        from app.core.config import get_settings
        from app.routes.alertmanager import router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(router, prefix="/alertmanager")
        app.dependency_overrides[get_settings] = lambda: mock_settings

        # Create and configure the service
        service = MatrixAlertService(mock_settings)
        service.send_alert_message = AsyncMock()
        app.state.matrix_alert_service = service

        client = TestClient(app)
        response = client.post(
            "/alertmanager/alerts",
            headers={"Authorization": "Bearer test-only-alertmanager-webhook-secret"},
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


class TestAlertCredentialResolution:
    """Tests for alert credential resolution without shared fallback."""

    def test_alert_helpers_prefer_lane_specific_values(self):
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_ALERT_USER_RESOLVED = "@alert:matrix.org"
        settings.MATRIX_ALERT_PASSWORD_RESOLVED = "alert-secret"
        settings.MATRIX_ALERT_USER = "@ignored:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "ignored-secret"
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"

        service = MatrixAlertService(settings)
        assert service._get_alert_user() == "@alert:matrix.org"
        assert service._get_alert_password() == "alert-secret"

    def test_alert_helpers_use_only_alert_values(self):
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        settings = MagicMock()
        settings.MATRIX_ALERT_USER_RESOLVED = ""
        settings.MATRIX_ALERT_PASSWORD_RESOLVED = ""
        settings.MATRIX_ALERT_USER = "@alert:matrix.org"
        settings.MATRIX_ALERT_PASSWORD = "alert-secret"
        settings.MATRIX_HOMESERVER_URL = "https://matrix.org"
        settings.MATRIX_ALERT_ROOM = "!alert:matrix.org"

        service = MatrixAlertService(settings)
        assert service._get_alert_user() == "@alert:matrix.org"
        assert service._get_alert_password() == "alert-secret"
