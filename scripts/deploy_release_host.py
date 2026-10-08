"""Fixed stdio owner for the selective updater; no arbitrary command endpoint."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import select
import stat
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.deployment_host import DeploymentHost

# The fixed launcher uses isolated Python; only this checked-in scripts tree is added.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.deployment_journal import now  # noqa: E402
from lib.deployment_journal import (  # noqa: E402
    JournalError,
    exclusive_record,
    read_record,
    require,
    timestamp,
)
from lib.deployment_protocol import canonical_sha256  # noqa: E402
from lib.deployment_protocol import (  # noqa: E402
    MAX_RECORD_BYTES,
    decode_object,
    effect_guard,
    encode_object,
    make_phase_receipt,
    validate_approval,
    validate_phase_receipt,
)


def private_directory(path: Path, *, create: bool = False) -> None:
    require(path.is_absolute() and ".." not in path.parts, "host_private_path")
    require(not any(p.is_symlink() for p in (path, *path.parents)), "host_private_path")
    if create:
        path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "host_private_directory",
    )


def pins(root: Path, expected: dict) -> None:
    for name, wanted in expected.items():
        path = root / name
        require(
            not any(p.is_symlink() for p in (path, *path.parents))
            and path.is_file()
            and path.stat().st_size <= 2 * 1024 * 1024
            and hashlib.sha256(path.read_bytes()).hexdigest() == wanted,
            "host_helper_pin",
        )


class Owner:
    def __init__(self, repository: Path, *, read_only: bool = False, host_factory=None):
        self.repository = repository
        self.read_only = read_only
        self.host_factory = host_factory
        self.host: DeploymentHost | None = None
        self.opened = False
        self.closed = False

    def _receipts(self) -> dict:
        result: dict[str, dict] = {}
        missing = False
        directory = self.operation / "receipts"
        if not directory.exists():
            return result
        private_directory(directory)
        for phase in self.plan["phases"]:
            path = directory / f"{phase}.json"
            if not path.exists():
                missing = True
                continue
            require(not missing, "host_receipt_order")
            record = read_record(path)
            validate_phase_receipt(
                record,
                self.plan,
                self.profile,
                phase,
                record["intent_sha256"],
                self.baseline["baseline_sha256"],
                approval=self.approval,
            )
            result[phase] = record
        return result

    def _next(self, phase: str) -> None:
        saved = self._receipts()
        require(
            len(saved) < len(self.plan["phases"])
            and self.plan["phases"][len(saved)] == phase,
            "host_phase_order",
        )

    def open(self, message: dict) -> dict:
        require(
            not self.opened
            and set(message) == {"command", "mode", "plan", "profile", "approval"},
            "host_open_schema",
        )
        require(
            message["mode"] in {"execute", "reconcile"}
            and self.read_only == (message["mode"] == "reconcile"),
            "host_open_mode",
        )
        self.plan, self.profile, self.approval = (
            message["plan"],
            message["profile"],
            message["approval"],
        )
        validate_approval(self.approval, self.plan, self.profile)
        require(
            self.profile["host"]["repository"] == str(self.repository),
            "host_repository_binding",
        )
        require(
            self.profile["host"]["candidate"]
            == str(Path(__file__).resolve().parents[1]),
            "host_tools_location",
        )
        pins(Path(self.profile["host"]["candidate"]), self.profile["helper_sha256"])
        pins(
            Path(self.profile["host"]["candidate"]),
            self.profile["recovery"]["expected_helper_sha256"],
        )
        root = Path(self.profile["host"]["operation_root"])
        private_directory(root)
        self.operation = root / canonical_sha256(self.plan)
        private_directory(self.operation, create=not self.read_only)
        for name, value in (
            ("plan", self.plan),
            ("profile", self.profile),
            ("approval", self.approval),
        ):
            path = self.operation / f"{name}.json"
            if path.exists():
                require(read_record(path) == value, "host_operation_binding")
            else:
                require(not self.read_only, "host_operation_missing")
                exclusive_record(path, value)
        self.opened = True
        baseline_path = self.operation / "session-baseline.json"
        if self.read_only:
            self.baseline = (
                read_record(baseline_path)
                if baseline_path.exists()
                else {"baseline_sha256": None}
            )
        else:
            from lib.deployment_host import DeploymentHost
            from lib.deployment_recovery import preflight_capture

            preflight_capture(self.profile)

            factory = self.host_factory or DeploymentHost
            self.host = factory(self.plan, self.profile, self.approval, self.operation)
            fresh = self.host.preflight()
            if baseline_path.exists():
                require(
                    read_record(baseline_path) == fresh, "host_session_baseline_changed"
                )
            else:
                exclusive_record(baseline_path, fresh)
            self.baseline = fresh
            private_directory(self.operation / "receipts", create=True)
            private_directory(self.operation / "recovery", create=True)
        return {
            "baseline": self.baseline,
            "receipts": self._receipts(),
            "host_status": self._status(),
        }

    def _status(self) -> dict:
        if self.host is not None:
            return self.host.status()
        phases = {}
        for phase in self.plan["phases"]:
            # Reconciliation is intentionally an observation, not success promotion.
            host_path = self.operation / "host" / f"{phase}.intent.json"
            result_path = self.operation / "host" / f"{phase}.result.json"
            if phase.endswith("_backup"):
                host_path = self.operation / "recovery" / phase / "capture-intent.json"
                # Canonical capture evidence alone is not a completed phase.
                result_path = self.operation / "receipts" / f"{phase}.json"
            phases[phase] = {
                "intent_present": host_path.exists(),
                "result_present": result_path.exists(),
            }
        return {"read_only": True, "phases": phases}

    def _validate_completion(self, final: dict, receipts: dict) -> None:
        private_directory(self.operation / "host")
        canonical = read_record(self.operation / "host" / "completion.json")
        require(
            canonical
            == {
                "complete": True,
                "fresh_runtime_verified": True,
                "baseline_sha256": self.baseline["baseline_sha256"],
            }
            and canonical["complete"] is True
            and canonical["fresh_runtime_verified"] is True,
            "host_completion_binding",
        )
        verification = final.get("verification")
        require(
            set(final) == {"verification", "receipts", "host_status", "complete"}
            and final["complete"] is True
            and len(receipts) == len(self.plan["phases"])
            and final["receipts"] == receipts
            and isinstance(final["host_status"], dict)
            and isinstance(verification, dict)
            and verification.get("complete") is True
            and verification.get("fresh_runtime_verified") is True
            and verification.get("active_marker_retired") is True
            and verification
            == canonical
            | {
                "active_marker_retired": True,
                "verified_at": verification.get("verified_at"),
            },
            "host_completion_evidence",
        )
        assert isinstance(verification, dict)
        require(
            timestamp(verification["verified_at"])
            >= timestamp(receipts["resume_scheduler"]["finished_at"]),
            "host_completion_time",
        )

    def _saved_completion(self) -> dict:
        # This is saved evidence, not fresh health verification. Never construct
        # the effect backend or retire a marker in a read-only session.
        final = read_record(self.operation / "final-host-status.json")
        self._validate_completion(final, self._receipts())
        return final

    def dispatch(self, message: dict) -> dict:
        command = message.get("command")
        if command == "open":
            return self.open(message)
        require(self.opened and not self.closed, "host_session_not_open")
        if command == "close":
            require(set(message) == {"command"}, "host_close_schema")
            if self.host is not None:
                self.host.close()
            self.closed = True
            return {"closed": True}
        if command == "completion":
            require(
                self.read_only and set(message) == {"command"},
                "host_completion_read_schema",
            )
            return self._saved_completion()
        if command == "status":
            require(set(message) == {"command"}, "host_status_schema")
            receipts = self._receipts()
            completing = self.host is not None and len(receipts) == len(
                self.plan["phases"]
            )
            completion_path = self.operation / "final-host-status.json"
            if completing:
                require(
                    not (completion_path.exists() or completion_path.is_symlink()),
                    "host_completion_already_saved",
                )
            verification: dict = {}
            if completing:
                assert self.host is not None
                verification = self.host.verify_completion() | {"verified_at": now()}
            result = {
                "verification": verification,
                "receipts": receipts,
                "host_status": self._status(),
                "complete": len(receipts) == len(self.plan["phases"]),
            }
            if completing:
                # The reply is recoverable only after final verification and marker
                # retirement. A disconnect before this write remains unpromoted.
                self._validate_completion(result, receipts)
                exclusive_record(completion_path, result)
            return result
        require(not self.read_only, "host_read_only")
        assert self.host is not None
        if command == "effect":
            require(
                set(message) == {"command", "phase", "intent_sha256"},
                "host_effect_schema",
            )
            phase, intent = message["phase"], message["intent_sha256"]
            self._next(phase)
            require(not phase.endswith("_restore"), "host_local_phase")
            effect_guard(self.plan, self.profile, self.approval, phase)
            started = now()
            if phase.endswith("_backup"):
                from lib.deployment_recovery import capture_backup

                self.host.verify_preservation()

                attempt = self.operation / "recovery" / phase
                private_directory(attempt, create=True)
                binding = {
                    "plan_sha256": canonical_sha256(self.plan),
                    "profile_sha256": canonical_sha256(self.profile),
                    "phase": phase,
                    "intent_sha256": intent,
                    "deadline": self.approval["deadline"],
                }
                payload = capture_backup(self.profile, attempt, binding)
                self.host.verify_backup_resumption(phase, intent, started)
            else:
                try:
                    payload = self.host.effect(phase, intent)
                except JournalError:
                    if phase in {"switch_api", "switch_web"}:
                        # The backend permits only a proven failed switch, and
                        # records availability restoration separately from release success.
                        try:
                            self.host.restore_availability(phase)
                        except (JournalError, OSError, ValueError):
                            pass
                    raise
            receipt = make_phase_receipt(
                self.plan,
                self.profile,
                phase,
                intent,
                self.baseline["baseline_sha256"],
                payload,
                started,
            )
            validate_phase_receipt(
                receipt,
                self.plan,
                self.profile,
                phase,
                intent,
                self.baseline["baseline_sha256"],
                approval=self.approval,
            )
            exclusive_record(self.operation / "receipts" / f"{phase}.json", receipt)
            return {"receipt": receipt}
        if command == "accept_restore":
            require(set(message) == {"command", "receipt"}, "host_restore_schema")
            receipt = message["receipt"]
            phase = receipt.get("phase")
            require(
                phase in {"prechange_restore", "postchange_restore"},
                "host_restore_phase",
            )
            self._next(phase)
            effect_guard(self.plan, self.profile, self.approval, phase)
            payload = validate_phase_receipt(
                receipt,
                self.plan,
                self.profile,
                phase,
                receipt.get("intent_sha256"),
                self.baseline["baseline_sha256"],
                approval=self.approval,
            )
            backup = self._receipts()[phase.replace("_restore", "_backup")]["payload"]
            require(
                all(
                    payload[key] == backup[key]
                    for key in ("ciphertext_sha256", "ciphertext_bytes")
                ),
                "host_restore_backup_join",
            )
            self.host.verify_preservation()
            exclusive_record(self.operation / "receipts" / f"{phase}.json", receipt)
            return {"receipt": receipt}
        raise JournalError("host_unknown_command")

    def export(self, message: dict, output) -> None:
        require(
            self.opened and not self.closed and not self.read_only, "host_export_mode"
        )
        require(
            set(message) == {"command", "phase", "receipt_sha256"}, "host_export_schema"
        )
        phase = message["phase"]
        require(phase in {"prechange_backup", "postchange_backup"}, "host_export_phase")
        receipt = self._receipts()[phase]
        require(
            canonical_sha256(receipt) == message["receipt_sha256"],
            "host_export_receipt",
        )
        effect_guard(self.plan, self.profile, self.approval, phase)
        payload = receipt["payload"]
        root = Path(self.profile["recovery"]["export_directory"])
        private_directory(root)
        path = root / payload["ciphertext_name"]
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_size == payload["ciphertext_bytes"],
                "host_export_file",
            )
            digest = hashlib.sha256()
            sequence = 0
            while chunk := stream.read(32768):
                effect_guard(self.plan, self.profile, self.approval, phase)
                digest.update(chunk)
                output(
                    {
                        "sequence": sequence,
                        "base64": base64.b64encode(chunk).decode("ascii"),
                    }
                )
                sequence += 1
            require(
                digest.hexdigest() == payload["ciphertext_sha256"], "host_export_digest"
            )
        output(
            {
                "eof": True,
                "ciphertext_sha256": payload["ciphertext_sha256"],
                "ciphertext_bytes": payload["ciphertext_bytes"],
            }
        )


def emit(message: dict) -> None:
    data = encode_object(message)
    fd = sys.stdout.fileno()
    os.set_blocking(fd, False)
    deadline = time.monotonic() + 30
    while data:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "host_output_timeout")
        _, ready, _ = select.select([], [fd], [], remaining)
        require(bool(ready), "host_output_timeout")
        try:
            count = os.write(fd, data)
        except BlockingIOError:
            continue
        require(count > 0, "host_output_closed")
        data = data[count:]


_INPUT_BUFFER = b""


def read_frame(timeout: float) -> bytes:
    global _INPUT_BUFFER
    deadline = time.monotonic() + timeout
    while b"\n" not in _INPUT_BUFFER:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "host_idle_timeout")
        ready, _, _ = select.select([sys.stdin.fileno()], [], [], remaining)
        require(bool(ready), "host_idle_timeout")
        chunk = os.read(sys.stdin.fileno(), 16384)
        if not chunk:
            require(not _INPUT_BUFFER, "host_partial_frame")
            return b""
        _INPUT_BUFFER += chunk
        require(
            b"\n" in _INPUT_BUFFER or len(_INPUT_BUFFER) <= MAX_RECORD_BYTES,
            "host_frame_size",
        )
    frame, _INPUT_BUFFER = _INPUT_BUFFER.split(b"\n", 1)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--locked", action="store_true")
    mode.add_argument("--read-only", action="store_true")
    args = parser.parse_args()
    owner = Owner(args.repository, read_only=args.read_only)
    try:
        while True:
            timeout = 60.0
            if owner.opened and not owner.read_only:
                timeout = max(
                    1.0,
                    min(
                        1800.0,
                        (
                            timestamp(owner.approval["deadline"]) - timestamp(now())
                        ).total_seconds()
                        + 30,
                    ),
                )
            raw = read_frame(timeout)
            if not raw:
                return 0
            message = decode_object(raw)
            if message.get("command") == "export":
                owner.export(message, emit)
            else:
                emit(owner.dispatch(message))
            if owner.closed:
                return 0
    except (JournalError, OSError, ValueError, KeyError, TypeError):
        try:
            emit({"error": "host_refused_or_uncertain"})
        except (JournalError, OSError):
            pass
        return 2
    finally:
        if owner.host is not None:
            owner.host.close()


if __name__ == "__main__":
    sys.exit(main())
