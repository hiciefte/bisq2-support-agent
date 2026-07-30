from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = REPO_ROOT / "scripts" / "lib" / "common.sh"
DOCKER_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "docker-utils.sh"
CHECK_HEALTH_SH = REPO_ROOT / "scripts" / "check-health.sh"
GIT_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "git-utils.sh"
ROLLBACK_SH = REPO_ROOT / "scripts" / "rollback.sh"
UPDATE_SH = REPO_ROOT / "scripts" / "update.sh"
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"
BACKUP_SH = REPO_ROOT / "scripts" / "backup.sh"
START_SH = REPO_ROOT / "scripts" / "start.sh"
STOP_SH = REPO_ROOT / "scripts" / "stop.sh"
RESTART_SH = REPO_ROOT / "scripts" / "restart.sh"
ROLLBACK_TOR_SH = REPO_ROOT / "scripts" / "rollback-tor.sh"
VERIFY_FEEDBACK_SH = REPO_ROOT / "scripts" / "verify-feedback-persistence.sh"
DRILL_ALERT_SH = REPO_ROOT / "scripts" / "drill-alert-delivery.sh"
CLEANUP_OLD_DATA_SH = REPO_ROOT / "scripts" / "cleanup_old_data.sh"
TRANSITION_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "production-gate-transition.md"


def clean_git_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    if overrides:
        env.update(overrides)
    return env


def run_bash(
    script: str, *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        env=clean_git_env(env),
        capture_output=True,
        text=True,
        check=False,
    )


def run_git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=clean_git_env(),
        capture_output=True,
        text=True,
        check=check,
    )


def init_git_repo(path: Path) -> None:
    run_git(path, "init")
    run_git(path, "config", "user.email", "ci@example.com")
    run_git(path, "config", "user.name", "CI")
    # Keep synthetic test repositories independent from a developer machine's
    # global Git signing and hooks configuration.
    run_git(path, "config", "commit.gpgsign", "false")
    run_git(path, "config", "core.hooksPath", "/dev/null")


