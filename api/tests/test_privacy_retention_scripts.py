from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROTATE_SCRIPT = REPO_ROOT / "docker/scripts/rotate-retention-logs.sh"
HOST_SCRIPT = REPO_ROOT / "scripts/configure-runtime-log-retention.sh"


def _run_rotation(
    log_base: Path,
    metrics_dir: Path,
    *arguments: str,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROTATE_SCRIPT), *arguments],
        env={
            **os.environ,
            "DATA_RETENTION_DAYS": "30",
            "RETENTION_LOG_BASE": str(log_base),
            "SCHEDULER_METRICS_DIR": str(metrics_dir),
            **(extra_env or {}),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _mark_recent_rotation(root: Path) -> None:
    marker = root / ".privacy-retention-last-run"
    marker.write_text(f"{int(time.time())}\n", encoding="utf-8")


def test_log_retention_dry_run_and_apply_are_bounded(tmp_path: Path) -> None:
    log_base = tmp_path / "logs"
    cron = log_base / "cron"
    nginx = log_base / "retention/nginx"
    cron.mkdir(parents=True)
    nginx.mkdir(parents=True)
    active = cron / "privacy-retention.log"
    active.write_text("current log line\n", encoding="utf-8")
    _mark_recent_rotation(cron)
    old_rotation = nginx / "access.log.old"
    old_rotation.write_text("old request metadata\n", encoding="utf-8")
    old_time = time.time() - 30 * 86400 - 60
    os.utime(old_rotation, (old_time, old_time))
    metrics_dir = tmp_path / "metrics"

    preview = _run_rotation(log_base, metrics_dir, "--dry-run")

    assert preview.returncode == 0, preview.stderr
    assert active.read_text(encoding="utf-8") == "current log line\n"
    assert old_rotation.exists()
    assert not metrics_dir.exists()

    applied = _run_rotation(log_base, metrics_dir)

    assert applied.returncode == 0, applied.stderr
    assert active.read_text(encoding="utf-8") == ""
    assert not old_rotation.exists()
    assert list(cron.glob("privacy-retention.log.*"))
    metrics = (metrics_dir / "privacy-retention-logs.prom").read_text(encoding="utf-8")
    assert "privacy_retention_log_files_deleted_last 1" in metrics
    assert 'store="application_logs"' in metrics
    success = next(
        line
        for line in metrics.splitlines()
        if line.startswith("privacy_retention_log_last_success_timestamp_seconds ")
    )
    assert abs(time.time() - int(success.rsplit(" ", 1)[1])) < 10


def test_log_retention_keeps_files_inside_exact_second_window(tmp_path: Path) -> None:
    log_base = tmp_path / "logs"
    nginx = log_base / "retention/nginx"
    nginx.mkdir(parents=True)
    retained_rotation = nginx / "access.log.retained"
    retained_rotation.write_text("recent request metadata\n", encoding="utf-8")
    retained_time = time.time() - 30 * 86400 + 60
    os.utime(retained_rotation, (retained_time, retained_time))

    result = _run_rotation(log_base, tmp_path / "metrics")

    assert result.returncode == 0, result.stderr
    assert retained_rotation.exists()


def test_log_rotation_purges_active_log_without_recent_checkpoint(
    tmp_path: Path,
) -> None:
    log_base = tmp_path / "logs"
    cron = log_base / "cron"
    cron.mkdir(parents=True)
    active = cron / "scheduler.log"
    active.write_text("historical metadata\n", encoding="utf-8")
    old_time = time.time() - 30 * 86400 - 60
    os.utime(active, (old_time, old_time))

    result = _run_rotation(log_base, tmp_path / "metrics")

    assert result.returncode == 0, result.stderr
    assert active.read_text(encoding="utf-8") == ""
    assert list(cron.glob("scheduler.log.*")) == []


def test_log_rotation_purges_mixed_age_active_log(tmp_path: Path) -> None:
    log_base = tmp_path / "logs"
    cron = log_base / "cron"
    cron.mkdir(parents=True)
    active = cron / "scheduler.log"
    active.write_text(
        "2026-01-01 old personal metadata\n2026-07-15 recent metadata\n",
        encoding="utf-8",
    )

    result = _run_rotation(log_base, tmp_path / "metrics")

    assert result.returncode == 0, result.stderr
    assert active.read_text(encoding="utf-8") == ""
    assert list(cron.glob("scheduler.log.*")) == []
    metrics = (tmp_path / "metrics/privacy-retention-logs.prom").read_text(
        encoding="utf-8"
    )
    assert "privacy_retention_log_files_deleted_last 1" in metrics


def test_log_rotation_purges_active_log_after_stale_checkpoint(tmp_path: Path) -> None:
    log_base = tmp_path / "logs"
    cron = log_base / "cron"
    cron.mkdir(parents=True)
    active = cron / "scheduler.log"
    active.write_text("recent write after an unbounded gap\n", encoding="utf-8")
    marker = cron / ".privacy-retention-last-run"
    marker.write_text("stale checkpoint\n", encoding="utf-8")
    stale_time = time.time() - 30 * 86400 - 60
    os.utime(marker, (stale_time, stale_time))

    result = _run_rotation(log_base, tmp_path / "metrics")

    assert result.returncode == 0, result.stderr
    assert active.read_text(encoding="utf-8") == ""
    assert list(cron.glob("scheduler.log.*")) == []


def test_log_rotation_uses_prior_run_as_oldest_record_boundary(
    tmp_path: Path,
) -> None:
    log_base = tmp_path / "logs"
    cron = log_base / "cron"
    cron.mkdir(parents=True)
    active = cron / "scheduler.log"
    active.write_text("personal metadata\n", encoding="utf-8")
    marker = cron / ".privacy-retention-last-run"
    marker.write_text("checkpoint\n", encoding="utf-8")
    boundary = time.time() - 86400
    os.utime(marker, (boundary, boundary))

    result = _run_rotation(log_base, tmp_path / "metrics")

    assert result.returncode == 0, result.stderr
    rotations = list(cron.glob("scheduler.log.*"))
    assert len(rotations) == 1
    assert abs(rotations[0].stat().st_mtime - boundary) < 2


def test_log_rotation_stages_next_checkpoint_before_truncation(
    tmp_path: Path,
) -> None:
    log_base = tmp_path / "logs"
    cron = log_base / "cron"
    cron.mkdir(parents=True)
    active = cron / "scheduler.log"
    active.write_text("initial metadata\n", encoding="utf-8")
    _mark_recent_rotation(cron)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    write_marker = tmp_path / "concurrent-write"
    chmod = fake_bin / "chmod"
    chmod.write_text(
        "#!/bin/bash\n"
        '/bin/chmod "$@"\n'
        'if [[ "$*" == *".log."* ]]; then\n'
        "  printf 'concurrent metadata\\n' >> \"$ACTIVE_LOG\"\n"
        '  touch "$WRITE_MARKER"\n'
        "  sleep 0.2\n"
        "fi\n",
        encoding="utf-8",
    )
    chmod.chmod(0o755)

    result = _run_rotation(
        log_base,
        tmp_path / "metrics",
        extra_env={
            "ACTIVE_LOG": str(active),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WRITE_MARKER": str(write_marker),
        },
    )

    assert result.returncode == 0, result.stderr
    checkpoint = cron / ".privacy-retention-last-run"
    assert active.read_text(encoding="utf-8") == "concurrent metadata\n"
    assert checkpoint.stat().st_mtime <= write_marker.stat().st_mtime


def test_log_retention_rejects_symlinked_base(tmp_path: Path) -> None:
    real_logs = tmp_path / "real"
    real_logs.mkdir()
    linked_logs = tmp_path / "linked"
    linked_logs.symlink_to(real_logs, target_is_directory=True)

    result = _run_rotation(linked_logs, tmp_path / "metrics", "--dry-run")

    assert result.returncode != 0
    assert "symlinked log base" in result.stderr


def test_scheduler_mounts_and_runs_privacy_jobs_without_docker_access() -> None:
    with (REPO_ROOT / "docker/docker-compose.yml").open(encoding="utf-8") as handle:
        scheduler = yaml.safe_load(handle)["services"]["scheduler"]
    serialized = yaml.safe_dump(scheduler)

    assert "privacy-retention.sh:/scripts/privacy-retention.sh:ro" in serialized
    assert "rotate-retention-logs.sh:/scripts/rotate-retention-logs.sh:ro" in serialized
    assert "@reboot /scripts/privacy-retention.sh" in scheduler["command"]
    assert "0 2 * * * /scripts/privacy-retention.sh" in scheduler["command"]
    assert "30 2 * * * /scripts/rotate-retention-logs.sh" in scheduler["command"]
    assert "docker.sock" not in serialized
    assert "ADMIN_API_KEY" not in serialized


def test_compatibility_cleanup_has_no_retention_override() -> None:
    script = (REPO_ROOT / "scripts/cleanup_old_data.sh").read_text(encoding="utf-8")

    assert "--dry-run" in script
    assert "--retention-days" not in script
    assert "/scripts/privacy-retention.sh" in script


def test_runtime_log_policy_defaults_to_read_only_check(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_root = tmp_path / "docker-data"
    docker_root.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = info ]; then printf \'%s\\n\' "$FAKE_DOCKER_ROOT"; exit 0; fi\n'
        "exit 1\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["bash", str(HOST_SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_ROOT": str(docker_root),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "require a host-managed age policy" in result.stdout
    assert {path.name for path in tmp_path.iterdir()} == {"bin", "docker-data"}
