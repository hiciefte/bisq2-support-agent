"""Real contract/shell adapter fixtures; no daemon, provider or private data."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import deployment_protocol as p  # noqa: E402
from lib import deployment_recovery as r  # noqa: E402


@pytest.fixture
def setup(tmp_path):
    tmp_path = tmp_path.resolve()
    tmp_path.chmod(0o700)
    profile = {
        "schema": "deployment-profile-v1",
        "name": "fixture",
        "transport": {
            "kind": "local_rehearsal",
            "ssh_alias": None,
            "host_python": "/usr/bin/python3",
        },
        "host": {
            "repository": "/srv/fixture/app",
            "candidate": "/srv/fixture/candidate",
            "operation_root": "/srv/fixture/operations",
            "compose_project": "fixture",
            "compose_file": "docker-compose.yml",
            "quality_remote": "origin",
            "readiness_timeout_seconds": 60,
            "nginx_url": "http://localhost:8000",
        },
        "phase_timeout_seconds": 300,
        "helper_sha256": {name: "1" * 64 for name in p.HOST_HELPERS},
        "recovery": {
            "export_directory": str(tmp_path),
            "encryption": "gpg",
            "recipient_file": str(tmp_path / "recipient"),
            "local_directory": str(tmp_path),
            "verifier_repository": str(ROOT),
            "identity_file": str(tmp_path / "key"),
            "expected_helper_sha256": {
                name: r._file(ROOT / name)[0] for name in p.VERIFIER_HELPERS
            },
            "verifier_runtime": {
                "docker_executable": "/usr/bin/docker",
                "docker_executable_sha256": "3" * 64,
                "docker_socket": str(tmp_path / "socket"),
                "runtime_image_id": "sha256:" + "4" * 64,
                "api_image_id": "sha256:" + "5" * 64,
                "qdrant_image_id": "sha256:" + "6" * 64,
                "uid": os.geteuid(),
                "gid": os.getegid(),
            },
        },
    }
    (tmp_path / "key").write_bytes(b"synthetic key; never loaded by fixture")
    (tmp_path / "key").chmod(0o600)
    binding = {
        "plan_sha256": "a" * 64,
        "profile_sha256": p.canonical_sha256(profile),
        "phase": "prechange_restore",
        "intent_sha256": "b" * 64,
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    ciphertext = b"only synthetic ciphertext bytes"
    envelope = {
        "schema": "deployment-phase-receipt-v1",
        "plan_sha256": "a" * 64,
        "profile_sha256": binding["profile_sha256"],
        "phase": "prechange_backup",
        "intent_sha256": "c" * 64,
        "baseline_sha256": "d" * 64,
        "started_at": r.now(),
        "finished_at": r.now(),
        "payload": {
            "ciphertext_name": "bisq-support-backup-fixture.tar.gz.gpg",
            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
            "ciphertext_bytes": len(ciphertext),
            "canonical_backup_receipt_sha256": "e" * 64,
            "destination_kind": "same_host_encrypted_export",
            "writers_resumed": True,
        },
    }
    return profile, binding, envelope, ciphertext, tmp_path / "attempt"


def test_receive_actual_envelope_atomic_private_and_no_retry(setup):
    profile, binding, envelope, ciphertext, attempt = setup
    receipt = r.receive_ciphertext(
        profile, attempt, envelope, [ciphertext[:5], ciphertext[5:]], binding
    )
    p.validate_receive_receipt(receipt, envelope)
    assert (attempt / "ciphertext").read_bytes() == ciphertext
    assert (attempt / "ciphertext").stat().st_mode & 0o777 == 0o600
    assert not (attempt / "ciphertext.partial").exists()
    with pytest.raises(r.JournalError):
        r.receive_ciphertext(profile, attempt, envelope, [ciphertext], binding)


@pytest.mark.parametrize(
    "frames",
    [
        [b"corrupt"],
        [b"only synthetic ciphertext byteX"],
        [b""],
        [b"x" * (r.MAX_FRAME + 1)],
    ],
)
def test_receive_corruption_never_publishes_or_allows_retry(setup, frames):
    profile, binding, envelope, ciphertext, attempt = setup
    with pytest.raises(r.JournalError):
        r.receive_ciphertext(profile, attempt, envelope, frames, binding)
    assert not (attempt / "receive-receipt.json").exists()
    assert not (attempt / "ciphertext").exists()
    assert (attempt / "receive-intent.json").exists()
    with pytest.raises(r.JournalError):
        r.receive_ciphertext(profile, attempt, envelope, [ciphertext], binding)


def test_receive_interrupted_generator_retains_partial_and_no_retry(setup):
    profile, binding, envelope, ciphertext, attempt = setup

    def frames():
        yield ciphertext[:4]
        raise OSError("fixture interruption")

    with pytest.raises(OSError):
        r.receive_ciphertext(profile, attempt, envelope, frames(), binding)
    assert (attempt / "ciphertext.partial").read_bytes() == ciphertext[:4]
    assert not (attempt / "ciphertext").exists()


@pytest.mark.parametrize("field", ["plan_sha256", "profile_sha256", "phase"])
def test_receive_wrong_envelope_binding_before_stream(setup, field):
    profile, binding, envelope, ciphertext, attempt = setup
    envelope[field] = "wrong"
    with pytest.raises(r.JournalError):
        r.receive_ciphertext(profile, attempt, envelope, [ciphertext], binding)
    assert not attempt.exists()


def fake_restore(monkeypatch, setup, *, cleanup=True, corruption=False):
    profile, binding, envelope, ciphertext, attempt = setup
    received = r.receive_ciphertext(profile, attempt, envelope, [ciphertext], binding)
    calls = []

    def docker(profile, args, **kwargs):
        calls.append(args)
        if args[0] == "run":
            assert "--network" in args and args[args.index("--network") + 1] == "none"
            assert "--read-only" in args and "--pull" in args
            assert str(ROOT / "scripts/restore.sh") in args
            assert "--verify" in args and "--component" in args
            assert args[args.index("--component") + 1] == "all"
            assert "--verify-api-image" in args and "--verify-qdrant-image" in args
            assert "--gpg-key-file" in args
            assert not any("verify-inside" in arg for arg in args)
            (attempt / "restore-container.id").write_text("f" * 64)
            r.exclusive_record(
                attempt / "canonical-restore.json",
                {
                    "schema": "canonical-restore-v1",
                    "ciphertext_sha256": (
                        hashlib.sha256(ciphertext).hexdigest()
                        if not corruption
                        else "0" * 64
                    ),
                    "ciphertext_bytes": len(ciphertext),
                    "components": ["all"],
                    "qdrant_restored": True,
                    "scratch_cleanup_verified": True,
                },
            )
            if not cleanup:
                (attempt / "restore-work" / "retained").write_text("synthetic")
            return b""
        if args[0] == "inspect":
            return json.dumps(
                [
                    {
                        "Id": "f" * 64,
                        "Name": "/bisq-restore-" + binding["intent_sha256"][:32],
                        "Image": profile["recovery"]["verifier_runtime"][
                            "runtime_image_id"
                        ],
                    }
                ]
            ).encode()
        if args[0] == "rm":
            return b""
        raise AssertionError(args)

    monkeypatch.setattr(r, "_docker", docker)
    return received, calls


def test_real_receive_to_restore_adapter_and_canonical_receipt_join(monkeypatch, setup):
    profile, binding, envelope, ciphertext, attempt = setup
    received, calls = fake_restore(monkeypatch, setup)
    proof = r.verify_restore(profile, attempt, received, binding)
    assert proof["receive_receipt_sha256"] == p.canonical_sha256(received)
    assert (
        proof["canonical_restore_receipt_sha256"]
        == r._file(attempt / "canonical-restore.json")[0]
    )
    assert proof["components"] == ["all"] and proof["qdrant_restored"] is True
    assert sum(c[0] == "run" for c in calls) == 1
    with pytest.raises(r.JournalError):
        r.verify_restore(profile, attempt, received, binding)
    assert sum(c[0] == "run" for c in calls) == 1


@pytest.mark.parametrize("cleanup,corruption", [(False, False), (True, True)])
def test_restore_bad_actual_receipt_or_leftover_cannot_pass(
    monkeypatch, setup, cleanup, corruption
):
    profile, binding, envelope, ciphertext, attempt = setup
    received, _ = fake_restore(
        monkeypatch, setup, cleanup=cleanup, corruption=corruption
    )
    with pytest.raises(r.JournalError, match="recovery_restore_receipt"):
        r.verify_restore(profile, attempt, received, binding)
    assert (attempt / "restore-intent.json").exists()


def test_restore_ciphertext_changed_before_effect(monkeypatch, setup):
    profile, binding, envelope, ciphertext, attempt = setup
    received, calls = fake_restore(monkeypatch, setup)
    (attempt / "ciphertext").write_bytes(b"changed")
    with pytest.raises(r.JournalError, match="recovery_ciphertext_changed"):
        r.verify_restore(profile, attempt, received, binding)
    assert calls == []


def bash(text):
    return subprocess.run(
        ["/bin/bash", "-c", text],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_canonical_backup_receipt_after_cleanup_only(tmp_path):
    tmp_path.chmod(0o700)
    cipher = tmp_path / "cipher.gpg"
    cipher.write_bytes(b"fixture")
    staging = tmp_path / "staging"
    staging.mkdir()
    receipt = tmp_path / "receipt.json"
    result = bash(f"""source {shlex.quote(str(ROOT/'scripts/backup.sh'))}
