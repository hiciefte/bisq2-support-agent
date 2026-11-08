"""Atomic public-wiki publication without silently changing reader access."""

import ctypes
import errno
import os
import stat
import sys


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
        info.st_uid,
        info.st_gid,
        info.st_mode,
    )


def replace_wiki_file(staged: str, destination: str) -> None:
    """Preserve owner/group, mode and access ACL, or leave destination untouched.

    Linux extended attributes and macOS extended ACLs are checked explicitly;
    unsupported platforms fail closed for an existing file. Timestamps are not
    copied: the index must still detect that wiki content changed. The caller
    owns cleanup of its staged file when this function raises.
    """
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
