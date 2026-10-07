"""Durable phase records for the checked-in updater.

This module records observations; it never runs commands or supplies authority.
The updater must hold the production lifecycle lock and verify a phase's actual
postconditions before recording success. An intent without an outcome blocks
continuation. Read-only inspection remains available after a release deadline.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class JournalError(RuntimeError):
    """A closed diagnostic code; never include command output or secret values."""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise JournalError(code)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise JournalError("record_timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise JournalError("record_timestamp") from error
    require(
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(parsed),
        "record_timestamp",
    )
    return parsed


def is_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def read_record(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_size <= 64 * 1024,
                "unsafe_record",
            )
            value = json.loads(stream.read(), object_pairs_hook=_object)
        require(isinstance(value, dict), "invalid_record")
        return value
    except (OSError, ValueError) as error:
        raise JournalError("record_unreadable") from error


def exclusive_record(path: Path, value: dict) -> None:
    """The existing migration journal's exclusive-write and fsync contract."""
    raw = encode(value)
    require(len(raw) <= 64 * 1024, "record_too_large")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except FileExistsError as error:
        raise JournalError("record_already_exists") from error


class DeploymentJournal:
    """One immutable plan and an append-only sequence of effect receipts."""

    def __init__(self, root: Path):
        self.root = root.absolute()
        require(
            not any(path.is_symlink() for path in (self.root, *self.root.parents)),
            "journal_symlink",
        )
        info = self.root.stat()
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            "unsafe_journal_directory",
        )
        self.plan = read_record(self.root / "plan.json")
        require(
            self.plan.get("schema") in {"deployment-plan-v1", "deployment-plan-v2"},
            "plan_schema",
        )
        require(
            isinstance(self.plan.get("phases"), list)
            and 1 <= len(self.plan["phases"]) <= 32,
            "plan_phases",
        )
        phases = self.plan["phases"]
        require(
            all(
                isinstance(p, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,47}", p)
                for p in phases
            )
            and len(set(phases)) == len(phases),
            "plan_phases",
        )
        self.plan_sha256 = digest(encode(self.plan))

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize journal writers; this is not the production lifecycle lock."""
        path = self.root / "journal.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600,
                "unsafe_journal_lock",
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise JournalError("journal_busy") from error
            require(
                digest(encode(read_record(self.root / "plan.json")))
                == self.plan_sha256,
                "plan_changed",
            )
            yield
        finally:
            os.close(fd)

    def _path(self, phase: str, suffix: str) -> Path:
        require(phase in self.plan["phases"], "unknown_phase")
        return self.root / f"{phase}.{suffix}.json"

    def _intent(self, phase: str) -> dict:
        value = read_record(self._path(phase, "intent"))
        require(
            set(value) == {"phase", "plan_sha256", "started_at"}
            and value["plan_sha256"] == self.plan_sha256
            and value["phase"] == phase,
            "intent_mismatch",
        )
        timestamp(value["started_at"])
        return value

    def _result(self, phase: str, intent: dict) -> dict:
        value = read_record(self._path(phase, "result"))
        require(
            set(value)
            == {"phase", "intent_sha256", "status", "evidence_sha256", "finished_at"}
            and value["phase"] == phase
            and value["intent_sha256"] == digest(encode(intent))
            and isinstance(value["status"], str)
            and value["status"] in {"succeeded", "failed", "uncertain"}
            and is_digest(value["evidence_sha256"]),
            "result_mismatch",
        )
        require(
            timestamp(value["finished_at"]) >= timestamp(intent["started_at"]),
            "record_timestamp_order",
        )
        return value

    def status(self) -> dict:
        require(
            digest(encode(read_record(self.root / "plan.json"))) == self.plan_sha256,
            "plan_changed",
        )
        phases: list[dict[str, str]] = []
        for phase in self.plan["phases"]:
            intent_path = self._path(phase, "intent")
            result_path = self._path(phase, "result")
            intent_exists = intent_path.exists() or intent_path.is_symlink()
            result_exists = result_path.exists() or result_path.is_symlink()
            require(not result_exists or intent_exists, "result_without_intent")
            state = "pending"
            if intent_exists:
                require(
                    all(item["status"] == "succeeded" for item in phases),
                    "phase_order",
                )
                intent = self._intent(phase)
                state = "uncertain"
                if result_exists:
                    result = self._result(phase, intent)
                    state = result["status"]
            phases.append({"phase": phase, "status": state})
        return {
            "plan_sha256": self.plan_sha256,
            "phases": phases,
            "completed": all(item["status"] == "succeeded" for item in phases),
            "needs_attention": any(
                item["status"] in {"failed", "uncertain"} for item in phases
            ),
        }

    def begin(self, phase: str) -> str:
        """Record intent before an effect. Repeated or out-of-order calls refuse."""
        with self.locked():
            phases = self.status()["phases"]
            require(phase in self.plan["phases"], "unknown_phase")
            index = self.plan["phases"].index(phase)
            require(
                all(p["status"] == "succeeded" for p in phases[:index]),
                "prior_phase_incomplete",
            )
            require(
                all(p["status"] == "pending" for p in phases[index:]),
                "phase_already_attempted",
            )
            value = {
                "phase": phase,
                "plan_sha256": self.plan_sha256,
                "started_at": now(),
            }
            exclusive_record(self._path(phase, "intent"), value)
            return digest(encode(value))

    def finish(
        self, phase: str, intent_sha256: str, status: str, evidence_sha256: str
    ) -> None:
        """Save a verified outcome; uncertain/failed outcomes are never overwritten."""
        require(status in {"succeeded", "failed", "uncertain"}, "outcome_status")
        require(is_digest(evidence_sha256), "evidence_hash")
        with self.locked():
            intent = self._intent(phase)
            require(digest(encode(intent)) == intent_sha256, "intent_mismatch")
            finished_at = now()
            require(
                timestamp(finished_at) >= timestamp(intent["started_at"]),
                "record_timestamp_order",
            )
            exclusive_record(
                self._path(phase, "result"),
                {
                    "phase": phase,
                    "intent_sha256": intent_sha256,
                    "status": status,
                    "evidence_sha256": evidence_sha256,
                    "finished_at": finished_at,
                },
            )
