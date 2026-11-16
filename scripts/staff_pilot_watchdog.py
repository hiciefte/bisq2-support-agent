#!/usr/bin/env python3
"""Host-local, once-only coordinator for a separately reviewed Staff pilot.

This does not activate a pilot or provide a controller. A bound installation must
supply pinned metadata-only health and canonical stop/finalize controllers. No
LLM, Matrix client, SSH connection or room capture is used by this process.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PHASES = ("stop", "scheduler-finalize")
CADENCE = 12 * 3600
GRACE = 15 * 60
DRAIN = 120


class Refusal(RuntimeError):
    """A fixed diagnostic code; never include subprocess or private content."""


def need(value, code):
    if not value:
        raise Refusal(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def private(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        need(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and not info.st_mode & 0o077,
            "private_regular_file_required",
        )
        need(info.st_size <= 1_000_000, "private_file_too_large")
        return stream.read()


def atomic(path, value, mode=0o600):
    """One fsynced replacement; a failed read never touches the last success."""
    raw = value if isinstance(value, bytes) else encoded(value)
    fd, name = tempfile.mkstemp(prefix=".pilot-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def exclusive(path, value):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse_time(value):
    parsed = datetime.fromisoformat(value)
    need(parsed.utcoffset() == timedelta(0), "utc_time_required")
    return parsed


def no_multiplexing(argv):
    """For next-pilot operator transport; OpenSSH uses the first option value.

    Never repair an ephemeral directory or weaken identity/host-key checking.
    This is consumed by the next transport preparation, not the host coordinator.
    """
    need(argv and Path(argv[0]).name == "ssh", "ssh_command_required")
    return [
        argv[0],
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ControlPersist=no",
        *argv[1:],
    ]


def load_binding(path, expected):
    raw = private(path)
    need(digest(raw) == expected, "binding_changed")
    b = json.loads(raw)
    need(
        set(b)
        == {
            "schema",
            "trial_id",
            "revision",
            "descriptor_sha256",
            "start_at",
            "end_at",
            "max_cases",
            "state_dir",
            "phase_dir",
            "metrics_path",
            "commands",
            "files_sha256",
            "receipt_lineage",
        },
        "binding_fields",
    )
    need(b["schema"] == "staff-pilot-host-watchdog-v1", "binding_schema")
    need(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", b["trial_id"]), "trial_id")
    need(
        re.fullmatch(r"[0-9a-f]{40}", b["revision"])
        and re.fullmatch(r"[0-9a-f]{64}", b["descriptor_sha256"]),
        "binding_pins",
    )
    need(
        timedelta(0)
        < parse_time(b["end_at"]) - parse_time(b["start_at"])
        <= timedelta(days=7)
        and type(b["max_cases"]) is int
        and 1 <= b["max_cases"] <= 20,
        "trial_limits",
    )
    need(
        parse_time(b["start_at"]).microsecond == 0
        and parse_time(b["end_at"]).microsecond == 0,
        "whole_second_boundaries_required",
    )
    need(set(b["commands"]) == {"limits", "health", *PHASES}, "command_set")
    need(
        b["files_sha256"]
        and all(
            Path(p).is_absolute() and re.fullmatch(r"[0-9a-f]{64}", h)
            for p, h in b["files_sha256"].items()
        ),
        "source_pins",
    )
    for key in ("state_dir", "phase_dir", "metrics_path"):
        need(Path(b[key]).is_absolute(), "absolute_path_required")
    need(Path(b["metrics_path"]).name.endswith(".prom"), "metrics_path")
    for command in b["commands"].values():
        need(
            isinstance(command, list)
            and command
            and all(isinstance(a, str) and "\x00" not in a for a in command)
            and command[0] in ("/usr/bin/python3", "/bin/bash")
            and any(a in b["files_sha256"] for a in command[1:]),
            "unpinned_command",
        )
    need(
        isinstance(b["receipt_lineage"], dict) and b["receipt_lineage"],
        "receipt_lineage",
    )
    return b


class Watchdog:
    def __init__(
        self,
        binding,
        binding_sha,
        *,
        run=subprocess.run,
        clock=lambda: datetime.now(timezone.utc),
        sleep=time.sleep,
    ):
        self.b = binding
        self.binding_sha = binding_sha
        self.run, self.clock, self.sleep = run, clock, sleep
        self.state = Path(binding["state_dir"])
        self.phases = Path(binding["phase_dir"])
        self.cutoff = parse_time(binding["end_at"])
        self.drain_observed = False

    def pins(self):
        for path, expected in self.b["files_sha256"].items():
            need(digest(private(Path(path))) == expected, "controller_source_changed")

    def command(self, kind):
        self.pins()
        argv = list(self.b["commands"][kind])
        if kind == "health":
            checkpoint = self.state / "checkpoint.json"
            argv += ["--checkpoint", str(checkpoint)] if checkpoint.exists() else []
        try:
            run = self.run(
                argv,
                capture_output=True,
                timeout=150 if kind in ("health", "limits") else 900,
                env={
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "HOME": "/root",
                    "LANG": "C.UTF-8",
                    "STAFF_PILOT_BINDING_SHA256": self.binding_sha,
                },
            )
        except subprocess.TimeoutExpired as exc:
            raise Refusal("command_timeout_requires_reconciliation") from exc
        if kind == "limits" and run.returncode != 0:
            try:
                failure = json.loads(run.stdout)
            except (ValueError, TypeError):
                failure = {}
            if failure.get("error_code") in {
                "limits_orphan_reservations",
                "limits_descriptor_changed",
            }:
                raise Refusal("material_safety_failure")
        need(run.returncode == 0, "command_failed_requires_reconciliation")
        if kind in ("health", "limits"):
            need(len(run.stdout) < 40000, "health_too_large")
            try:
                return json.loads(run.stdout)
            except (ValueError, TypeError) as exc:
                raise Refusal("health_not_json") from exc
        # Canonical files, never stdout or exit0, establish terminal success.
        return None

    def receipt(self, phase):
        folder = self.phases / phase
        own = self.state / (phase + ".intent.json")
        if not folder.exists() and not folder.is_symlink():
            need(not own.exists() and not own.is_symlink(), "ambiguous_local_intent")
            return None
        need(folder.is_dir() and not folder.is_symlink(), "phase_directory_invalid")
        need(
            (folder / "intent.json").exists() and (folder / "receipt.json").exists(),
            "ambiguous_canonical_intent",
        )
        intent = json.loads(private(folder / "intent.json"))
        receipt = json.loads(private(folder / "receipt.json"))
        for record in (intent, receipt):
            need(
                record.get("phase") == phase
                and record.get("descriptor_sha256") == self.b["descriptor_sha256"]
                and record.get("revision") == self.b["revision"]
                and all(
                    record.get(k) == v for k, v in self.b["receipt_lineage"].items()
                ),
                "terminal_lineage_changed",
            )
        need(receipt.get("success") is True, "terminal_failed_requires_reconciliation")
        if phase == "stop":
            need(
                receipt.get("generation_enabled") is False
                and receipt.get("sync_enabled") is False
                and all(
                    receipt.get(k) is True
                    for k in (
                        "api_healthy",
                        "identity_preserved",
                        "trial_ledger_preserved",
                        "original_histories_preserved",
                        "other_services_unchanged",
                    )
                ),
                "stop_not_verified",
            )
        else:
            need(
                receipt.get("scheduler_recreated") is False
                and all(
                    receipt.get(k) is True
                    for k in (
                        "scheduler_healthy",
                        "other_services_unchanged",
                        "expired_overlay_retained",
                        "indefinite_selected_job_hold_retained",
                    )
                ),
                "finalization_not_verified",
            )
        need(
            parse_time(receipt["completed_at"]) <= self.clock(), "receipt_time_invalid"
        )
        if phase == "scheduler-finalize":
            need(
                parse_time(receipt["completed_at"]) >= self.cutoff,
                "premature_finalization_receipt",
            )
        return receipt

    def phase(self, phase):
        previous = self.receipt(phase)
        if previous is not None:
            return previous
        exclusive(
            self.state / (phase + ".intent.json"),
            {
                "phase": phase,
                "at": self.clock().isoformat(),
                "binding_sha256": self.binding_sha,
                "no_retry": True,
            },
        )
        self.command(phase)
        receipt = self.receipt(phase)
        need(receipt is not None, "canonical_receipt_missing")
        return receipt

    def limits(self):
        """Independent ledger/cap read; it need not claim application health."""
        o = self.command("limits")
        need(
            isinstance(o, dict)
            and set(o)
            == {
                "trial_id",
                "revision",
                "descriptor_sha256",
                "captured_at",
                "max_cases",
                "reserved_cases",
                "uncertain_or_active_count",
                "matrix_requests",
                "provider_calls",
            }
            and o["trial_id"] == self.b["trial_id"]
            and o["revision"] == self.b["revision"]
            and o["descriptor_sha256"] == self.b["descriptor_sha256"]
            and o["max_cases"] == self.b["max_cases"]
            and type(o["reserved_cases"]) is int
            and o["reserved_cases"] >= 0
            and type(o["uncertain_or_active_count"]) is int
            and o["uncertain_or_active_count"] >= 0
            and o["matrix_requests"] == 0
            and o["provider_calls"] == 0
            and 0
            <= (self.clock() - parse_time(o["captured_at"])).total_seconds()
            <= 150,
            "limits_invalid",
        )
        return o

    def health(self):
        o = self.command("health")
        need(isinstance(o, dict), "health_not_successful")
        need(
            o.get("trial_id") == self.b["trial_id"]
            and o.get("revision") == self.b["revision"]
            and o.get("descriptor_sha256") == self.b["descriptor_sha256"],
            "health_binding_changed",
        )
        if (
            o.get("material_safety_failure") is True
            or o.get("matrix_requests", 0) != 0
            or o.get("provider_calls", 0) != 0
            or any(o.get(k) is False for k in ("predecessor_history_preserved",))
            or any(
                o.get("cursor", {}).get(k) is False
                for k in (
                    "same_established_identity",
                    "same_established_session",
                    "saved_cursor_present",
                )
            )
            or any(
                o.get("policy", {}).get(k) is False
                for k in ("scope_safe", "global_delivery_disabled")
            )
        ):
            raise Refusal("material_safety_failure")
        need(o.get("healthy") is True, "health_not_successful")
        need(
            0 <= (self.clock() - parse_time(o["captured_at"])).total_seconds() <= 150,
            "health_not_fresh",
        )
        cp = o.get("next_checkpoint")
        need(
            isinstance(cp, dict)
            and set(cp)
            == {
                "captured_at",
                "descriptor_sha256",
                "health_sha256",
                "ledger_sha256",
                "cursor_sha256",
            },
            "checkpoint_invalid",
        )
        need(
            cp["captured_at"] == o["captured_at"]
            and cp["descriptor_sha256"] == self.b["descriptor_sha256"]
            and cp["health_sha256"] == o["health_sha256"]
            and cp["ledger_sha256"] == o["ledger"]["summary_sha256"]
            and cp["cursor_sha256"] == o["cursor"]["cursor_sha256"]
            and all(
                re.fullmatch(r"[0-9a-f]{64}", cp[k]) for k in cp if k.endswith("sha256")
            ),
            "checkpoint_invalid",
        )
        need(
            o["ledger"]["max_cases"] == self.b["max_cases"]
            and type(o["ledger"]["reserved_cases"]) is int
            and 0 <= o["ledger"]["reserved_cases"] <= self.b["max_cases"],
            "cap_exceeded_or_invalid",
        )
        need(
            o.get("matrix_requests") == 0 and o.get("provider_calls") == 0,
            "health_scope_changed",
        )
        need(
            all(
                o.get(k) is True
                for k in (
                    "api_healthy",
                    "scheduler_healthy",
                    "predecessor_history_preserved",
                )
            )
            and all(
                o["cursor"].get(k) is True
                for k in (
                    "same_established_identity",
                    "same_established_session",
                    "saved_cursor_present",
                )
            )
            and o["policy"].get("scope_safe") is True
            and o["policy"].get("global_delivery_disabled") is True,
            "preservation_or_scope_failed",
        )
        return o

    def tick(self):
        # Reporting corruption must not prevent a bound due containment attempt.
        previous, saved_error = None, None
        success_path = self.state / "last-success.json"
        try:
            if success_path.exists():
                previous = json.loads(private(success_path))
                need(
                    previous.get("binding_sha256") == self.binding_sha,
                    "saved_binding_changed",
                )
                parse_time(previous["captured_at"])
        except Exception:
            saved_error = Refusal("saved_success_invalid")
        stale = (
            previous is None
            or saved_error is not None
            or (self.clock() - parse_time(previous["captured_at"])).total_seconds()
            > CADENCE + GRACE
        )
        stopped = self.receipt("stop") is not None
        observation, error, limits = None, None, None
        active_at_stop = None

        def enforce_deadline():
            nonlocal stopped
            if self.clock() >= self.cutoff:
                self.phase("stop")
                stopped = True
                self.phase("scheduler-finalize")

        def enforce_cap(counts):
            nonlocal stopped, active_at_stop, error
            if stopped or not counts or counts["reserved_cases"] < self.b["max_cases"]:
                return
            active_at_stop = counts.get("uncertain_or_active_count")
            # Unknown activity is uncertain and receives the same bounded drain.
            if active_at_stop is None or active_at_stop > 0:
                self.drain_observed = True
                self.sleep(
                    min(DRAIN, max(0, (self.cutoff - self.clock()).total_seconds()))
                )
                enforce_deadline()
                if not stopped:
                    try:
                        active_at_stop = self.limits()["uncertain_or_active_count"]
                    except Exception as exc:
                        error = exc
                        active_at_stop = None
            self.phase("stop")
            stopped = True
            enforce_deadline()

        enforce_deadline()
        if not stopped:
            try:
                limits = self.limits()
            except Exception as exc:
                error = exc
                if isinstance(exc, Refusal) and str(exc) == "material_safety_failure":
                    self.phase("stop")
                    stopped = True
            enforce_deadline()
            enforce_cap(limits)
            if not stopped:
                try:
                    observation = self.health()
                    enforce_deadline()
                    enforce_cap(observation["ledger"])
                except Exception as exc:
                    error = exc
                    if isinstance(exc, Refusal) and str(exc) in (
                        "material_safety_failure",
                        "cap_exceeded_or_invalid",
                    ):
                        self.phase("stop")
                        stopped = True
                enforce_deadline()
        if stopped or (observation is None and error is None):
            try:
                observation = self.health()
            except Exception as exc:
                error = exc
        # A successful pre-deadline read may return after the cutoff, including
        # an early-cap stopped check. Contain/finalize before claiming success.
        was_stopped = stopped
        enforce_deadline()
        if stopped and not was_stopped:
            observation = self.health()
        if error is not None:
            raise error
        if saved_error is not None:
            raise saved_error
        stop = self.receipt("stop")
        final = self.receipt("scheduler-finalize")
        if stopped:
            need(
                observation["policy"]["generation_enabled"] is False
                and observation["listener_configured_stopped"] is True,
                "stopped_health_not_verified",
            )
        return {
            "schema": "staff-pilot-host-success-v1",
            "binding_sha256": self.binding_sha,
            "captured_at": observation["captured_at"],
            "previous_success_missing_or_stale": stale,
            "stop_verified": stopped,
            "finalization_verified": final is not None,
            "cap_drain_observation_performed": self.drain_observed,
            "uncertain_or_active_at_stop": active_at_stop,
            "stop_completed_at": stop["completed_at"] if stop else None,
            "shutdown_delay_seconds": (
                max(0, (parse_time(stop["completed_at"]) - self.cutoff).total_seconds())
                if stop
                else None
            ),
            "finalization_delay_seconds": (
                max(
                    0, (parse_time(final["completed_at"]) - self.cutoff).total_seconds()
                )
                if final
                else None
            ),
            "observation": observation,
            "next_checkpoint": observation["next_checkpoint"],
        }


def metrics(binding, binding_sha, *, success, now):
    label = '{binding="' + binding_sha + '"}'
    last_path = Path(binding["state_dir"]) / "last-success.json"
    try:
        last = json.loads(private(last_path)) if last_path.exists() else None
        need(
            last is None or last.get("binding_sha256") == binding_sha,
            "saved_binding_changed",
        )
        timestamp = parse_time(last["captured_at"]).timestamp() if last else 0
        final = 1 if last and last.get("finalization_verified") is True else 0
    except Exception:
        timestamp, final = 0, 0
    text = (
        "\n".join(
            [
                f"staff_pilot_watchdog_last_attempt_success{label} {int(success)}",
                f"staff_pilot_watchdog_last_attempt_timestamp_seconds{label} {now.timestamp()}",
                f"staff_pilot_watchdog_last_success_timestamp_seconds{label} {timestamp}",
                f"staff_pilot_watchdog_finalized{label} {final}",
            ]
        )
        + "\n"
    )
    atomic(Path(binding["metrics_path"]), text.encode(), mode=0o644)


def render_units(*, script_path, binding_path, state_dir, binding_sha, cutoff):
    """Prepare files only; the independently reviewed installer owns activation.

    The cutoff has its own service and waits on the shared coordinator lock.
    Its one-shot deadline event cannot be coalesced into an active health unit.
    """
    for value in (script_path, binding_path, state_dir):
        need(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(value)), "unit_path_invalid")
    need(re.fullmatch(r"[0-9a-f]{64}", binding_sha), "binding_pin_invalid")
    need(parse_time(cutoff).microsecond == 0, "whole_second_boundaries_required")
    end = parse_time(cutoff).strftime("%Y-%m-%d %H:%M:%S UTC")
    service = f"""[Unit]
