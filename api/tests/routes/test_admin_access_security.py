"""Regression tests for hardened admin access channels."""

from app.core import security
from fastapi.testclient import TestClient


def test_admin_query_api_key_is_rejected(
    test_client: TestClient, test_settings
) -> None:
    response = test_client.get(f"/admin/feedback?api_key={test_settings.ADMIN_API_KEY}")

    assert response.status_code == 401


def test_admin_authorization_bearer_is_rejected(
    test_client: TestClient, test_settings
) -> None:
    response = test_client.get(
        "/admin/feedback",
        headers={"Authorization": f"Bearer {test_settings.ADMIN_API_KEY}"},
    )

    assert response.status_code == 401


def test_admin_x_api_key_still_allows_admin_feedback(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    from app.routes.admin import feedback as admin_feedback

    admin_feedback.reset_feedback_analytics_cache()
    monkeypatch.setattr(admin_feedback.feedback_service, "load_feedback", lambda: [])

    response = test_client.get(
        "/admin/feedback",
        headers={"X-API-KEY": test_settings.ADMIN_API_KEY},
    )

    assert response.status_code == 200


def test_grafana_key_allows_read_only_feedback_analytics(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    from app.routes.admin import feedback as admin_feedback

    admin_feedback.reset_feedback_analytics_cache()
    monkeypatch.setattr(admin_feedback.feedback_service, "load_feedback", lambda: [])

    response = test_client.get(
        "/admin/feedback",
        headers={"X-API-KEY": test_settings.GRAFANA_DATASOURCE_API_KEY},
    )

    assert response.status_code == 200


def test_grafana_key_cannot_delete_feedback(
    test_client: TestClient, test_settings
) -> None:
    response = test_client.delete(
        "/admin/feedback/web_abc123",
        headers={"X-API-KEY": test_settings.GRAFANA_DATASOURCE_API_KEY},
    )

    assert response.status_code == 403


def test_legacy_equal_grafana_and_admin_key_keeps_full_admin_access(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    monkeypatch.setattr(
        test_settings,
        "GRAFANA_DATASOURCE_API_KEY",
        test_settings.ADMIN_API_KEY,
    )

    response = test_client.delete(
        "/admin/feedback/nonexistent-feedback-id",
        headers={"X-API-KEY": test_settings.ADMIN_API_KEY},
    )

    assert response.status_code == 404


def test_grafana_key_works_when_admin_key_is_unset(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    from app.routes.admin import feedback as admin_feedback

    admin_feedback.reset_feedback_analytics_cache()
    monkeypatch.setattr(admin_feedback.feedback_service, "load_feedback", lambda: [])
    monkeypatch.setattr(test_settings, "ADMIN_API_KEY", "")

    response = test_client.get(
        "/admin/feedback",
        headers={"X-API-KEY": test_settings.GRAFANA_DATASOURCE_API_KEY},
    )

    assert response.status_code == 200


def test_grafana_key_remains_read_only_when_admin_key_is_unset(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    monkeypatch.setattr(test_settings, "ADMIN_API_KEY", "")

    response = test_client.delete(
        "/admin/feedback/web_abc123",
        headers={"X-API-KEY": test_settings.GRAFANA_DATASOURCE_API_KEY},
    )

    assert response.status_code == 403


def test_cookie_cannot_authenticate_when_admin_key_is_unset(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    monkeypatch.setattr(test_settings, "ADMIN_API_KEY", "")
    monkeypatch.setattr(security, "verify_admin_session_token", lambda _token: True)

    test_client.cookies.set(
        "admin_authenticated",
        "forged-empty-key-token",
    )
    response = test_client.get("/admin/feedback")

    assert response.status_code == 401


def test_header_auth_fails_closed_when_no_admin_or_grafana_key_is_configured(
    test_client: TestClient, test_settings, monkeypatch
) -> None:
    monkeypatch.setattr(test_settings, "ADMIN_API_KEY", "")
    monkeypatch.setattr(test_settings, "GRAFANA_DATASOURCE_API_KEY", "")

    response = test_client.get(
        "/admin/feedback",
        headers={"X-API-KEY": "unconfigured-key"},
    )

    assert response.status_code == 403
