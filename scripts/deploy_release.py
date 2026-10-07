"""Plan, execute and inspect bounded selective source releases.

Effects use a persistent host lifecycle owner and durable once-only receipts.
Offline planning/status do not load runtime configuration or contact a host.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn

from lib.deployment_journal import (
    DeploymentJournal,
    JournalError,
    digest,
    encode,
    exclusive_record,
    now,
    require,
    timestamp,
)
from lib.deployment_protocol import DEPLOYMENT_TOOLING, phases_for, validate_plan


def full_commit(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value))


def local_git(repository: Path, *args: str) -> bytes:
    # Ignore ambient repository/config overrides; never lazily fetch objects,
    # execute external diffs or ask Git to refresh/write the working index.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_LAZY_FETCH="1",
        GIT_ALLOW_PROTOCOL="",
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    try:
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-C",
                str(repository),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "safe.directory=" + str(repository),
                *args,
            ],
            capture_output=True,
            env=env,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise JournalError("local_git_unavailable") from error
    require(result.returncode == 0, "local_git_refused")
    require(len(result.stdout) <= 8 * 1024 * 1024, "source_diff_too_large")
    return result.stdout


def changed_paths(repository: Path, previous: str, candidate: str) -> list[str]:
    raw = local_git(
        repository,
        "diff",
        "--raw",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--no-abbrev",
        "-z",
        previous,
        candidate,
        "--",
    )
    entries = raw.split(b"\0")
    require(entries.pop() == b"" and len(entries) % 2 == 0, "source_diff_format")
    paths = []
    for header, name in zip(entries[::2], entries[1::2]):
        require(
            bool(
                re.fullmatch(
                    rb":(?:100644|100755|000000) (?:100644|100755|000000) "
                    rb"[0-9a-f]{40} [0-9a-f]{40} [AMD]",
                    header,
                )
            ),
            "unsupported_source_entry",
        )
        try:
            path = name.decode("utf-8")
        except UnicodeDecodeError as error:
            raise JournalError("unsupported_source_path") from error
        require(
            0 < len(path) <= 4096
            and not path.startswith("/")
            and not any(ord(char) < 32 for char in path)
            and not any(part in {"", ".", ".."} for part in path.split("/")),
            "unsupported_source_path",
        )
        paths.append(path)
    require(0 < len(paths) <= 4096, "source_change_count")
    return sorted(paths)


def classify_services(
    paths: list[str], *, include_deployment_tooling: bool = False
) -> list[str]:
    """A strict source-only subset of update.sh's selective rebuild rules."""
    selected = set()
    for path in paths:
        if include_deployment_tooling and path in DEPLOYMENT_TOOLING:
            continue
        if path.startswith(
            ("docs/", "api/tests/", "web/tests/", "web/e2e/")
        ) or path in {
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "LICENSE",
        }:
            continue
        parts = PurePosixPath(path).parts
        require(
            not any(
                part.startswith(".env") or "migration" in part.lower() for part in parts
            )
            and not path.startswith(
                ("api/app/db/", "api/app/resources/", "api/app/scripts/")
            ),
            "unsupported_change_scope",
        )
        if path.startswith("api/app/") or path in {
            "api/requirements.in",
            "api/requirements.txt",
        }:
            selected.add("api")
        elif path.startswith(
            (
                "web/src/",
                "web/app/",
                "web/components/",
                "web/lib/",
                "web/styles/",
                "web/public/",
            )
        ) or path in {
            "web/package.json",
            "web/package-lock.json",
            "web/yarn.lock",
            "web/pnpm-lock.yaml",
            "web/bun.lock",
            "web/bun.lockb",
        }:
            selected.add("web")
        else:
            raise JournalError("unsupported_change_scope")
    require(bool(selected), "no_service_source_changes")
    return sorted(selected)


def tooling_hashes(
    repository: Path, candidate: str, paths: list[str]
) -> dict[str, str]:
    """Pin candidate blobs for every changed path in the fixed tooling capability."""
    result = {}
    for path in paths:
        if path not in DEPLOYMENT_TOOLING:
            continue
        entry = local_git(repository, "ls-tree", "-z", candidate, "--", path)
        require(
            bool(
                re.fullmatch(
                    rb"100(?:644|755) blob [0-9a-f]{40}\t"
                    + re.escape(path.encode())
                    + rb"\0",
                    entry,
                )
            ),
            "unsupported_tooling_entry",
        )
        blob = entry.split(b" ", 2)[2].split(b"\t", 1)[0].decode()
        result[path] = digest(local_git(repository, "cat-file", "blob", blob))
    require(bool(result), "no_deployment_tooling_changes")
    return result


