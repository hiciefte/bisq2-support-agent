"""Operator-side ordinary release driver, with no generated remote shell source."""

from __future__ import annotations

import base64
import binascii
import contextlib
import fcntl
import os
import select
import shlex
import signal
import stat
import subprocess
import time
from pathlib import Path

from .deployment_journal import (
    DeploymentJournal,
    JournalError,
    digest,
    exclusive_record,
    is_digest,
    now,
    read_record,
    require,
    timestamp,
)
from .deployment_protocol import (
    MAX_RECORD_BYTES,
    canonical_sha256,
    decode_object,
    effect_guard,
    encode_object,
    make_phase_receipt,
    validate_approval,
    validate_phase_receipt,
)


def private_directory(path: Path, *, create: bool = False) -> Path:
    require(path.is_absolute() and ".." not in path.parts, "private_directory_path")
    require(
        not any(p.is_symlink() for p in (path, *path.parents)),
        "private_directory_symlink",
    )
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "private_directory_metadata",
    )
    return path


def pinned_helpers(root: Path, pins: dict) -> None:
    require(root.is_absolute() and root.resolve(strict=True) == root, "helper_root")
    for relative, expected in pins.items():
        path = root / relative
        require(
            path.is_file()
            and not any(p.is_symlink() for p in (path, *path.parents))
            and path.stat().st_size <= 2 * 1024 * 1024
            and digest(path.read_bytes()) == expected,
            "helper_pin_mismatch",
        )


class RemoteFailure(JournalError):
    """A remote response does not authorize replay, even when it is a known failure."""


class Transport:
    """One bounded stdio session holds the host lock across local verification."""

    def __init__(self, profile: dict, operation: Path, *, read_only: bool = False):
        self.profile = profile
        self.pending = b""
        self.closed = False
        transport, host = profile["transport"], profile["host"]
        bootstrap = Path(__file__).with_name("deployment_bootstrap.py").read_text()
        combined_pins = {
            **profile["helper_sha256"],
            **profile["recovery"]["expected_helper_sha256"],
        }
        require(
            all(
                combined_pins[name] == value
                for name, value in profile["helper_sha256"].items()
            ),
            "helper_pin_conflict",
        )
        spec = {
            "candidate": host["candidate"],
            "repository": host["repository"],
            "python": transport["host_python"],
            "read_only": read_only,
            "pins": combined_pins,
            "plan_sha256": canonical_sha256(read_record(operation / "plan.json")),
        }
        argv = [
            transport["host_python"],
            "-I",
            "-B",
            "-c",
            bootstrap,
            base64.b64encode(encode_object(spec)).decode("ascii"),
        ]
        if transport["kind"] == "ssh":
            argv = [
                "ssh",
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                "--",
                transport["ssh_alias"],
                shlex.join(argv),
            ]
        # Each connection gets its own diagnostics; never replace an earlier log.
        fd = os.open(
            operation / ("transport-" + str(time.time_ns()) + ".stderr"),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSH_AUTH_SOCK"}
        }
        try:
            self.process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=fd,
                env=env,
                start_new_session=True,
                bufsize=0,
            )
        finally:
            os.close(fd)

    def send(self, message: dict) -> None:
        require(not self.closed, "transport_closed")
        try:
            assert self.process.stdin is not None
            raw = encode_object(message)
            fd = self.process.stdin.fileno()
            os.set_blocking(fd, False)
            deadline = time.monotonic() + 30
            while raw:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "transport_write_timeout_uncertain")
                _, ready, _ = select.select([], [fd], [], remaining)
                require(bool(ready), "transport_write_timeout_uncertain")
                try:
                    count = os.write(fd, raw)
                except BlockingIOError:
                    continue
                require(count > 0, "transport_write")
                raw = raw[count:]
        except (OSError, BrokenPipeError) as error:
            raise JournalError("transport_write_uncertain") from error

    def receive(self, *, timeout: float | None = None) -> dict:
        limit = time.monotonic() + (
            timeout or self.profile["phase_timeout_seconds"] + 30
        )
        assert self.process.stdout is not None
        fd = self.process.stdout.fileno()
        while b"\n" not in self.pending:
            remaining = limit - time.monotonic()
            require(remaining > 0, "transport_timeout_uncertain")
            ready, _, _ = select.select([fd], [], [], remaining)
            require(bool(ready), "transport_timeout_uncertain")
            chunk = os.read(fd, 16384)
            require(bool(chunk), "transport_eof_uncertain")
            self.pending += chunk
            require(
                b"\n" in self.pending or len(self.pending) <= MAX_RECORD_BYTES,
                "transport_frame_size",
            )
        line, self.pending = self.pending.split(b"\n", 1)
        record = decode_object(line)
        if set(record) == {"error"}:
            # Do not trust remote exception text as a safe diagnostic or instruction.
            raise RemoteFailure("remote_phase_refused_or_failed")
        return record

    def request(self, message: dict) -> dict:
        self.send(message)
        return self.receive()

    def ciphertext(self, phase: str, receipt: dict):
        self.send(
            {
                "command": "export",
                "phase": phase,
                "receipt_sha256": canonical_sha256(receipt),
            }
        )
        sequence = 0
        while True:
            frame = self.receive()
            if set(frame) == {"eof", "ciphertext_sha256", "ciphertext_bytes"}:
                require(
                    frame["eof"] is True
                    and frame["ciphertext_sha256"]
                    == receipt["payload"]["ciphertext_sha256"]
                    and frame["ciphertext_bytes"]
                    == receipt["payload"]["ciphertext_bytes"],
                    "transport_ciphertext_end",
                )
                return
            require(
                set(frame) == {"sequence", "base64"}
                and type(frame["sequence"]) is int
                and frame["sequence"] == sequence
                and isinstance(frame["base64"], str),
                "transport_ciphertext_frame",
            )
            try:
                data = base64.b64decode(frame["base64"], validate=True)
            except (ValueError, binascii.Error) as error:
                raise JournalError("transport_ciphertext_frame") from error
            require(0 < len(data) <= 32768, "transport_ciphertext_frame")
            sequence += 1
            yield data

    def close(self, *, orderly: bool = False) -> None:
        if self.closed:
            return
        try:
            if orderly:
                require(
                    self.request({"command": "close"}) == {"closed": True},
                    "transport_close",
                )
        finally:
            self.closed = True
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
            if self.process.stdout is not None:
                self.process.stdout.close()


