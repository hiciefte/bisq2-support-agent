"""Reader-access preservation and fail-closed atomic publication regressions."""

import os
import pwd
import stat
import struct
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.scripts import download_bisq2_media_wiki as downloader
from app.scripts import wiki_atomic
from app.scripts.process_wiki_dump import WikiDumpProcessor

pytestmark = pytest.mark.unit


def files(tmp_path):
    """Create an existing protected corpus and a complete staged replacement."""
    target, staged = tmp_path / "target", tmp_path / "staged"
    target.write_text("old complete corpus")
    target.chmod(0o640)
    staged.write_text("new complete corpus")
    staged.chmod(0o600)
    return target, staged


def test_atomic_replacement_preserves_actual_owner_group_mode(tmp_path):
    """Replacing content retains the real existing reader identity and access bits."""
    target, staged = files(tmp_path)
    before = target.stat()
    wiki_atomic.replace_wiki_file(
        str(staged),
        str(target),
        expected_preimage=wiki_atomic.capture_wiki_preimage(str(target)),
    )
    after = target.stat()
    assert target.read_text() == "new complete corpus"
    assert (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)) == (
        before.st_uid,
        before.st_gid,
        0o640,
    )


def test_group_preservation_failure_never_publishes(tmp_path, monkeypatch):
    """A failed ownership transfer cannot expose a replacement with narrower access."""
    target, staged = files(tmp_path)
    real_stat = wiki_atomic.os.stat

    def staged_other_group(path, *args, **kwargs):
        """Simulate staging under a different primary group than the existing corpus."""
        value = real_stat(path, *args, **kwargs)
        if str(path) == str(staged):
            return SimpleNamespace(st_uid=value.st_uid, st_gid=value.st_gid + 10000)
        return value

    monkeypatch.setattr(wiki_atomic.os, "stat", staged_other_group)
    denied = Mock(side_effect=PermissionError("cannot preserve group"))
    monkeypatch.setattr(wiki_atomic.os, "chown", denied)
    with pytest.raises(PermissionError, match="preserve group"):
        wiki_atomic.replace_wiki_file(
            str(staged),
            str(target),
            expected_preimage=wiki_atomic.capture_wiki_preimage(str(target)),
        )
    assert target.read_text() == "old complete corpus"
    denied.assert_called_once_with(
        str(staged), target.lstat().st_uid, target.lstat().st_gid
    )


def test_linux_access_attributes_are_copied_and_verified(tmp_path, monkeypatch):
    """Copy both access ACL and security context, removing inherited extras."""
    target, staged = files(tmp_path)
    attributes = {
        str(target): {
            "system.posix_acl_access": b"original ACL",
            "security.selinux": b"original context",
        },
        str(staged): {
            "system.posix_acl_access": b"inherited ACL",
            "user.extra": b"temporary",
        },
    }
    monkeypatch.setattr(wiki_atomic.sys, "platform", "linux")
    monkeypatch.setattr(
        wiki_atomic.os,
        "listxattr",
        lambda path: list(attributes[str(path)]),
        raising=False,
    )
    monkeypatch.setattr(
        wiki_atomic.os,
        "getxattr",
        lambda path, name: attributes[str(path)][name],
        raising=False,
    )
    monkeypatch.setattr(
        wiki_atomic.os,
        "setxattr",
        lambda path, name, value: attributes[str(path)].__setitem__(name, value),
        raising=False,
    )
    monkeypatch.setattr(
        wiki_atomic.os,
        "removexattr",
        lambda path, name: attributes[str(path)].pop(name),
        raising=False,
    )
    wiki_atomic.replace_wiki_file(
        str(staged),
        str(target),
        expected_preimage=wiki_atomic.capture_wiki_preimage(str(target)),
    )
    assert attributes[str(staged)] == attributes[str(target)]


@pytest.mark.parametrize("failure", ["read", "write", "mismatch"])
def test_acl_failure_leaves_previous_corpus(tmp_path, monkeypatch, failure):
    """Reading, writing or verifying ACL failures all retain the prior complete file."""
    target, staged = files(tmp_path)
    monkeypatch.setattr(wiki_atomic.sys, "platform", "linux")
    monkeypatch.setattr(
        wiki_atomic.os,
        "listxattr",
        lambda _: ["system.posix_acl_access"],
        raising=False,
    )

    def get(path, name):
        """Simulate denied ACL reads or a mismatching replacement ACL."""
        if failure == "read":
            raise PermissionError("ACL read denied")
        return b"old ACL" if str(path) == str(target) else b"wrong ACL"

    def set_value(*args):
        """Simulate an OS refusing to apply the required access ACL."""
        if failure == "write":
            raise PermissionError("ACL write denied")

    monkeypatch.setattr(wiki_atomic.os, "getxattr", get, raising=False)
    monkeypatch.setattr(wiki_atomic.os, "setxattr", set_value, raising=False)
    with pytest.raises(OSError):
        wiki_atomic.replace_wiki_file(
            str(staged),
            str(target),
            expected_preimage=wiki_atomic.capture_wiki_preimage(str(target)),
        )
    assert target.read_text() == "old complete corpus"


