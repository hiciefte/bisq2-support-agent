"""Host producer/consumer fixtures: real filesystem/Git, command doubles only."""

import copy
import importlib
import json
import os
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_deployment_protocol import payload_for
from test_deployment_protocol import protocol as protocol_fixture
from test_deployment_protocol import records as records_fixture

protocol = protocol_fixture
records = records_fixture

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.unit


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("lib.deployment_host")


def container(service, digit, install):
    cid = digit * 64
    return {
        "Id": cid,
        "Image": "sha256:" + digit * 64,
        "Created": "fixture",
        "Config": {
            "Image": "old-" + service,
            "Hostname": cid[:12],
            "Env": ["BUILD_ID=build-ccccccc", "DATA_DIR=/data"],
            "Labels": {
                "com.docker.compose.service": service,
                "com.docker.compose.project": "fixture",
                "com.docker.compose.project.working_dir": str(install / "docker"),
                "com.docker.compose.config-hash": "old",
            },
            "Cmd": ["fixture"],
        },
        "Mounts": [{"Source": "/fixture/data", "Destination": "/data", "RW": True}],
        "HostConfig": {"NetworkMode": "fixture_default", "Binds": ["fixture"]},
        "State": {
            "Running": True,
            "Paused": False,
            "Restarting": False,
            "Pid": int(digit, 16) + 1,
            "StartedAt": "fixture-start",
            "Health": {"Status": "healthy"},
        },
        "RestartCount": 0,
    }


@pytest.fixture
def host(tmp_path, monkeypatch, module, protocol, records):
    plan, profile, approval = copy.deepcopy(records)
    instant = datetime.now(timezone.utc)
    plan["created_at"] = (instant - timedelta(minutes=1)).isoformat()
    plan["deadline"] = (instant + timedelta(hours=1)).isoformat()
    approval["approved_at"] = plan["created_at"]
    approval["deadline"] = plan["deadline"]
    install, candidate, operations = (
        tmp_path / name for name in ("install", "candidate", "operations")
    )
    for path in (install / "docker", candidate, operations):
        path.mkdir(parents=True)
    (install / "docker/.env").write_text("fixture")
    (install / "failed_updates/disaster-recovery").mkdir(parents=True, mode=0o700)
    profile["host"].update(
        repository=str(install),
        candidate=str(candidate),
        operation_root=str(operations),
    )
    approval["plan_sha256"] = protocol.canonical_sha256(plan)
    approval["profile_sha256"] = protocol.canonical_sha256(profile)
    op = operations / protocol.canonical_sha256(plan)
    op.mkdir(mode=0o700)
    (op / "receipts").mkdir(mode=0o700)
    monkeypatch.setattr(module, "verify_inherited_lock", lambda *_args: 7)
    obj = module.DeploymentHost(plan, profile, approval, op, runner=object())
    state = {
        name: container(name, digit, install)
        for name, digit in (
            ("api", "1"),
            ("web", "2"),
            ("nginx", "3"),
            ("scheduler", "4"),
        )
    }
    calls = []

    def shell(action, *args, **kwargs):
        calls.append((action, args))
        if action == "config":
            return module.encode({"services": dict.fromkeys(state, {})})
        if action == "build-id":
            return b"build-aaaaaaa\n"
        return b""

    monkeypatch.setattr(obj, "_shell", shell)
    monkeypatch.setattr(obj, "_helpers", lambda: None)
    monkeypatch.setattr(obj, "_source", lambda **kwargs: None)
    monkeypatch.setattr(obj, "_inspect", lambda: copy.deepcopy(state))
    monkeypatch.setattr(obj, "_disabled", lambda _containers: None)
    monkeypatch.setattr(
        obj, "_preserved_data", lambda _containers: {"fixture": "history"}
    )
    monkeypatch.setattr(
        obj, "_scheduler_jobs", lambda _scheduler: {"fixture": "held-cron"}
    )
    monkeypatch.setattr(obj, "_run", lambda *_args, **_kwargs: b"build-ccccccc\n")
    obj.preflight()
    obj.fixture_state, obj.fixture_calls = state, calls
    return obj


def save_receipt(host, module, protocol, phase, payload):
    intent = "f" * 64
    receipt = protocol.make_phase_receipt(
        host.plan,
        host.profile,
        phase,
        intent,
        host.baseline_sha256,
        payload,
        module.now(),
    )
    module.exclusive_record(host.operation / "receipts" / f"{phase}.json", receipt)
    return receipt