TARGET_DIR={shlex.quote(str(tmp_path))}; EXPORT_DIR="$TARGET_DIR"; COMPLETED_OUTPUT_NAME=cipher.gpg
BACKUP_RECEIPT={shlex.quote(str(receipt))}; STAGING_DIR={shlex.quote(str(staging))}; BACKUP_COMPLETED=true
trap cleanup EXIT
""")
    assert result.returncode == 0, result.stderr
    assert not staging.exists()
    assert (
        json.loads(receipt.read_text())["destination_kind"]
        == "same_host_encrypted_export"
    )


def test_canonical_restore_cleanup_failure_prevents_receipt(tmp_path):
    backup = tmp_path / "backup.gpg"
    backup.write_bytes(b"synthetic")
    work = tmp_path / "work"
    work.mkdir()
    receipt = tmp_path / "receipt.json"
    result = bash(f"""source {shlex.quote(str(ROOT/'scripts/restore.sh'))}
BACKUP_FILE={shlex.quote(str(backup))}; WORK_DIR={shlex.quote(str(work))}
VERIFICATION_RECEIPT={shlex.quote(str(receipt))}; VERIFICATION_SUCCEEDED=true
rm() {{ return 1; }}
trap cleanup EXIT
""")
    assert result.returncode != 0
    assert not receipt.exists() and work.exists()


def test_canonical_restore_explicit_images_skip_live_compose(tmp_path):
    snapshot = tmp_path / "snapshot"
    (snapshot / "components/qdrant").mkdir(parents=True)
    (snapshot / "components/qdrant/qdrant-snapshots.tar.gz").write_bytes(b"synthetic")
    calls = tmp_path / "calls"
    result = bash(f"""source {shlex.quote(str(ROOT/'scripts/restore.sh'))}