@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS ACL integration")
def test_native_darwin_extended_acl_survives(tmp_path):
    """Exercise a real macOS named-user ACL across the replacement inode."""
    target, staged = files(tmp_path)
    username = pwd.getpwuid(os.getuid()).pw_name
    subprocess.run(
        ["/bin/chmod", "+a", f"user:{username} allow read", str(target)],
        check=True,
        capture_output=True,
    )
    original_acl = wiki_atomic._darwin_acl(str(target))
    wiki_atomic.replace_wiki_file(
        str(staged),
        str(target),
        expected_preimage=wiki_atomic.capture_wiki_preimage(str(target)),
    )
    assert wiki_atomic._darwin_acl(str(target)) == original_acl


@pytest.mark.skipif(
    sys.platform != "linux" or os.geteuid() != 0,
    reason="Needs root Linux test container to create a genuinely separate group-only reader",
)
@pytest.mark.parametrize("writer", ["processor", "downloader"])
@pytest.mark.parametrize("access_kind", ["group", "named-user-acl"])
def test_separate_group_only_reader_retains_access_after_both_writers(
    writer, access_kind, monkeypatch
):
    """Exercise OS access, not just mode bits, without touching external data."""
    with tempfile.TemporaryDirectory(
        prefix="wiki-group-reader-", dir="/tmp"
    ) as directory:
        root = Path(directory)
        root.chmod(0o755)
        target = root / (
            "processed_wiki.jsonl" if writer == "processor" else "bisq2_dump.xml"
        )
        target.write_text("old corpus")
        if access_kind == "group":
            os.chown(target, 0, 65534)
            target.chmod(0o640)
        else:
            # Linux POSIX ACL xattr: owner rw, named uid65534 r, group none,
            # mask r, others none. No setfacl package or external tooling.
            acl = struct.pack("<I", 2) + b"".join(
                struct.pack("<HHI", tag, permissions, identifier)
                for tag, permissions, identifier in [
                    (1, 6, 0xFFFFFFFF),
                    (2, 4, 65534),
                    (4, 0, 0xFFFFFFFF),
                    (16, 4, 0xFFFFFFFF),
                    (32, 0, 0xFFFFFFFF),
                ]
            )
            os.setxattr(target, "system.posix_acl_access", acl)

        def read_as_group():
            """Attempt the actual read as a different UID/GID without supplementary groups."""
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import os,sys; os.setgroups([]); os.setgid(65534); os.setuid(65534); assert open(sys.argv[1]).read()",
                    str(target),
                ],
                capture_output=True,
            ).returncode

        assert read_as_group() == 0
        if writer == "processor":
            processor = WikiDumpProcessor("unused.xml", str(target))
            processor.context["general"] = [
                {"title": "Example", "content": "new corpus", "category": "general"}
            ]
            processor.save_processed_content(
                wiki_atomic.capture_wiki_preimage(str(target)),
                str(root / "unused.xml"),
                None,
            )
        else:
            import time

            page = SimpleNamespace(
                name="Example",
                namespace=0,
                pageid=1,
                revisions=lambda **_: iter(
                    [{"revid": 1, "timestamp": time.gmtime(0), "*": "new corpus"}]
                ),
            )
            monkeypatch.setattr(
                downloader.mwclient,
                "Site",
                lambda *_, **__: SimpleNamespace(
                    allpages=lambda namespace: [page] if namespace == 0 else []
                ),
            )
            monkeypatch.setattr(downloader.time, "sleep", lambda _: None)
            downloader.main(str(root))
        if access_kind == "group":
            assert target.stat().st_gid == 65534
        else:
            assert os.getxattr(target, "system.posix_acl_access") == acl
        assert read_as_group() == 0


