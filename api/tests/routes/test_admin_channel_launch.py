"""Tests for protected channel launch-control endpoints."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.channel_launch_control_service import ChannelLaunchControlService
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_route_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "routes"
        / "admin"
        / "channel_launch.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_admin_channel_launch_module", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_app(service: ChannelLaunchControlService | None) -> FastAPI:
    route_module = _load_route_module()
    app = FastAPI()
    app.include_router(route_module.router)
    if service is not None:
        app.state.channel_launch_control_service = service
    app.dependency_overrides[route_module.verify_admin_access] = lambda: None
    return app


def test_admin_can_stop_global_delivery_immediately(tmp_path) -> None:
    service = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    client = TestClient(_build_app(service))

    response = client.put(
        "/admin/channels/launch-control/global",
        json={"autonomous_delivery_enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["autonomous_delivery_enabled"] is False
    assert service.get_global_control().autonomous_delivery_enabled is False


def test_admin_cannot_override_environment_stop(tmp_path) -> None:
    service = ChannelLaunchControlService(str(tmp_path / "feedback.db"))
    client = TestClient(_build_app(service))

    response = client.put(
        "/admin/channels/launch-control/global",
        json={"autonomous_delivery_enabled": True},
    )

    assert response.status_code == 409
    assert service.get_global_control().autonomous_delivery_enabled is False


def test_admin_lists_safe_channel_defaults(tmp_path) -> None:
    service = ChannelLaunchControlService(str(tmp_path / "feedback.db"))
    client = TestClient(_build_app(service))

    response = client.get("/admin/channels/launch-control")

    assert response.status_code == 200
    policies = {item["channel_id"]: item for item in response.json()}
    assert policies["matrix"]["shadow_mode"] is True
    assert policies["bisq2"]["shadow_mode"] is True
    assert policies["matrix"]["canary_hourly_limit"] == 0
    assert policies["matrix"]["canary_daily_limit"] == 0
    assert policies["matrix"]["canary_reservation_count"] == 0


def test_admin_updates_bounded_canary_policy(tmp_path) -> None:
    service = ChannelLaunchControlService(str(tmp_path / "feedback.db"))
    client = TestClient(_build_app(service))

    response = client.put(
        "/admin/channels/launch-control/matrix",
        json={
            "shadow_mode": False,
            "canary_enabled": True,
            "canary_hourly_limit": 2,
            "canary_daily_limit": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["shadow_mode"] is False
    assert response.json()["canary_enabled"] is True
    assert response.json()["canary_hourly_limit"] == 2
    assert response.json()["canary_daily_limit"] == 5


def test_admin_reports_privacy_safe_canary_reservation_count(tmp_path) -> None:
    service = ChannelLaunchControlService(
        str(tmp_path / "feedback.db"), environment_enabled=True
    )
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "matrix",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=1,
        canary_daily_limit=1,
    )
    assert service.authorize_autonomous_delivery("matrix", "event-1").allowed
    client = TestClient(_build_app(service))

    response = client.get("/admin/channels/launch-control/matrix")

    assert response.status_code == 200
    assert response.json()["canary_reservation_count"] == 1
    assert "message_key" not in response.text
    assert "event-1" not in response.text


def test_admin_rejects_empty_or_unbounded_policy_updates(tmp_path) -> None:
    service = ChannelLaunchControlService(str(tmp_path / "feedback.db"))
    client = TestClient(_build_app(service))

    empty = client.put("/admin/channels/launch-control/matrix", json={})
    invalid = client.put(
        "/admin/channels/launch-control/matrix",
        json={"canary_hourly_limit": 3, "canary_daily_limit": 2},
    )

    assert empty.status_code == 422
    assert invalid.status_code == 400


def test_admin_launch_routes_return_503_without_service() -> None:
    client = TestClient(_build_app(None))

    response = client.get("/admin/channels/launch-control/global")

    assert response.status_code == 503
