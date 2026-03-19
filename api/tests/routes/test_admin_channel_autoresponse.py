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
    assert response.json()["ai_response_mode"] == "autonomous"
    assert response.json()["acknowledgment_mode"] == "message"
    assert response.json()["public_escalation_notice_enabled"] is False
    assert response.json()["escalation_notification_channel"] == "staff_room"
    assert response.json()["escalation_user_notice_mode"] == "message"
    assert response.json()["group_clarification_immediate"] is False


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
    assert response.json()["ai_response_mode"] == "autonomous"

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


def test_update_channel_autoresponse_policy_hitl_fields(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.put(
        "/admin/channels/autoresponse/matrix",
        json={
            "ai_response_mode": "hitl",
            "hitl_approval_timeout_seconds": 900,
            "staff_assist_surface": "admin_ui",
            "public_escalation_notice_enabled": False,
            "acknowledgment_mode": "message",
            "escalation_user_notice_mode": "none",
            "escalation_notification_channel": "staff_room",
            "timer_jitter_max_seconds": 20,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_response_mode"] == "hitl"
    assert payload["hitl_approval_timeout_seconds"] == 900
    assert payload["staff_assist_surface"] == "admin_ui"
    assert payload["public_escalation_notice_enabled"] is False
    assert payload["acknowledgment_mode"] == "message"
    assert payload["escalation_user_notice_mode"] == "none"
    assert payload["escalation_notification_channel"] == "staff_room"
    assert payload["timer_jitter_max_seconds"] == 20


def test_rejects_unsupported_channel(tmp_path) -> None:
    service = ChannelAutoResponsePolicyService(db_path=str(tmp_path / "feedback.db"))
    client = TestClient(_build_test_app(service))

    response = client.get("/admin/channels/autoresponse/unknown")
    assert response.status_code == 400


def test_returns_503_when_service_missing() -> None:
    client = TestClient(_build_test_app(service=None))

    response = client.get("/admin/channels/autoresponse")
    assert response.status_code == 503