def save_plan(operation: Path, repository: Path, plan: dict) -> None:
    # No implicit parents, symlink traversal, replacement, source or data writes.
    require(".." not in operation.parts, "operation_path")
    operation = operation.absolute()
    require(
        not any(path.is_symlink() for path in (operation, *operation.parents))
        and ".git" not in operation.parts,
        "operation_path",
    )
    # Check original components first: resolution must not hide a symlink or '..'.
    operation = operation.parent.resolve(strict=True) / operation.name
    try:
        relative = operation.relative_to(repository)
    except ValueError:
        relative = None
    if relative is not None:
        require(
            bool(relative.parts)
            and relative.parts[0] in {".agent-artifacts", "failed_updates"},
            "operation_in_source_tree",
        )
        local_git(repository, "check-ignore", "--quiet", "--", str(relative))
    require(not operation.exists(), "operation_already_exists")
    info = operation.parent.stat()
    require(stat.S_ISDIR(info.st_mode), "operation_parent")
    operation.mkdir(mode=0o700)
    exclusive_record(operation / "plan.json", plan)
    # The record fsync covers its own directory, not this new directory's entry.
    parent = os.open(operation.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def prepare(args: argparse.Namespace) -> dict:
    repository = args.repository.resolve(strict=True)
    require(
        full_commit(args.commit) and full_commit(args.previous), "full_commit_required"
    )
    require(
        Path(
            local_git(repository, "rev-parse", "--show-toplevel").decode().strip()
        ).resolve()
        == repository,
        "repository_root_required",
    )
    created_at = now()
    source = {}
    for label, commit in (("candidate", args.commit), ("previous", args.previous)):
        resolved = (
            local_git(repository, "rev-parse", "--verify", commit + "^{commit}")
            .decode()
            .strip()
        )
        require(resolved == commit, "commit_object_required")
        source[label + "_commit"] = resolved
        source[label + "_tree"] = (
            local_git(repository, "rev-parse", "--verify", commit + "^{tree}")
            .decode()
            .strip()
        )
    local_git(repository, "merge-base", "--is-ancestor", args.previous, args.commit)
    paths = changed_paths(repository, args.previous, args.commit)
    source["changed_paths_sha256"] = digest(encode(paths))
    services = sorted(args.services.split(","))
    include_tooling = getattr(args, "include_deployment_tooling", False)
    require(
        services
        == classify_services(paths, include_deployment_tooling=include_tooling),
        "service_selection_mismatch",
    )
    plan = {
        "schema": "deployment-plan-v3" if include_tooling else "deployment-plan-v2",
        "kind": (
            "selective-api-web-with-tooling-v1"
            if include_tooling
            else "selective-api-web-v1"
        ),
        "created_at": created_at,
        "deadline": args.deadline,
        "profile": args.profile,
        "source": source,
        "services": services,
        "phases": phases_for(services),
    }
    if include_tooling:
        plan["tooling_sha256"] = tooling_hashes(repository, args.commit, paths)
    validate_plan(plan)
    save_plan(args.operation, repository, plan)
    return inspect_status(args.operation)


def inspect_status(operation: Path) -> dict:
    journal = DeploymentJournal(operation)
    validate_plan(journal.plan)
    return {
        "schema": "deployment-status-v1",
        "execution_supported": journal.plan["schema"]
        in {"deployment-plan-v2", "deployment-plan-v3"},
        "runtime_binding": "not_assessed",
        "deadline_expired": timestamp(now()) >= timestamp(journal.plan["deadline"]),
        "journal": journal.status(),
    }


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise JournalError("arguments")


def main() -> int:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Save an offline source-only release plan")
    plan.add_argument("--repository", type=Path, required=True)
    plan.add_argument("--commit", required=True)
    plan.add_argument("--previous", required=True)
    plan.add_argument("--services", required=True, help="api, web, or api,web")
    plan.add_argument(
        "--include-deployment-tooling",
        action="store_true",
        help="Include only the fixed deployment tooling capability with exact blob pins",
    )
    plan.add_argument(
        "--profile", required=True, help="Protected profile name, never secret contents"
    )
    plan.add_argument(
        "--deadline", required=True, help="Effect deadline in UTC ISO 8601"
    )
    plan.add_argument(
        "--operation", type=Path, required=True, help="New private operation directory"
    )
    status = commands.add_parser(
        "status", help="Read journal evidence, including after deadline"
    )
    status.add_argument("--operation", type=Path, required=True)
    for name in ("apply", "continue", "reconcile"):
        action = commands.add_parser(
            name, help="Bounded execution or read-only reconciliation"
        )
        action.add_argument("--operation", type=Path, required=True)
        if name == "apply":
            action.add_argument("--profile", type=Path, required=True)
            action.add_argument("--approval", type=Path, required=True)
    try:
        args = parser.parse_args()
        if args.command == "plan":
            result = prepare(args)
        elif args.command == "status":
            result = inspect_status(args.operation)
        else:
            from lib.deployment_client import execute, reconcile

            result = (
                reconcile(args.operation)
                if args.command == "reconcile"
                else execute(
                    args.operation,
                    profile_path=getattr(args, "profile", None),
                    approval_path=getattr(args, "approval", None),
                )
            )
    except JournalError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print(json.dumps({"error": "local_state_unavailable"}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