def test_stale_acquisition_cannot_replace_completed_newer_process(tmp_path):
    """An older invocation retains its early token across a newer publication."""
    target, older = files(tmp_path)
    newer = tmp_path / "newer"
    newer.write_text("newer invocation completed")
    script = """
import sys
from app.scripts.wiki_atomic import capture_wiki_preimage, replace_wiki_file, WikiPublicationConflictError
token = capture_wiki_preimage(sys.argv[1])
print('ready', flush=True)
sys.stdin.readline()
try:
    replace_wiki_file(sys.argv[2], sys.argv[1], expected_preimage=token)
except WikiPublicationConflictError:
    print('stale refused', flush=True)
else:
    raise AssertionError('stale acquisition replaced completed newer publication')
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(target), str(older)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        token = wiki_atomic.capture_wiki_preimage(str(target))
        wiki_atomic.replace_wiki_file(str(newer), str(target), expected_preimage=token)
        stdout, stderr = process.communicate("continue\n", timeout=10)
        assert process.returncode == 0, stderr
        assert stdout.strip() == "stale refused"
        assert target.read_text() == "newer invocation completed"
        assert older.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize("exists", [True, False])
def test_concurrent_same_preimage_publishers_have_one_winner(tmp_path, exists):
    """The CAS and rename are serialized even when both workers are ready."""
    target = tmp_path / "target"
    if exists:
        target.write_text("original")
    token = wiki_atomic.capture_wiki_preimage(str(target))
    barrier = threading.Barrier(3)

    def publish(index):
        """Stage independently, then race publication with the shared early token."""
        staged = tmp_path / f"staged-{index}"
        staged.write_text(str(index))
        barrier.wait(timeout=10)
        try:
            wiki_atomic.replace_wiki_file(
                str(staged), str(target), expected_preimage=token
            )
        except wiki_atomic.WikiPublicationConflictError:
            return "conflict"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(publish, index) for index in range(2)]
        barrier.wait(timeout=10)
        outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == ["conflict", "published"]
    assert target.read_text() == str(outcomes.index("published"))


def test_changed_processing_input_refuses_output(tmp_path):
    """A live XML change during rendering must not publish the stale JSONL."""
    target, staged = files(tmp_path)
    source = tmp_path / "bisq2_dump.xml"
    source.write_text("old XML")
    token = wiki_atomic.capture_wiki_preimage(str(target))
    source_token = wiki_atomic.capture_wiki_preimage(str(source))
    source.write_text("updated XML")
    with pytest.raises(
        wiki_atomic.WikiPublicationConflictError, match="source changed"
    ):
        wiki_atomic.replace_wiki_file(
            str(staged),
            str(target),
            expected_preimage=token,
            expected_sources={str(source): source_token},
        )
    assert target.read_text() == "old complete corpus"
    assert staged.exists()


def test_file_fsync_failure_before_rename_retains_destination(tmp_path, monkeypatch):
    """A pre-replace durability error leaves the prior pathname and staging intact."""
    target, staged = files(tmp_path)
    token = wiki_atomic.capture_wiki_preimage(str(target))

    def fail_file_sync(fd):
        """Refuse file synchronization before the publication rename occurs."""
        raise OSError("file fsync failed")

    monkeypatch.setattr(wiki_atomic.os, "fsync", fail_file_sync)
    with pytest.raises(OSError, match="file fsync failed") as error:
        wiki_atomic.replace_wiki_file(str(staged), str(target), expected_preimage=token)
    assert not isinstance(error.value, wiki_atomic.WikiPublicationDurabilityError)
    assert target.read_text() == "old complete corpus"
    assert staged.exists()


def test_directory_fsync_failure_reports_published_uncertainty(tmp_path, monkeypatch):
    """A post-rename fsync error must not falsely promise the old file survived."""
    target, staged = files(tmp_path)
    token = wiki_atomic.capture_wiki_preimage(str(target))
    original = os.fsync

    def fail_directory_sync(fd):
        """Only fail the parent-directory sync after the file sync and rename."""
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory fsync failed")
        original(fd)

    monkeypatch.setattr(wiki_atomic.os, "fsync", fail_directory_sync)
    with pytest.raises(
        wiki_atomic.WikiPublicationDurabilityError, match="was replaced"
    ) as error:
        wiki_atomic.replace_wiki_file(str(staged), str(target), expected_preimage=token)
    assert error.value.published is True
    assert isinstance(error.value.__cause__, OSError)
    assert target.read_text() == "new complete corpus"
    assert not staged.exists()


def test_success_fsyncs_file_then_replaces_then_syncs_parent(tmp_path, monkeypatch):
    """Successful return includes a parent sync after the visible rename."""
    target, staged = files(tmp_path)
    token = wiki_atomic.capture_wiki_preimage(str(target))
    real_sync, real_replace = os.fsync, os.replace
    events = []

    def sync(fd):
        """Record whether the persisted descriptor is a file or its directory."""
        events.append("directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        return real_sync(fd)

    def replace(source, destination):
        """Mark the exact point at which the replacement becomes visible."""
        events.append("replace")
        return real_replace(source, destination)

    monkeypatch.setattr(wiki_atomic.os, "fsync", sync)
    monkeypatch.setattr(wiki_atomic.os, "replace", replace)
    wiki_atomic.replace_wiki_file(str(staged), str(target), expected_preimage=token)
    assert events == ["file", "replace", "directory"]


def test_unsafe_lock_does_not_modify_destination(tmp_path):
    """A substituted lock pathname cannot split the publication lock domain."""
    target, staged = files(tmp_path)
    (tmp_path / ".wiki-publication.lock").symlink_to(target)
    token = wiki_atomic.capture_wiki_preimage(str(target))
    with pytest.raises(OSError):
        wiki_atomic.replace_wiki_file(str(staged), str(target), expected_preimage=token)
    assert target.read_text() == "old complete corpus"