Description=Bounded Staff pilot health and terminal receipts
ConditionPathExists=!{state_dir}/finalized.json
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
User=root
UMask=0077
ExecStart=/usr/bin/python3 -B {script_path} --binding {binding_path} --binding-sha256 {binding_sha}
TimeoutStartSec=35min
Restart=no
"""
    cadence = """[Unit]
Description=Twelve-hour host Staff pilot check
[Timer]
OnBootSec=1min
OnUnitActiveSec=12h
AccuracySec=30s
Unit=bisq-staff-pilot-watchdog.service
[Install]
WantedBy=timers.target
"""
    deadline = f"""[Unit]
Description=Fixed Staff pilot cutoff
[Timer]
OnCalendar={end}
Persistent=true
AccuracySec=1s
RandomizedDelaySec=0
Unit=bisq-staff-pilot-cutoff.service
[Install]
WantedBy=timers.target
"""
    expected = f'staff_pilot_watchdog_expected{{binding="{binding_sha}"}} 1\n'
    expected += f'staff_pilot_watchdog_cutoff_timestamp_seconds{{binding="{binding_sha}"}} {parse_time(cutoff).timestamp()}\n'
    return {
        "bisq-staff-pilot-watchdog.service": service,
        "bisq-staff-pilot-cutoff.service": service.replace(
            " --binding ", " --wait-for-lock --binding "
        ).replace("TimeoutStartSec=35min", "TimeoutStartSec=70min"),
        "bisq-staff-pilot-health.timer": cadence,
        "bisq-staff-pilot-cutoff.timer": deadline,
        "staff-pilot-expected.prom": expected,
    }


def timer_realtime(value):
    """systemctl's C/UTC timestamp form, or explicit numeric microseconds."""
    if value.isdigit():
        return datetime.fromtimestamp(int(value) / 1_000_000, timezone.utc)
    try:
        return datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S UTC").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise Refusal("timer_deadline_unreadable") from exc


