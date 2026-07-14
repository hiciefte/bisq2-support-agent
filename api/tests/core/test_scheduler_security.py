"""Authentication contracts for the internal scheduler boundary."""

from types import SimpleNamespace

import pytest
from app.core import security
from fastapi import HTTPException


def test_scheduler_token_uses_constant_time_comparison(monkeypatch) -> None:
    comparisons: list[tuple[str, str]] = []

    def compare_digest(provided: str, configured: str) -> bool:
        comparisons.append((provided, configured))
        return True

    monkeypatch.setattr(security.secrets, "compare_digest", compare_digest)
    request = SimpleNamespace(
        headers={"X-Scheduler-Token": "provided-scheduler-token"},
        state=SimpleNamespace(),
    )
    settings = SimpleNamespace(SCHEDULER_API_TOKEN="configured-scheduler-token")

    assert security.verify_scheduler_access(request, settings) is True
    assert comparisons == [("provided-scheduler-token", "configured-scheduler-token")]
    assert request.state.scheduler_authenticated is True


def test_scheduler_rejects_mismatched_token_without_authenticating_request() -> None:
    request = SimpleNamespace(
        headers={"X-Scheduler-Token": "provided-scheduler-token-value"},
        state=SimpleNamespace(),
    )
    settings = SimpleNamespace(SCHEDULER_API_TOKEN="configured-scheduler-token-value")

    with pytest.raises(HTTPException) as exc_info:
        security.verify_scheduler_access(request, settings)

    assert exc_info.value.status_code == 403
    assert getattr(request.state, "scheduler_authenticated", False) is False
