"""Offline plan/status integration using real local Git objects, no Docker."""

import json
import os
import runpy
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/deploy_release.py"
UPDATE = ROOT / "scripts/update.sh"
JOURNAL = ROOT / "scripts/lib/deployment_journal.py"


def git(repository, *args):
    return subprocess.check_output(
        ["git", "-C", str(repository), *args],
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        },
        stderr=subprocess.DEVNULL,
    )


def commit(repository, changes):
    for name, contents in changes.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if contents is None:
            path.unlink()
        else:
            path.write_text(contents)
    git(repository, "add", ".")
    git(
        repository,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Fixture source",
    )
    return git(repository, "rev-parse", "HEAD").decode().strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q")
    previous = commit(
        root,
        {
            "api/app/example.py": "OLD = 1\n",
            ".gitignore": ".agent-artifacts/\nfailed_updates/\n",
        },
    )
    return root, previous


def plan_args(
    repository, previous, candidate, operation, *, services="api", deadline=None
):
    return [
        "plan",
        "--repository",
        str(repository),
        "--previous",
        previous,
        "--commit",
        candidate,
        "--services",
        services,
        "--profile",
        "primary",
        "--deadline",
        deadline or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "--operation",
        str(operation),
    ]


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, "-B", str(HELPER), *args],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def assert_error(result, code):
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"error": code}


@pytest.mark.parametrize(
    ("changes", "requested", "expected"),
    [
        ({"api/app/example.py": "NEW = 2\n"}, "api", ["api"]),
        ({"api/requirements.txt": "example==1.0\n"}, "api", ["api"]),
        ({"web/src/app/page.tsx": "export default 1;\n"}, "web", ["web"]),
        ({"web/package.json": "{}\n"}, "web", ["web"]),
        (
            {"web/package-lock.json": "{}\n", "api/app/example.py": "NEW = 2\n"},
            "web,api",
            ["api", "web"],
        ),
    ],
)
def test_plan_binds_immutable_source_and_selected_service_without_worktree_writes(
    repository, tmp_path, changes, requested, expected
):
    root, previous = repository
    candidate = commit(root, changes)
    # Planning uses committed objects and neither cleans nor stages local edits.
    (root / "api/app/example.py").write_text("private local change\n")
    before = git(root, "status", "--porcelain=v1", "-z")
    index_before = (root / ".git/index").read_bytes()
    operation = tmp_path / "operation"
    result = cli(*plan_args(root, previous, candidate, operation, services=requested))
    assert result.returncode == 0, result.stderr
    saved = json.loads((operation / "plan.json").read_text())
    assert saved["schema"] == "deployment-plan-v2"
    assert saved["source"]["candidate_commit"] == candidate
    assert (
        saved["source"]["candidate_tree"]
        == git(root, "rev-parse", candidate + "^{tree}").decode().strip()
    )
    assert saved["source"]["previous_commit"] == previous
    assert (
        saved["source"]["previous_tree"]
        == git(root, "rev-parse", previous + "^{tree}").decode().strip()
    )
    assert saved["services"] == expected
    assert "images" not in saved and "authorization" not in saved
    assert ("smoke_standard" in saved["phases"]) == ("api" in expected)
    assert ("smoke_live_mcp" in saved["phases"]) == ("api" in expected)
    assert git(root, "status", "--porcelain=v1", "-z") == before
    assert (root / ".git/index").read_bytes() == index_before
    assert stat.S_IMODE(operation.stat().st_mode) == 0o700
    assert stat.S_IMODE((operation / "plan.json").stat().st_mode) == 0o600
    assert sorted(path.name for path in operation.iterdir()) == ["plan.json"]
    status = json.loads(result.stdout)
    assert status["execution_supported"] is True
    assert status["runtime_binding"] == "not_assessed"
    assert status["journal"]["completed"] is False
    assert all(phase["status"] == "pending" for phase in status["journal"]["phases"])


@pytest.mark.parametrize(
    "path",
    [
        "docker/docker-compose.yml",
        "docker/api/Dockerfile",
        "scripts/update.sh",
        "api/data/faqs.db",
        "api/app/resources/wiki/seed.jsonl",
        "api/app/db/migrations/002_change.sql",
        "api/app/scripts/rebuild.py",
        "api/app/services/schema_migration.py",
        "web/.env",
        ".gitmodules",
        "unknown.txt",
    ],
)
def test_unsupported_changes_refuse_before_saving(repository, tmp_path, path):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n", path: "fixture\n"})
    operation = tmp_path / "operation"
    assert_error(
        cli(*plan_args(root, previous, candidate, operation)),
        "unsupported_change_scope",
    )
    assert not operation.exists()


