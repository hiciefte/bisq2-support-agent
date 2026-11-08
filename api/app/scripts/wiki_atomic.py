"""Atomic public-wiki publication without silently changing reader access."""

import ctypes
import errno
import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from typing import Iterator


def _xattrs(path: str) -> dict[str, bytes]:
    """Read all Linux attributes, including POSIX/NFS ACL and security labels."""
    return {name: os.getxattr(path, name) for name in os.listxattr(path)}


def _darwin_acl(source: str, target: str | None = None) -> bytes:
    """Read/copy macOS extended ACL through libc; errors fail publication."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
    libc.acl_get_file.restype = ctypes.c_void_p
    libc.acl_set_file.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
    libc.acl_set_file.restype = ctypes.c_int
    libc.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
    libc.acl_to_text.restype = ctypes.c_void_p
    libc.acl_free.argtypes = [ctypes.c_void_p]
    libc.acl_free.restype = ctypes.c_int
    libc.acl_init.argtypes = [ctypes.c_int]
    libc.acl_init.restype = ctypes.c_void_p
    acl_type_extended = 0x100
    acl = libc.acl_get_file(os.fsencode(source), acl_type_extended)
    if not acl and ctypes.get_errno() == errno.ENOENT and os.path.isfile(source):
        # macOS reports ENOENT for a present file with no extended ACL. Copy an
        # explicitly empty ACL so inherited entries on the temporary cannot leak.
        acl = libc.acl_init(0)
    if not acl:
        raise OSError(ctypes.get_errno(), "Cannot read wiki file ACL")
    text = None
    try:
        length = ctypes.c_ssize_t()
        text = libc.acl_to_text(acl, ctypes.byref(length))
        if not text:
            raise OSError(ctypes.get_errno(), "Cannot inspect wiki file ACL")
        value = ctypes.string_at(text, length.value)
        if (
            target is not None
            and libc.acl_set_file(os.fsencode(target), acl_type_extended, acl) != 0
        ):
            raise OSError(ctypes.get_errno(), "Cannot preserve wiki file ACL")
        return value
    finally:
        if text:
            libc.acl_free(text)
        libc.acl_free(acl)


def _identity(info: os.stat_result) -> tuple:
    """Detect a destination changed while its staged replacement was prepared."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_ctime_ns,
        info.st_mtime_ns,
        info.st_size,
        info.st_uid,
        info.st_gid,
        info.st_mode,
    )


class WikiPublicationConflictError(OSError):
    """The source or destination changed since acquisition/rendering began."""


class WikiPublicationDurabilityError(OSError):
    """Replacement is visible but directory durability could not be confirmed.

    Callers must report uncertainty, not claim the previous file was retained or
    retry/rollback automatically. The staged pathname has already been consumed.
    """

    published = True


