"""Authentication contracts for the internal scheduler boundary."""

from types import SimpleNamespace

from app.core import security


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