def test_wrong_services_and_short_refs_refuse(repository, tmp_path):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    assert_error(
        cli(*plan_args(root, previous, candidate, operation, services="api,web")),
        "service_selection_mismatch",
    )
    assert_error(
        cli(*plan_args(root, previous, candidate[:8], operation)),
        "full_commit_required",
    )
    assert not operation.exists()


def test_branch_names_missing_objects_and_reverse_history_refuse(repository, tmp_path):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    assert_error(
        cli(*plan_args(root, previous, "HEAD", operation)), "full_commit_required"
    )
    assert_error(
        cli(*plan_args(root, previous, "f" * 40, operation)), "local_git_refused"
    )
    assert_error(
        cli(*plan_args(root, candidate, previous, operation)), "local_git_refused"
    )
    assert not operation.exists()


def test_documentation_only_change_does_not_invent_service_work(repository, tmp_path):
    root, previous = repository
    candidate = commit(root, {"docs/release.md": "Reviewed release notes.\n"})
    operation = tmp_path / "operation"
    assert_error(
        cli(*plan_args(root, previous, candidate, operation)),
        "no_service_source_changes",
    )
    assert not operation.exists()


@pytest.mark.parametrize(
    "deadline",
    [
        "2020-01-01T00:00:00+00:00",
        "2030-01-01T00:00:00",
        "2030-01-01T02:00:00+02:00",
        "not-a-date",
    ],
)
def test_expired_or_non_utc_window_refuses(repository, tmp_path, deadline):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    result = cli(*plan_args(root, previous, candidate, operation, deadline=deadline))
    assert result.returncode == 2
    assert not operation.exists()


def test_existing_operation_and_source_destinations_cannot_be_overwritten(
    repository, tmp_path
):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    args = plan_args(root, previous, candidate, operation)
    assert cli(*args).returncode == 0
    before = (operation / "plan.json").read_bytes()
    assert_error(cli(*args), "operation_already_exists")
    assert (operation / "plan.json").read_bytes() == before
    assert_error(
        cli(*plan_args(root, previous, candidate, root / "api/new-operation")),
        "operation_in_source_tree",
    )
    assert_error(
        cli(*plan_args(root, previous, candidate, root / ".git/new-operation")),
        "operation_path",
    )
    ignored = root / ".agent-artifacts"
    ignored.mkdir()
    assert (
        cli(*plan_args(root, previous, candidate, ignored / "operation")).returncode
        == 0
    )


def test_symlinked_source_changes_and_output_paths_refuse(repository, tmp_path):
    root, previous = repository
    (root / "api/app/link.py").symlink_to("example.py")
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    assert_error(
        cli(*plan_args(root, previous, candidate, tmp_path / "operation")),
        "unsupported_source_entry",
    )
    normal = commit(root, {"api/app/example.py": "NEXT = 3\n"})
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert_error(
        cli(*plan_args(root, candidate, normal, alias / "operation")), "operation_path"
    )


@pytest.mark.parametrize("absolute", [True, False])
@pytest.mark.parametrize("via_ignored_directory", [True, False])
def test_update_plan_refuses_parent_traversal_without_source_writes(
    repository, tmp_path, absolute, via_ignored_directory
):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    if via_ignored_directory:
        anchor = root / ".agent-artifacts"
        anchor.mkdir()
        operation = anchor / ".." / "api" / "unwanted-operation"
    else:
        anchor = tmp_path / "outside"
        anchor.mkdir()
        operation = anchor / ".." / root.name / "api" / "unwanted-operation"
    if not absolute:
        operation = operation.relative_to(tmp_path)
    before = git(root, "status", "--porcelain=v1", "-z")
    index_before = (root / ".git/index").read_bytes()
    source_before = (root / "api/app/example.py").read_bytes()
    result = subprocess.run(
        ["bash", str(UPDATE), *plan_args(root, previous, candidate, operation)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert_error(result, "operation_path")
    assert not (root / "api/unwanted-operation").exists()
    assert git(root, "status", "--porcelain=v1", "-z") == before
    assert (root / ".git/index").read_bytes() == index_before
    assert (root / "api/app/example.py").read_bytes() == source_before


def test_plan_publication_syncs_record_and_both_directory_entries(
    repository, tmp_path, monkeypatch
):
    root, _ = repository
    operation = tmp_path / "operation"
    monkeypatch.syspath_prepend(str(HELPER.parent))
    release = runpy.run_path(str(HELPER))
    actual_fsync = os.fsync
    observed = []

    def observe_fsync(fd):
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode):
            observed.append("record")
        elif info.st_ino == operation.stat().st_ino:
            observed.append("operation")
        else:
            assert info.st_ino == tmp_path.stat().st_ino
            assert (operation / "plan.json").is_file()
            observed.append("parent")
        actual_fsync(fd)

    monkeypatch.setattr(os, "fsync", observe_fsync)
    release["save_plan"](operation, root, {"test": "publication"})
    assert observed == ["record", "operation", "parent"]


def test_parent_sync_failure_reports_failure_and_preserves_published_plan(
    repository, tmp_path, monkeypatch, capsys
):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    monkeypatch.syspath_prepend(str(HELPER.parent))
    release = runpy.run_path(str(HELPER))
    actual_fsync = os.fsync
    parent_info = tmp_path.stat()

    def fail_parent_sync(fd):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (parent_info.st_dev, parent_info.st_ino):
            raise OSError("Injected directory sync failure")
        actual_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_parent_sync)
    monkeypatch.setattr(
        sys, "argv", [str(HELPER), *plan_args(root, previous, candidate, operation)]
    )
    assert release["main"]() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "local_state_unavailable"}
    published = (operation / "plan.json").read_bytes()
    assert release["main"]() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err) == {"error": "operation_already_exists"}
    assert (operation / "plan.json").read_bytes() == published


