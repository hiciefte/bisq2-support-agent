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
    verifications = []
    route_verifications = []
    fail = {"phase": None, "drop": False, "drop_final": False}
    commands = []

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

        def verify_backup_resumption(self, phase, intent, started):
            route_verifications.append(phase)
            if fail.get("route"):
                raise journal.JournalError("synthetic_api_route_failed")

        def verify_completion(self):
            verifications.append("runtime")
            result = {
                "complete": True,
                "fresh_runtime_verified": True,
                "baseline_sha256": "b" * 64,
            }
            directory = self.directory / "host"
            directory.mkdir(mode=0o700, exist_ok=True)
            journal.exclusive_record(directory / "completion.json", result)
            return result | {"active_marker_retired": True}

        def close(self):
            pass

    class Wire:
        def __init__(self, profile, operation, *, read_only=False):
            self.owner = host.Owner(
                server, read_only=read_only, host_factory=SyntheticHost
            )

        def request(self, message):
            # Exercise the real strict codec and owner, not hand-built replies.
            commands.append((self.owner.read_only, message["command"]))
            incoming = protocol.decode_object(protocol.encode_object(message))
            reply = self.owner.dispatch(incoming)
            if fail["drop"] and message.get("phase") == "smoke_standard":
                raise journal.JournalError("synthetic_lost_response")
            if fail["drop_final"] and message["command"] == "status":
                raise journal.JournalError("synthetic_lost_final_response")
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
    assert len(setup.client.checked_receipts(j, setup.profile, setup.approval)) == len(
        setup.plan["phases"]
    )
    assert (setup.operation / "completion.json").exists()
    assert setup.client.execute(setup.operation, transport_factory=setup.Wire)[
        "already_complete"
    ]
    assert setup.effects == setup.plan["phases"]


def test_lost_final_response_recovers_saved_completion_without_effects(setup):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)
    assert setup.journal.DeploymentJournal(setup.operation).status()["completed"]
    assert not (setup.operation / "completion.json").exists()
    assert not (setup.operation / "final-host-status.json").exists()
    remote = setup.server / setup.protocol.canonical_sha256(setup.plan)
    saved = setup.journal.read_record(remote / "final-host-status.json")
    before = {path: path.read_bytes() for path in remote.rglob("*") if path.is_file()}
    setup.commands.clear()
    outcome = setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert outcome["completed"] is True
    assert outcome["completion_recovered"] is True
    assert outcome["effects_performed"] is False
    assert outcome["fresh_runtime_verified"] is False
    assert outcome["saved_runtime_verified"] is True
    assert setup.commands == [(True, "open"), (True, "completion"), (True, "close")]
    assert setup.effects == setup.plan["phases"]
    assert setup.verifications == ["runtime"]
    assert before == {
        path: path.read_bytes() for path in remote.rglob("*") if path.is_file()
    }
    completion = setup.journal.read_record(setup.operation / "completion.json")
    assert completion["verified_at"] == saved["verification"]["verified_at"]
    assert completion["host_status_sha256"] == setup.protocol.canonical_sha256(saved)
    assert setup.client.execute(
        setup.operation, transport_factory=lambda *a, **kw: pytest.fail("connected")
    )["already_complete"]


@pytest.mark.parametrize(
    "damage",
    [
        "absent_reply",
        "partial_reply",
        "invalid_json",
        "receipt_mismatch",
        "canonical_mismatch",
        "early_timestamp",
    ],
)
def test_lost_final_reply_refuses_missing_or_invalid_remote_completion(setup, damage):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)
    remote = setup.server / setup.protocol.canonical_sha256(setup.plan)
    path = remote / "final-host-status.json"
    if damage == "absent_reply":
        # Also models a disconnect after canonical completion but before the reply
        # record. Recovery must not retire a marker or infer an unsaved final reply.
        assert (remote / "host/completion.json").exists()
        path.unlink()
    elif damage == "invalid_json":
        path.write_text("{")
    elif damage == "canonical_mismatch":
        path = remote / "host/completion.json"
        record = setup.journal.read_record(path)
        record["baseline_sha256"] = "c" * 64
        path.write_bytes(setup.protocol.encode_object(record))
    else:
        record = setup.journal.read_record(path)
        if damage == "partial_reply":
            record["verification"].pop("active_marker_retired")
        elif damage == "receipt_mismatch":
            record["receipts"].pop("build")
        else:
            record["verification"]["verified_at"] = setup.plan["created_at"]
        path.write_bytes(setup.protocol.encode_object(record))
    before = {path: path.read_bytes() for path in remote.rglob("*") if path.is_file()}
    setup.commands.clear()
    with pytest.raises(setup.journal.JournalError):
        setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert setup.commands == [(True, "open"), (True, "completion")]
    assert before == {
        path: path.read_bytes() for path in remote.rglob("*") if path.is_file()
    }
    assert setup.verifications == ["runtime"]
    assert setup.effects == setup.plan["phases"]
    assert not (setup.operation / "completion.json").exists()
    assert not (setup.operation / "final-host-status.json").exists()


