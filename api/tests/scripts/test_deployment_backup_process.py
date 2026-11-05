"""Canonical backup boundary and uninterrupted monitoring-process checks."""

import copy
import importlib
import os
import shlex
import subprocess
from pathlib import Path

import pytest
from test_deployment_host import container

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.unit


@pytest.fixture
def backup_host(tmp_path, monkeypatch):
    """Build an isolated host with no Docker, network or provider access."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("lib.deployment_host")
    host = module.DeploymentHost.__new__(module.DeploymentHost)
    host.install = tmp_path / "install"
    host.install.mkdir()
    host.operation = tmp_path / "operation"
    host.root = host.operation / "host"
    host.root.mkdir(parents=True, mode=0o700)
    host.plan = {
        "schema": "deployment-plan-v5",
        "monitoring_sha256": {
            "docker/scripts/scheduler-heartbeat.sh": "a" * 64,
            "docker/prometheus/alert_rules.yml": "a" * 64,
        },
    }
    host.profile = {"fixture": "bound-profile"}
    host.approval = {"deadline": "2026-11-05T18:00:00+00:00"}
    prometheus = container("prometheus", "a", host.install)
    prometheus["State"]["StartedAt"] = "2026-11-05T09:00:00.000000001Z"
    host.baseline = {
        "containers": {"prometheus": copy.deepcopy(prometheus)},
        "monitoring": {
            "reload_timestamp": 1793869200,
            "heartbeat_file": {
                "inode": 1,
                "device": 1,
                "mode": 493,
                "uid": 0,
                "gid": 0,
            },
        },
    }
    host.baseline_sha256 = module.digest(module.encode(host.baseline))
    host.pause_expected = True
    host._capture_hashes = {}
    host._inspect = lambda: {"prometheus": copy.deepcopy(prometheus)}
    host._monitoring_file = lambda _: copy.deepcopy(
        host.baseline["monitoring"]["heartbeat_file"]
    )
    host._monitoring_reload_state = lambda _: {
        "success": 1,
        "timestamp": (
            host._process_started_ns(module.process_identity(prometheus)) + 100000000
        )
        / 10**9,
    }
    host._monitoring_mounts = lambda _: None
    host.verify_preservation = lambda: host._monitoring_preserved(host._inspect())
    host._state = lambda: {}
    host._prefix = lambda _: None
    routes = []
    host._api_ready = lambda *_args, **_kwargs: routes.append("route-verified")
    return host, module, prometheus, routes


def capture(backup_host, phase, *, offset=0):
    """Produce a real canonical receipt over synthetic bytes and owner-clock evidence."""
    host, module, prometheus, _ = backup_host
    # Ordinary owner checks continuity before invoking capture_backup.
    host.verify_preservation()
    attempt = host.operation / "recovery" / phase
    attempt.mkdir(parents=True, mode=0o700)
    intent = {
        "plan_sha256": module.digest(module.encode(host.plan)),
        "profile_sha256": module.digest(module.encode(host.profile)),
        "phase": phase,
        "intent_sha256": "f" * 64,
        "deadline": host.approval["deadline"],
    }
    module.exclusive_record(attempt / "capture-intent.json", intent)
    epoch = (
        host._process_started_ns(
            {"pid": 1, "restart_count": 0, "started_at": "2026-11-05T10:00:00Z"}
        )
        + offset * 10**9
    )
    os.utime(attempt / "capture-intent.json", ns=(epoch, epoch))
    prometheus["RestartCount"] = 0
    prometheus["State"]["Pid"] += 1
    prometheus["State"]["StartedAt"] = f"2026-11-05T10:00:{offset + 3:02d}.000000123Z"
    export = attempt / "export"
    export.mkdir(mode=0o700)
    ciphertext = export / "bisq-support-backup-synthetic.tar.gz.gpg"
    ciphertext.write_bytes(b"synthetic encrypted bytes, no private data")
    ciphertext.chmod(0o600)
    # Execute the actual ordinary producer, not a handwritten success receipt.
    program = f"""source {shlex.quote(str(ROOT / "scripts/backup.sh"))}
