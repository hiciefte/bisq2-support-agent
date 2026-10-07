"""Read-only ownership predicates; real Linux flock tests are explicit below."""

import fcntl
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "scripts/lib/lifecycle_lock.py"
COMMON = REPO / "scripts/lib/common.sh"
SPEC = importlib.util.spec_from_file_location("lifecycle_lock", SOURCE)
assert SPEC is not None and SPEC.loader is not None
lock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lock)
pytestmark = pytest.mark.unit


def process_stat(pid, parent, started=500, state="S"):
    fields = [state, str(parent), *["0"] * 17, str(started)]
    return f"{pid} (fixture (name)) " + " ".join(fields) + "\n"


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "installation"
    control = root / "failed_updates/disaster-recovery"
    control.mkdir(parents=True, mode=0o700)
    named = control / "recovery.lock"
    descriptor = os.open(named, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(descriptor, b"ready\n")
    info = os.fstat(descriptor)
    proc = tmp_path / "proc-fixture"
    (proc / "self/fdinfo").mkdir(parents=True)
    (proc / "200/fdinfo").mkdir(parents=True)
    (proc / "200/fd").mkdir()
    (proc / "200/fd" / str(descriptor)).symlink_to(named)
    (proc / "200/stat").write_text(process_stat(200, 0))
    line = (
        "3: FLOCK ADVISORY WRITE 200 "
        f"{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino} 0 EOF\n"
    )
    (proc / "locks").write_text(line)
    (proc / "self/fdinfo" / str(descriptor)).write_text("lock:\t" + line)
    (proc / "200/fdinfo" / str(descriptor)).write_text("lock:\t" + line)
    value = SimpleNamespace(
        root=root,
        control=control,
        named=named,
        descriptor=descriptor,
        proc=proc,
        line=line,
    )
    try:
        yield value
    finally:
        os.close(descriptor)


def verify(fixture):
    return lock.verify_inherited_lock(
        fixture.root, fixture.descriptor, proc=fixture.proc, borrower_pid=200
    )


def test_proc_fixture_proves_fd_without_changing_file_or_offset(fixture):
    before = fixture.named.stat()
    offset = os.lseek(fixture.descriptor, 2, os.SEEK_SET)
    assert verify(fixture) == 200
    assert fixture.named.read_bytes() == b"ready\n"
    assert lock._identity(fixture.named.stat()) == lock._identity(before)
    assert os.lseek(fixture.descriptor, 0, os.SEEK_CUR) == offset


@pytest.mark.parametrize("which", ["self", "owner"])
def test_each_kernel_descriptor_and_live_owner_join_is_required(fixture, which):
    paths = {
        "self": fixture.proc / "self/fdinfo" / str(fixture.descriptor),
        "owner": fixture.proc / "200/fdinfo" / str(fixture.descriptor),
    }
    paths[which].write_text("")
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


@pytest.mark.parametrize("global_view", ["empty", "absent"])
def test_descriptor_proof_survives_namespace_hidden_global_lock(fixture, global_view):
    # Observed on the actual Linux fixture after the flock utility exited:
    # fdinfo retains FLOCK WRITE with PID 0 while /proc/locks is empty.
    if global_view == "empty":
        (fixture.proc / "locks").write_text("")
    else:
        (fixture.proc / "locks").unlink()
    line = fixture.line.replace("WRITE 200", "WRITE 0")
    for who in ("self", "200"):
        (fixture.proc / who / "fdinfo" / str(fixture.descriptor)).write_text(
            "lock:\t" + line
        )
    assert verify(fixture) == 200


def test_default_borrower_is_verifier_after_shell_exec(fixture, monkeypatch):
    monkeypatch.setattr(lock.os, "getpid", lambda: 200)
    monkeypatch.setattr(lock.os, "getppid", lambda: 999)
    assert (
        lock.verify_inherited_lock(fixture.root, fixture.descriptor, proc=fixture.proc)
        == 200
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("FLOCK ADVISORY WRITE", "FLOCK ADVISORY READ"),
        ("FLOCK", "POSIX"),
        ("FLOCK", "OFDLCK"),
        ("3: FLOCK", "3: -> FLOCK"),
        (" 0 EOF", " 1 EOF"),
    ],
)
def test_shared_waiting_or_nonflock_entries_are_not_ownership(fixture, before, after):
    (fixture.proc / "self/fdinfo" / str(fixture.descriptor)).write_text(
        "lock:\t" + fixture.line.replace(before, after)
    )
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


