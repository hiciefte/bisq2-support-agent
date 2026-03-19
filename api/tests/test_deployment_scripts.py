from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = REPO_ROOT / "scripts" / "lib" / "common.sh"
DOCKER_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "docker-utils.sh"
GIT_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "git-utils.sh"


def run_bash(
    script: str, *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        env=merged_env,
        capture_output=True,
        text=True,
        check=False,
    )


def init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"], cwd=path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "ci@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True)


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


def test_validate_runtime_configuration_rejects_invalid_retriever_backend() -> None:
    result = run_bash(
        f"""
        source "{COMMON_SH}"
        export RETRIEVER_BACKEND=hybrid
        validate_runtime_configuration
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode != 0
    assert "Unsupported RETRIEVER_BACKEND='hybrid'" in result.stdout


def test_validate_runtime_configuration_requires_trust_monitor_secret() -> None:
    result = run_bash(
        f"""
        source "{COMMON_SH}"
        export RETRIEVER_BACKEND=qdrant
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
    default_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    conflicted = tmp_path / "conflicted.txt"
    conflicted.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflicted.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True
    )

    subprocess.run(
        ["git", "checkout", "-b", "side"], cwd=tmp_path, check=True, capture_output=True
    )
    conflicted.write_text("side\n", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "side"], cwd=tmp_path, check=True, capture_output=True
    )

    subprocess.run(
        ["git", "checkout", default_branch],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    conflicted.write_text("main\n", encoding="utf-8")
    subprocess.run(
        ["git", "commit", "-am", "main"], cwd=tmp_path, check=True, capture_output=True
    )

    merge = subprocess.run(
        ["git", "merge", "side"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
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
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True
    )

    result = run_bash(
        f"""
        source "{GIT_UTILS_SH}"
        stash_changes "{tmp_path}"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 2
    assert "did not create a new stash entry" in result.stdout


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
        export RETRIEVER_BACKEND=qdrant
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
        export RETRIEVER_BACKEND=qdrant
        refresh_runtime_services "{tmp_path}" "docker-compose.yml"
        """,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    logged = log_file.read_text(encoding="utf-8")
    assert (
        "compose -f docker-compose.yml up -d qdrant api web nginx bisq2-api" in logged
    )
