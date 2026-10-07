#!/usr/bin/env python3
"""Read-only Linux proof of an inherited canonical lifecycle flock.

Never acquire, release, chmod, chown or replace a borrowed lock. Linux fdinfo
associates FLOCK with its open file description; a pathname or /proc/locks entry
alone cannot show that this descriptor owns it. The acquiring flock utility may
already have exited, so also prove a live borrower/ancestor still holds the
matching descriptor instead of trusting the PID printed in a kernel lock line.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

LOCK_LINE = re.compile(
    r"^(?:lock:\s+)?\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s+(?:\d+|-1)\s+"
    r"([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)\s+0\s+EOF\s*$"
)


class LifecycleLockError(RuntimeError):
    """A borrowed descriptor failed the canonical ownership proof."""


def _require(condition: bool) -> None:
    if not condition:
        raise LifecycleLockError("inherited_lifecycle_lock_invalid")


def verify_active_operation(install_dir: Path) -> None:
    """A prior incomplete deployment excludes every different lifecycle owner."""
    marker = install_dir / "failed_updates/disaster-recovery/deployment-active.json"
    if not marker.exists() and not marker.is_symlink():
        return
    try:
        fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(
                stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and info.st_size <= 8192
            )
            record = json.loads(stream.read())
        _require(
            set(record) == {"schema", "plan_sha256", "profile_sha256", "operation"}
            and record["schema"] == "deployment-active-v1"
        )
        _require(
            all(
                isinstance(record[k], str) and re.fullmatch(r"[0-9a-f]{64}", record[k])
                for k in ("plan_sha256", "profile_sha256")
            )
        )
        _require(
            record["plan_sha256"]
            == os.environ.get("BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256")
        )
    except (OSError, ValueError, TypeError) as error:
        raise LifecycleLockError("inherited_lifecycle_lock_invalid") from error


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _process(proc: Path, pid: int) -> tuple[int, int]:
    """Return parent PID and start ticks; transient S/R state is not identity."""
    value = (proc / str(pid) / "stat").read_text()
    prefix, separator, tail = value.rpartition(") ")
    _require(bool(separator) and prefix.partition(" (")[0] == str(pid))
    fields = tail.split()
    _require(len(fields) >= 20 and fields[0] not in {"Z", "X", "x"})
    parent, started = int(fields[1]), int(fields[19])
    _require(parent >= 0 and started > 0)
    return parent, started


def _has_exclusive_lock(path: Path, info: os.stat_result) -> bool:
    expected = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
    for line in path.read_text().splitlines():
        match = LOCK_LINE.fullmatch(line.strip())
        if (
            match
            and (
                int(match[1], 16),
                int(match[2], 16),
                int(match[3]),
            )
            == expected
        ):
            return True
    return False


def _live_owner(
    proc: Path, borrower_pid: int, descriptor: int, info: os.stat_result
) -> int:
    seen: set[int] = set()
    chain: list[tuple[int, tuple[int, int]]] = []
    pid = borrower_pid
    for _ in range(256):
        _require(pid > 0 and pid not in seen)
        seen.add(pid)
        process = _process(proc, pid)
        chain.append((pid, process))
        directory = proc / str(pid)
        try:
            held = (directory / "fd" / str(descriptor)).stat()
            owns = _identity(held) == _identity(info) and _has_exclusive_lock(
                directory / "fdinfo" / str(descriptor), info
            )
        except FileNotFoundError:
            owns = False
        if owns:
            # A vanished/reused process or changed ancestry cannot supply proof.
            _require(all(_process(proc, item) == before for item, before in chain))
            return pid
        pid = process[0]
        if pid == 0:
            break
    raise LifecycleLockError("inherited_lifecycle_lock_invalid")


def verify_inherited_lock(
    install_dir: Path,
    descriptor: int,
    *,
    proc: Path = Path("/proc"),
    borrower_pid: int | None = None,
) -> int:
    """Verify without mutation; return the live holder PID proved by fdinfo.

    The verifier itself holds the borrowed descriptor, including when a shell
    tail-execs it and no parent retains that descriptor. `proc` permits an
    isolated fixture, never a CLI/env
    override. File and directory owners need not match: the standalone producer
    preserves existing UIDs/GIDs and imposes 0600/0700 without chown.
    """
    try:
        _require(type(descriptor) is int and 3 <= descriptor < 2**31)
        root = install_dir.resolve(strict=True)
        _require(root.is_dir())
        updates = root / "failed_updates"
        control = updates / "disaster-recovery"
        lock = control / "recovery.lock"
        block = control / "recovery-blocked"
        parents = (updates, control)
        before_parents = [path.lstat() for path in parents]
        _require(all(stat.S_ISDIR(info.st_mode) for info in before_parents))
        _require(stat.S_IMODE(before_parents[1].st_mode) == 0o700)
        _require(not block.exists() and not block.is_symlink())
        verify_active_operation(root)
        named, held = lock.lstat(), os.fstat(descriptor)
        _require(
            stat.S_ISREG(named.st_mode)
            and stat.S_IMODE(named.st_mode) == 0o600
            and named.st_nlink == 1
            and _identity(named) == _identity(held)
        )
        _require(os.pread(descriptor, 4096, 0).split(b"\n", 1)[0] != b"blocked")
        # fdinfo proves this open description owns the lock; another open() of
        # the same inode must fail. /proc/locks may omit a real inherited flock
        # whose acquiring utility has exited or is outside this PID namespace.
        _require(_has_exclusive_lock(proc / "self/fdinfo" / str(descriptor), held))
        borrower = os.getpid() if borrower_pid is None else borrower_pid
        owner = _live_owner(proc, borrower, descriptor, held)
        _require(
            _identity(lock.lstat()) == _identity(named)
            and _identity(os.fstat(descriptor)) == _identity(held)
            and all(
                _identity(path.lstat()) == _identity(before)
                for path, before in zip(parents, before_parents)
            )
            and not block.exists()
            and not block.is_symlink()
            and os.pread(descriptor, 4096, 0).split(b"\n", 1)[0] != b"blocked"
            and _has_exclusive_lock(proc / "self/fdinfo" / str(descriptor), held)
        )
        _require(_live_owner(proc, borrower, descriptor, held) == owner)
        return owner
    except (OSError, ValueError, IndexError) as error:
        raise LifecycleLockError("inherited_lifecycle_lock_invalid") from error


def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--active-marker":
            verify_active_operation(Path(sys.argv[2]))
            return 0
        _require(
            len(sys.argv) == 3
            and len(sys.argv[2]) <= 10
            and sys.argv[2].isascii()
            and sys.argv[2].isdigit()
        )
        verify_inherited_lock(Path(sys.argv[1]), int(sys.argv[2]))
    except LifecycleLockError:
        print("inherited_lifecycle_lock_invalid", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