def test_durable_baseline_reconnect_cannot_replace_changed_scheduler(
    host, module, monkeypatch
):
    original = (host.root / "baseline.private.json").read_bytes()
    host.fixture_state["scheduler"]["State"]["Pid"] += 1
    with pytest.raises(module.JournalError, match="host_scheduler_process_changed"):
        host.preflight()
    assert (host.root / "baseline.private.json").read_bytes() == original


def test_real_effect_output_validates_exact_protocol_and_receipt_join(
    host, module, protocol, monkeypatch
):
    built = payload_for("build")
    monkeypatch.setattr(host, "_build", lambda: built)
    payload = host.effect("build", "f" * 64)
    assert payload == built
    with pytest.raises(module.JournalError, match="record_unreadable"):
        host._state()
    save_receipt(host, module, protocol, "build", payload)
    assert host._state() == {"build": built}
    with pytest.raises(
        module.JournalError, match="host_phase_order|host_phase_repeated"
    ):
        host.effect("build", "f" * 64)


def test_cannot_switch_before_both_build_and_local_restore_receipts(host, module):
    with pytest.raises(module.JournalError, match="host_phase_order"):
        host.effect("switch_api", "f" * 64)
    assert not (host.root / "switch_api.intent.json").exists()


@pytest.mark.parametrize("field", ["Image", "Mounts", "Config"])
def test_unrelated_container_drift_refuses(host, module, field):
    changed = host.fixture_state["nginx"]
    if field == "Image":
        changed[field] = "sha256:" + "e" * 64
    elif field == "Mounts":
        changed[field].append(copy.deepcopy(changed[field][0]))
    else:
        changed[field]["Env"].reverse()
    with pytest.raises(module.JournalError, match="host_service_identity_changed"):
        host.verify_preservation()


def test_scheduler_unpause_drift_refuses(host, module):
    host.pause_expected = True
    with pytest.raises(module.JournalError, match="host_scheduler_state_changed"):
        host.verify_preservation()


def test_mount_order_is_irrelevant_but_duplicate_is_not(host, module):
    before = host.baseline["containers"]["api"]
    before["Mounts"].append(
        {"Source": "/fixture/config", "Destination": "/config", "RW": False}
    )
    current = copy.deepcopy(before)
    current["Id"] = "a" * 64
    current["Config"]["Hostname"] = current["Id"][:12]
    current["Mounts"].reverse()
    current["Image"] = "sha256:" + "a" * 64
    current["Config"]["Image"] = current["Image"]
    current["Config"]["Env"][0] = "BUILD_ID=build-aaaaaaa"
    current["Config"]["Labels"]["com.docker.compose.config-hash"] = "new"
    host._replacement("api", current, current["Image"])
    current["Mounts"].append(copy.deepcopy(current["Mounts"][0]))
    with pytest.raises(module.JournalError, match="host_replacement_mounts"):
        host._replacement("api", current, current["Image"])


@pytest.mark.parametrize("field", ["env", "host", "image"])
def test_replacement_rejects_runtime_drift_or_third_image(host, module, field):
    current = copy.deepcopy(host.baseline["containers"]["api"])
    if field == "env":
        current["Config"]["Env"].append("NEW_SECRET=fixture")
    elif field == "host":
        current["HostConfig"]["Privileged"] = True
    else:
        current["Image"] = "sha256:" + "e" * 64
    with pytest.raises(module.JournalError):
        host._replacement("api", current, host.baseline["containers"]["api"]["Image"])


def test_replacement_environment_order_and_build_id_only_may_change(host, module):
    host.baseline["containers"]["api"]["Config"]["Env"] += ["TOKEN=a=b", "EMPTY="]
    current = copy.deepcopy(host.baseline["containers"]["api"])
    current["Config"]["Env"] = [
        "DATA_DIR=/data",
        "BUILD_ID=build-aaaaaaa",
        "EMPTY=",
        "TOKEN=a=b",
    ]
    host._replacement("api", current, current["Image"])
    current["Config"]["Env"][0] = "DATA_DIR=/different"
    with pytest.raises(module.JournalError, match="host_replacement_configuration"):
        host._replacement("api", current, current["Image"])