def test_live_ancestor_can_hold_inherited_open_description(fixture):
    owner = fixture.proc / "200"
    owner.rename(fixture.proc / "100")
    (fixture.proc / "100/stat").write_text(process_stat(100, 0, 400))
    (fixture.proc / "200").mkdir()
    (fixture.proc / "200/stat").write_text(process_stat(200, 100))
    assert verify(fixture) == 100


def test_unrelated_process_is_not_a_valid_owner(fixture):
    (fixture.proc / "200").rename(fixture.proc / "100")
    (fixture.proc / "100/stat").write_text(process_stat(100, 0))
    (fixture.proc / "200").mkdir()
    (fixture.proc / "200/stat").write_text(process_stat(200, 0))
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


def test_dead_or_reused_owner_is_rejected(fixture, monkeypatch):
    path = fixture.proc / "200/stat"
    path.write_text(process_stat(200, 0, state="Z"))
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)
    path.write_text(process_stat(200, 0))
    original = lock._process
    calls = 0

    def reused(proc, pid):
        nonlocal calls
        result = original(proc, pid)
        calls += 1
        return result if calls == 1 else (result[0], result[1] + 1)

    monkeypatch.setattr(lock, "_process", reused)
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


def test_transient_process_state_does_not_change_identity(fixture):
    before = lock._process(fixture.proc, 200)
    (fixture.proc / "200/stat").write_text(process_stat(200, 0, state="R"))
    assert lock._process(fixture.proc, 200) == before
    assert verify(fixture) == 200


@pytest.mark.parametrize("change", ["mode", "hardlink", "replaced", "symlink"])
def test_unsafe_or_replaced_named_lock_is_rejected(fixture, change):
    if change == "mode":
        fixture.named.chmod(0o640)
    elif change == "hardlink":
        os.link(fixture.named, fixture.named.with_name("extra-link"))
    else:
        moved = fixture.named.with_name("old-lock")
        fixture.named.rename(moved)
        if change == "replaced":
            fixture.named.write_bytes(b"ready\n")
            fixture.named.chmod(0o600)
        else:
            fixture.named.symlink_to(moved)
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


@pytest.mark.parametrize("change", ["mode", "symlink"])
def test_control_directory_is_private_and_not_symlinked(fixture, change):
    if change == "mode":
        fixture.control.chmod(0o750)
    else:
        moved = fixture.control.with_name("actual-control")
        fixture.control.rename(moved)
        fixture.control.symlink_to(moved, target_is_directory=True)
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


def test_lock_and_control_owners_need_not_match(fixture, monkeypatch):
    original = Path.lstat

    def different_owner(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path != fixture.control:
            return info
        # Existing standalone producer chmods without chown. This models a
        # legitimate independently owned control directory without host chown.
        fields = {
            name: getattr(info, name) for name in dir(info) if name.startswith("st_")
        }
        fields["st_uid"] = info.st_uid + 1000
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "lstat", different_owner)
    assert verify(fixture) == 200


@pytest.mark.parametrize("blocked", ["file", "broken_symlink", "sentinel"])
def test_recovery_block_is_never_bypassed(fixture, blocked):
    marker = fixture.control / "recovery-blocked"
    if blocked == "sentinel":
        os.pwrite(fixture.descriptor, b"blocked\n", 0)
    elif blocked == "file":
        marker.write_bytes(b"private failure")
    else:
        marker.symlink_to(fixture.control / "absent")
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


def test_metadata_change_during_proof_refuses(fixture, monkeypatch):
    original = lock._live_owner

    def changing(*args):
        owner = original(*args)
        fixture.named.chmod(0o640)
        return owner

    monkeypatch.setattr(lock, "_live_owner", changing)
    with pytest.raises(lock.LifecycleLockError):
        verify(fixture)


