from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = REPO_ROOT / "scripts" / "lib" / "common.sh"
DOCKER_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "docker-utils.sh"
CHECK_HEALTH_SH = REPO_ROOT / "scripts" / "check-health.sh"
GIT_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "git-utils.sh"
ROLLBACK_SH = REPO_ROOT / "scripts" / "rollback.sh"
UPDATE_SH = REPO_ROOT / "scripts" / "update.sh"


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
    docker.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{docker_log}"\n'
        'if [ "$1" = "ps" ]; then echo "docker-api-1"; exit 0; fi\n'
        'if [ "$1" = "exec" ]; then echo "7"; exit 0; fi\n'
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
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
    assert "app.scripts.migrate_to_sqlite" not in docker_log.read_text(encoding="utf-8")


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
    docker.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{docker_log}"\n'
        'if [ "$1" = "ps" ]; then echo "docker-api-1"; exit 0; fi\n'
        'if [ "$1" = "exec" ]; then exit 70; fi\n'
        "exit 64\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = run_bash(
        f"""
        export PATH="{fakebin}:$PATH"
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
    assert "app.scripts.migrate_to_sqlite" not in docker_log.read_text(encoding="utf-8")


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
    (data_dir / "faqs.db").write_bytes(b"sqlite fixture")

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
    assert (backup_dir / "faqs.db").read_bytes() == b"sqlite fixture"
    assert "Backing up production data files" in result.stderr
    assert "Backed up 1 production data file(s)" in result.stderr


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
        "prometheus grafana node-exporter scheduler alertmanager cadvisor\n"
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
    assert restarted_log.read_text(encoding="utf-8").splitlines() == [
        "matrix-alert-relay"
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
