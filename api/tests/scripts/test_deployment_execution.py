"""Ordinary client/owner integration with explicit synthetic effect doubles.

These test phase ordering, replay refusal and the wire contract. They are not
Docker, restore or production-readiness evidence; those backends have separate
canonical integration/rehearsal coverage.
"""

import copy
import importlib
import json
import runpy
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    protocol = importlib.import_module("lib.deployment_protocol")
    client = importlib.import_module("lib.deployment_client")
    host = importlib.import_module("deploy_release_host")
    journal = importlib.import_module("lib.deployment_journal")
    fixtures = runpy.run_path(
        str(Path(__file__).with_name("test_deployment_protocol.py"))
    )
    plan, profile, approval = fixtures["records"].__wrapped__(protocol)
    instant = datetime.now(timezone.utc)
    plan["created_at"] = (instant - timedelta(minutes=2)).isoformat()
    plan["deadline"] = (instant + timedelta(hours=1)).isoformat()
    approval["approved_at"] = (instant - timedelta(minutes=1)).isoformat()
    approval["deadline"] = plan["deadline"]
    server = tmp_path / "server"
    server.mkdir(mode=0o700)
    operation = tmp_path / "operator"
    operation.mkdir(mode=0o700)
    profile["host"].update(
        candidate=str(ROOT), repository=str(server), operation_root=str(server)
    )
    profile["recovery"]["verifier_repository"] = str(ROOT)
    profile["recovery"]["local_directory"] = str(tmp_path)
    profile["helper_sha256"] = {
        name: journal.digest((ROOT / name).read_bytes())
        for name in protocol.HOST_HELPERS
        if (ROOT / name).exists()
    }
    # The adapter may still be landing when authoring tests; every pin must exist
    # for the actual gate, never substitute placeholder pins.
    assert set(profile["helper_sha256"]) == protocol.HOST_HELPERS
    profile["recovery"]["expected_helper_sha256"] = {
        name: journal.digest((ROOT / name).read_bytes())
        for name in protocol.VERIFIER_HELPERS
    }
    approval["plan_sha256"] = protocol.canonical_sha256(plan)
    approval["profile_sha256"] = protocol.canonical_sha256(profile)
    journal.exclusive_record(operation / "plan.json", plan)
    profile_path, approval_path = tmp_path / "profile.json", tmp_path / "approval.json"
    journal.exclusive_record(profile_path, profile)
    journal.exclusive_record(approval_path, approval)
    effects = []
    fail = {"phase": None, "drop": False}

    class SyntheticHost:
        def __init__(self, plan, profile, approval, directory):
            self.directory = directory

        def preflight(self):
            return {
                "baseline_sha256": "b" * 64,
                "build_id": "build-aaaaaaa",
                "services": ["api", "web"],
                "channels_disabled": True,
            }

        def effect(self, phase, intent):
            marker = self.directory / f"synthetic-{phase}.json"
            journal.exclusive_record(marker, {"intent": intent})
            effects.append(phase)
            if fail["phase"] == phase:
                raise journal.JournalError("synthetic_effect_failed")
            return fixtures["payload_for"](phase)

        def status(self):
            return {"synthetic": True}

        def restore_availability(self, phase):
            raise journal.JournalError("synthetic_recovery_unavailable")

        def verify_preservation(self):
            return {"preserved": True}

        def verify_completion(self):
            return {
                "complete": True,
                "fresh_runtime_verified": True,
                "active_marker_retired": True,
            }

        def close(self):
            pass

    class Wire:
        def __init__(self, profile, operation, *, read_only=False):
            self.owner = host.Owner(
                server, read_only=read_only, host_factory=SyntheticHost
            )

        def request(self, message):
            # Exercise the real strict codec and owner, not hand-built replies.
            incoming = protocol.decode_object(protocol.encode_object(message))
            reply = self.owner.dispatch(incoming)
            if fail["drop"] and message.get("phase") == "smoke_standard":
                raise journal.JournalError("synthetic_lost_response")
            return protocol.decode_object(protocol.encode_object(reply))

        def ciphertext(self, phase, receipt):
            yield b"synthetic-ciphertext"

        def close(self, *, orderly=False):
            if orderly:
                self.request({"command": "close"})

    def capture(profile, attempt, binding):
        effects.append(binding["phase"])
        journal.exclusive_record(attempt / "synthetic-capture-intent.json", binding)
        return fixtures["payload_for"](binding["phase"])

    def receive(profile, attempt, envelope, stream, binding):
        assert b"".join(stream) == b"synthetic-ciphertext"
        journal.exclusive_record(attempt / "synthetic-receive.json", binding)
        return {"synthetic": True}

    def restore(profile, attempt, received, binding):
        effects.append(binding["phase"])
        journal.exclusive_record(attempt / "synthetic-restore-intent.json", binding)
        if fail["phase"] == binding["phase"]:
            raise journal.JournalError("synthetic_restore_failed")
        return fixtures["payload_for"](binding["phase"])

    recovery = types.ModuleType("lib.deployment_recovery")
    recovery.capture_backup = capture
    recovery.receive_ciphertext = receive
    recovery.verify_restore = restore
    recovery.preflight_recovery = lambda profile: None
    recovery.preflight_capture = lambda profile: None
    monkeypatch.setitem(sys.modules, "lib.deployment_recovery", recovery)
    return types.SimpleNamespace(**locals())


