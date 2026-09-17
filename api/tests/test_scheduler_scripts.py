"""Static security contracts for scheduler shell entrypoints."""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIVILEGED_JOB_SCRIPTS = (
    "process-feedback.sh",
    "update-wiki.sh",
    "reconcile-llm-wiki-coverage.sh",
    "poll-matrix.sh",
    "privacy-retention.sh",
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


@pytest.mark.parametrize(
    ("configured", "arguments", "expected_endpoint", "expected_code"),
    [
        (None, [], "/internal/scheduler/privacy-retention", 0),
        ("false", [], "/internal/scheduler/privacy-retention", 0),
        ("true", [], "/internal/scheduler/privacy-retention?dry_run=true", 0),
        (
            "false",
            ["--dry-run"],
            "/internal/scheduler/privacy-retention?dry_run=true",
            0,
        ),
        (
            "true",
            ["--dry-run"],
            "/internal/scheduler/privacy-retention?dry_run=true",
            0,
        ),
        ("invalid", [], None, 2),
        ("invalid", ["--dry-run"], None, 2),
    ],
)
def test_privacy_retention_preview_requests(
    tmp_path: Path,
    configured: str | None,
    arguments: list[str],
    expected_endpoint: str | None,
    expected_code: int,
) -> None:
    """Run the actual job with a local replacement for its container API helper."""
    helper = tmp_path / "scheduler-api.sh"
    helper.write_text(
        "scheduler_api_post() {\n"
        '    printf "%s\\n" "$1" > "$REQUEST_CAPTURE"\n'
        '    printf \'{"status":"success","dry_run":true,"deleted_rows":{}}\\n\'\n'
        "}\n",
        encoding="utf-8",
    )
    script = tmp_path / "privacy-retention.sh"
    script.write_text(
        _script("privacy-retention.sh").replace(
            "source /scripts/lib/scheduler-api.sh", f"source {shlex.quote(str(helper))}"
        ),
        encoding="utf-8",
    )
    capture = tmp_path / "request"
    environment = dict(os.environ, REQUEST_CAPTURE=str(capture))
    environment.pop("PRIVACY_RETENTION_DRY_RUN", None)
    if configured is not None:
        environment["PRIVACY_RETENTION_DRY_RUN"] = configured
    result = subprocess.run(
        ["bash", str(script), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_code, result.stderr
    if expected_endpoint is None:
        assert not capture.exists()
    else:
        assert capture.read_text(encoding="utf-8").strip() == expected_endpoint


def test_scheduler_passes_retention_preview_setting() -> None:
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "docker/docker-compose.yml").read_text())
    assert (
        "PRIVACY_RETENTION_DRY_RUN=${PRIVACY_RETENTION_DRY_RUN:-false}"
        in compose["services"]["scheduler"]["environment"]
    )