VERIFY_API_IMAGE=sha256:{'a'*64}; VERIFY_QDRANT_IMAGE=sha256:{'b'*64}; COMPONENTS=(all)
image_id_for_service() {{ echo unexpected >&2; return 2; }}
docker() {{ printf '%s\\n' "$*" >> {shlex.quote(str(calls))}; }}
run_scratch_qdrant_helper() {{ printf '%s\\n' "$*" >> {shlex.quote(str(calls))}; cat >/dev/null; }}
cleanup_scratch_qdrant() {{ :; }}
verify_qdrant_in_scratch {shlex.quote(str(snapshot))}
""")
    assert result.returncode == 0, result.stderr
    assert (
        "qdrant-import" in calls.read_text()
        and "sha256:" + "a" * 64 in calls.read_text()
    )


def test_expired_receive_before_any_effect(setup):
    profile, binding, envelope, ciphertext, attempt = setup
    binding["deadline"] = "2020-01-01T00:00:00+00:00"
    with pytest.raises(r.JournalError, match="effect_deadline"):
        r.receive_ciphertext(profile, attempt, envelope, [ciphertext], binding)
    assert not attempt.exists()


def test_preflight_missing_key_before_docker(monkeypatch, setup):
    profile, *_ = setup
    Path(profile["recovery"]["identity_file"]).unlink()
    calls = []
    monkeypatch.setattr(r, "_docker", lambda *a, **kw: calls.append(a))
    with pytest.raises((FileNotFoundError, r.JournalError)):
        r.preflight_recovery(profile)
    assert calls == []


def test_capture_preflight_uses_only_canonical_readonly_checks(monkeypatch, setup):
    profile, *_ = setup
    Path(profile["recovery"]["recipient_file"]).write_text("A" * 40 + "\n")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert "main" not in argv[2] and "acquire" not in argv[2]
        assert "validate_configuration" in argv[2]
        assert "capture_backup_target_identity" in argv[2]
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(r.subprocess, "run", run)
    assert r.preflight_capture(profile)["capture_inputs_ready"] is True
    assert len(calls) == 1


def test_uncertain_restore_is_not_repeated(monkeypatch, setup):
    profile, binding, envelope, ciphertext, attempt = setup
    received, _ = fake_restore(monkeypatch, setup)
    calls = []

    def uncertain(profile, args, **kwargs):
        calls.append(args)
        if args[0] == "run":
            (attempt / "restore-container.id").write_text("f" * 64)
            raise r.JournalError("recovery_docker_uncertain")
        if args[0] == "inspect":
            return json.dumps(
                [
                    {
                        "Id": "f" * 64,
                        "Name": "/bisq-restore-" + binding["intent_sha256"][:32],
                        "Image": profile["recovery"]["verifier_runtime"][
                            "runtime_image_id"
                        ],
                    }
                ]
            ).encode()
        if args[0] == "rm":
            return b""
        raise AssertionError(args)

    monkeypatch.setattr(r, "_docker", uncertain)
    with pytest.raises(r.JournalError, match="recovery_docker_uncertain"):
        r.verify_restore(profile, attempt, received, binding)
    assert not (attempt / "canonical-restore.json").exists()
    with pytest.raises(r.JournalError):
        r.verify_restore(profile, attempt, received, binding)
    assert sum(c[0] == "run" for c in calls) == 1
    assert (attempt / "restore-work").exists()


def test_canonical_export_refuses_offhost_option_mix(tmp_path):
    result = bash(f"""source {shlex.quote(str(ROOT/'scripts/backup.sh'))}