def test_status_is_read_only_after_deadline_without_repository(repository, tmp_path):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    assert cli(*plan_args(root, previous, candidate, operation)).returncode == 0
    # An expired fixture needs no effects and must remain inspectable.
    path = operation / "plan.json"
    saved = json.loads(path.read_text())
    saved.update(
        created_at="2020-01-01T00:00:00+00:00", deadline="2020-01-02T00:00:00+00:00"
    )
    path.write_text(json.dumps(saved))
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    root.rename(tmp_path / "repository-unavailable")
    result = cli("status", "--operation", str(operation))
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["deadline_expired"] is True
    assert status["execution_supported"] is True
    assert status["journal"]["needs_attention"] is False
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)
    assert not (operation / "journal.lock").exists()


def test_status_reports_uncertain_intent_without_replay(repository, tmp_path):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    planned = cli(*plan_args(root, previous, candidate, operation))
    plan_hash = json.loads(planned.stdout)["journal"]["plan_sha256"]
    intent = operation / "build.intent.json"
    intent.write_text(
        json.dumps(
            {
                "phase": "build",
                "plan_sha256": plan_hash,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    intent.chmod(0o600)
    before = intent.read_bytes()
    status = json.loads(cli("status", "--operation", str(operation)).stdout)
    assert status["journal"]["phases"][0]["status"] == "uncertain"
    assert status["journal"]["needs_attention"] is True
    assert not (operation / "build.result.json").exists()
    assert before == intent.read_bytes()


def test_update_plan_status_route_before_any_runtime_library(repository, tmp_path):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    scripts = tmp_path / "entrypoint"
    (scripts / "lib").mkdir(parents=True)
    shutil.copyfile(UPDATE, scripts / "update.sh")
    shutil.copyfile(HELPER, scripts / "deploy_release.py")
    shutil.copyfile(JOURNAL, scripts / "lib/deployment_journal.py")
    shutil.copyfile(
        ROOT / "scripts/lib/deployment_protocol.py",
        scripts / "lib/deployment_protocol.py",
    )
    # These real shell files fail immediately if the old initialization runs.
    sentinel = tmp_path / "runtime-library-loaded"
    for name in ("common.sh", "docker-utils.sh", "git-utils.sh"):
        (scripts / "lib" / name).write_text(f"touch '{sentinel}'\nexit 91\n")
    operation = tmp_path / "operation"
    for args in [
        plan_args(root, previous, candidate, operation),
        ["status", "--operation", str(operation)],
    ]:
        result = subprocess.run(
            ["bash", str(scripts / "update.sh"), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["execution_supported"] is True
        assert not sentinel.exists()


def test_git_overrides_and_external_diff_do_not_redirect_or_execute(
    repository, tmp_path
):
    root, previous = repository
    candidate = commit(root, {"api/app/example.py": "NEW = 2\n"})
    sentinel = tmp_path / "external-diff-ran"
    git(root, "config", "diff.external", f"touch {sentinel}")
    env = dict(
        os.environ, GIT_DIR=str(tmp_path / "missing"), GIT_WORK_TREE=str(tmp_path)
    )
    result = cli(*plan_args(root, previous, candidate, tmp_path / "operation"), env=env)
    assert result.returncode == 0, result.stderr
    assert not sentinel.exists()


def test_unimplemented_commands_are_not_exposed_as_working_effects():
    for command in ("apply", "continue", "reconcile"):
        assert_error(cli(command), "arguments")