def timer_monotonic(value):
    if value.isdigit():
        return int(value) / 1_000_000
    units = {
        "us": 0.000001,
        "ms": 0.001,
        "s": 1,
        "min": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }
    parts = re.findall(r"([0-9]+(?:\.[0-9]+)?)(us|ms|min|s|h|d|w)", value)
    need(
        parts and " ".join(n + u for n, u in parts) == value,
        "timer_monotonic_unreadable",
    )
    return sum(float(number) * units[unit] for number, unit in parts)


def verify_installation(
    binding,
    binding_sha,
    *,
    script_path,
    binding_path,
    unit_dir=Path("/etc/systemd/system"),
    run=subprocess.run,
    clock=lambda: datetime.now(timezone.utc),
    monotonic=time.monotonic,
):
    """Read installed files/systemd metadata; never install, enable or activate.

    The new pilot's activation controller must require this successful acceptance
    receipt, including a fresh initial host health result, before generation-on.
    """
    need(clock() < parse_time(binding["end_at"]), "activation_cutoff_not_future")
    need(
        not (Path(binding["state_dir"]) / "finalized.json").exists(),
        "activation_already_finalized",
    )
    watchdog = Watchdog(binding, binding_sha)
    for phase in PHASES:
        for prior in (
            watchdog.phases / phase,
            watchdog.state / (phase + ".intent.json"),
        ):
            need(
                not prior.exists() and not prior.is_symlink(),
                "activation_terminal_attempt_exists",
            )
    watchdog.pins()
    need(
        binding["files_sha256"].get(str(script_path)) == digest(private(script_path)),
        "coordinator_not_pinned",
    )
    rendered = render_units(
        script_path=script_path,
        binding_path=binding_path,
        state_dir=binding["state_dir"],
        binding_sha=binding_sha,
        cutoff=binding["end_at"],
    )
    proofs = {}
    for name, content in rendered.items():
        if name.endswith(".prom"):
            target = Path(binding["metrics_path"]).with_name(name)
        else:
            target = unit_dir / name
        # Unit/metric files are intentionally readable; parent directories must
        # be root-controlled and installer-reviewed. Refuse symlink replacement.
        need(
            not target.is_symlink()
            and target.is_file()
            and target.read_bytes() == content.encode(),
            "installed_file_changed",
        )
        info = target.stat()
        need(
            info.st_uid == os.geteuid() and not info.st_mode & 0o022,
            "installed_file_owner_or_mode",
        )
        proofs[name] = digest(content.encode())
        if name.endswith(".prom"):
            continue
        observed = run(
            [
                "systemctl",
                "show",
                name,
                "--no-pager",
                "--property=LoadState,ActiveState,UnitFileState,FragmentPath,NeedDaemonReload,DropInPaths,NextElapseUSecRealtime,NextElapseUSecMonotonic",
            ],
            capture_output=True,
            timeout=15,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
        )
        fields = dict(
            line.split("=", 1)
            for line in observed.stdout.decode().splitlines()
            if "=" in line
        )
        need(
            fields.get("LoadState") == "loaded"
            and fields.get("NeedDaemonReload") == "no"
            and fields.get("FragmentPath") == str(target)
            and fields.get("DropInPaths") == "",
            "installed_unit_not_loaded_exactly",
        )
        if name.endswith(".timer"):
            need(
                fields.get("ActiveState") == "active"
                and fields.get("UnitFileState") == "enabled",
                "installed_timer_not_active",
            )
            if name == "bisq-staff-pilot-cutoff.timer":
                need(
                    timer_realtime(fields.get("NextElapseUSecRealtime", ""))
                    == parse_time(binding["end_at"]),
                    "installed_cutoff_trigger_changed",
                )
            else:
                delay = (
                    timer_monotonic(fields.get("NextElapseUSecMonotonic", ""))
                    - monotonic()
                )
                need(0 < delay <= CADENCE + GRACE, "installed_health_trigger_missing")
    last = json.loads(private(Path(binding["state_dir"]) / "last-success.json"))
    attempt = json.loads(private(Path(binding["state_dir"]) / "last-attempt.json"))
    need(
        last.get("binding_sha256") == binding_sha
        and attempt.get("binding_sha256") == binding_sha
        and attempt.get("success") is True
        and last.get("observation", {}).get("healthy") is True
        and last.get("observation", {}).get("policy", {}).get("generation_enabled")
        is False
        and last.get("stop_verified") is False
        and last.get("finalization_verified") is False
        and 0 <= (clock() - parse_time(last["captured_at"])).total_seconds() <= 150,
        "initial_host_health_not_verified",
    )
    return {
        "success": True,
        "binding_sha256": binding_sha,
        "checked_at": clock().isoformat(),
        "installed_file_sha256": proofs,
        "timers_enabled_and_active": True,
        "initial_success_sha256": digest(
            private(Path(binding["state_dir"]) / "last-success.json")
        ),
        "activation_performed": False,
    }


