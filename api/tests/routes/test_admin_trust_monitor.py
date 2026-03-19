from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.channels.chatops import ChatOpsAuditStore
from app.channels.staff import StaffResolver
from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.models import TrustEventType
from app.channels.trust_monitor.publisher import InMemoryTrustAlertPublisher
from app.channels.trust_monitor.service import TrustMonitorService
from app.services.trust_monitor_policy_service import TrustMonitorPolicyService
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "routes"
        / "admin"
        / "trust_monitor.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_admin_trust_monitor_module", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        TRUST_MONITOR_ENABLED=True,
        TRUST_MONITOR_NAME_COLLISION_ENABLED=True,
        TRUST_MONITOR_SILENT_OBSERVER_ENABLED=True,
        TRUST_MONITOR_ALERT_SURFACE="admin_ui",
        TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=["!support:matrix.org"],
        TRUST_MONITOR_MATRIX_STAFF_ROOM="!staff:matrix.org",
        TRUST_MONITOR_SILENT_OBSERVER_WINDOW_DAYS=14,
        TRUST_MONITOR_EARLY_READ_WINDOW_SECONDS=30,
        TRUST_MONITOR_MINIMUM_OBSERVATIONS=3,
        TRUST_MONITOR_MINIMUM_EARLY_READ_HITS=2,
        TRUST_MONITOR_READ_TO_REPLY_RATIO_THRESHOLD=3.0,
        TRUST_MONITOR_EVIDENCE_TTL_DAYS=7,
        TRUST_MONITOR_AGGREGATE_TTL_DAYS=30,
        TRUST_MONITOR_FINDING_TTL_DAYS=30,
        TRUST_MONITOR_ACTOR_KEY_SECRET="secret-key",
    )


def _build_app(tmp_path) -> tuple[TestClient, TrustMonitorService]:
    module = _load_module()
    settings = _settings()
    policy_service = TrustMonitorPolicyService(
        db_path=str(tmp_path / "feedback.db"),
        settings=settings,
    )
    service = TrustMonitorService(
        db_path=str(tmp_path / "feedback.db"),
        settings=settings,
        policy_service=policy_service,
        publisher=InMemoryTrustAlertPublisher(),
        staff_resolver=StaffResolver(
            trusted_staff_ids=["@alice:matrix.org"],
            display_names=["Alice Support"],
        ),
    )
    app = FastAPI()
    app.state.trust_monitor_service = service
    app.state.trust_monitor_policy_service = policy_service
    app.state.chatops_audit_store = ChatOpsAuditStore(
        db_path=str(tmp_path / "feedback.db")
    )
    app.include_router(module.router)
    app.dependency_overrides[module.verify_admin_access] = lambda: None
    return TestClient(app), service


def test_get_and_patch_policy(tmp_path) -> None:
    client, _ = _build_app(tmp_path)

    response = client.get("/admin/security/trust-monitor/policy")
    assert response.status_code == 200
    assert response.json()["enabled"] is True

    patch = client.patch(
        "/admin/security/trust-monitor/policy",
        json={"alert_surface": "staff_room", "silent_observer_enabled": False},
    )
    assert patch.status_code == 200
    payload = patch.json()
    assert payload["alert_surface"] == "staff_room"
    assert payload["silent_observer_enabled"] is False
    assert isinstance(payload["updated_at"], str)


def test_list_findings_and_apply_actions(tmp_path) -> None:
    client, service = _build_app(tmp_path)
    finding = service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@copycat:matrix.org",
            actor_display_name="Alice Support",
            event_type=TrustEventType.MEMBER_JOINED,
            occurred_at=datetime.now(UTC),
            external_event_id="debug:copycat",
        )
    )
    assert finding is not None
    finding_id = finding.id

    listing = client.get("/admin/security/findings")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    resolve = client.post(f"/admin/security/findings/{finding_id}/resolve")
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "resolved"

    counts = client.get("/admin/security/findings/counts")
    assert counts.status_code == 200
    assert counts.json()["resolved"] == 1


def test_get_ops_and_audit_feeds(tmp_path) -> None:
    client, service = _build_app(tmp_path)
    service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@copycat:matrix.org",
            actor_display_name="Alice Support",
            event_type=TrustEventType.MEMBER_JOINED,
            occurred_at=datetime.now(UTC),
            external_event_id="debug:copycat-ops",
        )
    )
    service.apply_retention(now=datetime.now(UTC))
    client.app.state.chatops_audit_store.add_entry(
        channel_id="matrix",
        room_id="!staff:matrix.org",
        actor_id="@alice:matrix.org",
        command_name="claim",
        case_id=42,
        source_message_id="$event-1",
        ok=True,
        idempotent=False,
        metadata={"result": "ok"},
        created_at=datetime.now(UTC),
    )

    ops = client.get("/admin/security/trust-monitor/ops")
    assert ops.status_code == 200
    ops_payload = ops.json()
    assert ops_payload["monitored_public_rooms"] == ["!support:matrix.org"]
    assert ops_payload["last_retention_run"] is not None

    access = client.get("/admin/security/trust-monitor/access-audit")
    assert access.status_code == 200
    assert isinstance(access.json()["items"], list)

    chatops = client.get("/admin/security/chatops/audit")
    assert chatops.status_code == 200
    assert len(chatops.json()["items"]) == 1
    assert chatops.json()["items"][0]["command_name"] == "claim"