@pytest.mark.parametrize("side", ["original", "replacement"])
@pytest.mark.parametrize(
    "entries",
    [
        ["BUILD_ID=build-aaaaaaa", "BUILD_ID=build-bbbbbbb", "DATA_DIR=/data"],
        ["BUILD_ID=build-aaaaaaa", "DATA_DIR=/data", "DATA_DIR=/data"],
        ["BUILD_ID=build-aaaaaaa", "DATA_DIR"],
        ["BUILD_ID=build-aaaaaaa", "=/data"],
        ["BUILD_ID=build-aaaaaaa", "DATA_DIR=/data\x00"],
        ["BUILD_ID=build-aaaaaaa", None],
        {"BUILD_ID": "build-aaaaaaa", "DATA_DIR": "/data"},
    ],
)
def test_replacement_environment_is_validated_before_normalizing_build_id(
    host, module, side, entries
):
    current = copy.deepcopy(host.baseline["containers"]["api"])
    target = host.baseline["containers"]["api"] if side == "original" else current
    target["Config"]["Env"] = entries
    with pytest.raises(module.JournalError, match="host_replacement_environment"):
        host._replacement("api", current, current["Image"])


def recorded_builder_image(host, module, protocol, monkeypatch, *, image_labels=None):
    builder = "com.docker.compose.image.builder"
    image = {
        "Id": "sha256:" + "8" * 64,
        "Config": {
            "Labels": {builder: "classic"} if image_labels is None else image_labels
        },
    }
    built = payload_for("build")
    built["images"]["api"]["image_inspect_sha256"] = module.digest(module.encode(image))
    monkeypatch.setattr(host, "_build", lambda: built)
    result = host.effect("build", "f" * 64)
    save_receipt(host, module, protocol, "build", result)
    module.private_bytes(
        host.root / "build_api.image.private.json", module.encode(image)
    )
    current = copy.deepcopy(host.baseline["containers"]["api"])
    current["Image"] = image["Id"]
    current["Config"]["Labels"][builder] = "classic"
    return current, image


def test_replacement_builder_metadata_joins_saved_image_and_build_receipt(
    host, module, protocol, monkeypatch
):
    current, _ = recorded_builder_image(host, module, protocol, monkeypatch)
    host._replacement("api", current, current["Image"])
    # No general image-label waiver accompanies the single proven builder key.
    current["Config"]["Labels"]["fixture.new.label"] = "unapproved"
    with pytest.raises(module.JournalError, match="host_replacement_configuration"):
        host._replacement("api", current, current["Image"])


@pytest.mark.parametrize(
    "change", ["hash", "id", "service", "receipt", "intent", "label"]
)
def test_replacement_builder_rejects_unbound_or_forged_metadata(
    host, module, protocol, monkeypatch, change
):
    current, image = recorded_builder_image(host, module, protocol, monkeypatch)
    if change in {"hash", "id"}:
        if change == "hash":
            image["Config"]["Labels"]["fixture.tamper"] = "changed"
        else:
            image["Id"] = "sha256:" + "9" * 64
        (host.root / "build_api.image.private.json").write_bytes(module.encode(image))
    elif change == "service":
        module.private_bytes(
            host.root / "build_web.image.private.json", module.encode(image)
        )
        current = copy.deepcopy(host.baseline["containers"]["web"])
        current["Image"] = image["Id"]
        current["Config"]["Labels"]["com.docker.compose.image.builder"] = "classic"
    elif change == "receipt":
        path = host.operation / "receipts/build.json"
        receipt = module.read_record(path)
        receipt["payload"]["images"]["api"]["image_inspect_sha256"] = "e" * 64
        path.write_bytes(module.encode(receipt))
    elif change == "intent":
        path = host.root / "build.intent.json"
        intent = module.read_record(path)
        intent["client_intent_sha256"] = "e" * 64
        path.write_bytes(module.encode(intent))
    else:
        current["Config"]["Labels"]["com.docker.compose.image.builder"] = "forged"
    with pytest.raises(module.JournalError, match="host_builder_"):
        host._replacement(
            "web" if change == "service" else "api", current, current["Image"]
        )


def test_replacement_builder_requires_label_in_recorded_image(
    host, module, protocol, monkeypatch
):
    current, _ = recorded_builder_image(
        host, module, protocol, monkeypatch, image_labels={}
    )
    with pytest.raises(module.JournalError, match="host_builder_image_label"):
        host._replacement("api", current, current["Image"])


