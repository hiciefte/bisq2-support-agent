"""Source-boundary migration fixtures using disposable real Git repositories."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/migrate_wiki_cache.py"
spec = importlib.util.spec_from_file_location("wiki_cache_migration", HELPER)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL
    )


def commit(root, message):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        message,
    )
    return git(root, "rev-parse", "HEAD").decode().strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q")
    cache = root / migration.CACHE
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'{"public":"immutable seed"}\n')
    (root / ".gitignore").write_text("failed_updates/\n.local-data/\n")
    (root / "app.py").write_text("old source\n")
    (root / "obsolete.py").write_text("removed source\n")
    (root / "shared.py").symlink_to("app.py")
    (root / "scripts").mkdir()
    (root / "scripts/placeholder").write_text("fixture source\n")
    previous = commit(root, "legacy source")
    seed = root / migration.SEED
    seed.parent.mkdir(parents=True)
    seed.write_bytes(cache.read_bytes())
    cache.unlink()
    (root / ".gitignore").write_text(
        "failed_updates/\n.local-data/\n/" + migration.CACHE + "\n"
    )
    (root / "app.py").write_text("new source\n")
    (root / "obsolete.py").unlink()
    target = commit(root, "separate seed and runtime")
    git(root, "reset", "--hard", previous)
    cache.write_bytes(b"live bytes preserved exactly\n\x00")
    cache.chmod(0o640)
    (root / "failed_updates/disaster-recovery").mkdir(parents=True)
    (root / ".local-data").mkdir()
    (root / ".local-data/identity").write_bytes(b"unrelated fixture")
    return root, previous, target


def test_migration_preserves_runtime_identity_and_clean_source(repository):
    root, previous, target = repository
    original = migration.runtime_identity(root)
    link_inode = (root / "shared.py").lstat().st_ino
    migration.migrate(root, target, previous)
    assert migration.runtime_identity(root) == original
    assert not git(root, "status", "--porcelain", "--untracked-files=all")
    assert git(root, "rev-parse", "HEAD").decode().strip() == target
    assert (root / "app.py").read_text() == "new source\n"
    assert (root / "shared.py").is_symlink()
    assert (root / "shared.py").readlink() == Path("app.py")
    assert (root / "shared.py").lstat().st_ino == link_inode
    assert not (root / "obsolete.py").exists()
    assert (root / ".local-data/identity").read_bytes() == b"unrelated fixture"
    assert (root / migration.BLOCK).is_file()
    with pytest.raises((migration.Refused, FileNotFoundError)):
        migration.check_pending(root)
    migration.complete_deployment(root)
    assert not (root / migration.BLOCK).exists()
    migration.check_pending(root)
    receipt = json.loads(
        (root / migration.JOURNAL / "deployment-complete.json").read_text()
    )
    assert receipt["deployment_complete"] is True
    assert receipt["before"] == previous and receipt["target"] == target


@pytest.mark.parametrize("kind", ["unstaged", "staged", "untracked", "index_flag"])
def test_source_changes_refuse_before_attempt(repository, kind):
    root, previous, target = repository
    original = migration.runtime_identity(root)
    if kind == "untracked":
        (root / "new-input.py").write_text("unreviewed\n")
    else:
        (root / "app.py").write_text("unreviewed\n")
        if kind == "staged":
            git(root, "add", "app.py")
        elif kind == "index_flag":
            git(root, "update-index", "--assume-unchanged", "app.py")
    with pytest.raises(migration.Refused):
        migration.migrate(root, target, previous)
    assert not (root / migration.JOURNAL).exists()
    assert migration.runtime_identity(root) == original


@pytest.mark.parametrize("kind", ["cache", "parent", "source", "hardlink"])
def test_unsafe_runtime_or_source_paths_refuse(repository, tmp_path, kind):
    root, previous, target = repository
    if kind == "hardlink":
        os.link(root / migration.CACHE, tmp_path / "cache-link")
    elif kind == "parent":
        parent = (root / migration.CACHE).parent
        destination = tmp_path / "old-parent"
        parent.rename(destination)
        parent.symlink_to(destination, target_is_directory=True)
    else:
        path = root / (migration.CACHE if kind == "cache" else "app.py")
        destination = tmp_path / "old-file"
        destination.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(destination)
    with pytest.raises(migration.Refused):
        migration.migrate(root, target, previous)
    assert not (root / migration.JOURNAL).exists()


def test_changed_upstream_seed_refuses(repository):
    root, previous, target = repository
    runtime = (root / migration.CACHE).read_bytes()
    git(root, "reset", "--hard", target)
    (root / migration.SEED).write_bytes(b"different upstream knowledge\n")
    changed = commit(root, "changed seed")
    git(root, "reset", "--hard", previous)
    (root / migration.CACHE).write_bytes(runtime)
    with pytest.raises(migration.Refused, match="upstream_cache_or_seed_changed"):
        migration.migrate(root, changed, previous)
    assert not (root / migration.JOURNAL).exists()
    assert (root / migration.CACHE).read_bytes() == runtime


def test_changed_tracked_symlink_refuses_before_attempt(repository):
    root, previous, target = repository
    runtime = (root / migration.CACHE).read_bytes()
    git(root, "reset", "--hard", target)
    (root / "shared.py").unlink()
    (root / "shared.py").symlink_to("different.py")
    changed = commit(root, "change symlink")
    git(root, "reset", "--hard", previous)
    (root / migration.CACHE).write_bytes(runtime)
    with pytest.raises(migration.Refused, match="symlink_source_change"):
        migration.migrate(root, changed, previous)
    assert not (root / migration.JOURNAL).exists()
    assert (root / migration.CACHE).read_bytes() == runtime


def test_target_cannot_keep_runtime_tracked(repository):
    root, previous, target = repository
    with pytest.raises(migration.Refused, match="runtime_path_must_be_untracked"):
        migration.migrate(root, previous, previous)


@pytest.mark.parametrize(
    "changed_path",
    ["Dockerfile", "docker/docker-compose.extra.yaml", "docker/bisq2-api/Dockerfile"],
)
def test_full_rebuild_refuses_before_source_or_intent(repository, changed_path):
    root, previous, target = repository
    runtime = (root / migration.CACHE).read_bytes()
    git(root, "reset", "--hard", target)
    path = root / changed_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture topology change\n")
    changed = commit(root, "change topology")
    git(root, "reset", "--hard", previous)
    (root / migration.CACHE).write_bytes(runtime)
    before = migration.runtime_identity(root)
    with pytest.raises(migration.Refused, match="full_rebuild_not_supported"):
        migration.migrate(root, changed, previous)
    assert migration.runtime_identity(root) == before
    assert git(root, "rev-parse", "HEAD").decode().strip() == previous
    assert not (root / migration.JOURNAL).exists()


def test_ignored_input_collision_refuses(repository):
    root, previous, target = repository
    (root / ".git/info/exclude").write_text(migration.SEED + "\n")
    path = root / migration.SEED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"existing ignored data")
    with pytest.raises(migration.Refused, match="would_overwrite_untracked_data"):
        migration.migrate(root, target, previous)
    assert path.read_bytes() == b"existing ignored data"


def test_partial_failure_keeps_block_and_prevents_retry(repository, monkeypatch):
    root, previous, target = repository
    original = migration.runtime_identity(root)
    original_git = migration.git

    def fail_at_checkout(root, *args, **kwargs):
        if args[0] == "checkout-index":
            raise migration.Refused("injected_checkout_failure")
        return original_git(root, *args, **kwargs)

    monkeypatch.setattr(migration, "git", fail_at_checkout)
    with pytest.raises(migration.Refused, match="injected_checkout"):
        migration.migrate(root, target, previous)
    assert (root / migration.JOURNAL / "intent.json").exists()
    assert not (root / migration.JOURNAL / "complete.json").exists()
    assert (root / migration.BLOCK).exists()
    assert migration.runtime_identity(root) == original
    assert not git(root, "ls-files", "--", migration.CACHE)
    assert git(root, "rev-parse", "HEAD").decode().strip() == previous
    with pytest.raises(migration.Refused, match="prior_attempt"):
        migration.migrate(root, target, previous)


@pytest.mark.parametrize("kind", ["runtime", "source", "marker"])
def test_completion_refuses_changed_state_and_preserves_block(repository, kind):
    root, previous, target = repository
    migration.migrate(root, target, previous)
    path = (
        root
        / {"runtime": migration.CACHE, "source": "app.py", "marker": migration.BLOCK}[
            kind
        ]
    )
    path.write_text('{"changed":true}\n')
    with pytest.raises(migration.Refused):
        migration.complete_deployment(root)
    assert (root / migration.BLOCK).exists()
    assert not (root / migration.JOURNAL / "deployment-complete.json").exists()


def sourced_updater(tmp_path, body):
    env = dict(os.environ, BISQ_SUPPORT_INSTALL_DIR=str(tmp_path))
    script = f'source "{ROOT}/scripts/update.sh" >/dev/null\n' + body
    return subprocess.run(
        ["bash", "-c", script], text=True, capture_output=True, env=env
    )


def test_migration_failure_does_not_call_legacy_rollback(tmp_path):
    result = sourced_updater(
        tmp_path,
        """