TARGET_DIR={shlex.quote(str(export))}; EXPORT_DIR="$TARGET_DIR"
COMPLETED_OUTPUT_NAME={shlex.quote(ciphertext.name)}
BACKUP_RECEIPT={shlex.quote(str(attempt / "canonical-backup.json"))}
write_backup_receipt
"""
    subprocess.run(["bash", "-c", program], check=True, capture_output=True)
    os.utime(
        attempt / "canonical-backup.json", ns=(epoch + 5 * 10**9, epoch + 5 * 10**9)
    )
    accepted = module.digest((attempt / "canonical-backup.json").read_bytes())
    host._capture_hashes[phase] = accepted
    start = {"schema": "deployment-monitoring-capture-intent-v1", "binding": intent}
    module.exclusive_record(attempt / "monitoring-capture.intent.json", start)
    module.exclusive_record(
        attempt / "monitoring-capture.result.json",
        {
            "schema": "deployment-monitoring-capture-result-v1",
            "intent_sha256": module.digest(module.encode(start)),
            "canonical_backup_receipt_sha256": accepted,
            "began": {
                "wall_before_ns": epoch - 1,
                "monotonic_ns": 100,
                "wall_after_ns": epoch,
            },
            "finished": {
                "wall_before_ns": epoch + 5 * 10**9,
                "monotonic_ns": 100 + 5 * 10**9,
                "wall_after_ns": epoch + 5 * 10**9 + 1,
            },
        },
    )
    return attempt


def resume(host, phase, intent, started):
    """Pass the capture-accepted raw receipt hash into the maintained verifier."""
    return host._verify_backup_resumption(
        phase, intent, started, canonical_receipt_sha256=host._capture_hashes[phase]
    )


def test_both_backup_boundaries_accept_only_the_canonical_process(backup_host):
    """Keep the initial baseline immutable while both bound restarts advance the chain."""
    host, module, prometheus, routes = backup_host
    original = copy.deepcopy(host.baseline)
    for phase, offset in (("prechange_backup", 0), ("postchange_backup", 10)):
        capture(backup_host, phase, offset=offset)
        with pytest.raises(
            module.JournalError, match="host_monitoring_process_changed"
        ):
            host.verify_preservation()
        resume(host, phase, "f" * 64, module.now())
        host.verify_preservation()
        assert module.read_record(host.root / "backup-processes" / (phase + ".json"))[
            "after"
        ] == module.process_identity(prometheus)
    assert routes == ["route-verified", "route-verified"]
    assert host.baseline == original
    # A reconnect loads the immutable baseline plus the two persisted proofs.
    reconnect = copy.copy(host)
    assert reconnect._monitoring_expected_state()["process"] == module.process_identity(
        prometheus
    )
    prometheus["State"]["StartedAt"] = "2026-11-05T10:01:00Z"
    with pytest.raises(module.JournalError, match="host_monitoring_process_changed"):
        reconnect._monitoring_preserved(reconnect._inspect())


@pytest.mark.parametrize(
    "fault",
    [
        "missing_receipt",
        "wrong_intent",
        "not_resumed",
        "cleanup_failed",
        "late_restart",
        "early_restart",
        "auto_restart",
        "new_identity",
        "changed_config",
    ],
)
def test_unproved_restart_never_becomes_a_checkpoint(backup_host, fault):
    """Refuse missing or contradictory evidence before adopting a restarted process."""
    host, module, prometheus, routes = backup_host
    attempt = capture(backup_host, "prechange_backup")
    path = attempt / "canonical-backup.json"
    if fault == "missing_receipt":
        path.unlink()
    elif fault in {"not_resumed", "cleanup_failed"}:
        value = module.read_record(path)
        value[
            "writers_resumed" if fault == "not_resumed" else "scratch_cleanup_verified"
        ] = False
        path.write_bytes(module.encode(value))
    elif fault == "late_restart":
        prometheus["State"]["StartedAt"] = "2026-11-05T10:00:06Z"
    elif fault == "early_restart":
        prometheus["State"]["StartedAt"] = "2026-11-05T09:59:59Z"
    elif fault == "auto_restart":
        prometheus["RestartCount"] += 1
    elif fault == "new_identity":
        prometheus["Id"] = "b" * 64
    elif fault == "changed_config":
        prometheus["Config"]["Cmd"] = ["unreviewed"]
    with pytest.raises((module.JournalError, OSError)):
        resume(
            host,
            "prechange_backup",
            ("e" if fault == "wrong_intent" else "f") * 64,
            module.now(),
        )
    assert not (host.root / "backup-processes/prechange_backup.json").exists()
    assert routes == []


@pytest.mark.parametrize(
    "fault",
    ["receipt_bytes", "capture_mtime", "checkpoint_process", "completion_bytes"],
)
def test_saved_proof_tampering_is_not_accepted_on_reconnect(backup_host, fault):
    """Revalidate every saved capture join before trusting a reconnected checkpoint."""
    host, module, _, _ = backup_host
    attempt = capture(backup_host, "prechange_backup")
    resume(host, "prechange_backup", "f" * 64, module.now())
    if fault == "receipt_bytes":
        path = attempt / "canonical-backup.json"
        value = module.read_record(path)
        value["ciphertext_sha256"] = "e" * 64
        path.write_bytes(module.encode(value))
    elif fault == "completion_bytes":
        path = attempt / "monitoring-capture.result.json"
        value = module.read_record(path)
        value["canonical_backup_receipt_sha256"] = "e" * 64
        path.write_bytes(module.encode(value))
    elif fault == "capture_mtime":
        path = attempt / "capture-intent.json"
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1))
    else:
        path = host.root / "backup-processes/prechange_backup.json"
        value = module.read_record(path)
        value["after"]["pid"] += 1
        path.write_bytes(module.encode(value))
    with pytest.raises(module.JournalError):
        host.verify_preservation()


@pytest.mark.parametrize(
    "fault", ["postchange_only", "unexpected_file", "plan_binding", "baseline_binding"]
)
def test_checkpoint_chain_rejects_unbound_or_out_of_order_records(backup_host, fault):
    """Reject extra, reordered or rebound private checkpoint files."""
    host, module, _, _ = backup_host
    capture(backup_host, "prechange_backup")
    resume(host, "prechange_backup", "f" * 64, module.now())
    path = host.root / "backup-processes/prechange_backup.json"
    if fault == "postchange_only":
        path.rename(path.with_name("postchange_backup.json"))
    elif fault == "unexpected_file":
        path.with_name("unreviewed.json").write_text("{}")
    else:
        value = module.read_record(path)
        value["plan_sha256" if fault == "plan_binding" else "baseline_sha256"] = (
            "e" * 64
        )
        path.write_bytes(module.encode(value))
    with pytest.raises(module.JournalError):
        host.verify_preservation()


def test_failed_route_retains_process_proof_and_is_not_retried(backup_host):
    """Preserve a proved capture when route verification fails, without replay."""
    host, module, _, _ = backup_host
    capture(backup_host, "prechange_backup")

    def fail(*_args, **_kwargs):
        raise module.JournalError("route_failure")

    host._api_ready = fail
    with pytest.raises(module.JournalError, match="route_failure"):
        resume(host, "prechange_backup", "f" * 64, module.now())
    assert (
        module.read_record(host.root / "backup-routes/prechange_backup.result.json")[
            "status"
        ]
        == "failed"
    )
    with pytest.raises(module.JournalError):
        resume(host, "prechange_backup", "f" * 64, module.now())
    assert host.pause_expected is True


@pytest.mark.parametrize("fault", ["failed", "before_start", "after_capture"])
def test_backup_reload_state_must_belong_to_that_restart(backup_host, fault):
    """Require successful configuration load strictly inside the owner capture window."""
    host, module, _, _ = backup_host
    capture(backup_host, "prechange_backup")
    started = (
        host._process_started_ns(module.process_identity(host._inspect()["prometheus"]))
        / 10**9
    )
    state = {"success": 1, "timestamp": started + 0.1}
    if fault == "failed":
        state["success"] = 0
    else:
        state["timestamp"] = started - 1 if fault == "before_start" else started + 10
    host._monitoring_reload_state = lambda _: state
    with pytest.raises(module.JournalError, match="host_monitoring_backup_reload"):
        resume(host, "prechange_backup", "f" * 64, module.now())
    assert not (host.root / "backup-processes/prechange_backup.json").exists()


@pytest.mark.parametrize("drift", [False, True])
def test_both_backups_then_publication_reload_and_resumed_heartbeat(
    backup_host, monkeypatch, drift
):
    """Use the latest startup load for one publication HUP and resumed heartbeat."""
    host, module, prometheus, _ = backup_host
    for phase, offset in (("prechange_backup", 0), ("postchange_backup", 10)):
        capture(backup_host, phase, offset=offset)
        resume(host, phase, "f" * 64, module.now())
    checkpoint = host._monitoring_expected_state()
    assert (
        checkpoint["reload_timestamp"]
        != host.baseline["monitoring"]["reload_timestamp"]
    )
    reload_state = {
        "success": 1,
        "timestamp": checkpoint["reload_timestamp"] + int(drift),
    }
    host._monitoring_reload_state = lambda _: copy.deepcopy(reload_state)
    host.host = {"readiness_timeout_seconds": 1}
    host._monitoring_file = lambda _: copy.deepcopy(
        host.baseline["monitoring"]["heartbeat_file"]
    ) | {"sha256": "a" * 64}
    host._inspect = lambda: {"prometheus": copy.deepcopy(prometheus), "scheduler": {}}
    host._preserved = lambda current: host._monitoring_preserved(current)
    calls = []

    def command(argv, *_args, **_kwargs):
        calls.append(argv)
        if argv[:4] == ["docker", "kill", "--signal", "HUP"]:
            reload_state["timestamp"] += 1
        return b""

    host._run = command
    host._monitoring_loaded_rules = lambda _: "b" * 64
    if drift:
        with pytest.raises(module.JournalError, match="host_monitoring_reload_drift"):
            host._monitoring_reload()
        assert calls == []
        return
    host._monitoring_reload()
    assert sum(argv[:4] == ["docker", "kill", "--signal", "HUP"] for argv in calls) == 1
    resumed = int(reload_state["timestamp"]) + 2
    host.baseline["monitoring"]["heartbeat_timestamp"] = resumed - 100
    raw = (
        f"scheduler_heartbeat_timestamp_seconds {resumed}\n"
        f"scheduler_retention_hold_active 1\nscheduler_retention_hold_invalid 0\n"
        f"scheduler_retention_hold_cutoff_timestamp_seconds {resumed - 50}\n"
        f"scheduler_retention_hold_observed_timestamp_seconds {resumed}\n"
    ).encode()
    host._container_file = lambda *_args: raw
    host._monitoring_scraped_hold = lambda *_args: {"consumed": True}
    monkeypatch.setattr(module.time, "time", lambda: resumed + 1)
    host._monitoring_observe_heartbeat(resumed)
    assert (host.root / "monitoring-heartbeat.private.json").exists()


@pytest.mark.parametrize("before_count", [0, 3, 19])
def test_explicit_start_resets_count_then_later_drift_refuses(
    backup_host, before_count
):
    """Accept explicit-start counter reset only at capture, then restore strict equality."""
    host, module, prom, _ = backup_host
    prom["RestartCount"] = before_count
    host.baseline["containers"]["prometheus"]["RestartCount"] = before_count
    host.baseline_sha256 = module.digest(module.encode(host.baseline))
    capture(backup_host, "prechange_backup")
    resume(host, "prechange_backup", "f" * 64, module.now())
    assert host._monitoring_expected_state()["process"]["restart_count"] == 0
    prom["RestartCount"] = 1
    with pytest.raises(module.JournalError, match="host_monitoring_process_changed"):
        host.verify_preservation()


@pytest.mark.parametrize(
    "fault",
    [
        "changed_receipt",
        "wrong_accepted_hash",
        "missing_completion",
        "window_hash",
        "clock_forward",
        "clock_backward",
        "sample_order",
        "unknown_sample",
        "bool_time",
    ],
)
def test_capture_window_and_accepted_receipt_are_required(backup_host, fault):
    """Reject receipt substitution, missing completion and inconsistent clock samples."""
    host, module, _, routes = backup_host
    attempt = capture(backup_host, "prechange_backup")
    result_path = attempt / "monitoring-capture.result.json"
    if fault == "changed_receipt":
        path = attempt / "canonical-backup.json"
        # Same parsed receipt, different bytes: capture accepted the original bytes.
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "wrong_accepted_hash":
        host._capture_hashes["prechange_backup"] = "e" * 64
    elif fault == "missing_completion":
        result_path.unlink()
    else:
        value = module.read_record(result_path)
        if fault == "window_hash":
            value["intent_sha256"] = "e" * 64
        elif fault == "clock_forward":
            value["finished"]["monotonic_ns"] -= 10000
        elif fault == "clock_backward":
            value["finished"]["monotonic_ns"] += 10000
        elif fault == "sample_order":
            value["began"]["wall_before_ns"] += 100
        elif fault == "unknown_sample":
            value["began"]["unreviewed"] = 1
        elif fault == "bool_time":
            value["began"]["monotonic_ns"] = True
        result_path.write_bytes(module.encode(value))
    with pytest.raises((module.JournalError, OSError)):
        resume(host, "prechange_backup", "f" * 64, module.now())
    assert not (host.root / "backup-processes/prechange_backup.json").exists()
    assert not routes


def test_filesystem_precision_and_skew_do_not_define_capture_window(backup_host):
    """Prove coarse filesystem time cannot enlarge or invalidate owner clock bounds."""
    host, module, _, _ = backup_host
    attempt = capture(backup_host, "prechange_backup")
    for path in attempt.glob("*.json"):
        os.utime(path, ns=(10**9, 10**9))
    resume(host, "prechange_backup", "f" * 64, module.now())
    host.verify_preservation()


def test_owner_clock_sampling_order(monkeypatch):
    """Preserve the wall-monotonic-wall measurement order used by the verifier."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    owner = importlib.import_module("deploy_release_host")
    wall = iter([100, 103])
    monkeypatch.setattr(owner.time, "time_ns", lambda: next(wall))
    monkeypatch.setattr(owner.time, "monotonic_ns", lambda: 102)
    assert owner.capture_clock_sample() == {
        "wall_before_ns": 100,
        "monotonic_ns": 102,
        "wall_after_ns": 103,
    }


