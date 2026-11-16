"""Regression checks for host checks independent of Codex and ephemeral SSH."""

import importlib.util
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[3] / "scripts/staff_pilot_watchdog.py"
spec = importlib.util.spec_from_file_location("staff_pilot_watchdog", SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def setup(tmp_path):
    now = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    phases = tmp_path / "phases"
    phases.mkdir(mode=0o700)
    controller = tmp_path / "controller.py"
    controller.write_text("# test-pinned controller\n")
    controller.chmod(0o600)
    b = {
        "schema": "staff-pilot-host-watchdog-v1",
        "trial_id": "pilot-test",
        "revision": "a" * 40,
        "descriptor_sha256": "b" * 64,
        "start_at": (now - timedelta(hours=1)).isoformat(),
        "end_at": (now + timedelta(hours=47)).isoformat(),
        "max_cases": 20,
        "state_dir": str(state),
        "phase_dir": str(phases),
        "metrics_path": str(tmp_path / "status.prom"),
        "commands": {
            k: ["/usr/bin/python3", str(controller), k]
            for k in ("limits", "health", *m.PHASES)
        },
        "files_sha256": {str(controller): m.digest(controller.read_bytes())},
        "receipt_lineage": {"resume_authority_kind": "reviewed_initial_activation"},
    }
    return SimpleNamespace(
        b=b, now=now, state=state, phases=phases, sha="c" * 64, controller=controller
    )


def health(s, reserved=1, active=0, stopped=False):
    cp = {
        "captured_at": s.now.isoformat(),
        "descriptor_sha256": s.b["descriptor_sha256"],
        "health_sha256": "d" * 64,
        "ledger_sha256": "e" * 64,
        "cursor_sha256": "f" * 64,
    }
    return {
        "healthy": True,
        "trial_id": s.b["trial_id"],
        "revision": s.b["revision"],
        "descriptor_sha256": s.b["descriptor_sha256"],
        "captured_at": s.now.isoformat(),
        "health_sha256": cp["health_sha256"],
        "next_checkpoint": cp,
        "ledger": {
            "summary_sha256": cp["ledger_sha256"],
            "reserved_cases": reserved,
            "max_cases": 20,
            "uncertain_or_active_count": active,
        },
        "cursor": {
            "cursor_sha256": cp["cursor_sha256"],
            "same_established_identity": True,
            "same_established_session": True,
            "saved_cursor_present": True,
        },
        "policy": {
            "generation_enabled": not stopped,
            "scope_safe": True,
            "global_delivery_disabled": True,
        },
        "listener_configured_stopped": stopped,
        "api_healthy": True,
        "scheduler_healthy": True,
        "predecessor_history_preserved": True,
        "matrix_requests": 0,
        "provider_calls": 0,
    }


def terminal(s, phase, success=True):
    folder = s.phases / phase
    folder.mkdir()
    base = {
        "phase": phase,
        "revision": s.b["revision"],
        "descriptor_sha256": s.b["descriptor_sha256"],
        **s.b["receipt_lineage"],
    }
    receipt = {**base, "success": success, "completed_at": s.now.isoformat()}
    if phase == "stop":
        receipt.update(
            generation_enabled=False,
            sync_enabled=False,
            api_healthy=True,
            identity_preserved=True,
            trial_ledger_preserved=True,
            original_histories_preserved=True,
            other_services_unchanged=True,
        )
    else:
        receipt.update(
            scheduler_recreated=False,
            scheduler_healthy=True,
            other_services_unchanged=True,
            expired_overlay_retained=True,
            indefinite_selected_job_hold_retained=True,
        )
    for name, data in [("intent.json", base), ("receipt.json", receipt)]:
        path = folder / name
        path.write_bytes(m.encoded(data))
        path.chmod(0o600)
    return receipt


def limits(s, reserved=1, active=0):
    return {
        "trial_id": s.b["trial_id"],
        "revision": s.b["revision"],
        "descriptor_sha256": s.b["descriptor_sha256"],
        "captured_at": s.now.isoformat(),
        "max_cases": s.b["max_cases"],
        "reserved_cases": reserved,
        "uncertain_or_active_count": active,
        "matrix_requests": 0,
        "provider_calls": 0,
    }


def runner(s, results, limits_results=None):
    calls = []

    def run(argv, **kwargs):
        kind = argv[2]
        calls.append(kind)
        if kind == "limits":
            value = limits_results.pop(0) if limits_results else limits(s)
            if isinstance(value, Exception):
                raise value
            return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode())
        if kind != "health":
            terminal(s, kind)
            return SimpleNamespace(returncode=0, stdout=b"controller output ignored")
        next_value = results.pop(0)
        if isinstance(next_value, Exception):
            raise next_value
        return SimpleNamespace(returncode=0, stdout=json.dumps(next_value).encode())

    return run, calls