def test_completion_recovery_receipt_mismatch_refuses_before_readback(setup):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)
    remote = setup.server / setup.protocol.canonical_sha256(setup.plan)
    path = remote / "receipts/build.json"
    record = setup.journal.read_record(path)
    record["payload"]["images"]["api"]["image_inspect_sha256"] = "f" * 64
    path.write_bytes(setup.protocol.encode_object(record))
    setup.commands.clear()
    with pytest.raises(
        setup.journal.JournalError, match="host_client_receipt_mismatch"
    ):
        setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert setup.commands == [(True, "open")]
    assert setup.effects == setup.plan["phases"]
    assert setup.verifications == ["runtime"]


def test_completion_recovery_preserves_exclusive_local_publication(setup):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)

    class ConcurrentRecord(setup.Wire):
        def request(self, message):
            result = super().request(message)
            if message["command"] == "completion":
                setup.journal.exclusive_record(
                    setup.operation / "completion.json", {"partial": True}
                )
            return result

    with pytest.raises(setup.journal.JournalError, match="record_already_exists"):
        setup.client.execute(setup.operation, transport_factory=ConcurrentRecord)
    assert setup.journal.read_record(setup.operation / "completion.json") == {
        "partial": True
    }
    with pytest.raises(setup.journal.JournalError):
        setup.client.execute(
            setup.operation, transport_factory=lambda *a, **kw: pytest.fail("connected")
        )
    assert setup.effects == setup.plan["phases"]


@pytest.mark.parametrize(
    "damage", ["baseline", "timestamp", "verification_schema", "receipt"]
)
def test_completion_recovery_validates_wire_reply_before_any_local_publication(
    setup, damage
):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)

    class CorruptReply(setup.Wire):
        def request(self, message):
            result = super().request(message)
            if message["command"] == "completion":
                if damage == "baseline":
                    result["verification"]["baseline_sha256"] = "f" * 64
                elif damage == "timestamp":
                    result["verification"]["verified_at"] = setup.plan["created_at"]
                elif damage == "verification_schema":
                    result["verification"]["unknown"] = True
                else:
                    result["receipts"].pop("build")
            return result

    with pytest.raises(setup.journal.JournalError):
        setup.client.execute(setup.operation, transport_factory=CorruptReply)
    assert not (setup.operation / "completion.json").exists()
    assert not (setup.operation / "final-host-status.json").exists()
    assert setup.effects == setup.plan["phases"]


def test_completion_recovery_rechecks_approval_before_connection(setup):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)
    path = setup.operation / "approval.json"
    record = setup.journal.read_record(path)
    record["profile_sha256"] = "f" * 64
    path.write_bytes(setup.protocol.encode_object(record))
    with pytest.raises(setup.journal.JournalError):
        setup.client.execute(
            setup.operation, transport_factory=lambda *a, **kw: pytest.fail("connected")
        )
    assert setup.effects == setup.plan["phases"]


@pytest.mark.parametrize("location", ["local", "remote"])
def test_completion_recovery_rechecks_approved_image_consumers(setup, location):
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)
    directory = (
        setup.operation
        if location == "local"
        else setup.server / setup.protocol.canonical_sha256(setup.plan)
    )
    path = directory / "receipts/switch_api.json"
    receipt = setup.journal.read_record(path)
    receipt["payload"]["consumers"]["matrix-alert-relay"] = {
        "container_id": "5" * 64,
        "image_id": receipt["payload"]["image_id"],
        "ready": True,
    }
    path.write_bytes(setup.protocol.encode_object(receipt))
    if location == "local":
        result_path = directory / "switch_api.result.json"
        result = setup.journal.read_record(result_path)
        result["evidence_sha256"] = setup.protocol.canonical_sha256(receipt)
        result_path.write_bytes(setup.protocol.encode_object(result))
    setup.commands.clear()
    with pytest.raises(setup.journal.JournalError, match="receipt_consumer_scope"):
        setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert setup.commands == ([] if location == "local" else [(True, "open")])
    assert not (setup.operation / "completion.json").exists()
    assert not (setup.operation / "final-host-status.json").exists()
    assert setup.effects == setup.plan["phases"]


