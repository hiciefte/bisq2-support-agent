"""Tests for admin channel autoresponse endpoints."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.channel_autoresponse_policy_service import (
    ChannelAutoResponsePolicyService,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_channel_autoresponse_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "routes"
        / "admin"
        / "channel_autoresponse.py"
    )
    module_name = "test_admin_channel_autoresponse_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_test_app(service: ChannelAutoResponsePolicyService | None) -> FastAPI:
    channel_autoresponse_module = _load_channel_autoresponse_module()

    app = FastAPI()
    app.include_router(channel_autoresponse_module.router)
    if service is not None:
        app.state.channel_autoresponse_policy_service = service
    app.dependency_overrides[channel_autoresponse_module.verify_admin_access] = (
        lambda: None
    )
    return app


def test_list_channel_autoresponse_policies(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.get("/admin/channels/autoresponse")
    assert response.status_code == 200

    payload = response.json()
    assert [entry["channel_id"] for entry in payload] == ["bisq2", "matrix", "web"]
    assert all("enabled" in entry for entry in payload)
    assert all("generation_enabled" in entry for entry in payload)


def test_get_channel_autoresponse_policy(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.get("/admin/channels/autoresponse/bisq2")
    assert response.status_code == 200
    assert response.json()["channel_id"] == "bisq2"
    assert response.json()["enabled"] is False
    assert response.json()["generation_enabled"] is False


def test_update_channel_autoresponse_policy(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.put(
        "/admin/channels/autoresponse/matrix",
        json={"generation_enabled": True},
    )
    assert response.status_code == 200
    assert response.json()["channel_id"] == "matrix"
    assert response.json()["enabled"] is False
    assert response.json()["generation_enabled"] is True

    reloaded = service.get_policy("matrix")
    assert reloaded.generation_enabled is True
    assert reloaded.enabled is False


def test_update_channel_autoresponse_policy_requires_one_field(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.put(
        "/admin/channels/autoresponse/web",
        json={},
    )
    assert response.status_code == 422


def test_rejects_unsupported_channel(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.get("/admin/channels/autoresponse/unknown")
    assert response.status_code == 400


def test_returns_503_when_service_missing() -> None:
    client = TestClient(_build_test_app(service=None))

    response = client.get("/admin/channels/autoresponse")
    assert response.status_code == 503