EXPORT_DIR={shlex.quote(str(tmp_path))}; TARGET_DIR=/wrong
validate_configuration
""")
    assert result.returncode != 0
    assert "mutually exclusive" in result.stdout


def test_canonical_backup_cleanup_failure_no_receipt(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    receipt = tmp_path / "receipt.json"
    result = bash(f"""source {shlex.quote(str(ROOT/'scripts/backup.sh'))}
BACKUP_RECEIPT={shlex.quote(str(receipt))}; STAGING_DIR={shlex.quote(str(work))}; BACKUP_COMPLETED=true
rm() {{ return 1; }}
trap cleanup EXIT
""")
    assert result.returncode != 0 and not receipt.exists()


def test_scratch_cleanup_refuses_other_owner(tmp_path):
    log = tmp_path / "calls"
    result = bash(f"""source {shlex.quote(str(ROOT/'scripts/restore.sh'))}
SCRATCH_TOKEN=our-token; SCRATCH_QDRANT_CONTAINER=fixture-name
docker() {{ printf '%s\\n' "$*" >> {shlex.quote(str(log))}; echo wrong-owner; }}
cleanup_scratch_qdrant
""")
    assert result.returncode != 0 and "rm " not in log.read_text()


def test_canonical_capture_receipt_to_shared_phase_to_receive(monkeypatch, setup):
    profile, binding, _, ciphertext, attempt = setup
    binding = dict(binding, phase="prechange_backup")
    Path(profile["recovery"]["recipient_file"]).write_text("A" * 40 + "\n")
    monkeypatch.setenv("BISQ_SUPPORT_LIFECYCLE_LOCK_FD", "202")
    monkeypatch.setenv("BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256", binding["plan_sha256"])
    real_run = subprocess.run

    def capture(argv, **kwargs):
        assert argv[:2] == ["/bin/bash", str(ROOT / "scripts/backup.sh")]
        assert (
            kwargs["env"]["BISQ_SUPPORT_DEPLOYMENT_PLAN_SHA256"]
            == binding["plan_sha256"]
        )
        assert kwargs["pass_fds"] == (202,)
        target = Path(argv[argv.index("--export-dir") + 1])
        name = "bisq-support-backup-synthetic.tar.gz.gpg"
        (target / name).write_bytes(ciphertext)
        (target / name).chmod(0o600)
        receipt = argv[argv.index("--receipt") + 1]
        # Run the exact ordinary shell receipt producer, not a JSON facsimile.
        program = f"""source {shlex.quote(str(ROOT/'scripts/backup.sh'))}
