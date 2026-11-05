"""The retention alert exception requires proof from the actual cron entries."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "docker/scripts/scheduler-heartbeat.sh"
TRIAL_ID = "matrix-staff-observability-test"
CUTOFF = "1792659600"
GUARD = f"false && : {TRIAL_ID} {CUTOFF} && "
HELD_SCRIPTS = (
    "/scripts/process-feedback.sh",
    "/scripts/poll-matrix.sh",
    "/scripts/privacy-retention.sh",
    "/scripts/rotate-retention-logs.sh",
)


def _crontab(*, held: bool = True) -> str:
    config = yaml.safe_load(
        (REPO_ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    )
    command = config["services"]["scheduler"]["command"]
    entries = re.findall(r"echo '([^']+)' [>]+ /etc/crontabs/root", command)
    assert len(entries) > 6
    selected = 0
    for index, entry in enumerate(entries):
        for script in HELD_SCRIPTS:
            if script in entry:
                selected += 1
                if held:
                    entries[index] = entry.replace(script, GUARD + script)
    assert selected == 6
    return "\n".join(entries) + "\n"


def _observe(tmp_path: Path, content: str | None) -> dict[str, float]:
    crontab = tmp_path / "root-crontab"
    if content is not None:
        crontab.write_text(content, encoding="utf-8")
    metrics_dir = tmp_path / "metrics"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "SCHEDULER_METRICS_DIR": str(metrics_dir),
            "SCHEDULER_CRONTAB_FILE": str(crontab),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    if content is not None:
        assert crontab.read_text(encoding="utf-8") == content
    return {
        name: float(value)
        for line in (metrics_dir / "scheduler-heartbeat.prom").read_text().splitlines()
        if line and not line.startswith("#")
        for name, value in [line.split()]
    }


def test_complete_guard_is_observed_without_touching_cron(tmp_path: Path) -> None:
    metrics = _observe(tmp_path, _crontab())

    assert metrics["scheduler_retention_hold_active"] == 1
    assert metrics["scheduler_retention_hold_cutoff_timestamp_seconds"] == int(CUTOFF)
    assert metrics["scheduler_retention_hold_invalid"] == 0
    assert (
        metrics["scheduler_retention_hold_observed_timestamp_seconds"]
        == metrics["scheduler_heartbeat_timestamp_seconds"]
    )
    assert not any("last_success" in name for name in metrics)
    assert not any(TRIAL_ID in name for name in metrics)


def test_normal_crontab_does_not_claim_a_hold(tmp_path: Path) -> None:
    metrics = _observe(tmp_path, _crontab(held=False))

    assert metrics["scheduler_retention_hold_active"] == 0
    assert metrics["scheduler_retention_hold_invalid"] == 0
    assert metrics["scheduler_retention_hold_cutoff_timestamp_seconds"] == 0


@pytest.mark.parametrize(
    "change",
    [
        lambda text: text.replace(GUARD, "", 1),
        lambda text: "\n".join(text.splitlines()[1:]) + "\n",
        lambda text: text + text.splitlines()[0] + "\n",
        lambda text: text + "* * * * * /scripts/privacy-retention.sh\n",
        lambda text: text.replace(TRIAL_ID, "another-trial", 1),
        lambda text: text.replace(CUTOFF, "1792659601", 1),
        lambda text: text.replace(CUTOFF, "not-a-timestamp"),
        lambda text: text.replace(TRIAL_ID, "$(touch /tmp/unsafe)", 1),
        lambda text: text.replace(TRIAL_ID, "x" * 81),
        lambda text: text.replace(TRIAL_ID, "-invalid-id"),
        lambda text: text.replace(TRIAL_ID, "_invalid-id"),
        lambda text: text.replace("0 2 * * *", "0 3 * * *"),
        lambda text: text + "* * * * * /scripts/rotate-retention-logs.sh --dry-run\n",
    ],
    ids=[
        "unguarded-entry",
        "missing-entry",
        "duplicate-entry",
        "extra-retention-job",
        "mixed-trial",
        "mixed-cutoff",
        "malformed-cutoff",
        "shell-in-trial-id",
        "oversized-trial-id",
        "leading-hyphen-trial-id",
        "leading-underscore-trial-id",
        "changed-schedule",
        "extra-log-job",
    ],
)
def test_changed_guard_fails_closed(tmp_path: Path, change) -> None:
    metrics = _observe(tmp_path, change(_crontab()))

    assert metrics["scheduler_retention_hold_active"] == 0
    assert metrics["scheduler_retention_hold_invalid"] == 1
    assert metrics["scheduler_retention_hold_cutoff_timestamp_seconds"] == 0


def test_unreadable_crontab_fails_closed(tmp_path: Path) -> None:
    metrics = _observe(tmp_path, None)

    assert metrics["scheduler_retention_hold_active"] == 0
    assert metrics["scheduler_retention_hold_invalid"] == 1


def test_comments_cannot_supply_a_missing_guard(tmp_path: Path) -> None:
    entries = _crontab().splitlines()
    entries[0] = "# " + entries[0]
    metrics = _observe(tmp_path, "\n".join(entries) + "\n")

    assert metrics["scheduler_retention_hold_active"] == 0
    assert metrics["scheduler_retention_hold_invalid"] == 1


@pytest.mark.parametrize("content", ["", "# no jobs\n", "# " + GUARD + "\n"])
def test_empty_or_comment_only_crontab_cannot_claim_hold(
    tmp_path: Path, content: str
) -> None:
    metrics = _observe(tmp_path, content)

    assert metrics["scheduler_retention_hold_active"] == 0
    assert metrics["scheduler_retention_hold_cutoff_timestamp_seconds"] == 0