def test_ssh_ignores_missing_control_directory_without_changing_trust(tmp_path):
    config = tmp_path / "config"
    config.write_text(
        "Host test\n HostName example.invalid\n ControlMaster auto\n ControlPath /does/not/exist/socket\n StrictHostKeyChecking yes\n"
    )
    args = m.no_multiplexing(
        ["ssh", "-F", str(config), "-o", "BatchMode=yes", "test", "true"]
    )
    result = subprocess.run(
        [*args[:-2], "-G", "test"], capture_output=True, text=True, check=True
    )
    settings = dict(
        line.split(" ", 1) for line in result.stdout.splitlines() if " " in line
    )
    assert settings["controlmaster"] == "false"
    assert settings.get("controlpath", "none") == "none"
    assert settings["controlpersist"] == "no"
    assert settings["stricthostkeychecking"] == "true"
    assert settings["batchmode"] == "yes"


def test_success_persists_atomic_complete_checkpoint(setup):
    s = setup
    run, calls = runner(s, [health(s)])
    result = m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    saved = json.loads(m.private(s.state / "last-success.json"))
    assert saved == result and saved["next_checkpoint"] == health(s)["next_checkpoint"]
    assert calls == ["limits", "health"] and saved["previous_success_missing_or_stale"]


@pytest.mark.parametrize(
    "broken",
    [
        "unhealthy",
        "missing_checkpoint",
        "wrong_descriptor",
        "future",
        "calls",
        "usage_cap",
    ],
)
def test_exit_zero_is_not_success_and_prior_checkpoint_survives(setup, broken):
    s = setup
    first, _ = runner(s, [health(s)])
    m.run_once(s.b, s.sha, run=first, clock=lambda: s.now)
    old = (s.state / "last-success.json").read_bytes()
    cp = (s.state / "checkpoint.json").read_bytes()
    o = health(s)
    if broken == "unhealthy":
        o["healthy"] = False
    if broken == "missing_checkpoint":
        o.pop("next_checkpoint")
    if broken == "wrong_descriptor":
        o["descriptor_sha256"] = "0" * 64
    if broken == "future":
        o["captured_at"] = (s.now + timedelta(seconds=1)).isoformat()
    if broken == "calls":
        o["matrix_requests"] = 1
    if broken == "usage_cap":
        o["ledger"]["reserved_cases"] = 21
    run, _ = runner(s, [o, health(s, stopped=True)])
    with pytest.raises(m.Refusal):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert (s.state / "last-success.json").read_bytes() == old
    assert (s.state / "checkpoint.json").read_bytes() == cp
    assert (
        'last_attempt_success{binding="' + s.sha + '"} 0'
        in Path(s.b["metrics_path"]).read_text()
    )


