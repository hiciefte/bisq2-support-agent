"""Static security contracts for scheduler shell entrypoints."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVILEGED_JOB_SCRIPTS = (
    "process-feedback.sh",
    "update-wiki.sh",
    "reconcile-llm-wiki-coverage.sh",
    "poll-matrix.sh",
)


def _script(name: str) -> str:
    return (REPO_ROOT / "docker" / "scripts" / name).read_text(encoding="utf-8")


def test_privileged_jobs_use_only_the_scoped_scheduler_api() -> None:
    for script_name in PRIVILEGED_JOB_SCRIPTS:
        content = _script(script_name)

        assert "/scripts/lib/scheduler-api.sh" in content
        assert "/internal/scheduler/" in content
        assert "ADMIN_API_KEY" not in content
        assert "docker exec" not in content
        assert "docker restart" not in content
        assert "docker ps" not in content

    helper = _script("lib/scheduler-api.sh")
    assert "SCHEDULER_API_TOKEN" in helper
    assert "X-Scheduler-Token" in helper
    assert "ADMIN_API_KEY" not in helper


def test_rag_health_external_heartbeat_is_opt_in() -> None:
    content = _script("rag-health-check.sh")

    assert 'HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"' in content
    assert 'if [ -z "$HEALTHCHECK_URL" ]; then' in content
    assert "hc-ping.com" not in content