@pytest.mark.parametrize("fails", [False, True])
def test_owner_capture_completion_joins_hash_and_blocks_retry(
    tmp_path, monkeypatch, fails
):
    """Join accepted bytes to completion and prohibit a second capture after interruption."""
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    owner_module = importlib.import_module("deploy_release_host")
    recovery = importlib.import_module("lib.deployment_recovery")
    owner = owner_module.Owner.__new__(owner_module.Owner)
    owner.opened, owner.closed, owner.read_only = True, False, False
    owner.plan = {"schema": "deployment-plan-v5"}
    owner.profile = {"test_only": True}
    owner.approval = {"deadline": "2026-11-05T18:00:00+00:00"}
    owner.baseline = {"baseline_sha256": "b" * 64}
    owner.operation = tmp_path / "owner"
    owner.operation.mkdir(mode=0o700)
    (owner.operation / "receipts").mkdir(mode=0o700)
    (owner.operation / "recovery").mkdir(mode=0o700)
    owner._next = lambda phase: None
    verifications, captures = [], []
    owner.host = SimpleNamespace(
        verify_preservation=lambda: None,
        verify_backup_resumption=lambda *a, **kw: verifications.append(kw),
    )
    monkeypatch.setattr(owner_module, "effect_guard", lambda *a: None)
    monkeypatch.setattr(owner_module, "validate_phase_receipt", lambda *a, **kw: None)
    monkeypatch.setattr(
        owner_module, "make_phase_receipt", lambda *a: {"payload": a[5]}
    )

    def capture(profile, attempt, binding):
        """Simulate an accepted capture hash, or fail before producing it."""
        captures.append(binding)
        if fails:
            raise owner_module.JournalError("capture_failed")
        return {"canonical_backup_receipt_sha256": "c" * 64}

    monkeypatch.setattr(recovery, "capture_backup", capture)
    message = {
        "command": "effect",
        "phase": "prechange_backup",
        "intent_sha256": "f" * 64,
    }
    if fails:
        with pytest.raises(owner_module.JournalError, match="capture_failed"):
            owner.dispatch(message)
    else:
        receipt = owner.dispatch(message)["receipt"]
        assert receipt["payload"]["canonical_backup_receipt_sha256"] == "c" * 64
        assert verifications == [{"canonical_receipt_sha256": "c" * 64}]
    attempt = owner.operation / "recovery/prechange_backup"
    assert (attempt / "monitoring-capture.intent.json").exists()
    assert (attempt / "monitoring-capture.result.json").exists() is not fails
    with pytest.raises(owner_module.JournalError):
        owner.dispatch(message)
    assert len(captures) == 1


def test_readonly_status_sees_interrupted_precapture_intent(tmp_path, monkeypatch):
    """Report the sidecar intent even when capture has not written its own intent."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("deploy_release_host")
    owner = module.Owner.__new__(module.Owner)
    owner.host = None
    owner.plan = {"schema": "deployment-plan-v5", "phases": ["prechange_backup"]}
    owner.operation = tmp_path
    attempt = tmp_path / "recovery/prechange_backup"
    attempt.mkdir(parents=True)
    (attempt / "monitoring-capture.intent.json").write_text("{}")
    assert owner._status()["phases"]["prechange_backup"] == {
        "intent_present": True,
        "result_present": False,
    }