def test_original_image_recovery_preserves_original_builder_label(host, module):
    builder = "com.docker.compose.image.builder"
    original = host.baseline["containers"]["api"]
    original["Config"]["Labels"][builder] = "original-builder"
    current = copy.deepcopy(original)
    current["Config"]["Env"].reverse()
    host._replacement("api", current, original["Image"])
    current["Config"]["Labels"][builder] = "classic"
    with pytest.raises(module.JournalError, match="host_builder_image"):
        host._replacement("api", current, original["Image"])


def test_failed_smoke_is_never_replayed(host, module, monkeypatch):
    monkeypatch.setattr(host, "_prefix", lambda _phase: None)

    def fail(_kind):
        raise module.HostCommandError("host_command_timeout", uncertain=True)

    monkeypatch.setattr(host, "_smoke", fail)
    with pytest.raises(module.HostCommandError):
        host.effect("smoke_standard", "f" * 64)
    outcome = module.read_record(host.root / "smoke_standard.result.json")
    assert outcome["status"] == "uncertain"
    with pytest.raises(
        module.JournalError, match="host_effect_requires_reconciliation"
    ):
        host.effect("smoke_standard", "e" * 64)


def test_effect_deadline_refuses_before_intent(host, module, monkeypatch):
    monkeypatch.setattr("lib.deployment_protocol.now", lambda: host.plan["deadline"])
    with pytest.raises(module.JournalError, match="effect_deadline"):
        host.effect("build", "f" * 64)
    assert not (host.root / "build.intent.json").exists()


def test_command_runner_private_output_and_bounded_descendant_cleanup(tmp_path, module):
    fd = os.open(tmp_path / "fixture-lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        runner = module.CommandRunner(tmp_path, fd)
        result = runner.run(
            [sys.executable, "-c", "print('public fixture')"], "success", 10
        )
        assert result == b"public fixture\n"
        assert (tmp_path / "success.stdout").stat().st_mode & 0o777 == 0o600
        code = "import os,time; p=os.fork(); time.sleep(30)"
        with pytest.raises(module.HostCommandError) as caught:
            runner.run([sys.executable, "-c", code], "timeout", 1)
        assert caught.value.uncertain
        assert (tmp_path / "timeout.intent.json").exists()
        assert not (tmp_path / "timeout.result.json").exists()
    finally:
        os.close(fd)


def test_get_build_id_actual_linked_worktree(tmp_path):
    repo, worktree = tmp_path / "repo", tmp_path / "linked"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "source").write_text("fixture")
    subprocess.run(["git", "-C", str(repo), "add", "source"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Fixture",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree)],
        check=True,
        capture_output=True,
    )
    expected = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"]
    ).strip()
    for path in (repo, worktree):
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; get_build_id "$2"',
                "fixture",
                str(ROOT / "scripts/lib/git-utils.sh"),
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        assert result.stdout.strip() == b"build-" + expected