def bindings(
    journal: DeploymentJournal,
    profile_path: Path | None = None,
    approval_path: Path | None = None,
) -> tuple[dict, dict]:
    if profile_path is not None or approval_path is not None:
        require(
            profile_path is not None and approval_path is not None, "binding_arguments"
        )
        require(
            all(item["status"] == "pending" for item in journal.status()["phases"]),
            "apply_already_attempted",
        )
        assert profile_path is not None and approval_path is not None
        profile, approval = read_record(profile_path), read_record(approval_path)
        validate_approval(approval, journal.plan, profile)
        require(
            journal.plan["schema"] in {"deployment-plan-v2", "deployment-plan-v3"},
            "effect_plan_version",
        )
        # Interrupted snapshot publication is preserved; a repeat apply never overwrites it.
        exclusive_record(journal.root / "profile.json", profile)
        exclusive_record(journal.root / "approval.json", approval)
    else:
        profile, approval = read_record(journal.root / "profile.json"), read_record(
            journal.root / "approval.json"
        )
        validate_approval(approval, journal.plan, profile)
    return profile, approval


def checked_receipts(journal: DeploymentJournal, profile: dict, approval: dict) -> dict:
    receipts = {}
    baseline = None
    for item in journal.status()["phases"]:
        phase = item["phase"]
        if item["status"] != "succeeded":
            continue
        intent = read_record(journal.root / f"{phase}.intent.json")
        receipt = read_record(journal.root / "receipts" / f"{phase}.json")
        validate_phase_receipt(
            receipt,
            journal.plan,
            profile,
            phase,
            canonical_sha256(intent),
            baseline,
            approval=approval,
        )
        baseline = receipt["baseline_sha256"]
        result = read_record(journal.root / f"{phase}.result.json")
        require(
            result["evidence_sha256"] == canonical_sha256(receipt),
            "journal_receipt_join",
        )
        receipts[phase] = receipt
    return receipts


