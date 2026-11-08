"""Reader-access preservation and fail-closed atomic publication regressions."""

import os
import pwd
import stat
import struct
import subprocess
import sys
import tempfile
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
    target, staged = files(tmp_path)
    before = target.stat()
    wiki_atomic.replace_wiki_file(str(staged), str(target))
    after = target.stat()
    assert target.read_text() == "new complete corpus"
    assert (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)) == (
        before.st_uid,
        before.st_gid,
        0o640,
    )


def test_group_preservation_failure_never_publishes(tmp_path, monkeypatch):
    target, staged = files(tmp_path)
    real_stat = wiki_atomic.os.stat

    def staged_other_group(path, *args, **kwargs):
        value = real_stat(path, *args, **kwargs)
        if str(path) == str(staged):
            return SimpleNamespace(st_uid=value.st_uid, st_gid=value.st_gid + 10000)
        return value

    monkeypatch.setattr(wiki_atomic.os, "stat", staged_other_group)
    denied = Mock(side_effect=PermissionError("cannot preserve group"))
    monkeypatch.setattr(wiki_atomic.os, "chown", denied)
    with pytest.raises(PermissionError, match="preserve group"):
        wiki_atomic.replace_wiki_file(str(staged), str(target))
    assert target.read_text() == "old complete corpus"
    denied.assert_called_once_with(
        str(staged), target.lstat().st_uid, target.lstat().st_gid
    )


def test_linux_access_attributes_are_copied_and_verified(tmp_path, monkeypatch):
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
    wiki_atomic.replace_wiki_file(str(staged), str(target))
    assert attributes[str(staged)] == attributes[str(target)]


@pytest.mark.parametrize("failure", ["read", "write", "mismatch"])
def test_acl_failure_leaves_previous_corpus(tmp_path, monkeypatch, failure):
    target, staged = files(tmp_path)
    monkeypatch.setattr(wiki_atomic.sys, "platform", "linux")
    monkeypatch.setattr(
        wiki_atomic.os,
        "listxattr",
        lambda _: ["system.posix_acl_access"],
        raising=False,
    )

    def get(path, name):
        if failure == "read":
            raise PermissionError("ACL read denied")
        return b"old ACL" if str(path) == str(target) else b"wrong ACL"

    def set_value(*args):
        if failure == "write":
            raise PermissionError("ACL write denied")

    monkeypatch.setattr(wiki_atomic.os, "getxattr", get, raising=False)
    monkeypatch.setattr(wiki_atomic.os, "setxattr", set_value, raising=False)
    with pytest.raises(OSError):
        wiki_atomic.replace_wiki_file(str(staged), str(target))
    assert target.read_text() == "old complete corpus"


@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS ACL integration")
def test_native_darwin_extended_acl_survives(tmp_path):
    target, staged = files(tmp_path)
    username = pwd.getpwuid(os.getuid()).pw_name
    subprocess.run(
        ["/bin/chmod", "+a", f"user:{username} allow read", str(target)],
        check=True,
        capture_output=True,
    )
    original_acl = wiki_atomic._darwin_acl(str(target))
    wiki_atomic.replace_wiki_file(str(staged), str(target))
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
            processor.save_processed_content()
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