def test_complete_real_host_phase_sequence_with_fixture_commands(
    host, module, protocol, monkeypatch
):
    state = host.fixture_state
    built = {
        s: {
            "Id": "sha256:" + d * 64,
            "Config": {
                "Env": ["BUILD_ID=build-aaaaaaa"],
                "Labels": {"com.docker.compose.image.builder": "classic"},
            },
        }
        for s, d in (("api", "a"), ("web", "b"))
    }
    commands = []
    base_shell = host._shell

    def shell(action, *args, **kwargs):
        if action == "switch":
            overlay = module.private_json(Path(args[0]))
            service = args[1]
            replacement = copy.deepcopy(state[service])
            replacement["Id"] = ("c" if service == "api" else "d") * 64
            replacement["Image"] = overlay["services"][service]["image"]
            replacement["Config"]["Image"] = replacement["Image"]
            replacement["Config"]["Hostname"] = replacement["Id"][:12]
            replacement["Config"]["Env"][0] = "BUILD_ID=build-aaaaaaa"
            replacement["Config"]["Env"].reverse()
            replacement["Config"]["Labels"][
                "com.docker.compose.image.builder"
            ] = "classic"
            state[service] = replacement
        return base_shell(action, *args, **kwargs)

    def run(argv, _label, *_args, **_kwargs):
        commands.append(argv)
        if argv[:2] == ["docker", "pause"]:
            state["scheduler"]["State"]["Paused"] = True
        elif argv[:2] == ["docker", "unpause"]:
            state["scheduler"]["State"]["Paused"] = False
        elif "cat" in argv:
            return b"build-aaaaaaa\n"
        elif argv[-1].endswith("/health/ready"):
            return b'{"status":"ready"}'
        elif argv[-1].endswith("/health"):
            return b'{"build_id":"build-aaaaaaa"}'
        elif argv[-1].endswith("/login"):
            return b"fixture build-aaaaaaa"
        return b""

    monkeypatch.setattr(host, "_shell", shell)
    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(host, "_git", lambda *args: "")
    monkeypatch.setattr(
        host,
        "_image",
        lambda ref: next(
            v
            for k, v in built.items()
            if ref == v["Id"] or ref.startswith("bisq-release-" + k + ":")
        ),
    )
    for phase in host.plan["phases"]:
        payload = (
            payload_for(phase)
            if phase.endswith(("_backup", "_restore"))
            else host.effect(phase, "f" * 64)
        )
        save_receipt(host, module, protocol, phase, payload)
        if phase != "resume_scheduler":
            assert host.active_marker.exists()
    result = host.verify_completion()
    assert result["fresh_runtime_verified"] and result["active_marker_retired"]
    assert not host.active_marker.exists()
    assert module.read_record(host.root / "completion.json")["complete"] is True
    assert state["scheduler"]["Id"] == "4" * 64
    assert state["scheduler"]["State"]["Paused"] is False
    # All builds precede the first switch; no API/web broad Compose invocation.
    actions = [name for name, _args in host.fixture_calls]
    assert actions.index("build") < actions.index("switch")
    assert actions.count("build") == 2 and actions.count("switch") == 2
    assert len([c for c in commands if c[:2] == ["docker", "unpause"]]) == 1


def failed_switch(
    host, module, protocol, monkeypatch, status="failed", *, builder_metadata=False
):
    phase = "switch_api"
    image = {
        "Id": "sha256:" + "a" * 64,
        "Config": {
            "Labels": (
                {"com.docker.compose.image.builder": "classic"}
                if builder_metadata
                else {}
            )
        },
    }
    built = payload_for("build")
    built["images"]["api"].update(
        image_id=image["Id"], image_inspect_sha256=module.digest(module.encode(image))
    )
    monkeypatch.setattr(host, "_build", lambda: built)
    host.effect("build", "f" * 64)
    for prior in host.plan["phases"][: host.plan["phases"].index(phase)]:
        save_receipt(
            host,
            module,
            protocol,
            prior,
            built if prior == "build" else payload_for(prior),
        )
    intent = {
        "phase": phase,
        "client_intent_sha256": "f" * 64,
        "baseline_sha256": host.baseline_sha256,
        "started_at": module.now(),
    }
    module.exclusive_record(host.root / f"{phase}.intent.json", intent)
    module.exclusive_record(
        host.root / f"{phase}.result.json",
        {
            "intent_sha256": module.digest(module.encode(intent)),
            "status": status,
            "code": "host_api_readiness",
        },
    )
    module.private_bytes(
        host.root / "build_api.image.private.json",
        module.encode(image),
    )
    host.fixture_state["api"]["Image"] = "sha256:" + "a" * 64
    host.fixture_state["api"]["Config"]["Image"] = "sha256:" + "a" * 64
    host.fixture_state["api"]["Config"]["Env"].reverse()
    if builder_metadata:
        host.fixture_state["api"]["Config"]["Labels"][
            "com.docker.compose.image.builder"
        ] = "classic"
    host.fixture_state["scheduler"]["State"]["Paused"] = True
    host.pause_expected = True
    monkeypatch.setattr(host, "_image", lambda ref: {"Id": ref})
    return phase


@pytest.mark.parametrize("builder_metadata", [False, True])
def test_known_failed_switch_restores_only_original_image_and_retains_failure(
    host, module, protocol, monkeypatch, builder_metadata
):
    phase = failed_switch(
        host, module, protocol, monkeypatch, builder_metadata=builder_metadata
    )

    def shell(action, overlay, service, **kwargs):
        assert action == "switch" and service == "api"
        saved = module.private_json(overlay)
        assert saved["services"][service]["image"] == "sha256:" + "1" * 64
        host.fixture_state[service]["Image"] = saved["services"][service]["image"]
        host.fixture_state[service]["Config"]["Labels"].pop(
            "com.docker.compose.image.builder", None
        )

    monkeypatch.setattr(host, "_shell", shell)
    monkeypatch.setattr(host, "_configuration", lambda: None)
    monkeypatch.setattr(host, "_ready", lambda *args: None)
    result = host.restore_availability(phase)
    assert (
        result["status"] == "availability_restored"
        and result["rollout_complete"] is False
    )
    assert (
        module.read_record(host.root / "switch_api.result.json")["status"] == "failed"
    )
    assert host.fixture_state["scheduler"]["State"]["Paused"] is True
    with pytest.raises(module.JournalError, match="record_already_exists"):
        host.restore_availability(phase)


