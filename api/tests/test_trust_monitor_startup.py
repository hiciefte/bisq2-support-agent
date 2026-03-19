from __future__ import annotations


def test_trust_monitor_policy_service_import_does_not_trigger_cycle() -> None:
    from app.services.trust_monitor_policy_service import TrustMonitorPolicyService

    assert TrustMonitorPolicyService is not None