def run(fixture):
    return fixture.client.execute(
        fixture.operation,
        profile_path=fixture.profile_path,
        approval_path=fixture.approval_path,
        transport_factory=fixture.Wire,
    )


def test_complete_phase_flow_joins_actual_producer_consumer_contract(setup):
    assert run(setup)["completed"] is True
    assert setup.effects == setup.plan["phases"]
    j = setup.journal.DeploymentJournal(setup.operation)
    assert j.status()["completed"]
    assert len(setup.client.checked_receipts(j, setup.profile)) == len(
        setup.plan["phases"]
    )
    assert (setup.operation / "completion.json").exists()
    assert setup.client.execute(setup.operation, transport_factory=setup.Wire)[
        "already_complete"
    ]
    assert setup.effects == setup.plan["phases"]


@pytest.mark.parametrize(
    "phase",
    [
        "build",
        "prechange_backup",
        "prechange_restore",
        "switch_api",
        "smoke_standard",
        "postchange_restore",
        "publish_source",
        "resume_scheduler",
    ],
)
def test_failed_or_interrupted_phase_blocks_every_later_effect_and_continue(
    setup, phase
):
    setup.fail["phase"] = phase
    if phase.endswith("_backup"):

        def broken(*args):
            raise setup.journal.JournalError("synthetic_capture_uncertain")

        setup.recovery.capture_backup = broken
    with pytest.raises(
        setup.journal.JournalError, match="phase_requires_reconciliation"
    ):
        run(setup)
    assert setup.journal.DeploymentJournal(setup.operation).status()["needs_attention"]
    before = list(setup.effects)
    with pytest.raises(setup.journal.JournalError, match="reconciliation_required"):
        setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert setup.effects == before
    observed = setup.client.reconcile(setup.operation, transport_factory=setup.Wire)
    assert observed["effects_performed"] is False
    assert observed["automatic_retry_permitted"] is False
    assert setup.effects == before


def test_lost_smoke_response_is_never_resent_or_automatically_promoted(setup):
    setup.fail["drop"] = True
    with pytest.raises(
        setup.journal.JournalError, match="phase_requires_reconciliation"
    ):
        run(setup)
    assert setup.effects.count("smoke_standard") == 1
    remote = setup.client.reconcile(setup.operation, transport_factory=setup.Wire)
    assert "smoke_standard" in remote["remote"]["receipts"]
    with pytest.raises(setup.journal.JournalError, match="reconciliation_required"):
        setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert setup.effects.count("smoke_standard") == 1


def test_copied_plan_cannot_create_second_remote_namespace(setup, tmp_path):
    assert run(setup)["completed"]
    second = tmp_path / "second"
    second.mkdir(mode=0o700)
    setup.journal.exclusive_record(second / "plan.json", setup.plan)
    with pytest.raises(
        setup.journal.JournalError, match="host_client_receipt_mismatch"
    ):
        setup.client.execute(
            second,
            profile_path=setup.profile_path,
            approval_path=setup.approval_path,
            transport_factory=setup.Wire,
        )
    assert setup.effects == setup.plan["phases"]
    assert len([p for p in setup.server.iterdir() if p.is_dir()]) == 1


def test_receipt_hash_tamper_refuses_before_connection(setup):
    assert run(setup)["completed"]
    path = setup.operation / "receipts/build.json"
    record = json.loads(path.read_bytes())
    record["payload"]["images"]["api"]["image_inspect_sha256"] = "f" * 64
    path.write_bytes(setup.protocol.encode_object(record))
    with pytest.raises(setup.journal.JournalError, match="journal_receipt_join"):
        setup.client.execute(
            setup.operation, transport_factory=lambda *a: pytest.fail("connected")
        )


def test_read_only_session_refuses_any_effect_even_with_valid_approval(setup):
    assert run(setup)["completed"]
    wire = setup.Wire(setup.profile, setup.operation, read_only=True)
    wire.request(
        {
            "command": "open",
            "mode": "reconcile",
            "plan": setup.plan,
            "profile": setup.profile,
            "approval": setup.approval,
        }
    )
    with pytest.raises(setup.journal.JournalError, match="host_read_only"):
        wire.request({"command": "effect", "phase": "build", "intent_sha256": "1" * 64})