def test_original_image_recovery_rejects_candidate_builder_before_readiness(
    host, module, protocol, monkeypatch
):
    phase = failed_switch(host, module, protocol, monkeypatch, builder_metadata=True)

    def shell(action, overlay, service, **kwargs):
        host.fixture_state[service]["Image"] = host.baseline["containers"][service][
            "Image"
        ]

    def unexpected_readiness(*args):
        pytest.fail("Unproven rollback metadata must be refused before readiness")

    monkeypatch.setattr(host, "_shell", shell)
    monkeypatch.setattr(host, "_configuration", lambda: None)
    monkeypatch.setattr(host, "_ready", unexpected_readiness)
    with pytest.raises(module.JournalError, match="host_builder_image"):
        host.restore_availability(phase)
    assert (
        module.read_record(host.root / "availability-recovery.result.json")["status"]
        == "failed"
    )
    assert (
        module.read_record(host.root / "switch_api.result.json")["status"] == "failed"
    )


def test_uncertain_switch_is_never_restored_automatically(
    host, module, protocol, monkeypatch
):
    phase = failed_switch(host, module, protocol, monkeypatch, status="uncertain")
    with pytest.raises(module.JournalError, match="host_recovery_not_known_failure"):
        host.restore_availability(phase)
    assert not (host.root / "availability-recovery.intent.json").exists()


def test_global_marker_blocks_other_plan_and_legacy_caller(host, module, monkeypatch):
    lock = importlib.import_module("lib.lifecycle_lock")
    host._marker(create=True)
    monkeypatch.delenv("BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256", raising=False)
    with pytest.raises(lock.LifecycleLockError):
        lock.verify_active_operation(host.install)
    monkeypatch.setenv("BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256", "e" * 64)
    with pytest.raises(lock.LifecycleLockError):
        lock.verify_active_operation(host.install)
    monkeypatch.setenv(
        "BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256", module.digest(module.encode(host.plan))
    )
    lock.verify_active_operation(host.install)
    marker_before = host.active_marker.read_bytes()
    host.plan["source"]["candidate_commit"] = "e" * 40
    with pytest.raises(module.JournalError, match="host_other_operation_active"):
        host._marker()
    assert host.active_marker.read_bytes() == marker_before


def test_protected_identity_and_trial_rows_hash_without_exporting_content(
    host, module, monkeypatch
):
    import sqlite3

    data = host.install / "api/data"
    data.mkdir(parents=True)
    (data / "matrix_session.json").write_text('{"access_token":"private fixture"}')
    (data / "matrix_polling_state.json").write_text('{"since_token":"private cursor"}')
    with closing(sqlite3.connect(data / "escalations.db")) as db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, question TEXT, channel_metadata TEXT)"
        )
        db.execute(
            "INSERT INTO escalations VALUES(1, 'matrix', 'private question', NULL)"
        )
        db.execute(
            "CREATE TABLE matrix_context_attempts(escalation_id INTEGER, reserved_at TEXT)"
        )
        db.execute("INSERT INTO matrix_context_attempts VALUES(1, 'fixture')")
        db.commit()
    first = module.DeploymentHost._preserved_data(host, host.fixture_state)
    assert b"private" not in module.encode(first)
    with closing(sqlite3.connect(data / "escalations.db")) as db:
        db.execute("UPDATE matrix_context_attempts SET reserved_at='changed'")
        db.commit()
    assert module.DeploymentHost._preserved_data(host, host.fixture_state) != first


