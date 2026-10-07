"""Canonical encrypted export, bounded transfer and full isolated restore.

The caller owns authorization and the deployment journal. This module has no SSH,
provider or arbitrary-command interface. Interrupted local receives/restores retain
an exclusive intent and cannot be repeated; their files are reconciliation evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from lib.deployment_journal import (
    JournalError,
    exclusive_record,
    is_digest,
    now,
    read_record,
    require,
    timestamp,
)
from lib.deployment_protocol import (
    VERIFIER_HELPERS,
    canonical_sha256,
    make_receive_receipt,
    validate_profile,
    validate_receive_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
MAX_FRAME = 1024 * 1024


def _directory(path: Path, *, create: bool = False) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
    require(path.is_absolute() and path.resolve() == path, "recovery_directory")
    st = path.lstat()
    require(
        stat.S_ISDIR(st.st_mode)
        and st.st_uid == os.geteuid()
        and stat.S_IMODE(st.st_mode) == 0o700,
        "recovery_directory",
    )
    return path


def _file(path: Path, *, private: bool = False) -> tuple[str, int]:
    require(
        path.is_absolute() and path.resolve() == path and "," not in str(path),
        "recovery_file",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "recovery_file")
        if private:
            require(
                st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == 0o600,
                "recovery_private_file",
            )
        return hashlib.file_digest(stream, "sha256").hexdigest(), st.st_size


def _metadata(path: Path) -> None:
    # Intentionally do not read key contents during preflight.
    require(path.is_absolute() and path.resolve() == path, "recovery_key")
    st = path.lstat()
    require(
        stat.S_ISREG(st.st_mode)
        and st.st_uid == os.geteuid()
        and st.st_nlink == 1
        and st.st_size > 0
        and stat.S_IMODE(st.st_mode) == 0o600,
        "recovery_key",
    )


def _helpers(root: Path, profile: dict) -> None:
    pins = profile["recovery"]["expected_helper_sha256"]
    require(set(pins) == VERIFIER_HELPERS, "recovery_helpers")
    for name, pin in pins.items():
        require(_file(root / name)[0] == pin, "recovery_helper_changed")


def _remaining(profile: dict, binding: dict) -> float:
    require(
        set(binding)
        == {"plan_sha256", "profile_sha256", "phase", "intent_sha256", "deadline"},
        "recovery_binding",
    )
    require(
        all(
            is_digest(binding[key])
            for key in ("plan_sha256", "profile_sha256", "intent_sha256")
        )
        and binding["profile_sha256"] == canonical_sha256(profile)
        and binding["phase"]
        in {
            "prechange_backup",
            "postchange_backup",
            "prechange_restore",
            "postchange_restore",
        },
        "recovery_binding",
    )
    seconds = (timestamp(binding["deadline"]) - timestamp(now())).total_seconds()
    require(seconds > 0, "effect_deadline")
    return min(seconds, profile["phase_timeout_seconds"])


def _env() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _docker(
    profile: dict,
    args: list[str],
    *,
    timeout: float = 30,
    output=None,
    config: Path | None = None,
) -> bytes:
    runtime = profile["recovery"]["verifier_runtime"]
    require(
        _file(Path(runtime["docker_executable"]))[0]
        == runtime["docker_executable_sha256"],
        "recovery_docker_changed",
    )
    argv = [
        runtime["docker_executable"],
        "--host",
        "unix://" + runtime["docker_socket"],
    ]
    if config:
        argv += ["--config", str(config)]
    # No caller environment, Docker context, remote daemon or credential helper.
    try:
        result = subprocess.run(
            argv + args,
            env=_env(),
            stdin=subprocess.DEVNULL,
            stdout=output or subprocess.PIPE,
            stderr=output or subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise JournalError("recovery_docker_uncertain") from error
    require(result.returncode == 0, "recovery_docker_failed")
    return result.stdout or b""


def preflight_recovery(profile: dict) -> dict:
    """Read local metadata and run a disposable, networkless public-tool probe."""
    validate_profile(profile)
    recovery = profile["recovery"]
    runtime = recovery["verifier_runtime"]
    _directory(Path(recovery["local_directory"]))
    _metadata(Path(recovery["identity_file"]))
    _helpers(Path(recovery["verifier_repository"]), profile)
    socket = Path(runtime["docker_socket"])
    require(
        socket.is_absolute() and stat.S_ISSOCK(socket.stat().st_mode),
        "recovery_docker_socket",
    )
    for key in ("runtime_image_id", "api_image_id", "qdrant_image_id"):
        result = json.loads(_docker(profile, ["image", "inspect", runtime[key]]))
        require(
            isinstance(result, list)
            and len(result) == 1
            and result[0]["Id"] == runtime[key],
            "recovery_image_changed",
        )
    # No private data, key, source or daemon socket is mounted in this probe.
    name = "bisq-recovery-tools-" + os.urandom(12).hex()
    with tempfile.TemporaryDirectory(prefix="bisq-recovery-probe-") as temporary:
        config = Path(temporary)
        os.chmod(config, 0o700)
        cidfile = config / "container.id"
        try:
            _docker(
                profile,
                [
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--cidfile",
                    str(cidfile),
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--user",
                    f'{runtime["uid"]}:{runtime["gid"]}',
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,size=16m",
                    "--entrypoint",
                    "/bin/bash",
                    runtime["runtime_image_id"],
                    "-ec",
                    (
                        "command -v bash python3 docker tar flock "
                        + ("gpg gpgconf" if recovery["encryption"] == "gpg" else "age")
                        + " >/dev/null"
                    ),
                ],
                timeout=30,
                config=config,
            )
        except JournalError:
            # No retry. An unresolved probe launch is not tooling readiness.
            _remove_outer(profile, cidfile, name, config)
            raise
    return {
        "local_tooling_ready": True,
        "key_metadata_checked": True,
        "runtime_image_id": runtime["runtime_image_id"],
    }


def preflight_capture(profile: dict) -> dict:
    """Validate ordinary backup inputs before a scheduler pause or writer stop."""
    validate_profile(profile)
    _helpers(ROOT, profile)
    recovery = profile["recovery"]
    _directory(Path(recovery["export_directory"]))
    _file(Path(recovery["recipient_file"]))
    recipient = Path(recovery["recipient_file"]).read_text().strip()
    require(
        (
            bool(re.fullmatch(r"(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})", recipient))
            if recovery["encryption"] == "gpg"
            else bool(re.fullmatch(r"age1[0-9a-z]{20,100}", recipient))
        ),
        "recovery_recipient",
    )
    env = _env() | {
        "BISQ_SUPPORT_INSTALL_DIR": profile["host"]["repository"],
        "COMPOSE_PROJECT_NAME": profile["host"]["compose_project"],
        "COMPOSE_FILE": profile["host"]["compose_file"],
    }
    for key in ("HOME", "GNUPGHOME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    # These are the ordinary script's read-only argument/configuration checks.
    # No main, lifecycle acquisition, snapshots, encryption or retention runs.
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1"; shift; parse_args "$@"; initialize_paths; validate_configuration; capture_backup_target_identity',
            "backup-preflight",
            str(ROOT / "scripts/backup.sh"),
            "--export-dir",
            recovery["export_directory"],
            "--encryption",
            recovery["encryption"],
            "--recipient",
            recipient,
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=min(30, profile["phase_timeout_seconds"]),
        check=False,
    )
    require(result.returncode == 0, "recovery_capture_preflight")
    return {
        "capture_inputs_ready": True,
        "destination_kind": "same_host_encrypted_export",
    }


def _capture_run(
    argv: list[str], *, env: dict, pass_fds: tuple[int, ...], stdout, timeout: float
) -> subprocess.Popen:
    """Contain local snapshot/encryption descendants without replaying an effect."""
    try:
        child = subprocess.Popen(
            argv,
            env=env,
            pass_fds=pass_fds,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise JournalError("recovery_capture_uncertain") from error

    def contain() -> None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The leader may have exited while a child ignores TERM and still holds
        # the borrowed lock. Always kill the remaining group, not just the leader.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=2)

    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        contain()
        raise JournalError("recovery_capture_uncertain") from error
    except BaseException:
        contain()
        raise
    return child


def capture_backup(profile: dict, attempt_dir: Path, binding: dict) -> dict:
    validate_profile(profile)
    timeout = _remaining(profile, binding)
    require(binding["phase"].endswith("_backup"), "recovery_phase")
    attempt = _directory(attempt_dir, create=True)
    _helpers(ROOT, profile)
    recovery = profile["recovery"]
    destination = _directory(Path(recovery["export_directory"]))
    recipient_path = Path(recovery["recipient_file"])
    _file(recipient_path)
    recipient = recipient_path.read_text().strip()
    require(
        (
            bool(re.fullmatch(r"(?:[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64})", recipient))
            if recovery["encryption"] == "gpg"
            else bool(re.fullmatch(r"age1[0-9a-z]{20,100}", recipient))
        ),
        "recovery_recipient",
    )
    canonical = attempt / "canonical-backup.json"
    # A caller's journal guards dispatch; this local marker also blocks direct
    # re-entry after interruption before a receipt has been returned.
    exclusive_record(attempt / "capture-intent.json", binding)
    env = _env() | {
        "BISQ_SUPPORT_INSTALL_DIR": profile["host"]["repository"],
        "COMPOSE_PROJECT_NAME": profile["host"]["compose_project"],
        "COMPOSE_FILE": profile["host"]["compose_file"],
        "TMPDIR": str(attempt),
    }
    inherited = os.environ.get("BISQ_SUPPORT_LIFECYCLE_LOCK_FD", "")
    require(inherited.isdigit(), "recovery_inherited_lock_required")
    env["BISQ_SUPPORT_LIFECYCLE_LOCK_FD"] = inherited
    plan_owner = os.environ.get("BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256")
    if plan_owner is not None:
        require(plan_owner == binding["plan_sha256"], "recovery_owner_plan")
        env["BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256"] = plan_owner
    if recovery["encryption"] == "gpg":
        # Public encryption keyring location is ordinary operator configuration;
        # no private key is needed or transferred to this host.
        if os.environ.get("GNUPGHOME"):
            env["GNUPGHOME"] = os.environ["GNUPGHOME"]
        if os.environ.get("HOME"):
            env["HOME"] = os.environ["HOME"]
    with _private_log(attempt / "backup.log") as log:
        try:
            result = _capture_run(
                [
                    "/bin/bash",
                    str(ROOT / "scripts/backup.sh"),
                    "--export-dir",
                    str(destination),
                    "--encryption",
                    recovery["encryption"],
                    "--recipient",
                    recipient,
                    "--receipt",
                    str(canonical),
                ],
                env=env,
                pass_fds=(int(inherited),),
                stdout=log,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise JournalError("recovery_capture_uncertain") from error
    require(result.returncode == 0, "recovery_capture_failed")
    _remaining(profile, binding)
    record = read_record(canonical)
    require(
        set(record)
        == {
            "schema",
            "ciphertext_name",
            "ciphertext_sha256",
            "ciphertext_bytes",
            "destination_kind",
            "writers_resumed",
            "scratch_cleanup_verified",
        }
        and record["schema"] == "canonical-backup-v1"
        and record["destination_kind"] == "same_host_encrypted_export"
        and record["writers_resumed"] is True
        and record["scratch_cleanup_verified"] is True,
        "recovery_capture_receipt",
    )
    require(
        re.fullmatch(
            r"bisq-support-backup-[A-Za-z0-9_.-]+\.tar\.gz\.(age|gpg)",
            record["ciphertext_name"],
        )
        is not None,
        "recovery_ciphertext_name",
    )
    require(
        _file(destination / record["ciphertext_name"], private=True)
        == (record["ciphertext_sha256"], record["ciphertext_bytes"]),
        "recovery_ciphertext_changed",
    )
    return {
        key: record[key]
        for key in (
            "ciphertext_name",
            "ciphertext_sha256",
            "ciphertext_bytes",
            "destination_kind",
            "writers_resumed",
        )
    } | {"canonical_backup_receipt_sha256": _file(canonical)[0]}


def _private_log(path: Path):
    return os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    )


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def receive_ciphertext(
    profile: dict,
    attempt_dir: Path,
    export_receipt: dict,
    stream: Iterable[bytes],
    binding: dict,
) -> dict:
    validate_profile(profile)
    _remaining(profile, binding)
    require(binding["phase"].endswith("_restore"), "recovery_phase")
    require(
        export_receipt["plan_sha256"] == binding["plan_sha256"]
        and export_receipt["profile_sha256"] == binding["profile_sha256"]
        and export_receipt["phase"] == binding["phase"].replace("_restore", "_backup"),
        "recovery_export_binding",
    )
    received = make_receive_receipt(export_receipt)
    validate_receive_receipt(received, export_receipt)
    attempt = _directory(attempt_dir, create=True)
    require(
        attempt.is_relative_to(Path(profile["recovery"]["local_directory"])),
        "recovery_local_path",
    )
    exclusive_record(
        attempt / "receive-intent.json",
        binding | {"export_receipt_sha256": canonical_sha256(export_receipt)},
    )
    exclusive_record(attempt / "export-receipt.json", export_receipt)
    partial = attempt / "ciphertext.partial"
    destination = attempt / "ciphertext"
    sha = hashlib.sha256()
    count = 0
    with _private_log(partial) as output:
        for frame in stream:
            _remaining(profile, binding)
            require(
                isinstance(frame, bytes) and 0 < len(frame) <= MAX_FRAME,
                "recovery_transfer_frame",
            )
            count += len(frame)
            require(count <= received["ciphertext_bytes"], "recovery_transfer_size")
            output.write(frame)
            sha.update(frame)
        require(
            count == received["ciphertext_bytes"]
            and sha.hexdigest() == received["ciphertext_sha256"],
            "recovery_transfer_digest",
        )
        output.flush()
        os.fsync(output.fileno())
    _remaining(profile, binding)
    # link is an atomic no-overwrite publication on the same private filesystem.
    os.link(partial, destination, follow_symlinks=False)
    partial.unlink()
    _fsync_directory(attempt)
    exclusive_record(attempt / "receive-receipt.json", received)
    return received


def _remove_outer(profile: dict, cidfile: Path, name: str, config: Path) -> None:
    # A launch without a known owned ID is ambiguous; never delete by guessed name.
    require(
        cidfile.is_file() and not cidfile.is_symlink(), "recovery_container_uncertain"
    )
    cid = cidfile.read_text().strip()
    require(
        re.fullmatch(r"[0-9a-f]{64}", cid) is not None, "recovery_container_uncertain"
    )
    info = json.loads(_docker(profile, ["inspect", cid], config=config))
    require(
        len(info) == 1
        and info[0]["Id"] == cid
        and info[0]["Name"] == "/" + name
        and info[0]["Image"]
        == profile["recovery"]["verifier_runtime"]["runtime_image_id"],
        "recovery_container_identity",
    )
    _docker(profile, ["rm", "--force", cid], config=config)


def verify_restore(
    profile: dict, attempt_dir: Path, receive_receipt: dict, binding: dict
) -> dict:
    validate_profile(profile)
    _remaining(profile, binding)
    require(binding["phase"].endswith("_restore"), "recovery_phase")
    recovery = profile["recovery"]
    runtime = recovery["verifier_runtime"]
    attempt = _directory(attempt_dir)
    export = read_record(attempt / "export-receipt.json")
    validate_receive_receipt(receive_receipt, export)
    require(
        read_record(attempt / "receive-receipt.json") == receive_receipt,
        "recovery_receive_changed",
    )
    ciphertext = attempt / "ciphertext"
    require(
        _file(ciphertext, private=True)
        == (receive_receipt["ciphertext_sha256"], receive_receipt["ciphertext_bytes"]),
        "recovery_ciphertext_changed",
    )
    _helpers(Path(recovery["verifier_repository"]), profile)
    _metadata(Path(recovery["identity_file"]))
    exclusive_record(
        attempt / "restore-intent.json",
        binding | {"receive_receipt_sha256": canonical_sha256(receive_receipt)},
    )
    work = attempt / "restore-work"
    work.mkdir(mode=0o700)
    config = attempt / "docker-config"
    config.mkdir(mode=0o700)
    canonical = attempt / "canonical-restore.json"
    cidfile = attempt / "restore-container.id"
    name = "bisq-restore-" + binding["intent_sha256"][:32]
    source = Path(recovery["verifier_repository"])
    command = [
        "run",
        "--pull",
        "never",
        "--name",
        name,
        "--cidfile",
        str(cidfile),
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        f'{runtime["uid"]}:{runtime["gid"]}',
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=64m",
        "--env",
        "DOCKER_HOST=unix:///var/run/docker.sock",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "TMPDIR=" + str(work),
        "--env",
        "BISQ_SUPPORT_INSTALL_DIR=" + str(source),
        # On Docker Desktop the CLI socket is on macOS; bind sources are resolved
        # by the Linux daemon and its local socket is /var/run/docker.sock.
        "--mount",
        "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock",
        "--mount",
        f"type=bind,src={attempt},dst={attempt}",
        "--mount",
        f'type=bind,src={recovery["identity_file"]},dst={recovery["identity_file"]},readonly',
    ]
    for helper in sorted(VERIFIER_HELPERS):
        path = source / helper
        command += ["--mount", f"type=bind,src={path},dst={path},readonly"]
    # A later narrow readonly bind prevents the verifier from rewriting ciphertext.
    command += [
        "--mount",
        f"type=bind,src={ciphertext},dst={ciphertext},readonly",
        "--entrypoint",
        "/bin/bash",
        runtime["runtime_image_id"],
        str(source / "scripts/restore.sh"),
        "--backup",
        str(ciphertext),
        "--encryption",
        recovery["encryption"],
        "--verify",
        "--component",
        "all",
        "--verify-api-image",
        runtime["api_image_id"],
        "--verify-qdrant-image",
        runtime["qdrant_image_id"],
        "--verification-receipt",
        str(canonical),
        "--identity" if recovery["encryption"] == "age" else "--gpg-key-file",
        recovery["identity_file"],
    ]
    with _private_log(attempt / "restore.log") as log:
        try:
            _docker(
                profile,
                command,
                timeout=_remaining(profile, binding),
                output=log,
                config=config,
            )
        except JournalError:
            # Exact owned outer container is removed once. Canonical resource
            # cleanup may remain uncertain after a hard kill: no success receipt,
            # no retry, and the attempt and plaintext directory stay private.
            _remove_outer(profile, cidfile, name, config)
            raise
    _remove_outer(profile, cidfile, name, config)
    _remaining(profile, binding)
    record = read_record(canonical)
    require(
        set(record)
        == {
            "schema",
            "ciphertext_sha256",
            "ciphertext_bytes",
            "components",
            "qdrant_restored",
            "scratch_cleanup_verified",
        }
        and record["schema"] == "canonical-restore-v1"
        and record["ciphertext_sha256"] == receive_receipt["ciphertext_sha256"]
        and record["ciphertext_bytes"] == receive_receipt["ciphertext_bytes"]
        and record["components"] == ["all"]
        and record["qdrant_restored"] is True
        and record["scratch_cleanup_verified"] is True
        and not any(work.iterdir()),
        "recovery_restore_receipt",
    )
    require(
        _file(ciphertext, private=True)
        == (receive_receipt["ciphertext_sha256"], receive_receipt["ciphertext_bytes"]),
        "recovery_ciphertext_changed",
    )
    work.rmdir()
    return {
        key: record[key]
        for key in (
            "ciphertext_sha256",
            "ciphertext_bytes",
            "components",
            "qdrant_restored",
            "scratch_cleanup_verified",
        )
    } | {
        "receive_receipt_sha256": canonical_sha256(receive_receipt),
        "canonical_restore_receipt_sha256": _file(canonical)[0],
        "local_runtime_image_id": runtime["runtime_image_id"],
    }
