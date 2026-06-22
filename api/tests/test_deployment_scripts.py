from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = REPO_ROOT / "scripts" / "lib" / "common.sh"
DOCKER_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "docker-utils.sh"
GIT_UTILS_SH = REPO_ROOT / "scripts" / "lib" / "git-utils.sh"


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