def _execute(
    operation: Path,
    *,
    profile_path: Path | None = None,
    approval_path: Path | None = None,
    transport_factory=Transport,
) -> dict:
    journal = DeploymentJournal(operation)
    profile, approval = bindings(journal, profile_path, approval_path)
    state = journal.status()
    require(not state["needs_attention"], "reconciliation_required")
    receipts = checked_receipts(journal, profile, approval)
    if state["completed"]:
        if not any(
            path.exists() or path.is_symlink()
            for path in (
                journal.root / "completion.json",
                journal.root / "final-host-status.json",
            )
        ):
            return recover_completion(
                journal, profile, approval, receipts, transport_factory
            )
        completion = read_record(journal.root / "completion.json")
        require(
            completion.get("schema") == "deployment-completion-v1"
            and completion.get("plan_sha256") == journal.plan_sha256
            and completion.get("profile_sha256") == canonical_sha256(profile),
            "completion_binding",
        )
        verify_completion_record(journal, profile, receipts, completion)
        return {
            "completed": True,
            "already_complete": True,
            "plan_sha256": journal.plan_sha256,
        }
    phase = next(
        item["phase"] for item in state["phases"] if item["status"] == "pending"
    )
    effect_guard(journal.plan, profile, approval, phase)
    # Resolve operator-owned recovery tools before any remote disruption.
    pinned_helpers(
        Path(profile["recovery"]["verifier_repository"]),
        profile["recovery"]["expected_helper_sha256"],
    )
    from .deployment_recovery import preflight_recovery

    local_root = Path(profile["recovery"]["local_directory"])
    require(
        all(
            (journal.root / "recovery" / phase).is_relative_to(local_root)
            for phase in ("prechange_restore", "postchange_restore")
        ),
        "recovery_local_path",
    )
    preflight_recovery(profile)
    private_directory(journal.root / "receipts", create=True)
    private_directory(journal.root / "recovery", create=True)
    transport = transport_factory(profile, journal.root)
    orderly = False
    try:
        opened = transport.request(
            {
                "command": "open",
                "mode": "execute",
                "plan": journal.plan,
                "profile": profile,
                "approval": approval,
            }
        )
        require(
            set(opened) == {"baseline", "receipts", "host_status"}, "transport_open"
        )
        require(opened["receipts"] == receipts, "host_client_receipt_mismatch")
        baseline = opened["baseline"]["baseline_sha256"]
        for receipt in receipts.values():
            require(receipt["baseline_sha256"] == baseline, "baseline_changed")
        for item in state["phases"]:
            if item["status"] == "succeeded":
                continue
            phase = item["phase"]
            effect_guard(journal.plan, profile, approval, phase)
            started = now()
            intent_hash = journal.begin(phase)
            try:
                if phase.endswith("_restore"):
                    from .deployment_recovery import receive_ciphertext, verify_restore

                    backup_phase = phase.replace("_restore", "_backup")
                    capture = receipts[backup_phase]
                    attempt = private_directory(
                        journal.root / "recovery" / phase, create=True
                    )
                    binding = {
                        "plan_sha256": journal.plan_sha256,
                        "profile_sha256": canonical_sha256(profile),
                        "phase": phase,
                        "intent_sha256": intent_hash,
                        "deadline": approval["deadline"],
                    }
                    received = receive_ciphertext(
                        profile,
                        attempt,
                        capture,
                        transport.ciphertext(backup_phase, capture),
                        binding,
                    )
                    payload = verify_restore(profile, attempt, received, binding)
                    receipt = make_phase_receipt(
                        journal.plan,
                        profile,
                        phase,
                        intent_hash,
                        baseline,
                        payload,
                        started,
                    )
                    accepted = transport.request(
                        {"command": "accept_restore", "receipt": receipt}
                    )
                    require(accepted == {"receipt": receipt}, "restore_acceptance")
                else:
                    reply = transport.request(
                        {
                            "command": "effect",
                            "phase": phase,
                            "intent_sha256": intent_hash,
                        }
                    )
                    require(set(reply) == {"receipt"}, "transport_effect")
                    receipt = reply["receipt"]
                validate_phase_receipt(
                    receipt,
                    journal.plan,
                    profile,
                    phase,
                    intent_hash,
                    baseline,
                    approval=approval,
                )
                exclusive_record(journal.root / "receipts" / f"{phase}.json", receipt)
                journal.finish(
                    phase, intent_hash, "succeeded", canonical_sha256(receipt)
                )
                receipts[phase] = receipt
            except (JournalError, OSError, ValueError) as error:
                # Keep the intent uncertain if even recording an outcome is unsafe.
                evidence = {
                    "schema": "deployment-failure-v1",
                    "phase": phase,
                    "observed_at": now(),
                    "code": "phase_failed_or_uncertain",
                }
                exclusive_record(journal.root / f"{phase}.failure.json", evidence)
                journal.finish(
                    phase, intent_hash, "uncertain", canonical_sha256(evidence)
                )
                raise JournalError("phase_requires_reconciliation") from error
        final = transport.request({"command": "status"})
        publish_completion(journal, profile, receipts, final)
        orderly = True
        return {
            "completed": True,
            "plan_sha256": journal.plan_sha256,
            "phases": len(receipts),
            "transport": profile["transport"]["kind"],
            "fresh_runtime_verified": True,
        }
    finally:
        transport.close(orderly=orderly)