def test_rollback_rejects_unknown_option_before_orchestration(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(ROLLBACK_SH), "--not-a-real-option"],
        cwd=REPO_ROOT,
        env=clean_git_env({"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)}),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Unknown option" in result.stdout
    assert "Validating environment" not in result.stdout


def test_rollback_fails_cleanly_when_no_backup_reference_exists(
    tmp_path: Path,
) -> None:
    result = run_bash(
        f"""
        source "{ROLLBACK_SH}"
        INSTALL_DIR="{tmp_path}"
        validate_git_repo() {{ return 0; }}
        get_latest_backup() {{ return 1; }}
        perform_rollback ""
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode == 1
    assert "No backup tags found" in result.stdout


def test_update_script_can_be_sourced_without_running_orchestration(
    tmp_path: Path,
) -> None:
    result = run_bash(
        f"""
        source "{UPDATE_SH}"
        declare -F run_faq_sqlite_migration >/dev/null
        echo sourced-without-main
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert "sourced-without-main" in result.stdout
    assert "Creating system backup" not in result.stdout


def test_real_update_main_holds_lifecycle_lock_and_preserves_order(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "update-order.log"
    result = run_bash(
        f"""
        source "{UPDATE_SH}"
        record() {{ printf '%s\n' "$1" >> "{log_file}"; }}
        acquire_production_lifecycle_lock() {{ record lock; }}
        ensure_release_source_tree_clean() {{ record clean; }}
        validate_environment() {{ record validate; }}
        create_system_backup() {{ record backup; }}
        perform_update() {{ record update; NO_REPO_UPDATES=false; export NO_REPO_UPDATES; }}
        verify_release_ai_quality_gate() {{ record quality; }}
        run_faq_migration() {{ record faq-boundary; }}
        analyze_changes() {{ record analyze; }}
        fix_permissions() {{ record permissions; }}
        run_faq_sqlite_migration() {{ record faq-sqlite; }}
        apply_updates() {{ record apply; }}
        verify_feedback_persistence() {{ record feedback; }}
        cleanup_backups() {{ record cleanup; }}
        show_service_status() {{ record status; }}
        main
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "lock",
        "clean",
        "validate",
        "backup",
        "update",
        "quality",
        "faq-boundary",
        "analyze",
        "permissions",
        "faq-sqlite",
        "apply",
        "feedback",
        "cleanup",
        "status",
    ]


def test_deploy_does_not_stop_services_after_reporting_success() -> None:
    deploy = DEPLOY_SH.read_text(encoding="utf-8")

    success_index = deploy.index('echo "Deployment complete!"')
    after_success = deploy[success_index:]

    assert 'run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" up -d' in deploy
    assert 'run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" down' not in after_success
    assert after_success.count("Deployment complete!") == 1


def test_existing_data_operations_pin_the_existing_compose_project() -> None:
    update = UPDATE_SH.read_text(encoding="utf-8")
    backup = BACKUP_SH.read_text(encoding="utf-8")
    restore = (REPO_ROOT / "scripts" / "restore.sh").read_text(encoding="utf-8")

    for script in (backup, restore):
        assert "pin_existing_compose_project" in script
        assert '"$DOCKER_DIR" "$COMPOSE_FILE" existing' in script
    assert "pin_existing_compose_project" in update
    assert '"$DOCKER_DIR" "$COMPOSE_FILE" running' in update
    assert "validate_existing_api_data_identity" in update
    assert '"$INSTALL_DIR/api/data" running' in update
    assert "docker-api-1" not in update


def test_existing_stack_entry_points_pin_before_compose_actions() -> None:
    scripts = (
        START_SH,
        STOP_SH,
        RESTART_SH,
        ROLLBACK_SH,
        CHECK_HEALTH_SH,
        VERIFY_FEEDBACK_SH,
        ROLLBACK_TOR_SH,
        DRILL_ALERT_SH,
        CLEANUP_OLD_DATA_SH,
    )

    for script_path in scripts:
        script = script_path.read_text(encoding="utf-8")
        assert any(
            name in script
            for name in (
                "pin_existing_compose_project",
                "pin_configured_or_existing_compose_project",
            )
        )

    assert "pin_existing_compose_project" not in DEPLOY_SH.read_text(encoding="utf-8")


def test_production_mutators_share_the_recovery_lifecycle_lock() -> None:
    lifecycle_scripts = (
        UPDATE_SH,
        START_SH,
        STOP_SH,
        RESTART_SH,
        ROLLBACK_SH,
        CHECK_HEALTH_SH,
        ROLLBACK_TOR_SH,
        CLEANUP_OLD_DATA_SH,
    )
    for script_path in lifecycle_scripts:
        assert "acquire_production_lifecycle_lock" in script_path.read_text(
            encoding="utf-8"
        )

    common = COMMON_SH.read_text(encoding="utf-8")
    backup = BACKUP_SH.read_text(encoding="utf-8")
    restore = (REPO_ROOT / "scripts" / "restore.sh").read_text(encoding="utf-8")
    assert 'failed_updates/disaster-recovery"' in common
    assert (
        'RECOVERY_CONTROL_DIR="$INSTALL_DIR/failed_updates/disaster-recovery"' in backup
    )
    assert (
        'RECOVERY_CONTROL_DIR="$INSTALL_DIR/failed_updates/disaster-recovery"'
        in restore
    )


def test_transition_runbook_proves_private_access_and_exact_build() -> None:
    runbook = TRANSITION_RUNBOOK.read_text(encoding="utf-8")

    assert "${EXTERNAL_HTTP_URL:?" in runbook
    assert '"$EXTERNAL_HTTP_URL"' in runbook
    assert "  7)" in runbook
    assert "7|28)" not in runbook
    assert (
        "  28)\n"
        "    echo 'External HTTP probe timed out; ingress closure is unproven' >&2\n"
        "    exit 1"
    ) in runbook
    assert "failed unexpectedly" in runbook
    assert '"$SSH_TARGET"' in runbook
    assert "/admin" in runbook
    assert 'EXPECTED_BUILD_ID="build-$(git -C' in runbook
    assert "rev-parse --short" in runbook
    assert "'.build_id'" in runbook
    assert "`BISQ_SUPPORT_LIFECYCLE_LOCK_FD`" in runbook


def test_production_lifecycle_lock_is_reentrant_in_one_process(
    tmp_path: Path,
) -> None:
    install_dir = tmp_path / "bisq-support-test"
    install_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    flock_log = tmp_path / "flock.log"
    flock = fakebin / "flock"
    flock.write_text(
        "#!/bin/bash\n" f'printf \'%s\\n\' "$*" >> "{flock_log}"\n',
        encoding="utf-8",
    )
    flock.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{COMMON_SH}"
        setup_colors
        acquire_production_lifecycle_lock "{install_dir}"
        acquire_production_lifecycle_lock "{install_dir}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert flock_log.read_text(encoding="utf-8").splitlines() == ["-n 202"]
    lock_file = install_dir / "failed_updates" / "disaster-recovery" / "recovery.lock"
    assert lock_file.is_file()
    assert lock_file.stat().st_mode & 0o777 == 0o600


def test_update_migration_guard_never_overwrites_nonempty_faq_store(
    tmp_path: Path,
) -> None:
    migration_script = tmp_path / "api" / "app" / "scripts" / "migrate_to_sqlite.py"
    migration_script.parent.mkdir(parents=True)
    migration_script.write_text("# synthetic migration marker\n", encoding="utf-8")
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fakebin / "docker"
    api_container_id = "aaaaaaaaaaaa"
    docker.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{docker_log}"\n'
        f'if [ "$1" = "compose" ]; then echo "{api_container_id}"; exit 0; fi\n'
        'if [ "$1" = "exec" ]; then echo "existing:7"; exit 0; fi\n'
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export COMPOSE_PROJECT_NAME=legacy-project
        source "{UPDATE_SH}"
        INSTALL_DIR="{tmp_path}"
        DOCKER_DIR="{docker_dir}"
        COMPOSE_FILE="docker-compose.yml"
        run_faq_sqlite_migration
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert "SQLite already has 7 FAQs" in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert (
        "compose --project-name legacy-project -f docker-compose.yml "
        "ps --status running -q api"
    ) in docker_calls
    assert f"exec {api_container_id} python -c" in docker_calls
    assert "app.scripts.migrate_to_sqlite" not in docker_calls


def test_update_migration_guard_preserves_empty_authoritative_faq_store(
    tmp_path: Path,
) -> None:
    migration_script = tmp_path / "api" / "app" / "scripts" / "migrate_to_sqlite.py"
    migration_script.parent.mkdir(parents=True)
    migration_script.write_text("# synthetic migration marker\n", encoding="utf-8")
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fakebin / "docker"
    api_container_id = "aaaaaaaaaaaa"
    docker.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{docker_log}"\n'
        f'if [ "$1" = "compose" ]; then echo "{api_container_id}"; exit 0; fi\n'
        'if [ "$1" = "exec" ]; then echo "existing:0"; exit 0; fi\n'
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export COMPOSE_PROJECT_NAME=legacy-project
        source "{UPDATE_SH}"
        INSTALL_DIR="{tmp_path}"
        DOCKER_DIR="{docker_dir}"
        COMPOSE_FILE="docker-compose.yml"
        run_faq_sqlite_migration
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode == 0, result.stderr
    assert "SQLite already has 0 FAQs" in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert "app.scripts.migrate_to_sqlite" not in docker_calls


def test_update_migration_guard_aborts_when_faq_count_probe_fails(
    tmp_path: Path,
) -> None:
    migration_script = tmp_path / "api" / "app" / "scripts" / "migrate_to_sqlite.py"
    migration_script.parent.mkdir(parents=True)
    migration_script.write_text("# synthetic migration marker\n", encoding="utf-8")
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fakebin / "docker"
    api_container_id = "bbbbbbbbbbbb"
    docker.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{docker_log}"\n'
        f'if [ "$1" = "compose" ]; then echo "{api_container_id}"; exit 0; fi\n'
        'if [ "$1" = "exec" ]; then exit 70; fi\n'
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export COMPOSE_PROJECT_NAME=legacy-project
        source "{UPDATE_SH}"
        INSTALL_DIR="{tmp_path}"
        DOCKER_DIR="{docker_dir}"
        COMPOSE_FILE="docker-compose.yml"
        run_faq_sqlite_migration
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode != 0
    assert "Could not verify the authoritative FAQ store" in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert f"exec {api_container_id} python -c" in docker_calls
    assert "app.scripts.migrate_to_sqlite" not in docker_calls


def test_update_migration_guard_refuses_stopped_api_without_starting_it(
    tmp_path: Path,
) -> None:
    migration_script = tmp_path / "api" / "app" / "scripts" / "migrate_to_sqlite.py"
    migration_script.parent.mkdir(parents=True)
    migration_script.write_text("# synthetic migration marker\n", encoding="utf-8")
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{docker_log}"\n'
        'if [ "$1" = "compose" ]; then exit 0; fi\n'
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export COMPOSE_PROJECT_NAME=legacy-project
        source "{UPDATE_SH}"
        INSTALL_DIR="{tmp_path}"
        DOCKER_DIR="{docker_dir}"
        COMPOSE_FILE="docker-compose.yml"
        run_faq_sqlite_migration
        """,
        cwd=REPO_ROOT,
        env={"BISQ_SUPPORT_INSTALL_DIR": str(tmp_path)},
    )

    assert result.returncode != 0
    assert "refusing to start a stale image" in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8")
    assert "ps --status running -q api" in docker_calls
    assert "up -d api" not in docker_calls
    assert "exec " not in docker_calls


def test_update_migration_logs_use_unique_private_temp_files() -> None:
    update_script = UPDATE_SH.read_text(encoding="utf-8")

    assert 'mktemp "/tmp/bisq-support-migration-dryrun.XXXXXXXX"' in update_script
    assert 'mktemp "/tmp/bisq-support-migration.XXXXXXXX"' in update_script
    assert 'tee "$dryrun_log"' in update_script
    assert 'tee "$migration_log"' in update_script
    assert "tee /tmp/migration" not in update_script
    assert 'rm -f -- "$dryrun_log" "$migration_log"' in update_script


def test_source_deploy_paths_imports_custom_secrets_directory(tmp_path: Path) -> None:
    deploy_env = tmp_path / "deploy.env"
    secrets_dir = tmp_path / "custom-secrets"
    deploy_env.write_text(f"BISQ_SUPPORT_SECRETS_DIR={secrets_dir}\n", encoding="utf-8")

    result = run_bash(
        f"""
        source "{COMMON_SH}"
        source_deploy_paths "{deploy_env}"
        printf '%s' "$BISQ_SUPPORT_SECRETS_DIR"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith(str(secrets_dir))


def test_source_deploy_paths_imports_compose_override(tmp_path: Path) -> None:
    deploy_env = tmp_path / "deploy.env"
    deploy_env.write_text(
        "BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml\n",
        encoding="utf-8",
    )

    result = run_bash(
        f"""
        source "{COMMON_SH}"
        source_deploy_paths "{deploy_env}"
        printf '%s' "$BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("docker-compose.tls.yml")


def _write_recording_docker(
    fakebin: Path, log_path: Path, *, relay_has_build: bool = False
) -> None:
    relay_config = (
        '{"services":{"matrix-alert-relay":{"build":{"context":".."}}}}'
        if relay_has_build
        else '{"services":{"matrix-alert-relay":{"image":"relay:local"}}}'
    )
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        f'printf \'%s\\n\' "$*" >> "{log_path}"\n'
        'if [[ "$*" == *"config --format json"* ]]; then\n'
        f"  printf '%s\\n' '{relay_config}'\n"
        "fi\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)


def test_compose_helper_preserves_base_only_behavior(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        unset BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE
        source "{COMMON_SH}"
        run_docker_compose "{docker_dir}" docker-compose.yml ps api
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert docker_log.read_text(encoding="utf-8") == (
        "compose -f docker-compose.yml ps api\n"
    )


def _write_compose_identity_docker(
    fakebin: Path, log_path: Path, docker_dir: Path, data_dir: Path
) -> None:
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f'printf \'%s\\n\' "$*" >> "{log_path}"\n'
        "api_id=0123456789ab\n"
        "qdrant_id=abcdef012345\n"
        'canonical_ids="${FAKE_CANONICAL_IDS-$api_id\\\\n$qdrant_id}"\n'
        'project_ids="${FAKE_PROJECT_IDS-$canonical_ids}"\n'
        'working_ids="${FAKE_WORKING_IDS-$canonical_ids}"\n'
        'if [ "$1" = ps ]; then\n'
        '  if [[ "$*" == *"com.docker.compose.service=api"* ]]; then\n'
        '    ids="${FAKE_API_IDS-$api_id}"\n'
        '  elif [[ "$*" == *"com.docker.compose.project="* ]]; then\n'
        '    ids="$project_ids"\n'
        "  else\n"
        '    ids="$working_ids"\n'
        "  fi\n"
        '  [ -z "$ids" ] || printf \'%b\\n\' "$ids"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = compose ]; then\n'
        '  if [[ "$*" == *"ps --all --orphans=false --no-trunc -q"* ]]; then\n'
        '    [ -z "$canonical_ids" ] || printf \'%b\\n\' "$canonical_ids"\n'
        '  elif [[ "$*" == *"ps api"* ]]; then\n'
        "    printf '%s\\n' \"$api_id\"\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = inspect ] && [ "$2" = --format ]; then\n'
        '  container_id="${4:-}"\n'
        '  state="${FAKE_API_STATE:-running}"\n'
        f'  working_dir="${{FAKE_WORKING_DIR:-{docker_dir}}}"\n'
        '  if [[ "$3" == *"com.docker.compose.container-number"* ]]; then\n'
        "    service=api\n"
        '    [ "$container_id" = "$qdrant_id" ] && service=qdrant\n'
        '    printf \'legacy-project|%s|%s|1|False|%s\\n\' "$working_dir" "$service" "$state"\n'
        "    exit 0\n"
        "  fi\n"
        '  if [[ "$3" == *"com.docker.compose.oneoff"* ]] && [[ "$3" == *".State.Status"* ]]; then\n'
        '    printf \'legacy-project|%s|api|False|%s\\n\' "$working_dir" "$state"\n'
        "    exit 0\n"
        "  fi\n"
        '  if [ "$3" = \'{{index .Config.Labels "com.docker.compose.project"}}\' ]; then\n'
        "    printf '%s\\n' legacy-project\n"
        "    exit 0\n"
        "  fi\n"
        '  if [[ "$3" == *".Config.Env"* ]]; then\n'
        "    printf '%b\\n' \"${FAKE_DATA_DIR_ENTRY-DATA_DIR=/data}\"\n"
        "    exit 0\n"
        "  fi\n"
        '  if [[ "$3" == *\'.Destination "/data"\'* ]]; then\n'
        f'    source="${{FAKE_DATA_SOURCE:-{data_dir}}}"\n'
        "    printf 'bind|%s\\n' \"$source\"\n"
        '    if [ "${FAKE_DUPLICATE_DATA_MOUNT:-false}" = true ]; then printf \'bind|%s\\n\' "$source"; fi\n'
        "    exit 0\n"
        "  fi\n"
        '  if [[ "$3" == *"com.docker.compose.service"* ]] && [[ "$3" == *"volume|%s"* ]]; then\n'
        '    if [ "$container_id" = "$api_id" ]; then\n'
        f"      printf 'api|/data|bind|%s\\n' \"${{FAKE_DATA_SOURCE:-{data_dir}}}\"\n"
        f"      if [ \"${{FAKE_LEGACY_SOURCE_BIND:-false}}\" = true ]; then printf 'api|/app/app|bind|%s\\n' '{data_dir.parent}'; fi\n"
        '    elif [ "$container_id" = "$qdrant_id" ]; then\n'
        "      printf 'qdrant|/qdrant/storage|volume|%s\\n' \"${FAKE_VOLUME_NAME:-legacy-qdrant-data}\"\n"
        "      if [ \"${FAKE_DUPLICATE_VOLUME_MOUNT:-false}\" = true ]; then printf 'qdrant|/qdrant/storage|volume|other-data\\n'; fi\n"
        "    fi\n"
        "    exit 0\n"
        "  fi\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)


def test_compose_project_pin_reuses_stopped_stack_and_data(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        unset COMPOSE_PROJECT_NAME BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE
        export FAKE_API_STATE=exited
        export FAKE_LEGACY_SOURCE_BIND=true
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        validate_existing_api_data_identity \
            "{docker_dir}" docker-compose.yml "{data_dir}" existing
        capture_compose_persistent_mounts "{docker_dir}" docker-compose.yml
        run_docker_compose "{docker_dir}" docker-compose.yml ps api
        printf 'project=%s\n' "$COMPOSE_PROJECT_NAME"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "project=legacy-project" in result.stdout
    assert f"api|/data|bind|{data_dir}" in result.stdout
    assert "qdrant|/qdrant/storage|volume|legacy-qdrant-data" in result.stdout
    assert "|/app/app|bind|" not in result.stdout
    docker_calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert docker_calls[-1] == (
        "compose --project-name legacy-project -f docker-compose.yml ps api"
    )


def test_compose_project_pin_rejects_ambiguous_existing_stack(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = ps ]; then\n'
        "  printf '%s\\n' 0123456789ab abcdef012345\n"
        "  exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        unset COMPOSE_PROJECT_NAME
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "Exactly one API container" in result.stderr


def test_compose_project_running_mode_rejects_stopped_api(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export FAKE_API_STATE=exited
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml running
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "API container is not running" in result.stderr


def test_persisted_project_fallback_rejects_foreign_project_collision(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / ".env").write_text(
        "COMPOSE_PROJECT_NAME=legacy-project\n", encoding="utf-8"
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export FAKE_API_IDS=''
        export FAKE_CANONICAL_IDS=''
        export FAKE_WORKING_IDS=''
        export FAKE_PROJECT_IDS=111111111111
        source "{COMMON_SH}"
        setup_colors
        pin_configured_or_existing_compose_project \
            "{docker_dir}" docker-compose.yml
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "occupied by a different working directory" in result.stderr


def test_compose_project_pin_rejects_stale_project_container(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export FAKE_PROJECT_IDS='0123456789ab\nabcdef012345\n111111111111'
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "ambiguous or stale containers" in result.stderr


def test_api_data_identity_rejects_duplicate_setting_and_mount(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    duplicate_env = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export FAKE_DATA_DIR_ENTRY='DATA_DIR=/data\nDATA_DIR=/data'
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        validate_existing_api_data_identity \
            "{docker_dir}" docker-compose.yml "{data_dir}" existing
        """,
        cwd=REPO_ROOT,
    )
    duplicate_mount = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export FAKE_DUPLICATE_DATA_MOUNT=true
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        validate_existing_api_data_identity \
            "{docker_dir}" docker-compose.yml "{data_dir}" existing
        """,
        cwd=REPO_ROOT,
    )

    assert duplicate_env.returncode != 0
    assert "exactly DATA_DIR=/data" in duplicate_env.stderr
    assert duplicate_mount.returncode != 0
    assert "data mount has invalid identity" in duplicate_mount.stderr


def test_compose_mount_capture_rejects_duplicate_logical_mount(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export FAKE_DUPLICATE_VOLUME_MOUNT=true
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        capture_compose_persistent_mounts "{docker_dir}" docker-compose.yml
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "mount identity is duplicated" in result.stderr


def test_persisted_compose_project_survives_container_removal(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / ".env").write_text("OPENAI_MODEL=test-model\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{COMMON_SH}"
        setup_colors
        pin_configured_or_existing_compose_project \
            "{docker_dir}" docker-compose.yml
        unset COMPOSE_PROJECT_NAME
        export FAKE_API_IDS=''
        export FAKE_CANONICAL_IDS=''
        export FAKE_PROJECT_IDS=''
        export FAKE_WORKING_IDS=''
        pin_configured_or_existing_compose_project \
            "{docker_dir}" docker-compose.yml
        printf '%s' "$COMPOSE_PROJECT_NAME"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.endswith("legacy-project")
    env_text = (docker_dir / ".env").read_text(encoding="utf-8")
    assert env_text.count("COMPOSE_PROJECT_NAME=legacy-project") == 1


def test_compose_project_pin_rejects_export_form_persisted_override(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    data_dir = tmp_path / "api" / "data"
    docker_dir.mkdir()
    data_dir.mkdir(parents=True)
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / ".env").write_text(
        "export COMPOSE_PROJECT_NAME=other-project\n", encoding="utf-8"
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_compose_identity_docker(fakebin, docker_log, docker_dir, data_dir)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{COMMON_SH}"
        setup_colors
        pin_existing_compose_project "{docker_dir}" docker-compose.yml existing
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "one canonical assignment" in result.stderr


def test_compose_helper_applies_persisted_tls_override(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / "docker-compose.tls.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml
        source "{COMMON_SH}"
        run_docker_compose "{docker_dir}" docker-compose.yml up -d nginx
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert docker_log.read_text(encoding="utf-8") == (
        "compose -f docker-compose.yml -f docker-compose.tls.yml up -d nginx\n"
    )


def test_compose_helper_rejects_unreviewed_override(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=unreviewed.yml
        source "{COMMON_SH}"
        run_docker_compose "{docker_dir}" docker-compose.yml up -d nginx
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "must be empty or docker-compose.tls.yml" in result.stderr
    assert not docker_log.exists()


def test_compose_helper_fails_closed_when_tls_override_is_missing(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml
        source "{COMMON_SH}"
        run_docker_compose "{docker_dir}" docker-compose.yml up -d nginx
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "unavailable in the Docker directory" in result.stderr
    assert not docker_log.exists()


def test_compose_helper_rejects_stale_tls_inputs_without_override(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / ".env").write_text(
        "\n".join(
            (
                "NGINX_HTTP_BIND_ADDRESS=0.0.0.0",
                "NGINX_TLS_CERTIFICATE_FILENAME=certificate.pem",
                "NGINX_TLS_REDIRECT_HTTP=true",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        unset BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE
        source "{COMMON_SH}"
        run_docker_compose "{docker_dir}" docker-compose.yml up -d nginx
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "conflicts with clearnet TLS settings" in result.stderr
    assert not docker_log.exists()


def test_compose_helper_rejects_export_form_exposure_override(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / ".env").write_text(
        "NGINX_HTTP_BIND_ADDRESS=127.0.0.1\n"
        "export NGINX_HTTP_BIND_ADDRESS=0.0.0.0\n",
        encoding="utf-8",
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        unset BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE NGINX_HTTP_BIND_ADDRESS
        source "{COMMON_SH}"
        run_docker_compose "{docker_dir}" docker-compose.yml up -d nginx
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "one canonical assignment" in result.stderr
    assert not docker_log.exists()


def test_production_compose_actions_use_persisted_override_helper() -> None:
    scripts = (
        DOCKER_UTILS_SH,
        UPDATE_SH,
        DEPLOY_SH,
        START_SH,
        STOP_SH,
        CHECK_HEALTH_SH,
        ROLLBACK_TOR_SH,
        VERIFY_FEEDBACK_SH,
    )

    for script in scripts:
        for line in script.read_text(encoding="utf-8").splitlines():
            if "docker compose" not in line:
                continue
            stripped = line.strip()
            allowed = (
                stripped.startswith("#")
                or "docker compose version" in line
                or stripped.startswith(("log_", "echo"))
            )
            assert allowed, f"{script.name} bypasses run_docker_compose: {stripped}"


def _write_deploy_health_docker(
    fakebin: Path,
    log_path: Path,
    *,
    completion_state: str = "exited 0",
) -> None:
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        f'printf \'%s\\n\' "$*" >> "{log_path}"\n'
        'if [ "$1" = "inspect" ]; then\n'
        f"  printf '%s\\n' \"{completion_state}\"\n"
        "  exit 0\n"
        "fi\n"
        'case "$*" in\n'
        '  *"config --services")\n'
        "    printf '%s\\n' scheduler-secret-init api alertmanager-secret-init web\n"
        "    ;;\n"
        '  *"ps --all -q scheduler-secret-init")\n'
        "    echo scheduler-init-container\n"
        "    ;;\n"
        '  *"ps --all -q alertmanager-secret-init")\n'
        "    echo alertmanager-init-container\n"
        "    ;;\n"
        '  *"ps --filter health=healthy -q api web")\n'
        "    printf '%s\\n' api-container web-container\n"
        "    ;;\n"
        "  *)\n"
        "    exit 64\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)


def test_deploy_health_excludes_successful_one_shots_from_denominator(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / "docker-compose.tls.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_deploy_health_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        export BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml
        source "{DOCKER_UTILS_SH}"
        wait_for_compose_health \
            "{docker_dir}" \
            docker-compose.yml \
            10 \
            1 \
            scheduler-secret-init \
            alertmanager-secret-init
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "All 2 long-running Docker services are healthy" in result.stdout
    commands = docker_log.read_text(encoding="utf-8").splitlines()
    compose_commands = [
        command for command in commands if command.startswith("compose ")
    ]
    assert compose_commands
    assert all(
        "-f docker-compose.yml -f docker-compose.tls.yml" in command
        for command in compose_commands
    )
    health_command = next(
        command for command in commands if "ps --filter health=healthy" in command
    )
    assert health_command.endswith("-q api web")
    assert "secret-init" not in health_command


def test_deploy_health_rejects_failed_one_shot(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_deploy_health_docker(fakebin, docker_log, completion_state="exited 17")

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        wait_for_compose_health \
            "{docker_dir}" \
            docker-compose.yml \
            10 \
            1 \
            scheduler-secret-init \
            alertmanager-secret-init
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "scheduler-secret-init did not complete successfully" in result.stdout
    commands = docker_log.read_text(encoding="utf-8").splitlines()
    assert not any("ps --filter health=healthy" in command for command in commands)


def test_deploy_invokes_health_check_for_both_secret_initializers() -> None:
    deploy_script = DEPLOY_SH.read_text(encoding="utf-8")

    health_call = re.search(
        r"wait_for_compose_health .*?scheduler-secret-init .*?alertmanager-secret-init",
        deploy_script.replace("\\\n", " "),
    )
    assert health_call is not None


def test_full_rebuild_builds_api_image_once_and_recreates_relay(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        rebuild_services "{docker_dir}" docker-compose.yml
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    commands = docker_log.read_text(encoding="utf-8").splitlines()
    build_command = next(command for command in commands if " build " in command)

    assert build_command.endswith(" api web bisq2-api")
    assert "matrix-alert-relay" not in build_command
    assert any(
        command.endswith("stop api matrix-alert-relay web bisq2-api")
        for command in commands
    )
    assert any(
        command.endswith("up -d qdrant api matrix-alert-relay web bisq2-api")
        for command in commands
    )


def test_full_rebuild_builds_relay_for_legacy_compose_topology(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    _write_recording_docker(fakebin, docker_log, relay_has_build=True)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        rebuild_services "{docker_dir}" docker-compose.yml
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    commands = docker_log.read_text(encoding="utf-8").splitlines()
    build_command = next(command for command in commands if " build " in command)

    assert build_command.endswith("api web bisq2-api matrix-alert-relay")


def test_selective_api_update_recreates_shared_image_relay() -> None:
    update_script = UPDATE_SH.read_text(encoding="utf-8")

    assert (
        'build --build-arg BUILD_ID="${BUILD_ID:-bisq-support-build}" api'
        in update_script
    )
    assert "up -d --no-deps api matrix-alert-relay" in update_script
    assert 'wait_for_healthy "matrix-alert-relay" 60' in update_script


def commit_file(repo: Path, relative_path: str, content: str, message: str) -> str:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    run_git(repo, "add", relative_path)
    run_git(repo, "commit", "-m", message)
    return run_git(repo, "rev-parse", "HEAD").stdout.strip()


def run_git_update_detector(function_name: str, repo: Path, prev_head: str) -> int:
    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        {function_name} "{repo}" "{prev_head}"
        """,
        cwd=REPO_ROOT,
    )
    return result.returncode


def test_source_env_file_exports_variables_to_child_process(tmp_path: Path) -> None:
    env_file = tmp_path / "deploy.env"
    env_file.write_text("EXPORTED_FROM_DEPLOY=visible\n", encoding="utf-8")

    result = run_bash(
        f"""
        source "{COMMON_SH}"
        source_env_file "{env_file}"
        env | grep '^EXPORTED_FROM_DEPLOY=visible$'
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr


def test_preserve_production_data_command_substitution_returns_backup_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bisq-support-test"
    data_dir = repo / "api" / "data"
    data_dir.mkdir(parents=True)
    with sqlite3.connect(data_dir / "faqs.db") as connection:
        connection.execute("CREATE TABLE faqs (question TEXT NOT NULL)")
        connection.execute("INSERT INTO faqs (question) VALUES ('fixture')")

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        realpath() {{
            if [ "$1" = "-e" ]; then
                command realpath "$2"
            else
                command realpath "$@"
            fi
        }}
        flock() {{ return 0; }}
        backup_dir=$(preserve_production_data "{repo}")
        printf '%s' "$backup_dir"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    output_lines = result.stdout.splitlines()
    assert len(output_lines) == 1
    backup_dir = Path(output_lines[0])
    assert backup_dir.is_dir()
    assert backup_dir.parent == data_dir
    with sqlite3.connect(backup_dir / "faqs.db") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            connection.execute("SELECT question FROM faqs").fetchone()[0] == "fixture"
        )
    assert "Backing up production data files" in result.stderr
    assert "Backed up 1 production data file(s)" in result.stderr


def test_preserve_production_data_does_not_skip_authoritative_file_over_50_mb(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bisq-support-test"
    data_dir = repo / "api" / "data"
    data_dir.mkdir(parents=True)
    source = data_dir / "conversations.jsonl"
    source.write_bytes(b"")
    with source.open("r+b") as stream:
        stream.truncate(51 * 1024 * 1024)

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        realpath() {{
            if [ "$1" = "-e" ]; then
                command realpath "$2"
            else
                command realpath "$@"
            fi
        }}
        flock() {{ return 0; }}
        preserve_production_data "{repo}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    backup_dir = Path(result.stdout.splitlines()[-1])
    assert (backup_dir / source.name).stat().st_size == source.stat().st_size
    assert "Skipping oversized file" not in result.stderr


def test_backup_gpg_recipient_rejects_non_fingerprint_before_keyring_lookup(
    tmp_path: Path,
) -> None:
    gpg_log = tmp_path / "gpg.log"

    result = run_bash(
        f"""
        source "{BACKUP_SH}"
        gpg() {{ printf '%s\n' "$*" >> "{gpg_log}"; }}
        RECIPIENT=0123456789ABCDEF
        validate_gpg_recipient_fingerprint
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert "full 40- or 64-character fingerprint" in result.stdout + result.stderr
    assert not gpg_log.exists()


def test_backup_gpg_recipient_requires_one_exact_keyring_match(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789ABCDEF0123456789ABCDEF01234567"
    other_fingerprint = "FEDCBA9876543210FEDCBA9876543210FEDCBA98"

    missing = run_bash(
        f"""
        source "{BACKUP_SH}"
        gpg() {{ printf 'fpr:::::::::{other_fingerprint}:\n'; }}
        RECIPIENT={fingerprint}
        validate_gpg_recipient_fingerprint
        """,
        cwd=REPO_ROOT,
    )
    ambiguous = run_bash(
        f"""
        source "{BACKUP_SH}"
        gpg() {{
            printf 'fpr:::::::::{fingerprint}:\n'
            printf 'fpr:::::::::{fingerprint}:\n'
        }}
        RECIPIENT={fingerprint}
        validate_gpg_recipient_fingerprint
        """,
        cwd=REPO_ROOT,
    )

    assert missing.returncode == 2
    assert "no exact public-key match" in missing.stdout + missing.stderr
    assert ambiguous.returncode == 2
    assert "resolves ambiguously" in ambiguous.stdout + ambiguous.stderr


def test_backup_gpg_recipient_resolves_and_normalizes_exact_fingerprint(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789ABCDEF0123456789ABCDEF01234567"
    gpg_log = tmp_path / "gpg.log"

    result = run_bash(
        f"""
        source "{BACKUP_SH}"
        gpg() {{
            printf '%s\n' "$*" > "{gpg_log}"
            printf 'fpr:::::::::{fingerprint}:\n'
        }}
        RECIPIENT={fingerprint.lower()}
        validate_gpg_recipient_fingerprint
        printf '%s' "$RECIPIENT"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == fingerprint
    assert gpg_log.read_text(encoding="utf-8").strip() == (
        "--batch --with-colons --fingerprint --list-keys -- " + fingerprint
    )


def test_backup_gpg_encryption_keeps_atomic_publish_without_trust_override(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789ABCDEF0123456789ABCDEF01234567"
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    gpg_log = tmp_path / "gpg.log"
    staging.mkdir()
    target.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")

    result = run_bash(
        f"""
        source "{BACKUP_SH}"
        gpg() {{
            printf '%s\n' "$*" > "{gpg_log}"
            local output=''
            while [ "$#" -gt 0 ]; do
                if [ "$1" = --output ]; then
                    output="$2"
                    shift 2
                else
                    shift
                fi
            done
            cat > "$output"
        }}
        revalidate_backup_target() {{ return 0; }}
        STAGING_DIR="{staging}"
        TARGET_DIR="{target}"
        ENCRYPTION=gpg
        RECIPIENT={fingerprint}
        encrypt_backup 20260101T000000Z
        """,
        cwd=REPO_ROOT,
    )

    completed = target / "bisq-support-backup-20260101T000000Z.tar.gz.gpg"
    gpg_args = gpg_log.read_text(encoding="utf-8").strip()
    assert result.returncode == 0, result.stderr
    assert completed.is_file()
    assert completed.stat().st_mode & 0o777 == 0o600
    assert not list(target.glob(".*.partial.*"))
    assert "--trust-model" not in gpg_args
    assert f"--recipient {fingerprint}" in gpg_args
    assert re.search(r"--output .*/\.bisq-support-backup-.*\.partial\.\d+", gpg_args)


def test_preserve_production_data_command_substitution_returns_empty_without_data(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bisq-support-test"
    (repo / "api" / "data").mkdir(parents=True)

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        realpath() {{
            if [ "$1" = "-e" ]; then
                command realpath "$2"
            else
                command realpath "$@"
            fi
        }}
        flock() {{ return 0; }}
        backup_dir=$(preserve_production_data "{repo}")
        printf '%s' "$backup_dir"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "Backing up production data files" in result.stderr
    assert "No production data files found to backup" in result.stderr
    assert not list((repo / "api" / "data").glob(".backup_*"))


def test_release_update_never_copies_live_runtime_data(tmp_path: Path) -> None:
    repo = tmp_path / "bisq-support-test"
    data_dir = repo / "api" / "data"
    data_dir.mkdir(parents=True)
    init_git_repo(repo)
    tracked = repo / "tracked.txt"
    tracked.write_text("reviewed\n", encoding="utf-8")
    run_git(repo, "add", "tracked.txt")
    run_git(repo, "commit", "-m", "base")
    runtime_file = data_dir / "conversations.jsonl"
    runtime_file.write_text("live-write\n", encoding="utf-8")
    copy_marker = tmp_path / "runtime-copy-called"

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        ensure_repository_update_safe() {{ return 0; }}
        ensure_release_source_tree_clean() {{ return 0; }}
        check_local_changes() {{ return 1; }}
        fetch_remote() {{ return 0; }}
        reset_to_remote() {{ return 0; }}
        ensure_runtime_data_git_boundary() {{ return 0; }}
        preserve_production_data() {{ touch "{copy_marker}"; return 0; }}
        restore_production_data() {{ touch "{copy_marker}"; return 0; }}
        set +e
        update_repository "{repo}" origin main false
        status=$?
        set -e
        [ "$status" -eq 2 ]
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert runtime_file.read_text(encoding="utf-8") == "live-write\n"
    assert not copy_marker.exists()


def test_runtime_data_boundary_rejects_tracked_database(tmp_path: Path) -> None:
    repo = tmp_path / "bisq-support-test"
    data_dir = repo / "api" / "data"
    data_dir.mkdir(parents=True)
    init_git_repo(repo)
    database = data_dir / "faqs.db"
    database.write_bytes(b"fixture")
    run_git(repo, "add", "-f", "api/data/faqs.db")
    run_git(repo, "commit", "-m", "track unsafe runtime data")

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        ensure_runtime_data_git_boundary "{repo}" HEAD
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "must not track production runtime data" in result.stdout


def test_runtime_data_boundary_rejects_data_root_replacement(tmp_path: Path) -> None:
    for replacement_type in ("file", "symlink"):
        repo = tmp_path / replacement_type
        data_dir = repo / "api" / "data"
        data_dir.mkdir(parents=True)
        init_git_repo(repo)
        (repo / ".gitignore").write_text("api/data/faqs.db\n", encoding="utf-8")
        (data_dir / "keep.txt").write_text("reviewed\n", encoding="utf-8")
        run_git(repo, "add", ".gitignore", "api/data/keep.txt")
        run_git(repo, "commit", "-m", "base")
        base_ref = run_git(repo, "rev-parse", "HEAD").stdout.strip()

        run_git(repo, "rm", "-r", "api/data")
        (repo / "api").mkdir(exist_ok=True)
        if replacement_type == "file":
            data_dir.write_text("replacement\n", encoding="utf-8")
        else:
            data_dir.symlink_to("replacement")
        run_git(repo, "add", "-f", "api/data")
        run_git(repo, "commit", "-m", "replace data root")
        target_ref = run_git(repo, "rev-parse", "HEAD").stdout.strip()

        run_git(repo, "reset", "--hard", base_ref)
        database = data_dir / "faqs.db"
        database.write_bytes(b"live database")
        result = run_bash(
            f"""
            source "{GIT_UTILS_SH}"
            boundary_status=0
            ensure_runtime_data_git_boundary "{repo}" "{target_ref}" || boundary_status=$?
            if [ "$boundary_status" -eq 0 ]; then
                git -C "{repo}" reset --hard "{target_ref}"
            fi
            exit "$boundary_status"
            """,
            cwd=REPO_ROOT,
        )

        assert result.returncode != 0
        assert database.read_bytes() == b"live database"


def test_runtime_data_boundary_rejects_content_below_database(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bisq-support-test"
    data_dir = repo / "api" / "data"
    data_dir.mkdir(parents=True)
    init_git_repo(repo)
    (repo / ".gitignore").write_text("api/data/faqs.db\n", encoding="utf-8")
    (data_dir / "keep.txt").write_text("reviewed\n", encoding="utf-8")
    run_git(repo, "add", ".gitignore", "api/data/keep.txt")
    run_git(repo, "commit", "-m", "base")
    base_ref = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    database_dir = data_dir / "faqs.db"
    database_dir.mkdir()
    (database_dir / "child").write_text("replacement\n", encoding="utf-8")
    run_git(repo, "add", "-f", "api/data/faqs.db/child")
    run_git(repo, "commit", "-m", "nest content below database")
    target_ref = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    run_git(repo, "reset", "--hard", base_ref)
    database = data_dir / "faqs.db"
    database.write_bytes(b"live database")
    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        boundary_status=0
        ensure_runtime_data_git_boundary "{repo}" "{target_ref}" || boundary_status=$?
        if [ "$boundary_status" -eq 0 ]; then
            git -C "{repo}" reset --hard "{target_ref}"
        fi
        exit "$boundary_status"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert database.read_bytes() == b"live database"


def test_update_repository_aborts_before_git_work_when_preservation_fails(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bisq-support-test"
    repo.mkdir()
    mutation_marker = tmp_path / "git-work-started"

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        validate_git_repo() {{ return 0; }}
        ensure_repository_update_safe() {{ return 0; }}
        preserve_production_data() {{ return 1; }}
        check_local_changes() {{ touch "{mutation_marker}"; return 1; }}
        fetch_remote() {{ touch "{mutation_marker}"; return 0; }}
        if update_repository "{repo}" origin main; then
            exit 99
        fi
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert not mutation_marker.exists()
    assert "Failed to preserve production data" in result.stdout + result.stderr


def test_release_update_rejects_patch_before_stash_or_git_work(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bisq-support-test"
    repo.mkdir()
    init_git_repo(repo)
    tracked = repo / "tracked.txt"
    tracked.write_text("reviewed\n", encoding="utf-8")
    run_git(repo, "add", "tracked.txt")
    run_git(repo, "commit", "-m", "base")
    tracked.write_text("local patch\n", encoding="utf-8")
    mutation_marker = tmp_path / "git-work-started"

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        ensure_repository_update_safe() {{ return 0; }}
        preserve_production_data() {{ touch "{mutation_marker}"; return 0; }}
        fetch_remote() {{ touch "{mutation_marker}"; return 0; }}
        if update_repository "{repo}" origin main false; then
            exit 99
        fi
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert tracked.read_text(encoding="utf-8") == "local patch\n"
    assert not mutation_marker.exists()
    assert run_git(repo, "stash", "list").stdout == ""
    assert "Release updates require a clean source tree" in result.stdout


def test_validate_runtime_configuration_requires_trust_monitor_secret() -> None:
    result = run_bash(
        f"""
        source "{COMMON_SH}"
        export TRUST_MONITOR_ENABLED=true
        unset TRUST_MONITOR_ACTOR_KEY_SECRET
        validate_runtime_configuration
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "TRUST_MONITOR_ACTOR_KEY_SECRET is required" in result.stdout


def test_ensure_repository_update_safe_rejects_unmerged_paths(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    default_branch = run_git(tmp_path, "branch", "--show-current").stdout.strip()
    conflicted = tmp_path / "conflicted.txt"
    conflicted.write_text("base\n", encoding="utf-8")
    run_git(tmp_path, "add", "conflicted.txt")
    run_git(tmp_path, "commit", "-m", "base")

    run_git(tmp_path, "checkout", "-b", "side")
    conflicted.write_text("side\n", encoding="utf-8")
    run_git(tmp_path, "commit", "-am", "side")

    run_git(tmp_path, "checkout", default_branch)
    conflicted.write_text("main\n", encoding="utf-8")
    run_git(tmp_path, "commit", "-am", "main")

    merge = run_git(tmp_path, "merge", "side", check=False)
    assert merge.returncode != 0

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        ensure_repository_update_safe "{tmp_path}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "Repository has unmerged paths" in result.stdout


def test_release_source_tree_guard_rejects_local_build_inputs(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("reviewed\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("runtime/\n", encoding="utf-8")
    run_git(tmp_path, "add", "tracked.txt", ".gitignore")
    run_git(tmp_path, "commit", "-m", "base")

    clean = run_bash(
        f'source "{GIT_UTILS_SH}"; ensure_release_source_tree_clean "{tmp_path}"',
        cwd=REPO_ROOT,
    )
    assert clean.returncode == 0, clean.stderr

    tracked.write_text("local change\n", encoding="utf-8")
    changed = run_bash(
        f'source "{GIT_UTILS_SH}"; ensure_release_source_tree_clean "{tmp_path}"',
        cwd=REPO_ROOT,
    )
    assert changed.returncode == 1
    assert "tracked local changes" in changed.stdout

    run_git(tmp_path, "restore", "tracked.txt")
    (tmp_path / "untracked.txt").write_text("local input\n", encoding="utf-8")
    untracked = run_bash(
        f'source "{GIT_UTILS_SH}"; ensure_release_source_tree_clean "{tmp_path}"',
        cwd=REPO_ROOT,
    )
    assert untracked.returncode == 1
    assert "untracked local inputs" in untracked.stdout

    (tmp_path / "untracked.txt").unlink()
    ignored_runtime = tmp_path / "runtime" / "state.db"
    ignored_runtime.parent.mkdir()
    ignored_runtime.write_text("runtime data\n", encoding="utf-8")
    ignored = run_bash(
        f'source "{GIT_UTILS_SH}"; ensure_release_source_tree_clean "{tmp_path}"',
        cwd=REPO_ROOT,
    )
    assert ignored.returncode == 0, ignored.stderr


def test_stash_changes_returns_noop_when_no_new_stash_is_created(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("clean\n", encoding="utf-8")
    run_git(tmp_path, "add", "tracked.txt")
    run_git(tmp_path, "commit", "-m", "base")

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        stash_changes "{tmp_path}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert "did not create a new stash entry" in result.stdout


def test_api_requirements_change_uses_api_rebuild_not_full_rebuild(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path)
    prev_head = commit_file(tmp_path, "README.md", "base\n", "base")
    commit_file(
        tmp_path,
        "api/requirements.txt",
        "langsmith==0.4.8\n",
        "change api requirements",
    )

    assert run_git_update_detector("needs_rebuild", tmp_path, prev_head) == 1
    assert run_git_update_detector("needs_api_rebuild", tmp_path, prev_head) == 0


def test_web_package_change_uses_web_rebuild_not_full_rebuild(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path)
    prev_head = commit_file(tmp_path, "README.md", "base\n", "base")
    commit_file(
        tmp_path,
        "web/package.json",
        '{"scripts":{"test":"jest"}}\n',
        "change web package",
    )

    assert run_git_update_detector("needs_rebuild", tmp_path, prev_head) == 1
    assert run_git_update_detector("needs_web_rebuild", tmp_path, prev_head) == 0


def test_compose_change_requires_full_rebuild(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    prev_head = commit_file(tmp_path, "README.md", "base\n", "base")
    commit_file(
        tmp_path,
        "docker/docker-compose.yml",
        "services: {}\n",
        "change compose",
    )

    assert run_git_update_detector("needs_rebuild", tmp_path, prev_head) == 0


def test_bisq2_api_image_change_requires_full_rebuild(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    prev_head = commit_file(tmp_path, "README.md", "base\n", "base")
    commit_file(
        tmp_path,
        "docker/bisq2-api/Dockerfile",
        "FROM eclipse-temurin:21\n",
        "change bisq2 image",
    )

    assert run_git_update_detector("needs_rebuild", tmp_path, prev_head) == 0


def test_restart_service_with_deps_starts_qdrant_for_api(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log_file = tmp_path / "docker.log"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n" f'echo "$*" >> "{log_file}"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        restart_service_with_deps api "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    logged = log_file.read_text(encoding="utf-8")
    assert "compose -f docker-compose.yml up -d qdrant api web nginx" in logged


def test_reconcile_runtime_services_falls_back_to_start(tmp_path: Path) -> None:
    log_file = tmp_path / "reconcile.log"

    result = run_bash(
        f"""
        source "{DOCKER_UTILS_SH}"
        check_and_repair_services() {{
            if [ ! -f "{tmp_path}/repair-ok" ]; then
                touch "{tmp_path}/repair-ok"
                echo repair-failed >> "{log_file}"
                return 1
            fi
            echo repair-succeeded >> "{log_file}"
            return 0
        }}
        start_services() {{
            echo start-called >> "{log_file}"
            return 0
        }}
        reconcile_runtime_services "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert lines == ["repair-failed", "start-called", "repair-succeeded"]


def test_health_repair_skips_relay_missing_from_rollback_compose(
    tmp_path: Path,
) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    checked_log = tmp_path / "checked.log"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'if [ "$*" = "compose -f docker-compose.yml config --services" ]; then\n'
        "    printf '%s\\n' qdrant nginx web api bisq2-api prometheus grafana "
        "node-exporter scheduler alertmanager cadvisor\n"
        "    exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        check_service() {{
            printf '%s\n' "$1" >> "{checked_log}"
            return 0
        }}
        check_and_repair_services "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    checked_services = set(checked_log.read_text(encoding="utf-8").splitlines())
    assert checked_services == {
        "qdrant",
        "nginx",
        "web",
        "api",
        "bisq2-api",
        "prometheus",
        "grafana",
        "node-exporter",
        "scheduler",
        "alertmanager",
        "cadvisor",
    }


def test_health_repair_keeps_relay_critical_when_compose_defines_it(
    tmp_path: Path,
) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    checked_log = tmp_path / "checked.log"
    restarted_log = tmp_path / "restarted.log"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'if [ "$*" = "compose -f docker-compose.yml config --services" ]; then\n'
        "    printf '%s\\n' qdrant nginx web api matrix-alert-relay bisq2-api "
        "prometheus blackbox-exporter grafana node-exporter scheduler "
        "alertmanager cadvisor\n"
        "    exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        check_service() {{
            printf '%s\n' "$1" >> "{checked_log}"
            [ "$1" != "matrix-alert-relay" ]
        }}
        restart_service_with_deps() {{
            printf '%s\n' "$1" >> "{restarted_log}"
            return 1
        }}
        check_and_repair_services "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    checked_services = checked_log.read_text(encoding="utf-8").splitlines()
    assert "matrix-alert-relay" in checked_services
    assert "blackbox-exporter" in checked_services
    assert restarted_log.read_text(encoding="utf-8").splitlines() == [
        "matrix-alert-relay"
    ]


def test_health_repair_keeps_blackbox_exporter_critical(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    restarted_log = tmp_path / "restarted.log"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'if [ "$*" = "compose -f docker-compose.yml config --services" ]; then\n'
        "    printf '%s\\n' nginx web api matrix-alert-relay bisq2-api "
        "prometheus blackbox-exporter grafana node-exporter scheduler "
        "alertmanager cadvisor\n"
        "    exit 0\n"
        "fi\n"
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        uses_qdrant_runtime() {{ return 1; }}
        check_service() {{ [ "$1" != "blackbox-exporter" ]; }}
        restart_service_with_deps() {{
            printf '%s\n' "$1" >> "{restarted_log}"
            return 1
        }}
        check_and_repair_services "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert restarted_log.read_text(encoding="utf-8").splitlines() == [
        "blackbox-exporter"
    ]


def test_refresh_runtime_services_includes_qdrant(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log_file = tmp_path / "refresh.log"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n" f'echo "$*" >> "{log_file}"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        refresh_runtime_services "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    logged = log_file.read_text(encoding="utf-8")
    assert (
        "compose -f docker-compose.yml up -d qdrant api matrix-alert-relay web nginx bisq2-api"
        in logged
    )


def test_live_data_chat_smoke_skips_when_mcp_disabled(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ENABLE_BISQ_MCP_INTEGRATION=false\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    curl_log = tmp_path / "curl.log"
    curl = fakebin / "curl"
    curl.write_text(
        "#!/bin/bash\n" f'echo "$*" >> "{curl_log}"\n' "exit 64\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        test_live_data_chat_endpoint "http://example.test/api/chat/query" 1 0 "{env_file}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "Skipping MCP live-data smoke check" in result.stdout
    assert not curl_log.exists()


def test_live_data_chat_smoke_requires_mcp_tool_metadata(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ENABLE_BISQ_MCP_INTEGRATION=true\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    curl = fakebin / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        "cat <<'EOF'\n"
        '{"answer":"BTC price is available.","mcp_tools_used":null}\n'
        "200\n"
        "EOF\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        test_live_data_chat_endpoint "http://example.test/api/chat/query" 1 0 "{env_file}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "MCP live-data smoke test failed after 1 attempts" in result.stdout


def test_live_data_chat_smoke_accepts_market_price_tool(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ENABLE_BISQ_MCP_INTEGRATION=true\n", encoding="utf-8")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    curl = fakebin / "curl"
    curl.write_text(
        "#!/bin/bash\n"
        "cat <<'EOF'\n"
        '{"answer":"BTC price is available.",'
        '"mcp_tools_used":[{"tool":"get_market_prices",'
        '"timestamp":"2026-07-07T00:00:00+00:00"}]}\n'
        "200\n"
        "EOF\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
        source "{DOCKER_UTILS_SH}"
        test_live_data_chat_endpoint "http://example.test/api/chat/query" 1 0 "{env_file}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "MCP live-data smoke test successful" in result.stdout
    assert "get_market_prices" in result.stdout


def test_standalone_health_check_tracks_all_runtime_services() -> None:
    content = CHECK_HEALTH_SH.read_text(encoding="utf-8")

    def array_values(name: str) -> set[str]:
        match = re.search(rf"local {name}=\((.*?)\)", content, flags=re.DOTALL)
        assert match is not None, f"Missing {name} array"
        return set(re.findall(r'"([^"]+)"', match.group(1)))

    critical_services = array_values("critical_services")
    all_services = array_values("all_services")

    assert {"qdrant", "matrix-alert-relay", "alertmanager"} <= critical_services
    assert {
        "qdrant",
        "matrix-alert-relay",
        "alertmanager",
        "cadvisor",
    } <= all_services