TARGET_DIR={shlex.quote(str(target))}; EXPORT_DIR="$TARGET_DIR"; COMPLETED_OUTPUT_NAME={name}
BACKUP_RECEIPT={shlex.quote(receipt)}
write_backup_receipt
"""
        return real_run(["/bin/bash", "-c", program], capture_output=True)

    monkeypatch.setattr(r, "_capture_run", capture)
    payload = r.capture_backup(profile, attempt, binding)
    envelope = {
        "schema": "deployment-phase-receipt-v1",
        "plan_sha256": binding["plan_sha256"],
        "profile_sha256": binding["profile_sha256"],
        "phase": "prechange_backup",
        "intent_sha256": binding["intent_sha256"],
        "baseline_sha256": "d" * 64,
        "started_at": r.now(),
        "finished_at": r.now(),
        "payload": payload,
    }
    receive_binding = dict(binding, phase="prechange_restore")
    received = r.receive_ciphertext(
        profile, attempt.parent / "receive", envelope, [ciphertext], receive_binding
    )
    p.validate_receive_receipt(received, envelope)
    assert (
        payload["canonical_backup_receipt_sha256"]
        == r._file(attempt / "canonical-backup.json")[0]
    )
    assert received["export_receipt_sha256"] == p.canonical_sha256(envelope)


def test_real_capture_timeout_contains_descendant_holding_borrowed_fd(tmp_path):
    import fcntl
    import time

    lock = tmp_path / "lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    child_pid = tmp_path / "child.pid"
    # The grandchild deliberately ignores TERM and inherits the same open file
    # description. Killing just the Bash leader would leave the lock held.
    program = """import os,signal,sys,time
p=os.fork()
if p==0:
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 open(sys.argv[1],'w').write(str(os.getpid()))
 while True: time.sleep(1)
while True: time.sleep(1)
"""
    try:
        with (tmp_path / "private.log").open("wb") as log:
            with pytest.raises(r.JournalError, match="recovery_capture_uncertain"):
                r._capture_run(
                    [sys.executable, "-c", program, str(child_pid)],
                    env=dict(os.environ),
                    pass_fds=(fd,),
                    stdout=log,
                    timeout=0.5,
                )
        assert child_pid.is_file()
        # Closing our copy does not unlock a surviving child's shared description.
        os.close(fd)
        fd = None
        contender = os.open(lock, os.O_RDWR)
        try:
            for _ in range(20):
                try:
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            else:
                pytest.fail("capture descendant retained the borrowed lock")
        finally:
            os.close(contender)
    finally:
        if fd is not None:
            os.close(fd)
