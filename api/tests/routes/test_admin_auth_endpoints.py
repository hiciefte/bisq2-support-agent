"""Tests for admin auth endpoints."""

from app.core.security import generate_admin_session_token
from fastapi.testclient import TestClient


def test_admin_auth_status_returns_false_without_session_cookie(
    test_client: TestClient,
) -> None:
    response = test_client.get("/admin/auth/status")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}


def test_admin_auth_status_returns_true_for_valid_session_cookie(
    test_client: TestClient,
) -> None:
    test_client.cookies.set("admin_authenticated", generate_admin_session_token())

    status_response = test_client.get("/admin/auth/status")

    assert status_response.status_code == 200
    assert status_response.json() == {"authenticated": True}
    assert "set-cookie" in status_response.headers


def test_admin_auth_status_returns_false_for_invalid_cookie(
    test_client: TestClient,
) -> None:
    test_client.cookies.set("admin_authenticated", "invalid-token")

    response = test_client.get("/admin/auth/status")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
