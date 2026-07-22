from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup.sh"
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore.sh"


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _fake_age(path: Path) -> None:
    path.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "output=''\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = --output ]; then output="$2"; shift 2; else shift; fi\n'
        "done\n"
        'cat > "$output"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.mark.parametrize("failure_call", [1, 2, 3])
def test_backup_mount_drift_blocks_each_encryption_mutation_boundary(
    tmp_path: Path, failure_call: int
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_age(fake_bin / "age")
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
    validation_log = tmp_path / "validation.log"

    result = _run_bash(f"""
        export PATH="{fake_bin}:$PATH"
        source "{BACKUP_SCRIPT}"
        STAGING_DIR="{staging}"
        TARGET_DIR="{target}"
        ENCRYPTION=age
        RECIPIENT=test-recipient
        validation_count=0
        revalidate_backup_target() {{
            validation_count=$((validation_count + 1))
            printf '%s\n' "$validation_count" >> "{validation_log}"
            [ "$validation_count" -ne {failure_call} ]
        }}
        encrypt_backup 20260101T000000Z
        """)

    assert result.returncode != 0
    assert validation_log.read_text(encoding="utf-8").splitlines() == [
        str(value) for value in range(1, failure_call + 1)
    ]
    assert not (target / "bisq-support-backup-20260101T000000Z.tar.gz.age").exists()
    partials = list(target.glob(".*.partial.*"))
    assert len(partials) == (0 if failure_call == 1 else 1)
    if failure_call == 3:
        assert partials[0].stat().st_mode & 0o777 == 0o600


def test_backup_mount_drift_blocks_retention_without_deleting(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    old_backup = target / "bisq-support-backup-20200101T000000Z.tar.gz.age"
    old_backup.write_bytes(b"encrypted")
    os.utime(old_backup, (1, 1))

    result = _run_bash(f"""
        source "{BACKUP_SCRIPT}"
        TARGET_DIR="{target}"
        RETENTION_DAYS=1
        revalidate_backup_target() {{ return 1; }}
        apply_retention
        """)

    assert result.returncode != 0
    assert old_backup.is_file()


def test_recovery_guard_blocks_both_entrypoints_and_requires_explicit_clear(
    tmp_path: Path,
) -> None:
    install_dir = tmp_path / "install"
    data_dir = install_dir / "api" / "data"
    data_dir.mkdir(parents=True)
    work_dir = tmp_path / "private-rollback"
    work_dir.mkdir()
    marker = install_dir / "failed_updates" / "disaster-recovery" / "recovery-blocked"

    created = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        initialize_paths
        WORK_DIR="{work_dir}"
        mkdir -p "$RECOVERY_CONTROL_DIR"
        : > "$RECOVERY_LOCK_FILE"
        sync_recovery_path() {{ return 0; }}
        create_recovery_guard
        """)
    assert created.returncode == 0, created.stdout + created.stderr
    assert marker.is_file()
    assert marker.stat().st_mode & 0o777 == 0o600
    assert str(work_dir) in marker.read_text(encoding="utf-8")

    for script in (BACKUP_SCRIPT, RESTORE_SCRIPT):
        blocked = _run_bash(f"""
            export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
            source "{script}"
            initialize_paths
            ensure_recovery_not_blocked
            """)
        assert blocked.returncode != 0
        assert "recovery is blocked" in (blocked.stdout + blocked.stderr).lower()

    unconfirmed = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        main --clear-recovery-failure
        """)
    assert unconfirmed.returncode != 0
    assert marker.is_file()

    cleared = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        flock() {{ return 0; }}
        sync_recovery_path() {{ return 0; }}
        main --clear-recovery-failure --yes
        """)
    assert cleared.returncode == 0, cleared.stdout + cleared.stderr
    assert not marker.exists()


@pytest.mark.parametrize("script", [BACKUP_SCRIPT, RESTORE_SCRIPT])
def test_staged_recovery_uses_helper_from_reviewed_script_source(
    tmp_path: Path,
    script: Path,
) -> None:
    install_dir = tmp_path / "older-production-checkout"
    (install_dir / "api" / "data").mkdir(parents=True)

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{script}"
        initialize_paths
        printf '%s' "$DR_HELPER"
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.endswith(
        str(REPO_ROOT / "api" / "app" / "scripts" / "disaster_recovery.py")
    )
    assert str(install_dir) not in result.stdout


def test_staged_backup_mounts_reviewed_helper_into_api_image() -> None:
    backup = BACKUP_SCRIPT.read_text(encoding="utf-8")

    assert '--volume "$DR_HELPER:/app/app/scripts/disaster_recovery.py:ro"' in backup


def test_staged_restore_mounts_reviewed_helper_for_all_qdrant_operations() -> None:
    restore = RESTORE_SCRIPT.read_text(encoding="utf-8")

    helper_mount = '--volume "$DR_HELPER:/app/app/scripts/disaster_recovery.py:ro"'
    assert restore.count(helper_mount) == 4


@pytest.mark.parametrize(
    ("configured_services", "expected_status"),
    [
        ("api\nmatrix-alert-relay\nprometheus", 0),
        ("api\nmatrix-alert-relay-shadow\nprometheus", 1),
    ],
)
def test_matrix_relay_topology_detection_uses_exact_service_names(
    configured_services: str,
    expected_status: int,
) -> None:
    result = _run_bash(f"""
        source "{BACKUP_SCRIPT}"
        compose() {{ printf '%s\n' "{configured_services}"; }}
        set +e
        service_is_configured matrix-alert-relay
        status=$?
        set -e
        printf '%s' "$status"
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == str(expected_status)


def test_matrix_relay_topology_inspection_failure_is_distinct_from_absence() -> None:
    result = _run_bash(f"""
        source "{BACKUP_SCRIPT}"
        compose() {{ return 1; }}
        set +e
        service_is_configured matrix-alert-relay
        status=$?
        set -e
        printf '%s' "$status"
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "2"


def test_absent_matrix_relay_snapshot_is_a_zero_member_archive(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    (staging / "components" / "volumes").mkdir(parents=True)

    result = _run_bash(f"""
        source "{BACKUP_SCRIPT}"
        STAGING_DIR="{staging}"
        snapshot_absent_volume matrix
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    with tarfile.open(
        staging / "components" / "volumes" / "matrix.tar.gz", mode="r:gz"
    ) as archive:
        assert archive.getmembers() == []


def test_backup_only_synthesizes_matrix_volume_for_absent_relay_service() -> None:
    backup = BACKUP_SCRIPT.read_text(encoding="utf-8")
    present_branch = (
        "if service_is_configured matrix-alert-relay; then\n"
        '        matrix_volume="$(volume_for_service_path matrix-alert-relay /data)"'
    )

    assert present_branch in backup
    assert "absent_volume_args+=(--absent-volume-component matrix)" in backup
    assert 'if [ "$matrix_volume_absent" = true ]; then' in backup
    assert "snapshot_absent_volume matrix" in backup
    assert 'snapshot_volume matrix "$matrix_volume" "$helper_image"' in backup


@pytest.mark.parametrize("script", [BACKUP_SCRIPT, RESTORE_SCRIPT])
def test_lock_acquisition_rechecks_marker_after_stale_precheck(
    tmp_path: Path,
    script: Path,
) -> None:
    install_dir = tmp_path / "install"
    data_dir = install_dir / "api" / "data"
    data_dir.mkdir(parents=True)
    marker = install_dir / "failed_updates" / "disaster-recovery" / "recovery-blocked"

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{script}"
        initialize_paths
        ensure_recovery_not_blocked
        sync_recovery_path() {{ return 0; }}
        flock() {{
            mkdir -p "$(dirname "$RECOVERY_FAILURE_MARKER")"
            printf '%s\n' unresolved > "$RECOVERY_FAILURE_MARKER"
            return 0
        }}
        acquire_recovery_lock
        """)

    assert result.returncode != 0
    assert marker.is_file()
    assert "recovery is blocked" in (result.stdout + result.stderr).lower()
    assert not (data_dir / ".disaster-recovery.lock").exists()


@pytest.mark.parametrize("script", [BACKUP_SCRIPT, RESTORE_SCRIPT])
def test_recovery_lock_is_private_and_outside_container_data(
    tmp_path: Path,
    script: Path,
) -> None:
    install_dir = tmp_path / "install"
    data_dir = install_dir / "api" / "data"
    data_dir.mkdir(parents=True)

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{script}"
        initialize_paths
        sync_recovery_path() {{ return 0; }}
        flock() {{ return 0; }}
        open_recovery_lock
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    lock_file = install_dir / "failed_updates" / "disaster-recovery" / "recovery.lock"
    assert lock_file.is_file()
    assert lock_file.stat().st_mode & 0o777 == 0o600
    assert not (data_dir / ".disaster-recovery.lock").exists()


def test_guard_release_rejects_symlink_without_removing_target(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    control_dir = install_dir / "failed_updates" / "disaster-recovery"
    control_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("keep\n", encoding="utf-8")
    marker = control_dir / "recovery-blocked"
    marker.symlink_to(outside)

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        initialize_paths
        RECOVERY_GUARD_ACTIVE=true
        if release_recovery_guard; then
            exit 99
        fi
        test "$RECOVERY_GUARD_ACTIVE" = true
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.is_symlink()
    assert outside.read_text(encoding="utf-8") == "keep\n"


def test_incomplete_rollback_preserves_guard_before_unlock(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    data_dir = install_dir / "api" / "data"
    data_dir.mkdir(parents=True)
    work_dir = tmp_path / "private-rollback"
    work_dir.mkdir()
    event_log = tmp_path / "events.log"
    marker = install_dir / "failed_updates" / "disaster-recovery" / "recovery-blocked"

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        initialize_paths
        WORK_DIR="{work_dir}"
        mkdir -p "$RECOVERY_CONTROL_DIR"
        : > "$RECOVERY_LOCK_FILE"
        sync_recovery_path() {{ return 0; }}
        create_recovery_guard
        APPLY=true
        RESTORE_COMMITTED=false
        LOCK_FD=9
        STOPPED_SERVICES=(api)
        cleanup_scratch_qdrant() {{ return 0; }}
        service_is_running() {{ return 1; }}
        rollback_applied_components() {{
            printf '%s\n' rollback >> "{event_log}"
            rm -f -- "$RECOVERY_FAILURE_MARKER"
            return 1
        }}
        flock() {{
            if [ "$1" = -u ]; then
                test -f "$RECOVERY_FAILURE_MARKER"
                printf '%s\n' unlock >> "{event_log}"
            fi
        }}
        set +e
        false
        cleanup
        """)

    assert result.returncode != 0
    assert marker.is_file()
    assert work_dir.is_dir()
    assert event_log.read_text(encoding="utf-8").splitlines() == [
        "rollback",
        "unlock",
    ]


def test_marker_sync_failure_keeps_recovery_block_active(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    control_dir = install_dir / "failed_updates" / "disaster-recovery"
    control_dir.mkdir(parents=True)
    marker = control_dir / "recovery-blocked"
    marker.write_text("active\n", encoding="utf-8")
    lock_file = control_dir / "recovery.lock"
    lock_file.write_text("blocked\n", encoding="utf-8")

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        initialize_paths
        WORK_DIR="{tmp_path / 'private-rollback'}"
        RECOVERY_GUARD_ACTIVE=true
        sync_recovery_path() {{
            [ "$1" != "$RECOVERY_CONTROL_DIR" ]
        }}
        if release_recovery_guard; then
            exit 99
        fi
        test "$RECOVERY_GUARD_ACTIVE" = true
        ensure_recovery_not_blocked
        """)

    assert result.returncode != 0
    assert marker.is_file()
    assert lock_file.read_text(encoding="utf-8") == "blocked\n"
    assert "recovery is blocked" in (result.stdout + result.stderr).lower()


def test_guard_clear_keeps_marker_until_lock_state_is_durable(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    control_dir = install_dir / "failed_updates" / "disaster-recovery"
    control_dir.mkdir(parents=True)
    marker = control_dir / "recovery-blocked"
    marker.write_text("active\n", encoding="utf-8")
    lock_file = control_dir / "recovery.lock"
    lock_file.write_text("blocked\n", encoding="utf-8")
    event_log = tmp_path / "events.log"

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        initialize_paths
        RECOVERY_GUARD_ACTIVE=true
        set_recovery_lock_state() {{
            test -f "$RECOVERY_FAILURE_MARKER"
            : > "$RECOVERY_LOCK_FILE"
            printf '%s\n' clear-lock >> "{event_log}"
            return 1
        }}
        remove_recovery_marker_durably() {{
            printf '%s\n' remove-marker >> "{event_log}"
            return 0
        }}
        if release_recovery_guard; then
            exit 99
        fi
        test "$RECOVERY_GUARD_ACTIVE" = true
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.is_file()
    assert event_log.read_text(encoding="utf-8").splitlines() == ["clear-lock"]


def test_marker_removal_failure_reasserts_both_recovery_blocks(
    tmp_path: Path,
) -> None:
    install_dir = tmp_path / "install"
    control_dir = install_dir / "failed_updates" / "disaster-recovery"
    control_dir.mkdir(parents=True)
    marker = control_dir / "recovery-blocked"
    marker.write_text("active\n", encoding="utf-8")
    lock_file = control_dir / "recovery.lock"
    lock_file.write_text("blocked\n", encoding="utf-8")

    result = _run_bash(f"""
        export BISQ_SUPPORT_INSTALL_DIR="{install_dir}"
        source "{RESTORE_SCRIPT}"
        initialize_paths
        WORK_DIR="{tmp_path / 'private-rollback'}"
        sync_recovery_path() {{ return 0; }}
        remove_recovery_marker_durably() {{
            rm -f -- "$RECOVERY_FAILURE_MARKER"
            return 1
        }}
        if clear_recovery_block_durably; then
            exit 99
        fi
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.is_file()
    assert not marker.is_symlink()
    assert lock_file.read_text(encoding="utf-8") == "blocked\n"


def test_restart_failure_requiesces_every_partially_started_service(
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "events.log"
    result = _run_bash(f"""
        source "{RESTORE_SCRIPT}"
        STOPPED_SERVICES=(api scheduler)
        service_is_running() {{ return 0; }}
        compose() {{
            printf '%s\n' "$*" >> "{event_log}"
            [ "$1" != start ]
        }}
        if start_stopped_services; then
            exit 99
        fi
        printf '%s' "${{#STOPPED_SERVICES[@]}}"
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.endswith("2")
    assert event_log.read_text(encoding="utf-8").splitlines() == [
        "start api scheduler",
        "stop --timeout 30 api",
        "stop --timeout 30 scheduler",
    ]


def test_restore_commits_only_after_service_restart() -> None:
    success = _run_bash(f"""
        source "{RESTORE_SCRIPT}"
        COMPONENTS=(application)
        stop_selected_services() {{ STOPPED_SERVICES=(api); }}
        restore_application_data() {{ return 0; }}
        restore_qdrant() {{ return 0; }}
        start_stopped_services() {{
            [ "$RESTORE_COMMITTED" = false ]
            STOPPED_SERVICES=()
        }}
        release_recovery_guard() {{ [ "$RESTORE_COMMITTED" = true ]; }}
        apply_restore /snapshot
        printf '%s' "$RESTORE_COMMITTED"
        """)
    assert success.returncode == 0, success.stdout + success.stderr
    assert success.stdout == "true"

    failed = _run_bash(f"""
        source "{RESTORE_SCRIPT}"
        COMPONENTS=(application)
        stop_selected_services() {{ STOPPED_SERVICES=(api); }}
        restore_application_data() {{ return 0; }}
        restore_qdrant() {{ return 0; }}
        start_stopped_services() {{ return 1; }}
        if apply_restore /snapshot; then
            exit 99
        fi
        printf '%s' "$RESTORE_COMMITTED"
        """)
    assert failed.returncode == 0, failed.stdout + failed.stderr
    assert failed.stdout == "false"


def test_committed_restore_succeeds_when_guard_release_retry_recovers(
    tmp_path: Path,
) -> None:
    release_log = tmp_path / "release.log"
    result = _run_bash(f"""
        source "{RESTORE_SCRIPT}"
        COMPONENTS=(application)
        APPLY=true
        RECOVERY_GUARD_ACTIVE=true
        WORK_DIR="{tmp_path / 'work'}"
        mkdir -p "$WORK_DIR"
        stop_selected_services() {{ STOPPED_SERVICES=(api); }}
        restore_application_data() {{ return 0; }}
        restore_qdrant() {{ return 0; }}
        start_stopped_services() {{ STOPPED_SERVICES=(); return 0; }}
        cleanup_scratch_qdrant() {{ return 0; }}
        release_count=0
        release_recovery_guard() {{
            release_count=$((release_count + 1))
            printf '%s\n' "$release_count" >> "{release_log}"
            if [ "$release_count" -eq 1 ]; then
                return 1
            fi
            RECOVERY_GUARD_ACTIVE=false
            return 0
        }}
        apply_restore /snapshot || cleanup
        """)

    assert result.returncode == 0, result.stdout + result.stderr
    assert release_log.read_text(encoding="utf-8").splitlines() == ["1", "2"]


def test_guard_release_retry_does_not_mask_scratch_cleanup_failure(
    tmp_path: Path,
) -> None:
    result = _run_bash(f"""
        source "{RESTORE_SCRIPT}"
        COMPONENTS=(application)
        APPLY=true
        RECOVERY_GUARD_ACTIVE=true
        WORK_DIR="{tmp_path / 'work'}"
        mkdir -p "$WORK_DIR"
        stop_selected_services() {{ STOPPED_SERVICES=(api); }}
        restore_application_data() {{ return 0; }}
        restore_qdrant() {{ return 0; }}
        start_stopped_services() {{ STOPPED_SERVICES=(); return 0; }}
        cleanup_scratch_qdrant() {{ return 1; }}
        release_count=0
        release_recovery_guard() {{
            release_count=$((release_count + 1))
            if [ "$release_count" -eq 1 ]; then
                return 1
            fi
            RECOVERY_GUARD_ACTIVE=false
            return 0
        }}
        apply_restore /snapshot || cleanup
        """)

    assert result.returncode != 0


def test_application_component_is_documented_for_verify_and_restore() -> None:
    documentation = (REPO_ROOT / "docs" / "disaster-recovery.md").read_text(
        encoding="utf-8"
    )
    assert "Use `--component application`" in documentation
    assert "--apply --yes --component application" in documentation