def test_exported_canonical_acquire_uses_captured_marker_helper(tmp_path, module):
    install = tmp_path / "install"
    control = install / "failed_updates/disaster-recovery"
    control.mkdir(parents=True, mode=0o700)
    marker = {
        "schema": "deployment-active-v1",
        "plan_sha256": "a" * 64,
        "profile_sha256": "b" * 64,
        "operation": "/fixture/operation",
    }
    module.exclusive_record(control / "deployment-active.json", marker)
    # Routing fixture only: real Linux flock behavior is tested separately.
    script = 'source "$1"; flock() { return 0; }; export -f flock; bash -uc \'setup_colors; acquire_production_lifecycle_lock "$1"\' fixture "$2"'
    env = os.environ.copy()
    env["BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256"] = "a" * 64
    result = subprocess.run(
        [
            "bash",
            "-c",
            script,
            "fixture",
            str(ROOT / "scripts/lib/common.sh"),
            str(install),
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    env["BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256"] = "c" * 64
    result = subprocess.run(
        [
            "bash",
            "-c",
            script,
            "fixture",
            str(ROOT / "scripts/lib/common.sh"),
            str(install),
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode != 0
    assert b"incomplete deployment" in result.stderr
    assert b"unbound" not in result.stderr


@pytest.mark.parametrize(
    "metadata,accepted",
    [
        (
            {
                "response_kind": "public_context",
                "context_status": "preparing",
                "model_call_status": "not_started",
            },
            False,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "preparing",
                "model_call_status": "reserved",
            },
            False,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "delivery_pending",
                "model_call_status": "completed",
            },
            False,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "awaiting_review",
                "model_call_status": "completed",
            },
            False,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "delivery_uncertain",
                "model_call_status": "reserved",
            },
            False,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "needs_human",
                "model_call_status": "outcome_unknown",
            },
            False,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "delivery_uncertain",
                "model_call_status": "completed",
                "context_trial_id": "closed-fixture",
            },
            True,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "needs_human",
                "model_call_status": "completed",
            },
            True,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "deferred",
                "model_call_status": "not_started",
            },
            True,
        ),
        (
            {
                "response_kind": "public_context",
                "context_status": "delivered",
                "model_call_status": "completed",
            },
            True,
        ),
        ({"context_status": None, "model_call_status": "reserved"}, False),
        ({"context_trial_id": "", "model_call_status": "reserved"}, False),
        ({"response_kind": "public_context"}, False),
        ({"room_id": "ordinary fixture"}, True),
    ],
)
def test_context_drain_proof_uses_actual_flat_metadata_and_preserves_terminal_rows(
    host, module, metadata, accepted
):
    import sqlite3

    data = host.install / "api/data"
    data.mkdir(parents=True)
    database = data / "escalations.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT)"
        )
        db.execute(
            "INSERT INTO escalations VALUES(1, 'matrix', ?)", (json.dumps(metadata),)
        )
        db.commit()
    before = database.read_bytes()
    if accepted:
        result = module.DeploymentHost._preserved_data(host, host.fixture_state)
        assert result["tables"]["matrix_cases"]["count"] == 1
    else:
        with pytest.raises(module.JournalError, match="host_context_work_unsettled"):
            module.DeploymentHost._preserved_data(host, host.fixture_state)
    assert database.read_bytes() == before


def test_context_drain_proof_refuses_uninspectable_legacy_schema(host, module):
    import sqlite3

    data = host.install / "api/data"
    data.mkdir(parents=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db:
        db.execute("CREATE TABLE escalations(id INTEGER, channel TEXT)")
        db.commit()
    with pytest.raises(module.JournalError, match="host_history_schema"):
        module.DeploymentHost._preserved_data(host, host.fixture_state)


@pytest.mark.parametrize(
    "metadata",
    [
        "{broken",
        "null",
        "[]",
        '{"context_status":{},"model_call_status":"reserved"}',
        '{"context_status":"unknown-phase","model_call_status":"completed"}',
    ],
)
def test_context_drain_proof_refuses_malformed_or_unknown_metadata(
    host, module, metadata
):
    import sqlite3

    data = host.install / "api/data"
    data.mkdir(parents=True)
    with closing(sqlite3.connect(data / "escalations.db")) as db:
        db.execute(
            "CREATE TABLE escalations(id INTEGER, channel TEXT, channel_metadata TEXT)"
        )
        db.execute("INSERT INTO escalations VALUES(1, 'matrix', ?)", (metadata,))
        db.commit()
    with pytest.raises(
        module.JournalError, match="host_context_(metadata|work_unsettled)"
    ):
        module.DeploymentHost._preserved_data(host, host.fixture_state)
