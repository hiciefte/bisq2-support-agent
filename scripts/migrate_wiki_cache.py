"""Migrate the legacy tracked wiki cache without writing its runtime path.

Called only by the candidate updater while it owns the lifecycle lock. A durable
recovery block survives any interrupted transition until reviewed recovery.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

CACHE = "api/data/wiki/processed_wiki.jsonl"
SEED = "api/app/resources/wiki/processed_wiki.seed.jsonl"
JOURNAL = "failed_updates/wiki-cache-migration"
BLOCK = "failed_updates/disaster-recovery/recovery-blocked"


class Refused(RuntimeError):
    pass


def git(root, *args, input_bytes=None):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=input_bytes, capture_output=True, env=env
    )
    if result.returncode:
        raise Refused("git_operation_failed")
    return result.stdout


def require(value, reason):
    if not value:
        raise Refused(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def regular_path(root, relative, missing=False):
    path = root / relative
    for part in [path, *path.parents]:
        if part == root:
            break
        require(not part.is_symlink(), "symlink_refused")
        if part != path and part.exists():
            require(part.is_dir(), "non_directory_ancestor")
    if missing and not path.exists():
        return path
    require(stat.S_ISREG(path.lstat().st_mode), "regular_file_required")
    return path


def tree(root, revision):
    result = {}
    for item in git(root, "ls-tree", "-rz", revision).split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = raw_path.decode()
        require(
            mode in {"100644", "100755", "120000"} and kind == "blob",
            "unsupported_tree_entry",
        )
        require(
            not path.startswith("/") and ".." not in Path(path).parts, "invalid_path"
        )
        result[path] = (mode, oid)
    return result


def source_paths(root, old, new):
    """Validate source paths, preserving unchanged tracked symlinks in place."""
    unchanged_links = set()
    for name in set(old) | set(new):
        entries = (old.get(name), new.get(name))
        if any(entry and entry[0] == "120000" for entry in entries):
            require(entries[0] == entries[1], "symlink_source_change_refused")
            path = root / name
            require(path.is_symlink(), "tracked_symlink_missing")
            for parent in path.parents:
                if parent == root:
                    break
                require(
                    not parent.is_symlink() and parent.is_dir(),
                    "unsafe_symlink_ancestor",
                )
            unchanged_links.add(name)
            continue
        path = regular_path(root, name, missing=True)
        require(
            name == CACHE or name in old or not path.exists(),
            "would_overwrite_untracked_data",
        )
    return unchanged_links


def runtime_identity(root):
    path = regular_path(root, CACHE)
    info = path.stat()
    require(info.st_nlink == 1, "runtime_hardlink_refused")
    return {
        "sha256": sha(path.read_bytes()),
        "inode": info.st_ino,
        "device": info.st_dev,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def clean_source(root, legacy):
    require(
        all(
            item.startswith(b"H ")
            for item in git(root, "ls-files", "-v", "-z").split(b"\0")
            if item
        ),
        "index_flags_are_not_source_proof",
    )
    git(root, "diff", "--cached", "--quiet", "HEAD", "--")
    args = ["diff", "--quiet", "HEAD", "--", "."]
    if legacy:
        args.append(":(exclude)" + CACHE)
    git(root, *args)
    require(
        not git(root, "ls-files", "--others", "--exclude-standard", "-z"),
        "untracked_source_inputs",
    )


def exclusive_json(path, value):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def control_path(root, relative):
    path = root / relative
    for parent in [path, *path.parents]:
        if parent == root:
            break
        require(not parent.is_symlink(), "unsafe_control_path")
    return path


def replace_source_tree(root, before, after):
    """Normal index/ref replacement, explicit source checkout; cache is untouched.

    Unlike reset --hard, checkout-index only writes paths listed in the new
    source tree. Deletions are explicit. No skip-worktree/assume-unchanged flags,
    custom index, stashes or altered exclusions are used.
    """
    old, new = tree(root, before), tree(root, after)
    unchanged_links = source_paths(root, old, new)
    git(root, "read-tree", "--reset", after)
    names = sorted(set(new) - {CACHE} - unchanged_links)
    git(
        root,
        "checkout-index",
        "--force",
        "-z",
        "--stdin",
        input_bytes=b"".join(name.encode() + b"\0" for name in names),
    )
    for name in set(old) - set(new) - {CACHE}:
        regular_path(root, name).unlink()
    git(root, "update-ref", "HEAD", after, before)


def preflight(root, target, previous):
    root = Path(root).resolve()
    journal = control_path(root, JOURNAL)
    require(not journal.exists(), "prior_attempt_refused")
    require(not control_path(root, BLOCK).exists(), "recovery_already_blocked")
    before = git(root, "rev-parse", "HEAD").decode().strip()
    require(before == previous, "previous_revision_changed")
    target = git(root, "rev-parse", target + "^{commit}").decode().strip()
    git(root, "merge-base", "--is-ancestor", before, target)
    old, new = tree(root, before), tree(root, target)
    changed = {name for name in set(old) | set(new) if old.get(name) != new.get(name)}
    # Match the canonical needs_rebuild boundary before any source transition;
    # full-stack updates would recreate unrelated services during preservation.
    require(
        not any(
            re.match(
                r"^(Dockerfile$|docker/docker-compose[^/]*\.ya?ml$|docker/bisq2-api/)",
                name,
            )
            for name in changed
        ),
        "full_rebuild_not_supported_during_migration",
    )
    require(
        CACHE in old and CACHE not in new, "runtime_path_must_be_untracked_by_release"
    )
    require(
        SEED not in old and new.get(SEED) == old[CACHE],
        "upstream_cache_or_seed_changed",
    )
    # The reviewed migration must declare the exact runtime path ignored. A
    # source deletion alone would leave a nonignored build input after update.
    ignore = git(root, "show", target + ":.gitignore").decode().splitlines()
    require("/" + CACHE in ignore, "runtime_ignore_missing")
    clean_source(root, legacy=True)
    identity = runtime_identity(root)
    # Refuse source-path shape collisions before a durable attempt is recorded.
    source_paths(root, old, new)
    return {"before": before, "target": target, "runtime": identity}


def migrate(root, target, previous):
    root = Path(root).resolve()
    record = preflight(root, target, previous)
    journal = control_path(root, JOURNAL)
    journal.mkdir(mode=0o700)
    sync_directory(journal.parent)
    exclusive_json(journal / "intent.json", record)
    exclusive_json(control_path(root, BLOCK), record)
    replace_source_tree(root, record["before"], record["target"])
    require(
        runtime_identity(root) == record["runtime"], "runtime_changed_during_migration"
    )
    clean_source(root, legacy=False)
    git(root, "check-ignore", "--quiet", "--", CACHE)
    require(not git(root, "ls-files", "--", CACHE), "runtime_still_tracked")
    exclusive_json(journal / "complete.json", record)
    return record


def check_pending(root):
    journal = control_path(root, JOURNAL)
    if journal.exists():
        receipt = regular_path(root, JOURNAL + "/deployment-complete.json")
        require(
            json.loads(receipt.read_text()).get("deployment_complete") is True,
            "migration_requires_reconciliation",
        )


def complete_deployment(root):
    journal = control_path(root, JOURNAL)
    record = json.loads(regular_path(root, JOURNAL + "/complete.json").read_text())
    require(
        git(root, "rev-parse", "HEAD").decode().strip() == record["target"],
        "completed_revision_changed",
    )
    require(
        runtime_identity(root) == record["runtime"], "runtime_changed_since_migration"
    )
    clean_source(root, legacy=False)
    block = regular_path(root, BLOCK)
    require(json.loads(block.read_text()) == record, "recovery_block_owner_changed")
    exclusive_json(
        journal / "deployment-complete.json", {**record, "deployment_complete": True}
    )
    block.unlink()
    sync_directory(block.parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("preflight", "apply", "check-pending", "complete-deployment")
    )
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--target")
    parser.add_argument("--previous")
    args = parser.parse_args()
    root = args.repository.resolve()
    require(not sys.flags.optimize, "optimized_execution_forbidden")
    require(
        os.environ.get("BISQ_SUPPORT_LIFECYCLE_LOCK_FD", "").isdigit(),
        "updater_lock_required",
    )
    os.fstat(int(os.environ["BISQ_SUPPORT_LIFECYCLE_LOCK_FD"]))
    if args.phase in {"preflight", "apply"}:
        require(args.target and args.previous, "exact_revisions_required")
        require(
            all(
                len(value) == 40 and set(value) <= set("0123456789abcdef")
                for value in (args.target, args.previous)
            ),
            "full_commit_required",
        )
        operation = preflight if args.phase == "preflight" else migrate
        operation(root, args.target, args.previous)
    elif args.phase == "check-pending":
        check_pending(root)
    else:
        complete_deployment(root)
    print(json.dumps({"wiki_cache_migration": args.phase, "success": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No command output, runtime bytes, addresses or exception payloads.
        print(
            json.dumps(
                {"wiki_cache_migration": "refused", "error_type": type(exc).__name__}
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None
