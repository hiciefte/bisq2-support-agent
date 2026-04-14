"""Tests for the proactive trust-monitor persister.

Verifies the policy alert surface overrides whatever the detector produced,
which is the bug we are fixing: proactive scanner hardcodes BOTH but the
operator policy may want ADMIN_UI only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.channels.trust_monitor.models import TrustAlertSurface
from app.channels.trust_monitor.proactive_persistence import persist_proactive_finding


def _make_result(surface: TrustAlertSurface) -> SimpleNamespace:
    return SimpleNamespace(
        detector_key="user_directory_impersonation",
        suspect_actor_id="@bad:matrix.org",
        suspect_actor_key="@bad:matrix.org",
        suspect_display_name="suddenwhipvapor",
        score=0.95,
        evidence_summary={"matched_staff_name": "suddenwhipvapor"},
        alert_surface=surface,
        occurred_at=datetime.now(UTC),
    )


def _make_service(policy_surface: TrustAlertSurface):
    captured: dict = {}

    class _Store:
        def upsert_finding(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id="finding-1", **kwargs)

    class _Publisher:
        published: list = []

        def publish(self, finding):
            self.published.append(finding)

    publisher = _Publisher()
    service = SimpleNamespace(
        store=_Store(),
        publisher=publisher,
        policy_service=SimpleNamespace(
            get_policy=lambda: SimpleNamespace(alert_surface=policy_surface)
        ),
    )
    return service, captured, publisher


def test_persister_overrides_detector_surface_with_policy_admin_ui() -> None:
    service, captured, publisher = _make_service(TrustAlertSurface.ADMIN_UI)
    result = _make_result(TrustAlertSurface.BOTH)

    persist_proactive_finding(
        trust_monitor_service=service,
        sync_rooms=["!room:matrix.org"],
        result=result,
    )

    assert captured["alert_surface"] == TrustAlertSurface.ADMIN_UI
    assert len(publisher.published) == 1


def test_persister_uses_policy_both_when_configured() -> None:
    service, captured, _ = _make_service(TrustAlertSurface.BOTH)
    result = _make_result(TrustAlertSurface.ADMIN_UI)

    persist_proactive_finding(
        trust_monitor_service=service,
        sync_rooms=["!room:matrix.org"],
        result=result,
    )

    assert captured["alert_surface"] == TrustAlertSurface.BOTH


def test_persister_falls_back_space_id_when_no_sync_rooms() -> None:
    service, captured, _ = _make_service(TrustAlertSurface.ADMIN_UI)
    result = _make_result(TrustAlertSurface.BOTH)

    persist_proactive_finding(
        trust_monitor_service=service,
        sync_rooms=[],
        result=result,
    )

    assert captured["space_id"] == "proactive_scan"


def test_persister_swallows_exceptions() -> None:
    class _ExplodingStore:
        def upsert_finding(self, **_):
            raise RuntimeError("boom")

    service = SimpleNamespace(
        store=_ExplodingStore(),
        publisher=None,
        policy_service=SimpleNamespace(
            get_policy=lambda: SimpleNamespace(alert_surface=TrustAlertSurface.ADMIN_UI)
        ),
    )
    result = _make_result(TrustAlertSurface.BOTH)

    # Must not raise — the proactive scanner loop relies on this.
    persist_proactive_finding(
        trust_monitor_service=service,
        sync_rooms=["!room:matrix.org"],
        result=result,
    )
