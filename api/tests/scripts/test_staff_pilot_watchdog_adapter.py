"""Adapter contract checks: real saved shapes, synthetic SQLite and fake effects."""

import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    import staff_pilot_watchdog as w
    import staff_pilot_watchdog_adapter as a
finally:
    sys.path.remove(str(SCRIPTS))


@pytest.fixture
def setup(tmp_path):
    descriptor = {
        "trial_id": "pilot-test",
        "source_rooms": ["!source:example.invalid"],
        "staff_room": "!staff:example.invalid",
        "start_at": "2026-12-01T10:00:00+00:00",
        "end_at": "2026-12-03T10:00:00+00:00",
        "max_cases": 20,
    }
    path = tmp_path / "descriptor.json"
    path.write_bytes(w.encoded(descriptor))
    path.chmod(0o600)
    database = tmp_path / "escalations.db"
    db = sqlite3.connect(database)
    db.execute(
        "CREATE TABLE escalations (id INTEGER PRIMARY KEY, channel_metadata TEXT)"
    )
    db.execute(
        "CREATE TABLE matrix_context_trials (trial_id TEXT PRIMARY KEY, descriptor TEXT)"
    )
    db.execute(
        "CREATE TABLE matrix_context_trial_cases (trial_id TEXT, escalation_id INTEGER, reserved_at TEXT)"
    )
    db.commit()
    db.close()
    binding = {
        **{k: descriptor[k] for k in ("trial_id", "start_at", "end_at", "max_cases")},
        "revision": "a" * 40,
        "descriptor_sha256": w.digest(path.read_bytes()),
        "state_dir": str(tmp_path),
    }
    return SimpleNamespace(
        c={"descriptor_path": str(path), "database_path": str(database)},
        b=binding,
        d=descriptor,
        db=database,
    )


def insert(s, *, bound=True, count=1, active=False):
    with closing(sqlite3.connect(s.db)) as db, db:
        if bound:
            db.execute(
                "INSERT INTO matrix_context_trials VALUES (?,?)",
                (s.d["trial_id"], json.dumps(s.d)),
            )
        for i in range(count):
            db.execute(
                "INSERT INTO matrix_context_trial_cases VALUES (?,?,?)",
                (s.d["trial_id"], i, "2026-12-01T11:00:00+00:00"),
            )
            db.execute(
                "INSERT INTO escalations VALUES (?,?)",
                (
                    i,
                    json.dumps(
                        {
                            "context_status": "preparing" if active else "complete",
                            "model_call_status": "reserved" if active else "complete",
                            "private_conversation": "never leave SQLite",
                        }
                    ),
                ),
            )


def test_initial_absent_descriptor_zero_admissions_is_valid(setup):
    result = a.limits(setup.c, setup.b)
    assert result["reserved_cases"] == 0 and result["uncertain_or_active_count"] == 0


def test_cap_and_active_work_read_independently_of_api_health(setup):
    insert(setup, count=20, active=True)
    result = a.limits(setup.c, setup.b)
    assert result["reserved_cases"] == 20 and result["uncertain_or_active_count"] == 20
    assert "private_conversation" not in json.dumps(result)
    assert result["matrix_requests"] == result["provider_calls"] == 0


def test_orphan_reservations_are_not_zero_admissions(setup):
    insert(setup, bound=False)
    with pytest.raises(w.Refusal, match="limits_orphan_reservations"):
        a.limits(setup.c, setup.b)


def test_mismatched_bound_descriptor_refuses(setup):
    insert(setup)
    with closing(sqlite3.connect(setup.db)) as db, db:
        db.execute("UPDATE matrix_context_trials SET descriptor='{}'")
    with pytest.raises(w.Refusal, match="limits_descriptor_changed"):
        a.limits(setup.c, setup.b)


def test_retained_reservation_without_case_remains_consumed_and_uncertain(setup):
    insert(setup)
    with closing(sqlite3.connect(setup.db)) as db, db:
        db.execute("DELETE FROM escalations")
    result = a.limits(setup.c, setup.b)
    assert result["reserved_cases"] == result["uncertain_or_active_count"] == 1