def run_once(binding, binding_sha, *, wait_for_lock=False, **kwargs):
    state = Path(binding["state_dir"])
    info = state.lstat()
    need(
        stat.S_ISDIR(info.st_mode)
        and not state.is_symlink()
        and info.st_uid == os.geteuid()
        and not info.st_mode & 0o077,
        "private_state_directory_required",
    )
    fd = os.open(state / "watchdog.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait_for_lock else fcntl.LOCK_NB))
        watchdog = Watchdog(binding, binding_sha, **kwargs)
        try:
            result = watchdog.tick()
            # The full reviewed observation/checkpoint is one authoritative commit.
            atomic(state / "last-success.json", result)
            atomic(state / "checkpoint.json", result["next_checkpoint"])
            metrics(binding, binding_sha, success=True, now=watchdog.clock())
            atomic(
                state / "last-attempt.json",
                {
                    "success": True,
                    "at": watchdog.clock().isoformat(),
                    "binding_sha256": binding_sha,
                },
            )
            # Stop future timer work only after metrics and evidence are durable.
            if result["finalization_verified"]:
                atomic(
                    state / "finalized.json",
                    {
                        "binding_sha256": binding_sha,
                        "at": watchdog.clock().isoformat(),
                    },
                )
        except Exception as exc:
            code = str(exc) if isinstance(exc, Refusal) else "watchdog_failed"
            atomic(
                state / "last-attempt.json",
                {
                    "success": False,
                    "error_code": code,
                    "at": watchdog.clock().isoformat(),
                    "binding_sha256": binding_sha,
                },
            )
            metrics(binding, binding_sha, success=False, now=watchdog.clock())
            raise
        return result
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--wait-for-lock", action="store_true")
    parser.add_argument("--verify-installation", action="store_true")
    args = parser.parse_args()
    try:
        need(os.geteuid() == 0 and __debug__, "root_nonoptimized_execution_required")
        binding = load_binding(args.binding, args.binding_sha256)
        if args.verify_installation:
            result = verify_installation(
                binding,
                args.binding_sha256,
                script_path=Path(__file__).resolve(),
                binding_path=args.binding,
            )
        else:
            result = run_once(
                binding, args.binding_sha256, wait_for_lock=args.wait_for_lock
            )
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k not in ("observation", "next_checkpoint")
                }
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": (
                        str(exc) if isinstance(exc, Refusal) else "watchdog_failed"
                    ),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