WIKI_CACHE_MIGRATION_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
stop_services() { echo UNSAFE_STOP; }
rollback_to_ref() { echo UNSAFE_RESET; }
rebuild_services() { echo UNSAFE_REBUILD; }
rollback_update fixture_failure
""",
    )
    assert result.returncode == 2
    assert "manual recovery required" in result.stdout + result.stderr
    assert "UNSAFE_" not in result.stdout + result.stderr


def test_preflight_quality_gate_precedes_environment_and_source_change(tmp_path):
    result = sourced_updater(
        tmp_path,
        """
acquire_production_lifecycle_lock() { :; }
prepare_wiki_cache_migration() { echo CANDIDATE_QUALITY_REFUSED; return 1; }
validate_environment() { echo UNSAFE_ENVIRONMENT_MUTATION; }
create_system_backup() { echo UNSAFE_BACKUP_TAG; }
perform_update() { echo UNSAFE_SOURCE_CHANGE; }
main --migrate-legacy-wiki-cache aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --confirm-fresh-backup --confirm-writers-quiesced
""",
    )
    assert result.returncode == 1
    assert "CANDIDATE_QUALITY_REFUSED" in result.stdout
    assert "UNSAFE_" not in result.stdout


def test_missing_attestation_refuses_before_environment(tmp_path):
    result = sourced_updater(
        tmp_path,
        """