def capture_wiki_preimage(path: str) -> tuple | None:
    """Capture the destination/source identity before fetching or rendering.

    This is an overlap/CAS token, not a semantic MediaWiki revision number.
    An absent destination is a meaningful preimage; symlinks are not accepted.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Wiki source/destination must be a regular file")
    return _identity(info)


@contextmanager
def _publication_directory(destination: str) -> Iterator[int]:
    """Serialize cooperating wiki publishers across processes and threads.

    The stable lock is never unlinked: replacing a lock inode would split the
    serialization domain. Contention refuses immediately rather than waiting or
    retrying a staged result. Open read-only so a later authorized writer with a
    different UID can flock the same lock without changing its ownership.
    """
    parent = os.path.realpath(os.path.dirname(os.path.abspath(destination)))
    directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            lock_fd = os.open(
                ".wiki-publication.lock",
                flags | os.O_CREAT | os.O_EXCL,
                0o644,
                dir_fd=directory_fd,
            )
            os.fchmod(lock_fd, 0o644)
        except FileExistsError:
            lock_fd = os.open(".wiki-publication.lock", flags, dir_fd=directory_fd)
        lock = os.fstat(lock_fd)
        directory = os.fstat(directory_fd)
        if (
            not stat.S_ISREG(lock.st_mode)
            or lock.st_nlink != 1
            or stat.S_IMODE(lock.st_mode) != 0o644
        ):
            raise OSError("Unsafe wiki publication lock")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WikiPublicationConflictError(
                "Another wiki publication is in progress; staged result not published"
            ) from error
        current = os.stat(
            ".wiki-publication.lock", dir_fd=directory_fd, follow_symlinks=False
        )
        if (current.st_dev, current.st_ino) != (lock.st_dev, lock.st_ino):
            raise OSError("Wiki publication lock changed")
        path_directory = os.stat(parent, follow_symlinks=False)
        if (path_directory.st_dev, path_directory.st_ino) != (
            directory.st_dev,
            directory.st_ino,
        ):
            raise OSError("Wiki publication directory changed")
        yield directory_fd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(directory_fd)


def _preserve_and_replace(staged: str, destination: str) -> None:
    """Preserve reader access and fsync staged content under publication lock."""
    try:
        previous = os.lstat(destination)
    except FileNotFoundError:
        previous = None
    if previous is None:
        os.chmod(staged, 0o644)
    else:
        if not stat.S_ISREG(previous.st_mode):
            raise ValueError("Wiki destination must be a regular file")
        if sys.platform not in {"linux", "darwin"}:
            raise OSError("Cannot verify wiki access ACL on this platform")
        attributes = _xattrs(destination) if sys.platform == "linux" else None
        acl = _darwin_acl(destination) if sys.platform == "darwin" else None
        current = os.stat(staged)
        if (current.st_uid, current.st_gid) != (previous.st_uid, previous.st_gid):
            os.chown(staged, previous.st_uid, previous.st_gid)
        os.chmod(staged, stat.S_IMODE(previous.st_mode) & 0o777)
        if attributes is not None:
            for name in os.listxattr(staged):
                if name not in attributes:
                    os.removexattr(staged, name)
            for name, value in attributes.items():
                os.setxattr(staged, name, value)
            if _xattrs(staged) != attributes:
                raise OSError("Wiki replacement attributes/ACL differ")
        else:
            _darwin_acl(destination, staged)
            if _darwin_acl(staged) != acl:
                raise OSError("Wiki replacement ACL differs")
        access = os.stat(staged)
        if (access.st_uid, access.st_gid, stat.S_IMODE(access.st_mode) & 0o777) != (
            previous.st_uid,
            previous.st_gid,
            stat.S_IMODE(previous.st_mode) & 0o777,
        ):
            raise OSError("Wiki replacement owner/group/mode differ")
        if _identity(os.lstat(destination)) != _identity(previous):
            raise OSError("Wiki destination changed before publication")
    # Metadata changes must be durable as well as previously fsynced content.
    with open(staged, "rb") as handle:
        os.fsync(handle.fileno())
    if previous is None and os.path.lexists(destination):
        raise OSError("Wiki destination appeared before publication")
    os.replace(staged, destination)


def replace_wiki_file(
    staged: str,
    destination: str,
    *,
    expected_preimage: tuple | None,
    expected_sources: dict[str, tuple | None] | None = None,
) -> None:
    """Publish only against the pre-fetch/render identity, with durable rename.

    All cooperating writers in the wiki directory share a short publication
    lock. The token must be captured BEFORE expensive acquisition/processing;
    taking it here would let an older staged result replace a finished update.
    Sources are checked under the same lock (the live XML/JSONL share a parent).
    External offline input files are read-only dependencies, not a cross-folder
    transaction. No semantic freshness is inferred for content fetched after a
    completed update or for noncooperating external writers.

    Before replacement, errors retain the destination. After replacement, a
    directory-fsync failure raises WikiPublicationDurabilityError explicitly.
    Existing owner/group/mode/ACL preservation remains mandatory and fail-closed.
    """
    destination = os.path.abspath(destination)
    if os.path.realpath(os.path.dirname(os.path.abspath(staged))) != os.path.realpath(
        os.path.dirname(destination)
    ):
        raise ValueError("Wiki staging must share the destination directory")
    with _publication_directory(destination) as directory_fd:
        if capture_wiki_preimage(destination) != expected_preimage:
            raise WikiPublicationConflictError(
                "Wiki destination changed before publication"
            )
        for path, expected in (expected_sources or {}).items():
            if capture_wiki_preimage(path) != expected:
                raise WikiPublicationConflictError(
                    "Wiki source changed before publication"
                )
        _preserve_and_replace(staged, destination)
        try:
            os.fsync(directory_fd)
        except OSError as error:
            raise WikiPublicationDurabilityError(
                "Wiki destination was replaced; directory durability is uncertain"
            ) from error