def test_lost_final_reply_recovers_through_actual_readonly_bootstrap(
    setup, monkeypatch
):
    setup.profile["transport"]["host_python"] = str(Path(sys.executable).resolve())
    setup.approval["profile_sha256"] = setup.protocol.canonical_sha256(setup.profile)
    setup.profile_path.write_bytes(setup.protocol.encode_object(setup.profile))
    setup.approval_path.write_bytes(setup.protocol.encode_object(setup.approval))
    setup.fail["drop_final"] = True
    with pytest.raises(
        setup.journal.JournalError, match="synthetic_lost_final_response"
    ):
        run(setup)
    remote = setup.server / setup.protocol.canonical_sha256(setup.plan)
    before = {path: path.read_bytes() for path in remote.rglob("*") if path.is_file()}
    monkeypatch.setattr(
        setup.client, "effect_guard", lambda *a: pytest.fail("effect guard")
    )
    monkeypatch.setattr(
        setup.recovery,
        "preflight_recovery",
        lambda *a: pytest.fail("recovery preflight"),
    )
    # Proof retrieval remains usable after expiry without extending effect authority.
    monkeypatch.setattr(
        setup.client,
        "now",
        lambda: (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    )
    outcome = setup.client.execute(setup.operation)
    assert outcome["completion_recovered"] is True
    assert outcome["fresh_runtime_verified"] is False
    assert before == {
        path: path.read_bytes() for path in remote.rglob("*") if path.is_file()
    }
    assert setup.effects == setup.plan["phases"]
    assert setup.verifications == ["runtime"]


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


@pytest.mark.parametrize("missing_completion", [False, True])
def test_receipt_hash_tamper_refuses_before_connection(setup, missing_completion):
    assert run(setup)["completed"]
    if missing_completion:
        (setup.operation / "completion.json").unlink()
        (setup.operation / "final-host-status.json").unlink()
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


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "partial",
        "changed_status",
        "missing_status",
        "malformed_completion",
        "malformed_status",
        "dangling_completion",
        "dangling_status",
    ],
)
def test_completion_requires_full_fresh_evidence_join(setup, damage):
    assert run(setup)["completed"]
    completion = setup.operation / "completion.json"
    if damage == "missing":
        completion.unlink()
    elif damage == "partial":
        record = json.loads(completion.read_bytes())
        record.pop("verified_at")
        completion.write_bytes(setup.protocol.encode_object(record))
    elif damage == "missing_status":
        (setup.operation / "final-host-status.json").unlink()
    elif damage.startswith("malformed"):
        path = (
            completion
            if damage == "malformed_completion"
            else setup.operation / "final-host-status.json"
        )
        path.write_text("{")
    elif damage.startswith("dangling"):
        completion.unlink()
        (setup.operation / "final-host-status.json").unlink()
        path = (
            completion
            if damage == "dangling_completion"
            else setup.operation / "final-host-status.json"
        )
        path.symlink_to(setup.operation / "missing-evidence")
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


def test_capture_route_failure_has_no_success_receipt_or_capture_replay(setup):
    setup.fail["route"] = True
    with pytest.raises(
        setup.journal.JournalError, match="phase_requires_reconciliation"
    ):
        run(setup)
    remote = setup.server / setup.protocol.canonical_sha256(setup.plan)
    assert not (remote / "receipts/prechange_backup.json").exists()
    assert setup.effects == ["build", "pause_scheduler", "prechange_backup"]
    assert setup.route_verifications == ["prechange_backup"]
    with pytest.raises(setup.journal.JournalError, match="reconciliation_required"):
        setup.client.execute(setup.operation, transport_factory=setup.Wire)
    assert setup.effects.count("prechange_backup") == 1
    assert "resume_scheduler" not in setup.effects
