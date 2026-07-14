"""Tests for the isolated Matrix Alertmanager relay app."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.alert_relay import app
from app.core.config import Settings, get_settings
from fastapi.testclient import TestClient

TEST_WEBHOOK_SECRET = "test-only-alertmanager-webhook-secret"
AUTHORIZATION_HEADER = {"Authorization": f"Bearer {TEST_WEBHOOK_SECRET}"}

PAYLOAD = {
    "receiver": "matrix-critical",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "ApiDown", "severity": "critical"},
            "annotations": {"summary": "API is unavailable"},
        }
    ],
}


@pytest.fixture(autouse=True)
def configured_webhook_secret():
    """Give relay tests an explicit test-only webhook secret."""
    settings = Settings(
        _env_file=None,
        ALERTMANAGER_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield
    app.dependency_overrides.clear()


def test_relay_accepts_webhook_when_matrix_send_succeeds() -> None:
    service = MagicMock()
    service.is_configured.return_value = True
    service.send_alert_message = AsyncMock(return_value=True)
    app.state.matrix_alert_service = service

    response = TestClient(app).post(
        "/alerts", headers=AUTHORIZATION_HEADER, json=PAYLOAD
    )

    assert response.status_code == 200
    assert response.json()["alerts_processed"] == 1
    service.send_alert_message.assert_awaited_once()


def test_relay_returns_retryable_failure_when_matrix_send_fails() -> None:
    service = MagicMock()
    service.is_configured.return_value = True
    service.send_alert_message = AsyncMock(return_value=False)
    app.state.matrix_alert_service = service

    response = TestClient(app).post(
        "/alerts", headers=AUTHORIZATION_HEADER, json=PAYLOAD
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "matrix_delivery_failed"


def test_relay_batches_alert_group_to_avoid_partial_retry_duplicates() -> None:
    service = MagicMock()
    service.is_configured.return_value = True
    service.send_alert_message = AsyncMock(return_value=True)
    app.state.matrix_alert_service = service
    payload = {
        **PAYLOAD,
        "alerts": [
            *PAYLOAD["alerts"],
            {
                "status": "firing",
                "labels": {"alertname": "WebDown", "severity": "critical"},
                "annotations": {"summary": "Web is unavailable"},
            },
        ],
    }

    response = TestClient(app).post(
        "/alerts", headers=AUTHORIZATION_HEADER, json=payload
    )

    assert response.status_code == 200
    assert response.json()["alerts_processed"] == 2
    service.send_alert_message.assert_awaited_once()
    batched_message = service.send_alert_message.await_args.args[0]
    assert "ApiDown" in batched_message
    assert "WebDown" in batched_message


def test_relay_readiness_requires_matrix_configuration() -> None:
    service = MagicMock()
    service.is_configured.return_value = False
    app.state.matrix_alert_service = service

    response = TestClient(app).get("/ready")

    assert response.status_code == 503


def test_relay_readiness_requires_webhook_secret() -> None:
    service = MagicMock()
    service.is_configured.return_value = True
    app.state.matrix_alert_service = service
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        ALERTMANAGER_WEBHOOK_SECRET="",
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "alertmanager_webhook_not_configured"


def test_relay_readiness_uses_live_matrix_configuration() -> None:
    service = MagicMock()
    service.is_configured.return_value = True
    app.state.matrix_alert_service = service

    ready = TestClient(app).get("/ready")
    service.is_configured.return_value = False
    unavailable = TestClient(app).get("/ready")

    assert ready.status_code == 200
    assert unavailable.status_code == 503


def test_relay_rejects_unconfigured_delivery_before_send() -> None:
    service = MagicMock()
    service.is_configured.return_value = False
    service.send_alert_message = AsyncMock(return_value=True)
    app.state.matrix_alert_service = service

    response = TestClient(app).post(
        "/alerts", headers=AUTHORIZATION_HEADER, json=PAYLOAD
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "matrix_service_not_configured"
    service.send_alert_message.assert_not_awaited()