def test_offline_cli_refuses_effect_v1_before_opening_transport(setup):
    plan = copy.deepcopy(setup.plan)
    plan["schema"] = "deployment-plan-v1"
    plan["phases"].remove("publish_source")
    approval = copy.deepcopy(setup.approval)
    approval["plan_sha256"] = setup.protocol.canonical_sha256(plan)
    approval["phases"] = plan["phases"]
    (setup.operation / "plan.json").write_bytes(setup.protocol.encode_object(plan))
    setup.approval_path.write_bytes(setup.protocol.encode_object(approval))
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/deploy_release.py"),
            "apply",
            "--operation",
            str(setup.operation),
            "--profile",
            str(setup.profile_path),
            "--approval",
            str(setup.approval_path),
        ],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert json.loads(result.stderr) == {"error": "effect_plan_version"}
    assert not list(setup.server.iterdir())


@pytest.mark.parametrize("damage", ["missing", "partial", "changed_status"])
def test_completion_requires_full_fresh_evidence_join(setup, damage):
    assert run(setup)["completed"]
    completion = setup.operation / "completion.json"
    if damage == "missing":
        completion.unlink()
    elif damage == "partial":
        record = json.loads(completion.read_bytes())
        record.pop("verified_at")
        completion.write_bytes(setup.protocol.encode_object(record))
    else:
        path = setup.operation / "final-host-status.json"
        record = json.loads(path.read_bytes())
        record["verification"] = {}
        path.write_bytes(setup.protocol.encode_object(record))
    with pytest.raises(setup.journal.JournalError):
        setup.client.execute(
            setup.operation, transport_factory=lambda *a: pytest.fail("connected")
        )
    assert setup.effects == setup.plan["phases"]


def test_local_restore_path_mismatch_refuses_before_remote_disruption(setup):
    setup.profile["recovery"]["local_directory"] = str(setup.server)
    setup.approval["profile_sha256"] = setup.protocol.canonical_sha256(setup.profile)
    setup.profile_path.write_bytes(setup.protocol.encode_object(setup.profile))
    setup.approval_path.write_bytes(setup.protocol.encode_object(setup.approval))
    with pytest.raises(setup.journal.JournalError, match="recovery_local_path"):
        setup.client.execute(
            setup.operation,
            profile_path=setup.profile_path,
            approval_path=setup.approval_path,
            transport_factory=lambda *a: pytest.fail("connected"),
        )
    assert setup.effects == []


def test_actual_bootstrap_refuses_changed_launcher_before_running_it(setup, tmp_path):
    import shutil

    candidate = tmp_path / "candidate"
    combined = {
        **setup.profile["helper_sha256"],
        **setup.profile["recovery"]["expected_helper_sha256"],
    }
    for relative in combined:
        destination = candidate / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    setup.profile["host"]["candidate"] = str(candidate)
    setup.profile["transport"]["host_python"] = str(Path(sys.executable).resolve())
    sentinel = tmp_path / "must-not-run"
    (candidate / "scripts/lib/deployment_host.sh").write_text(
        f"touch '{sentinel}'\nexit 0\n"
    )
    transport = setup.client.Transport(setup.profile, setup.operation)
    try:
        with pytest.raises(setup.client.RemoteFailure):
            transport.receive(timeout=10)
    finally:
        transport.close()
    assert not sentinel.exists()


def test_actual_bootstrap_launcher_owner_readonly_subprocess(setup, tmp_path):
    assert run(setup)["completed"]
    # The candidate is the real checked-in tree, and every helper has its real pin.
    profile = copy.deepcopy(setup.profile)
    profile["transport"]["host_python"] = str(Path(sys.executable).resolve())
    approval = copy.deepcopy(setup.approval)
    approval["profile_sha256"] = setup.protocol.canonical_sha256(profile)
    remote = setup.server / setup.protocol.canonical_sha256(setup.plan)
    # A new synthetic runtime binding is written only in this disposable fixture.
    (remote / "profile.json").write_bytes(setup.protocol.encode_object(profile))
    (remote / "approval.json").write_bytes(setup.protocol.encode_object(approval))
    for path in (remote / "receipts").glob("*.json"):
        record = json.loads(path.read_bytes())
        record["profile_sha256"] = setup.protocol.canonical_sha256(profile)
        path.write_bytes(setup.protocol.encode_object(record))
    transport = setup.client.Transport(profile, setup.operation, read_only=True)
    try:
        result = transport.request(
            {
                "command": "open",
                "mode": "reconcile",
                "plan": setup.plan,
                "profile": profile,
                "approval": approval,
            }
        )
        assert result["host_status"]["read_only"] is True
        assert len(result["receipts"]) == len(setup.plan["phases"])
    finally:
        transport.close(orderly=True)


def test_readonly_status_observes_capture_intent_without_promoting_success(setup):
    owner = setup.host.Owner(setup.server, read_only=True)
    owner.plan = setup.plan
    owner.operation = setup.server / "status-fixture"
    attempt = owner.operation / "recovery" / "prechange_backup"
    attempt.mkdir(parents=True)
    (attempt / "capture-intent.json").write_text("{}")
    (attempt / "canonical-backup.json").write_text("{}")
    status = owner._status()["phases"]["prechange_backup"]
    assert status == {"intent_present": True, "result_present": False}