acquire_production_lifecycle_lock() { :; }
prepare_wiki_cache_migration() { echo UNSAFE_PREPARATION; }
main --migrate-legacy-wiki-cache aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --confirm-fresh-backup
""",
    )
    assert result.returncode == 2
    assert "UNSAFE_" not in result.stdout


def test_explicit_update_preserves_previous_head_for_rebuild_analysis(tmp_path):
    result = sourced_updater(
        tmp_path,
        f"""
INSTALL_DIR={tmp_path}
GIT_REMOTE=origin
GIT_BRANCH=main
WIKI_CACHE_MIGRATION_COMMIT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
WIKI_CACHE_MIGRATION_PREVIOUS=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
update_repository_with_wiki_cache_migration() {{
  test "$4" = "$WIKI_CACHE_MIGRATION_COMMIT"
  test "$5" = "$WIKI_CACHE_MIGRATION_PREVIOUS"
  PREV_HEAD="$5"; export PREV_HEAD
}}
update_repository() {{ echo UNSAFE_NORMAL_RESET_PATH; return 1; }}
perform_update
test "$PREV_HEAD" = aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
test "$NO_REPO_UPDATES" = false
echo CORRECT_PREVIOUS_HEAD
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CORRECT_PREVIOUS_HEAD" in result.stdout
    assert "UNSAFE_" not in result.stdout


@pytest.mark.parametrize("full_rebuild", ["true", "false"])
def test_migration_never_takes_full_rebuild_or_repair(tmp_path, full_rebuild):
    result = sourced_updater(
        tmp_path,
        f"""
WIKI_CACHE_MIGRATION_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
REBUILD_NEEDED={full_rebuild}
API_REBUILD_NEEDED=false
WEB_REBUILD_NEEDED=false
API_RESTART_NEEDED=false
WEB_RESTART_NEEDED=false
NGINX_RESTART_NEEDED=false
rebuild_services() {{ echo UNSAFE_REBUILD; }}
check_and_repair_services() {{ echo UNSAFE_REPAIR; }}
apply_updates
""",
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "manual recovery required" in result.stdout + result.stderr
    assert "UNSAFE_" not in result.stdout + result.stderr


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_candidate_index_flags_cannot_hide_changed_updater(repository, tmp_path, flag):
    root, previous, target = repository
    candidate = tmp_path / "candidate"
    git(root, "worktree", "add", "--detach", str(candidate), target)
    git(candidate, "update-index", flag, "app.py")
    (candidate / "app.py").write_text("hidden change\n")
    result = sourced_updater(
        tmp_path,
        f"""
SCRIPT_DIR={candidate}/scripts
INSTALL_DIR={root}
WIKI_CACHE_MIGRATION_COMMIT={target}
prepare_wiki_cache_migration
""",
    )
    # SCRIPT_DIR is only used to locate the candidate root before refusal.
    assert result.returncode != 0
    assert "Candidate index flags" in result.stdout + result.stderr