def test_deadline_does_not_wait_for_codex_or_initial_health(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"]) + timedelta(seconds=3)
    run, calls = runner(s, [health(s, reserved=20, stopped=True)])
    result = m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["stop", "scheduler-finalize", "health"]
    assert result["stop_verified"] and result["finalization_verified"]
    assert result["shutdown_delay_seconds"] == 3


def test_terminal_success_never_replayed_after_restart(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    terminal(s, "stop")
    terminal(s, "scheduler-finalize")
    run, calls = runner(s, [health(s, stopped=True)])
    m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["health"]


@pytest.mark.parametrize("partial", ["canonical", "local", "failed"])
def test_existing_or_ambiguous_intent_is_observe_only(setup, partial):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    if partial == "canonical":
        (s.phases / "stop").mkdir()
    elif partial == "local":
        m.exclusive(s.state / "stop.intent.json", {"phase": "stop"})
    else:
        terminal(s, "stop", success=False)
    run, calls = runner(s, [])
    with pytest.raises(m.Refusal):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert not calls


def test_phase_exit_zero_without_canonical_receipt_is_not_success(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    calls = []

    def run(argv, **kw):
        calls.append(argv[2])
        return SimpleNamespace(returncode=0, stdout=b"{}")

    with pytest.raises(m.Refusal):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["stop"] and not (s.state / "last-success.json").exists()
    with pytest.raises(m.Refusal):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["stop"]


def test_cap_drains_once_then_stops_without_finalizing_before_cutoff(setup):
    s = setup
    run, calls = runner(
        s, [health(s, 20, stopped=True)], [limits(s, 20, 1), limits(s, 20, 0)]
    )
    slept = []
    result = m.run_once(
        s.b, s.sha, run=run, clock=lambda: s.now, sleep=lambda n: slept.append(n)
    )
    assert calls == ["limits", "limits", "stop", "health"] and slept == [120]
    assert result["stop_verified"] and not result["finalization_verified"]


def test_active_work_at_deadline_is_contained_without_drain(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    run, calls = runner(s, [health(s, 20, 1, stopped=True)])
    result = m.run_once(
        s.b,
        s.sha,
        run=run,
        clock=lambda: s.now,
        sleep=lambda n: pytest.fail("no deadline delay"),
    )
    assert calls == ["stop", "scheduler-finalize", "health"]
    assert result["observation"]["ledger"]["uncertain_or_active_count"] == 1


def test_drain_limits_failure_does_not_erase_cap_obligation(setup):
    s = setup
    run, calls = runner(
        s,
        [health(s, 20, stopped=True)],
        [limits(s, 20, 1), RuntimeError("unavailable")],
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now, sleep=lambda n: None)
    assert calls == ["limits", "limits", "stop", "health"]
    assert not (s.state / "last-success.json").exists()
    assert (s.phases / "stop" / "receipt.json").exists()


def test_cap_is_checked_despite_full_health_failure(setup):
    s = setup
    bad = health(s, 20, stopped=True)
    bad["healthy"] = False
    run, calls = runner(s, [bad], [limits(s, 20)])
    with pytest.raises(m.Refusal, match="health_not_successful"):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["limits", "stop", "health"]


def test_successful_health_crossing_cutoff_still_stops(setup):
    s = setup
    s.b["end_at"] = (s.now + timedelta(seconds=1)).isoformat()
    base, calls = runner(s, [])
    health_calls = []

    def run(argv, **kw):
        if argv[2] == "health":
            health_calls.append(True)
            if len(health_calls) == 1:
                s.now += timedelta(seconds=2)
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(health(s, stopped=len(health_calls) > 1)).encode(),
            )
        return base(argv, **kw)

    result = m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert result["finalization_verified"] and calls == [
        "limits",
        "stop",
        "scheduler-finalize",
    ]
    assert len(health_calls) == 2


def test_already_stopped_health_crossing_cutoff_finalizes(setup):
    s = setup
    s.b["end_at"] = (s.now + timedelta(seconds=1)).isoformat()
    terminal(s, "stop")
    base, calls = runner(s, [])

    def run(argv, **kw):
        if argv[2] == "health":
            s.now += timedelta(seconds=2)
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(health(s, stopped=True)).encode()
            )
        return base(argv, **kw)

    result = m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert result["finalization_verified"] and calls == ["scheduler-finalize"]
    assert result["shutdown_delay_seconds"] == 0


def test_reporting_corruption_cannot_prevent_deadline_containment(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    m.atomic(s.state / "last-success.json", b"broken")
    run, calls = runner(s, [health(s, stopped=True)])
    with pytest.raises(m.Refusal, match="saved_success_invalid"):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["stop", "scheduler-finalize", "health"]
    assert (s.state / "last-success.json").read_bytes() == b"broken"


def test_material_scope_failure_contains_and_preserves_failed_health(setup):
    s = setup
    bad = health(s)
    bad["healthy"] = False
    bad["policy"]["scope_safe"] = False
    run, calls = runner(s, [bad, health(s, stopped=True)])
    with pytest.raises(m.Refusal, match="material_safety_failure"):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["limits", "health", "stop", "health"]
    assert not (s.state / "last-success.json").exists()


def test_shutdown_delay_does_not_grow_at_later_observations(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"]) + timedelta(seconds=3)
    terminal(s, "stop")
    terminal(s, "scheduler-finalize")
    s.now += timedelta(hours=12)
    run, calls = runner(s, [health(s, stopped=True)])
    result = m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert result["shutdown_delay_seconds"] == 3
    assert calls == ["health"]


def test_changed_controller_is_refused_before_effect(setup):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    s.controller.write_text("# changed\n")
    run, calls = runner(s, [])
    with pytest.raises(m.Refusal, match="controller_source_changed"):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == []


def test_stale_success_is_observed_and_units_are_host_owned(setup):
    s = setup
    run, _ = runner(s, [health(s)])
    m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    s.now += timedelta(hours=13)
    run, _ = runner(s, [health(s)])
    assert m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)[
        "previous_success_missing_or_stale"
    ]
    units = m.render_units(
        script_path="/opt/owned/watchdog.py",
        binding_path="/opt/owned/binding.json",
        state_dir="/opt/owned/state",
        binding_sha=s.sha,
        cutoff=s.b["end_at"],
    )
    assert "OnUnitActiveSec=12h" in units["bisq-staff-pilot-health.timer"]
    assert "OnBootSec=1min" in units["bisq-staff-pilot-health.timer"]
    assert "Persistent=true" in units["bisq-staff-pilot-cutoff.timer"]
    assert "AccuracySec=1s" in units["bisq-staff-pilot-cutoff.timer"]
    assert "Restart=no" in units["bisq-staff-pilot-watchdog.service"]
    assert (
        "Unit=bisq-staff-pilot-cutoff.service" in units["bisq-staff-pilot-cutoff.timer"]
    )
    assert "--wait-for-lock" in units["bisq-staff-pilot-cutoff.service"]


def test_final_reservation_between_limits_and_health_still_stops(setup):
    s = setup
    run, calls = runner(
        s, [health(s, 20), health(s, 20, stopped=True)], [limits(s, 19)]
    )
    result = m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert calls == ["limits", "health", "stop", "health"]
    assert result["stop_verified"]


def test_cutoff_waits_for_running_health_lock_instead_of_losing_wake(setup):
    import fcntl
    import threading

    s = setup
    s.now = m.parse_time(s.b["end_at"])
    fd = os.open(s.state / "watchdog.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    started, done = threading.Event(), threading.Event()
    result, errors = [], []
    run, calls = runner(s, [health(s, stopped=True)])

    def invoke():
        started.set()
        try:
            result.append(
                m.run_once(s.b, s.sha, run=run, clock=lambda: s.now, wait_for_lock=True)
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=invoke)
    thread.start()
    assert started.wait(1)
    assert not done.wait(0.05) and not calls
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    assert done.wait(2)
    thread.join()
    assert not errors and result[0]["finalization_verified"]
    assert calls == ["stop", "scheduler-finalize", "health"]


def test_metric_write_failure_does_not_finalize_or_claim_attempt_success(
    setup, monkeypatch
):
    s = setup
    s.now = m.parse_time(s.b["end_at"])
    run, _ = runner(s, [health(s, stopped=True)])

    def fail(*args, **kwargs):
        raise OSError("unavailable")

    monkeypatch.setattr(m, "metrics", fail)
    with pytest.raises(OSError):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert not (s.state / "finalized.json").exists()
    assert json.loads(m.private(s.state / "last-attempt.json"))["success"] is False


def test_fractional_cutoff_cannot_silently_render_an_early_timer(setup):
    with pytest.raises(m.Refusal, match="whole_second_boundaries_required"):
        m.render_units(
            script_path="/opt/pilot/watchdog.py",
            binding_path="/opt/pilot/binding.json",
            state_dir="/opt/pilot/state",
            binding_sha=setup.sha,
            cutoff="2026-12-03T11:00:00.500000+00:00",
        )


def test_premature_finalization_receipt_is_never_accepted(setup):
    s = setup
    terminal(s, "stop")
    terminal(s, "scheduler-finalize")
    run, _ = runner(s, [health(s, stopped=True)])
    with pytest.raises(m.Refusal, match="premature_finalization_receipt"):
        m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    assert not (s.state / "finalized.json").exists()


@pytest.mark.parametrize(
    "break_gate",
    [
        None,
        "timer_inactive",
        "timer_elapsed",
        "file_changed",
        "initial_health_missing",
        "initial_generation_on",
        "early_stop_attempt",
    ],
)
def test_activation_acceptance_needs_installed_exact_active_units(
    setup, tmp_path, break_gate
):
    s = setup
    units = tmp_path / "units"
    units.mkdir()
    binding_path = tmp_path / "binding.json"
    rendered = m.render_units(
        script_path=s.controller,
        binding_path=binding_path,
        state_dir=s.state,
        binding_sha=s.sha,
        cutoff=s.b["end_at"],
    )
    for name, content in rendered.items():
        destination = (
            Path(s.b["metrics_path"]).with_name(name)
            if name.endswith(".prom")
            else units / name
        )
        destination.write_text(content)
        destination.chmod(0o644)
    initial = health(s)
    initial["policy"]["generation_enabled"] = break_gate == "initial_generation_on"
    run, _ = runner(s, [initial])
    m.run_once(s.b, s.sha, run=run, clock=lambda: s.now)
    if break_gate == "early_stop_attempt":
        (s.phases / "stop").mkdir()
    if break_gate == "file_changed":
        (units / "bisq-staff-pilot-cutoff.timer").write_text("changed")
    if break_gate == "initial_health_missing":
        (s.state / "last-success.json").unlink()

    def systemctl(argv, **kw):
        name = argv[2]
        active = "inactive" if break_gate == "timer_inactive" else "active"
        deadline = (
            "0"
            if break_gate == "timer_elapsed"
            else str(int(m.parse_time(s.b["end_at"]).timestamp() * 1_000_000))
        )
        return SimpleNamespace(
            stdout=(
                f"LoadState=loaded\nActiveState={active}\nUnitFileState=enabled\nFragmentPath={units/name}\nNeedDaemonReload=no\nDropInPaths=\nNextElapseUSecRealtime={deadline}\nNextElapseUSecMonotonic=43201000000\n"
            ).encode()
        )

    if break_gate:
        with pytest.raises((m.Refusal, FileNotFoundError)):
            m.verify_installation(
                s.b,
                s.sha,
                script_path=s.controller,
                binding_path=binding_path,
                unit_dir=units,
                run=systemctl,
                clock=lambda: s.now,
                monotonic=lambda: 1,
            )
    else:
        proof = m.verify_installation(
            s.b,
            s.sha,
            script_path=s.controller,
            binding_path=binding_path,
            unit_dir=units,
            run=systemctl,
            clock=lambda: s.now,
            monotonic=lambda: 1,
        )
        assert (
            proof["success"]
            and proof["timers_enabled_and_active"]
            and not proof["activation_performed"]
        )
