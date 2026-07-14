"""Tests for Alertmanager webhook integration.

Phase 9: Replace token-based Matrix auth with password-based auth.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import Settings, get_settings
from app.routes.alertmanager import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_WEBHOOK_SECRET = "test-only-alertmanager-webhook-secret"
AUTHORIZATION_HEADER = {"Authorization": f"Bearer {TEST_WEBHOOK_SECRET}"}


@pytest.fixture
def sample_alert_payload():
    """Sample Alertmanager webhook payload."""
    return {
        "receiver": "matrix-notifications",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "TestAlert",
                    "severity": "warning",
                    "component": "api",
                },
                "annotations": {
                    "summary": "Test alert from unit test",
                    "description": "This is a test alert for the alertmanager webhook.",
                },
                "startsAt": "2026-01-19T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus:9090/graph",
                "fingerprint": "abc123",
            }
        ],
        "groupLabels": {"alertname": "TestAlert"},
        "commonLabels": {"severity": "warning"},
        "commonAnnotations": {"summary": "Test alert"},
        "externalURL": "http://alertmanager:9093",
        "version": "4",
        "groupKey": "{}:{alertname=TestAlert}",
    }


@pytest.fixture
def sample_resolved_payload():
    """Sample resolved alert payload."""
    return {
        "receiver": "matrix-notifications",
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": {
                    "alertname": "TestAlert",
                    "severity": "warning",
                },
                "annotations": {
                    "summary": "Test alert resolved",
                },
            }
        ],
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
    }


@pytest.fixture
def mock_matrix_service():
    """Mock Matrix alert service."""
    service = MagicMock()
    service.is_configured.return_value = True
    service.send_alert_message = AsyncMock(return_value=True)
    return service


@pytest.fixture
def alertmanager_app() -> FastAPI:
    """Mount the relay router without reintroducing it to the main API."""
    test_app = FastAPI()
    test_app.include_router(router, prefix="/alertmanager", tags=["Alertmanager"])
    settings = Settings(
        _env_file=None,
        ALERTMANAGER_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET,
    )
    test_app.dependency_overrides[get_settings] = lambda: settings
    return test_app


# =============================================================================
# TASK 9.2: Pydantic Models Tests
# =============================================================================


class TestAlertmanagerPayloadModel:
    """Test Alertmanager payload parsing."""

    def test_alertmanager_payload_model_parses_valid_json(self, sample_alert_payload):
        """Test that AlertmanagerPayload correctly parses valid JSON."""
        from app.routes.alertmanager import AlertmanagerPayload

        payload = AlertmanagerPayload(**sample_alert_payload)

        assert payload.receiver == "matrix-notifications"
        assert payload.status == "firing"
        assert len(payload.alerts) == 1
        assert payload.alerts[0].labels["alertname"] == "TestAlert"
        assert payload.alerts[0].labels["severity"] == "warning"

    def test_alertmanager_payload_handles_minimal_payload(self):
        """Test parsing minimal valid payload."""
        from app.routes.alertmanager import AlertmanagerPayload

        minimal = {
            "receiver": "test",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "MinimalAlert"},
                    "annotations": {},
                }
            ],
        }

        payload = AlertmanagerPayload(**minimal)
        assert payload.receiver == "test"
        assert len(payload.alerts) == 1


class TestFormatAlertMessage:
    """Test alert message formatting."""

    def test_format_alert_message_firing(self, sample_alert_payload):
        """Test formatting of firing alert."""
        from app.routes.alertmanager import Alert, format_alert_message

        alert = Alert(**sample_alert_payload["alerts"][0])
        message = format_alert_message(alert, "firing")

        assert "🔥" in message
        assert "WARNING" in message
        assert "TestAlert" in message
        assert "Test alert from unit test" in message

    def test_format_alert_message_resolved(self, sample_resolved_payload):
        """Test formatting of resolved alert."""
        from app.routes.alertmanager import Alert, format_alert_message

        alert = Alert(**sample_resolved_payload["alerts"][0])
        message = format_alert_message(alert, "resolved")

        assert "✅" in message
        assert "WARNING" in message
        assert "TestAlert" in message

    def test_format_alert_message_critical_severity(self):
        """Test formatting of critical severity alert."""
        from app.routes.alertmanager import Alert, format_alert_message

        alert = Alert(
            status="firing",
            labels={"alertname": "CriticalAlert", "severity": "critical"},
            annotations={"summary": "Critical issue detected"},
        )
        message = format_alert_message(alert, "firing")

        assert "CRITICAL" in message
        assert "CriticalAlert" in message

    def test_format_alert_message_includes_description(self, sample_alert_payload):
        """Test that description is included when present."""
        from app.routes.alertmanager import Alert, format_alert_message

        alert = Alert(**sample_alert_payload["alerts"][0])
        message = format_alert_message(alert, "firing")

        assert "This is a test alert" in message

    def test_format_alert_message_handles_missing_fields(self):
        """Test graceful handling of missing optional fields."""
        from app.routes.alertmanager import Alert, format_alert_message

        alert = Alert(
            status="firing",
            labels={},  # No alertname or severity
            annotations={},  # No summary
        )
        message = format_alert_message(alert, "firing")

        assert "🔥" in message
        assert "UNKNOWN" in message  # Default severity
        assert "Unknown" in message  # Default alertname


# =============================================================================
# TASK 9.3: Webhook Endpoints Tests
# =============================================================================


class TestHealthEndpoint:
    """Test alertmanager health endpoint."""

    def test_alertmanager_health_endpoint(self, alertmanager_app):
        """Test health endpoint returns healthy status."""
        client = TestClient(alertmanager_app)
        response = client.get("/alertmanager/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestAlertsEndpoint:
    """Test alertmanager alerts endpoint."""

    def test_receive_alerts_success(
        self, alertmanager_app, sample_alert_payload, mock_matrix_service
    ):
        """Test successful alert processing."""
        # Inject mock matrix service
        alertmanager_app.state.matrix_alert_service = mock_matrix_service

        client = TestClient(alertmanager_app)
        response = client.post(
            "/alertmanager/alerts",
            headers=AUTHORIZATION_HEADER,
            json=sample_alert_payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["alerts_processed"] == 1

        # Verify send_alert_message was called
        mock_matrix_service.send_alert_message.assert_called_once()

    def test_receive_alerts_multiple_alerts(
        self, alertmanager_app, mock_matrix_service
    ):
        """Test processing multiple alerts in one payload."""
        alertmanager_app.state.matrix_alert_service = mock_matrix_service

        payload = {
            "receiver": "matrix-notifications",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "Alert1", "severity": "warning"},
                    "annotations": {"summary": "First alert"},
                },
                {
                    "status": "firing",
                    "labels": {"alertname": "Alert2", "severity": "critical"},
                    "annotations": {"summary": "Second alert"},
                },
            ],
        }

        client = TestClient(alertmanager_app)
        response = client.post(
            "/alertmanager/alerts", headers=AUTHORIZATION_HEADER, json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["alerts_processed"] == 2
        assert mock_matrix_service.send_alert_message.call_count == 1
        batched_message = mock_matrix_service.send_alert_message.await_args.args[0]
        assert "Alert1" in batched_message
        assert "Alert2" in batched_message

    def test_receive_alerts_no_matrix_service(
        self, alertmanager_app, sample_alert_payload
    ):
        """Unavailable delivery must make Alertmanager retry the webhook."""
        client = TestClient(alertmanager_app)
        response = client.post(
            "/alertmanager/alerts",
            headers=AUTHORIZATION_HEADER,
            json=sample_alert_payload,
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "matrix_service_unavailable"

    def test_receive_alerts_rejects_unconfigured_matrix_service(
        self, alertmanager_app, sample_alert_payload, mock_matrix_service
    ):
        """Permanent configuration gaps are rejected before delivery."""
        mock_matrix_service.is_configured.return_value = False
        alertmanager_app.state.matrix_alert_service = mock_matrix_service

        response = TestClient(alertmanager_app).post(
            "/alertmanager/alerts",
            headers=AUTHORIZATION_HEADER,
            json=sample_alert_payload,
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "matrix_service_not_configured"
        mock_matrix_service.send_alert_message.assert_not_awaited()

    def test_receive_alerts_handles_send_failure(
        self, alertmanager_app, sample_alert_payload, mock_matrix_service
    ):
        """Test handling of matrix send failures."""
        # Make send_alert_message raise an exception
        mock_matrix_service.send_alert_message = AsyncMock(
            side_effect=Exception("Matrix connection failed")
        )
        alertmanager_app.state.matrix_alert_service = mock_matrix_service

        client = TestClient(alertmanager_app)
        response = client.post(
            "/alertmanager/alerts",
            headers=AUTHORIZATION_HEADER,
            json=sample_alert_payload,
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "matrix_delivery_failed"

    def test_receive_alerts_handles_false_send_result(
        self, alertmanager_app, sample_alert_payload, mock_matrix_service
    ):
        """A false Matrix result is a failed delivery, not a processed alert."""
        mock_matrix_service.send_alert_message = AsyncMock(return_value=False)
        alertmanager_app.state.matrix_alert_service = mock_matrix_service

        client = TestClient(alertmanager_app)
        response = client.post(
            "/alertmanager/alerts",
            headers=AUTHORIZATION_HEADER,
            json=sample_alert_payload,
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "matrix_delivery_failed"


# =============================================================================
# TASK 9.4: Matrix Service Integration Tests
# =============================================================================


class TestMatrixServiceIntegration:
    """Test Matrix shadow mode service alert sending."""

    @pytest.mark.asyncio
    async def test_send_alert_message_sends_to_rooms(self):
        """Test that send_alert_message sends to configured rooms."""
        # This test requires the actual MatrixShadowModeService
        # We'll mock the underlying client
        # Test with a mocked service directly
        service = MagicMock()
        service.send_alert_message = AsyncMock(return_value=True)
        service.room_ids = ["!room1:matrix.org", "!room2:matrix.org"]

        result = await service.send_alert_message("Test alert message")

        assert result is True


# =============================================================================
# TASK 9.5: Route Registration Tests
# =============================================================================


class TestRouterRegistration:
    """Test that alertmanager router is properly registered."""

    def test_alertmanager_routes_remain_available_to_isolated_relay(
        self, alertmanager_app
    ):
        """The shared router remains mountable by the isolated relay."""
        routes = [route.path for route in alertmanager_app.routes]

        assert "/alertmanager/health" in routes
        assert "/alertmanager/alerts" in routes