def test_legacy_saved_health_and_terminal_receipts_fit_coordinator(tmp_path):
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/staff_pilot_legacy_contract.json"
        ).read_text()
    )
    h = fixture["health"]
    phases = tmp_path / "phases"
    phases.mkdir()
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    b = {
        "trial_id": h["trial_id"],
        "revision": h["revision"],
        "descriptor_sha256": h["descriptor_sha256"],
        "max_cases": 20,
        "state_dir": str(state),
        "phase_dir": str(phases),
        "end_at": h["end_at"],
        "receipt_lineage": {
            k: fixture["receipts"]["stop"][k]
            for k in (
                "maintenance_resume_sha256",
                "original_resume_failure_sha256",
                "resume_authority_kind",
            )
        },
    }
    watch = w.Watchdog(
        b, "d" * 64, clock=lambda: datetime.fromisoformat(h["captured_at"])
    )
    watch.command = lambda kind: h
    assert watch.health() == h
    for phase, r in fixture["receipts"].items():
        folder = phases / phase
        folder.mkdir()
        intent = {
            k: r[k]
            for k in ("phase", "revision", "descriptor_sha256", *b["receipt_lineage"])
        }
        w.atomic(folder / "intent.json", intent)
        w.atomic(folder / "receipt.json", r)
        assert watch.receipt(phase) == r


def test_adapter_passes_checkpoint_and_never_normalizes_receipts(setup):
    s = setup
    s.c.update(
        health_command=[
            "/usr/bin/python3",
            "/prepared/health.py",
            "--trial-dir",
            "/prepared/trial",
        ],
        phase_commands={
            p: [
                "/bin/bash",
                "/prepared/control.sh",
                p,
                s.b["descriptor_sha256"],
                "none",
            ]
            for p in w.PHASES
        },
    )
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=b'{"healthy":false,"failure_code":"launch_controls_changed"}',
        )

    out = a.execute(
        s.c,
        s.b,
        "health",
        checkpoint=Path(s.b["state_dir"]) / "checkpoint.json",
        run=run,
    )
    assert out["material_safety_failure"] is True
    assert commands[0][-2:] == [
        "--checkpoint",
        str(Path(s.b["state_dir"]) / "checkpoint.json"),
    ]
    out = a.execute(s.c, s.b, "stop", run=run)
    assert out == {
        "controller_returned": True,
        "success_requires_canonical_receipt": True,
    }
    assert commands[1][-3:] == ["stop", s.b["descriptor_sha256"], "none"]


@pytest.mark.parametrize("metadata", [None, "{broken", "{}", '{"context_status":null}'])
def test_malformed_or_missing_metadata_keeps_cap_observable(setup, metadata):
    insert(setup, count=20)
    with closing(sqlite3.connect(setup.db)) as db, db:
        db.execute("UPDATE escalations SET channel_metadata=? WHERE id=0", (metadata,))
    result = a.limits(setup.c, setup.b)
    assert result["reserved_cases"] == 20 and result["uncertain_or_active_count"] == 1


@pytest.mark.parametrize(
    "code",
    [
        "forbidden_delivery_flag_enabled",
        "trial_runtime_binding_changed",
        "api_data_mount_changed",
        "established_session_changed",
        "session_path_changed",
        "held_attempt_changed",
        "closed_history_changed",
    ],
)
def test_material_codes_from_existing_snapshot_are_containment_signals(setup, code):
    setup.c["health_command"] = ["/usr/bin/python3", "/prepared/health.py"]

    def run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"healthy": False, "failure_code": code}).encode(),
        )

    assert (
        a.execute(setup.c, setup.b, "health", run=run)["material_safety_failure"]
        is True
    )


@pytest.mark.parametrize(
    "error_type,material",
    [
        ("HeldHistoryError", True),
        ("BindingError", True),
        ("OperationalError", False),
        ("FileNotFoundError", False),
    ],
)
def test_legacy_wrapped_guard_refusal_is_distinct_from_unavailable_read(
    setup, error_type, material
):
    setup.c["health_command"] = ["/usr/bin/python3", "/prepared/health.py"]

    def run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "healthy": False,
                    "failure_code": "watchdog_read_dependency_unavailable",
                    "error_type": error_type,
                }
            ).encode(),
        )

    assert (
        a.execute(setup.c, setup.b, "health", run=run).get(
            "material_safety_failure", False
        )
        is material
    )


def test_database_parent_symlink_is_not_canonical_binding(setup, tmp_path):
    link = tmp_path / "alias"
    link.symlink_to(tmp_path, target_is_directory=True)
    setup.c["database_path"] = str(link / setup.db.name)
    with pytest.raises(w.Refusal, match="limits_database_unavailable"):
        a.limits(setup.c, setup.b)