def test_shell_borrowed_branch_only_calls_verifier(tmp_path):
    log = tmp_path / "calls"
    program = f"""
set -euo pipefail
source "{COMMON}"
setup_colors
flock() {{ printf 'unexpected flock\n' >> "{log}"; return 90; }}
verify_inherited_production_lifecycle_lock() {{
    test "$1" = "{tmp_path}/must-not-be-created"
    printf 'verify:%s\n' "$BISQ_SUPPORT_LIFECYCLE_LOCK_FD" >> "{log}"
}}
export BISQ_SUPPORT_LIFECYCLE_LOCK_FD=202
acquire_production_lifecycle_lock "{tmp_path}/must-not-be-created"
"""
    result = subprocess.run(
        ["/bin/bash", "-c", program], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ["verify:202"]
    assert not (tmp_path / "must-not-be-created").exists()


def test_shell_rejects_unproved_borrow_without_changing_fd(tmp_path):
    path = tmp_path / "unlocked"
    path.write_bytes(b"untouched")
    program = f"""
set -euo pipefail
source "{COMMON}"
setup_colors
flock() {{ return 90; }}
exec 202<>"{path}"
export BISQ_SUPPORT_LIFECYCLE_LOCK_FD=202
if acquire_production_lifecycle_lock "{tmp_path}"; then exit 99; fi
test -e /dev/fd/202
test "$BISQ_SUPPORT_LIFECYCLE_LOCK_FD" = 202
"""
    before = path.stat()
    result = subprocess.run(
        ["/bin/bash", "-c", program], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Inherited production lifecycle lock is invalid" in result.stderr
    assert path.read_bytes() == b"untouched"
    assert lock._identity(path.stat()) == lock._identity(before)


def test_cli_refusal_is_closed_and_does_not_echo_paths():
    for arguments in ([], ["PRIVATE_SENTINEL", "bad"], ["PRIVATE_SENTINEL", "9" * 100]):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(SOURCE), *arguments],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert result.stdout == b""
        assert result.stderr == b"inherited_lifecycle_lock_invalid\n"


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux /proc/flock proof")
def test_linux_actual_standalone_and_inherited_shell_lock(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    program = f"""
set -euo pipefail
source "{COMMON}"
setup_colors
acquire_production_lifecycle_lock "{root}"
acquire_production_lifecycle_lock "{root}"
/bin/bash -c 'set -euo pipefail; source "$1"; setup_colors; acquire_production_lifecycle_lock "$2"' -- "{COMMON}" "{root}"
if flock -n "{root}/failed_updates/disaster-recovery/recovery.lock" true; then exit 91; fi
"""
    result = subprocess.run(
        ["/bin/bash", "-c", program], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert (
        root / "failed_updates/disaster-recovery/recovery.lock"
    ).stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux /proc/flock proof")
def test_linux_shell_exec_keeps_the_borrowed_open_description(tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    program = f"""
set -euo pipefail
source "{COMMON}"
setup_colors
acquire_production_lifecycle_lock "{root}"
exec python3 -I -B "{SOURCE}" "{root}" "$BISQ_SUPPORT_LIFECYCLE_LOCK_FD"
"""
    result = subprocess.run(
        ["/bin/bash", "-c", program], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux /proc/flock proof")
def test_linux_same_inode_without_inherited_open_description_is_rejected(tmp_path):
    root = tmp_path / "install"
    control = root / "failed_updates/disaster-recovery"
    control.mkdir(parents=True, mode=0o700)
    path = control / "recovery.lock"
    held = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    other = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(SOURCE), str(root), str(other)],
            pass_fds=(other,),
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 1
        # The failed verifier must not release the real parent's lock.
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)
        os.close(held)


@pytest.mark.skipif(sys.platform != "linux", reason="real Linux /proc/flock proof")
@pytest.mark.parametrize("kind", ["unlocked", "shared", "wrong_file"])
def test_linux_invalid_borrowed_descriptors_are_rejected(tmp_path, kind):
    root = tmp_path / "install"
    control = root / "failed_updates/disaster-recovery"
    control.mkdir(parents=True, mode=0o700)
    named = control / "recovery.lock"
    named.touch(mode=0o600)
    selected = named if kind != "wrong_file" else control / "other.lock"
    descriptor = os.open(selected, os.O_RDWR | os.O_CREAT, 0o600)
    other = os.open(selected, os.O_RDWR)
    try:
        if kind != "unlocked":
            mode = fcntl.LOCK_SH if kind == "shared" else fcntl.LOCK_EX
            fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
        before = lock._identity(os.fstat(descriptor))
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(SOURCE), str(root), str(descriptor)],
            pass_fds=(descriptor,),
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 1
        assert result.stderr == b"inherited_lifecycle_lock_invalid\n"
        assert lock._identity(os.fstat(descriptor)) == before
        if kind != "unlocked":
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)
        os.close(descriptor)