def publish_completion(journal, profile, receipts, final):
    verification = final.get("verification")
    baseline = receipts["resume_scheduler"]["baseline_sha256"]
    require(
        set(final) == {"verification", "receipts", "host_status", "complete"}
        and final.get("complete") is True
        and final.get("receipts") == receipts
        and isinstance(final.get("host_status"), dict)
        and isinstance(verification, dict)
        and set(verification)
        == {
            "complete",
            "fresh_runtime_verified",
            "active_marker_retired",
            "baseline_sha256",
            "verified_at",
        }
        and verification.get("complete") is True
        and verification.get("fresh_runtime_verified") is True
        and verification.get("active_marker_retired") is True
        and verification.get("baseline_sha256") == baseline
        and all(
            receipt["baseline_sha256"] == baseline for receipt in receipts.values()
        ),
        "host_completion_unverified",
    )
    verified_at = verification["verified_at"]
    require(
        timestamp(verified_at)
        >= timestamp(receipts["resume_scheduler"]["finished_at"]),
        "completion_time",
    )
    exclusive_record(journal.root / "final-host-status.json", final)
    exclusive_record(
        journal.root / "completion.json",
        {
            "schema": "deployment-completion-v1",
            "plan_sha256": journal.plan_sha256,
            "profile_sha256": canonical_sha256(profile),
            "verified_at": verified_at,
            "host_status_sha256": canonical_sha256(final),
        },
    )


def recover_completion(journal, profile, approval, receipts, transport_factory):
    """Recover a lost final reply, never repeat finalization or runtime probes."""
    transport = transport_factory(profile, journal.root, read_only=True)
    orderly = False
    try:
        opened = transport.request(
            {
                "command": "open",
                "mode": "reconcile",
                "plan": journal.plan,
                "profile": profile,
                "approval": approval,
            }
        )
        require(
            set(opened) == {"baseline", "receipts", "host_status"}, "transport_open"
        )
        require(opened["receipts"] == receipts, "host_client_receipt_mismatch")
        baseline = opened["baseline"]["baseline_sha256"]
        require(
            all(
                receipt["baseline_sha256"] == baseline for receipt in receipts.values()
            ),
            "baseline_changed",
        )
        final = transport.request({"command": "completion"})
        verification = final.get("verification")
        require(
            isinstance(verification, dict)
            and verification.get("baseline_sha256") == baseline,
            "completion_baseline",
        )
        publish_completion(journal, profile, receipts, final)
        orderly = True
        return {
            "completed": True,
            "completion_recovered": True,
            "plan_sha256": journal.plan_sha256,
            "effects_performed": False,
            "fresh_runtime_verified": False,
            "saved_runtime_verified": True,
        }
    finally:
        transport.close(orderly=orderly)


def reconcile(operation: Path, *, transport_factory=Transport) -> dict:
    """Read existing outcomes after uncertainty or expiry; never replay or promote."""
    journal = DeploymentJournal(operation)
    profile, approval = bindings(journal)
    transport = transport_factory(profile, journal.root, read_only=True)
    orderly = False
    try:
        remote = transport.request(
            {
                "command": "open",
                "mode": "reconcile",
                "plan": journal.plan,
                "profile": profile,
                "approval": approval,
            }
        )
        orderly = True
        return {
            "schema": "deployment-reconciliation-v1",
            "local": journal.status(),
            "remote": remote,
            "effects_performed": False,
            "automatic_retry_permitted": False,
        }
    finally:
        transport.close(orderly=orderly)


@contextlib.contextmanager
def execution_lock(operation: Path):
    private_directory(operation.absolute())
    fd = os.open(
        operation / "execution.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600,
            "execution_lock_metadata",
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise JournalError("execution_busy") from error
        yield
    finally:
        os.close(fd)


def execute(
    operation: Path,
    *,
    profile_path: Path | None = None,
    approval_path: Path | None = None,
    transport_factory=Transport,
) -> dict:
    with execution_lock(operation):
        return _execute(
            operation,
            profile_path=profile_path,
            approval_path=approval_path,
            transport_factory=transport_factory,
        )


def verify_completion_record(journal, profile, receipts, completion):
    require(
        set(completion)
        == {
            "schema",
            "plan_sha256",
            "profile_sha256",
            "verified_at",
            "host_status_sha256",
        }
        and completion["schema"] == "deployment-completion-v1"
        and completion["plan_sha256"] == journal.plan_sha256
        and completion["profile_sha256"] == canonical_sha256(profile)
        and is_digest(completion["host_status_sha256"]),
        "completion_schema",
    )
    final = read_record(journal.root / "final-host-status.json")
    require(
        canonical_sha256(final) == completion["host_status_sha256"]
        and final.get("complete") is True
        and final.get("receipts") == receipts
        and final.get("verification", {}).get("fresh_runtime_verified") is True
        and final.get("verification", {}).get("active_marker_retired") is True,
        "completion_evidence",
    )
    require(
        timestamp(completion["verified_at"])
        >= timestamp(receipts["resume_scheduler"]["finished_at"]),
        "completion_time",
    )
