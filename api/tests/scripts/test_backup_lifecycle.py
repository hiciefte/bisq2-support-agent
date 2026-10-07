"""Execute the real backup shell functions with local fixture commands only."""

from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts/backup.sh"
CONTAINER_ID = "a" * 64
SCHEDULER_ID = "d" * 64


@pytest.fixture
def fixture(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    (staging / "snapshot.data").write_text("fixture snapshot")
    (tmp_path / "container-id").write_text(CONTAINER_ID)
    (tmp_path / "writer-state.json").write_text(
        json.dumps(
            {
                "Id": CONTAINER_ID,
                "Running": True,
                "Paused": False,
                "Restarting": False,
                "Pid": 12345,
            }
        )
    )
    identity = {
        "Id": CONTAINER_ID,
        "Image": "sha256:" + "b" * 64,
        "Created": "2026-01-01T00:00:00Z",
        "Config": {"Env": ["PRIVATE_FIXTURE=do-not-log"], "Cmd": ["run", "api"]},
        "Mounts": [
            {"Type": "bind", "Source": "/fixture/data", "Destination": "/data"},
            {"Type": "volume", "Name": "fixture", "Destination": "/other"},
        ],
    }
    (tmp_path / "identities.json").write_text(json.dumps([identity] * 3))
    scheduler = copy.deepcopy(identity)
    scheduler["Id"] = SCHEDULER_ID
    scheduler["Config"]["Cmd"] = ["held", "scheduler"]
    (tmp_path / "scheduler-identity.json").write_text(json.dumps(scheduler))
    (tmp_path / "scheduler-state.json").write_text(
        json.dumps(
            {
                "Id": SCHEDULER_ID,
                "Running": True,
                "Paused": True,
                "Restarting": False,
                "Pid": 67890,
                "StartedAt": "2026-01-01T00:00:00Z",
            }
        )
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "root = pathlib.Path(os.environ['FIXTURE_ROOT'])\n"
        "assert sys.argv[1:3] == ['inspect', '--format']\n"
        "if sys.argv[3] == '{{.Image}}':\n"
        "    print('fixture-image')\n"
        "    sys.exit(0)\n"
        f"if sys.argv[-1] == {SCHEDULER_ID!r}:\n"
        "    name = 'scheduler-state.json' if '.State.Running' in sys.argv[3] "
        "else 'scheduler-identity.json'\n"
        "    value = json.loads((root / name).read_text())\n"
        "    if name == 'scheduler-state.json' and '.State.StartedAt' not in sys.argv[3]:\n"
        "        value.pop('StartedAt')\n"
        "    print(json.dumps(value))\n"
        "    sys.exit(0)\n"
        "if '.State.Running' in sys.argv[3]:\n"
        "    print((root / 'writer-state.json').read_text())\n"
        "    sys.exit(0)\n"
        "counter = root / 'inspect-count'\n"
        "index = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(index + 1))\n"
        "if os.environ.get('INSPECT_FAIL_AT') == str(index): sys.exit(9)\n"
        "values = json.loads((root / 'identities.json').read_text())\n"
        "print(json.dumps(values[index]))\n"
    )
    docker.chmod(0o700)
    return tmp_path, identity


def run(fixture, body: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    root, _ = fixture
    env = dict(os.environ)
    env.update(overrides)
    env["FIXTURE_ROOT"] = str(root)
    # The production entrypoint runs on Linux. Do not add macOS AppleDouble
    # files from the temporary fixture's extended attributes to its tar stream.
    env["COPYFILE_DISABLE"] = "1"
    env["PATH"] = str(root / "bin") + os.pathsep + env["PATH"]
    # No real Docker executable is reached; Compose is a finite shell fixture.
    script = f"""
        source {shlex.quote(str(BACKUP))}
        STAGING_DIR="$FIXTURE_ROOT/staging"
        compose() {{
            case "$*" in
                'ps --status running --services')
                    if [ "${{HAS_SCHEDULER:-0}}" = 1 ]; then printf 'scheduler\\n'; fi
                    printf 'api\\n' ;;
                'ps --all -q api') cat "$FIXTURE_ROOT/container-id" ;;
                'ps --all -q scheduler')
                    if [ "${{HAS_SCHEDULER:-0}}" = 1 ]; then
                        printf '%s\\n' '{SCHEDULER_ID}'
                    fi ;;
                'stop --timeout 30 api')
                    printf 'stop\\n' >> "$FIXTURE_ROOT/actions"
                    [ "${{STOP_FAIL:-0}}" != 1 ] ;;
                'stop --timeout 30 scheduler')
                    printf 'stop scheduler\\n' >> "$FIXTURE_ROOT/actions" ;;
                'start scheduler api')
                    printf 'start scheduler api\\n' >> "$FIXTURE_ROOT/actions" ;;
                'start api')
                    printf 'start\\n' >> "$FIXTURE_ROOT/actions"
                    if [ "${{INTERRUPT_START:-0}}" = 1 ]; then kill -TERM $$; fi
                    [ "${{START_FAIL:-0}}" != 1 ] ;;
                'run --rm --no-deps -T '*) tar -czf - -T /dev/null ;;
                *) return 99 ;;
            esac
        }}
        {body}
    """
    return subprocess.run(
        ["bash", "-c", script], env=env, text=True, capture_output=True, check=False
    )


def actions(fixture) -> list[str]:
    path = fixture[0] / "actions"
    return path.read_text().splitlines() if path.exists() else []


def identities(fixture, values) -> None:
    (fixture[0] / "identities.json").write_text(json.dumps(values))


def test_real_identity_accepts_object_and_mount_order_with_private_evidence(fixture):
    root, before = fixture
    reordered = dict(reversed(list(copy.deepcopy(before).items())))
    reordered["Mounts"].reverse()
    identities(fixture, [before, reordered, reordered])
    result = run(fixture, "quiesce_services; resume_services; resume_services")
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions(fixture) == ["stop", "start"]
    evidence = root / "staging.writer-identities"
    assert evidence.stat().st_mode & 0o777 == 0o700
    for phase in ("before", "resume", "after"):
        assert json.loads((evidence / f"api.{phase}.json").read_text()) == (
            before if phase == "before" else reordered
        )
        for suffix in ("id", "json", "sha256"):
            assert (evidence / f"api.{phase}.{suffix}").stat().st_mode & 0o777 == 0o600
    assert "do-not-log" not in result.stdout + result.stderr
    state_file = evidence / "api.after-state.json"
    assert state_file.stat().st_mode & 0o777 == 0o600
    assert json.loads(state_file.read_text())["Running"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Running", False),
        ("Running", 1),
        ("Paused", True),
        ("Restarting", True),
        ("Pid", 0),
        ("Pid", True),
        ("Id", "c" * 64),
    ],
)
def test_compose_success_with_invalid_writer_state_retains_evidence(
    fixture, field, value
):
    state_file = fixture[0] / "writer-state.json"
    state = json.loads(state_file.read_text())
    state[field] = value
    state_file.write_text(json.dumps(state))
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; CAPTURE_COMPLETE=true; "
        "resume_services; BACKUP_COMPLETED=true",
    )
    assert result.returncode != 0
    assert actions(fixture) == ["stop", "start"]
    assert "did not resume running" in result.stdout + result.stderr
    assert (fixture[0] / "staging/snapshot.data").exists()
    assert (fixture[0] / "staging.writer-identities/api.after-state.json").exists()
    assert (
        "resume_state=failed"
        in (fixture[0] / "staging/backup-failure.state").read_text()
    )


@pytest.mark.parametrize("phase_index", [1, 2])
@pytest.mark.parametrize("change", ["mount", "env_order", "duplicate_mount"])
def test_real_identity_rejects_drift_without_retry(fixture, phase_index, change):
    _, before = fixture
    changed = copy.deepcopy(before)
    if change == "mount":
        changed["Mounts"][0]["Source"] = "/changed"
    elif change == "env_order":
        before["Config"]["Env"].append("OTHER=value")
        changed = copy.deepcopy(before)
        changed["Config"]["Env"].reverse()
    else:
        changed["Mounts"].append(copy.deepcopy(changed["Mounts"][0]))
    values = [before, before, before]
    values[phase_index] = changed
    identities(fixture, values)
    result = run(fixture, "trap cleanup EXIT; quiesce_services; resume_services")
    assert result.returncode != 0
    assert actions(fixture).count("start") == (0 if phase_index == 1 else 1)
    assert "Backup writer identity changed: api" in result.stdout + result.stderr
    assert (fixture[0] / "staging/snapshot.data").exists()
    assert (
        "resume_state=failed"
        in (fixture[0] / "staging/backup-failure.state").read_text()
    )


def test_changed_container_id_refuses_start_and_preserves_inspection(fixture):
    root, before = fixture
    changed = copy.deepcopy(before)
    changed["Id"] = "c" * 64
    identities(fixture, [before, changed])
    result = run(
        fixture,
        'trap cleanup EXIT; quiesce_services; printf "%s" "'
        + "c" * 64
        + '" > "$FIXTURE_ROOT/container-id"; resume_services',
    )
    assert result.returncode != 0
    assert actions(fixture) == ["stop"]
    assert (root / "staging.writer-identities/api.resume.json").exists()


def test_failed_stop_gets_one_cleanup_resume_but_keeps_snapshot(fixture):
    result = run(fixture, "trap cleanup EXIT; quiesce_services", STOP_FAIL="1")
    assert result.returncode != 0
    assert actions(fixture) == ["stop", "start"]
    state = (fixture[0] / "staging/backup-failure.state").read_text()
    assert "resume_state=succeeded" in state
    assert "capture_complete=false" in state


def test_failed_start_is_not_repeated_by_cleanup(fixture):
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; CAPTURE_COMPLETE=true; resume_services",
        START_FAIL="1",
    )
    assert result.returncode != 0
    assert actions(fixture) == ["stop", "start"]
    state = (fixture[0] / "staging/backup-failure.state").read_text()
    assert "capture_complete=true" in state
    assert "resume_state=failed" in state
    assert (fixture[0] / "staging.writer-identities/api.after.json").exists()


def test_interrupted_resume_state_never_starts_again(fixture):
    result = run(
        fixture,
        "trap cleanup EXIT; trap 'exit 143' TERM; quiesce_services; resume_services",
        INTERRUPT_START="1",
    )
    assert result.returncode == 143
    assert actions(fixture) == ["stop", "start"]
    assert (fixture[0] / "staging/snapshot.data").exists()


def test_cleanup_resume_failure_promotes_success_status(fixture):
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; BACKUP_COMPLETED=true; exit 0",
        START_FAIL="1",
    )
    assert result.returncode != 0
    assert actions(fixture) == ["stop", "start"]
    assert (fixture[0] / "staging/snapshot.data").exists()


@pytest.mark.parametrize("initial_status", [0, 23])
def test_cleanup_retains_partial_cipher_and_original_failure(fixture, initial_status):
    root, _ = fixture
    partial = root / "partial-cipher"
    partial.write_text("partial")
    partial.chmod(0o600)
    result = run(
        fixture,
        'trap cleanup EXIT; PARTIAL_OUTPUT="$FIXTURE_ROOT/partial-cipher"; '
        f"BACKUP_COMPLETED=true; exit {initial_status}",
    )
    assert result.returncode == (initial_status or 1)
    assert partial.read_text() == "partial"
    assert (root / "staging/snapshot.data").exists()


def test_success_removes_staging_only_after_completed_backup(fixture):
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; resume_services; BACKUP_COMPLETED=true",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (fixture[0] / "staging").exists()
    assert not (fixture[0] / "staging.writer-identities").exists()
    assert actions(fixture) == ["stop", "start"]


@pytest.mark.parametrize("failure", ["remove", "unlock"])
def test_cleanup_disposal_or_unlock_failure_is_nonzero(fixture, failure):
    injected = (
        "rm() { return 17; };"
        if failure == "remove"
        else "LOCK_FD=201; flock() { return 17; };"
    )
    result = run(fixture, "trap cleanup EXIT; " + injected + " BACKUP_COMPLETED=true")
    assert result.returncode == 17
    if failure == "remove":
        assert (fixture[0] / "staging/snapshot.data").exists()


def test_inspect_failure_keeps_partial_evidence_and_does_not_stop(fixture):
    result = run(fixture, "trap cleanup EXIT; quiesce_services", INSPECT_FAIL_AT="0")
    assert result.returncode != 0
    assert actions(fixture) == []
    assert (fixture[0] / "staging.writer-identities/api.before.json").exists()


def test_writer_evidence_is_exclusive_and_cannot_be_reused(fixture):
    result = run(
        fixture,
        "prepare_writer_metadata; capture_writer_identity api before; "
        "capture_writer_identity api before",
    )
    assert result.returncode != 0
    assert (fixture[0] / "inspect-count").read_text() == "1"


@pytest.mark.parametrize("encryption", ["age", "gpg"])
def test_failed_encryption_retains_private_partial_and_complete_snapshot(
    fixture, encryption
):
    root, _ = fixture
    target = root / "target"
    target.mkdir(mode=0o700)
    encryptor = root / "bin" / encryption
    encryptor.write_text(
        "#!/bin/bash\n"
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = --output ]; then output=$2; shift 2; else shift; fi\n'
        "done\n"
        'cat > "$output"\n'
        "exit 19\n"
    )
    encryptor.chmod(0o700)
    result = run(
        fixture,
        'trap cleanup EXIT; umask 022; TARGET_DIR="$FIXTURE_ROOT/target"; '
        f"ENCRYPTION={encryption}; RECIPIENT=fixture; CAPTURE_COMPLETE=true; "
        "revalidate_backup_target() { :; }; encrypt_backup 20260101T000000Z",
    )
    assert result.returncode != 0
    partials = list(target.glob(".*.partial.*"))
    assert len(partials) == 1
    assert partials[0].stat().st_mode & 0o777 == 0o600
    assert partials[0].stat().st_size > 0
    assert (root / "staging/snapshot.data").exists()
    assert (
        "capture_complete=true" in (root / "staging/backup-failure.state").read_text()
    )
    assert list(target.glob("bisq-support-backup-*")) == []


def test_private_docker_config_never_enters_backup_archive(fixture):
    root, _ = fixture
    target = root / "target"
    target.mkdir(mode=0o700)
    encryptor = root / "bin/age"
    encryptor.write_text(
        "#!/bin/bash\n"
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = --output ]; then output=$2; shift 2; else shift; fi\n'
        "done\n"
        'cat > "$output"\n'
    )
    encryptor.chmod(0o700)
    result = run(
        fixture,
        "quiesce_services; resume_services; "
        'TARGET_DIR="$FIXTURE_ROOT/target"; ENCRYPTION=age; RECIPIENT=fixture; '
        "revalidate_backup_target() { :; }; encrypt_backup 20260101T000000Z",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    artifact = target / "bisq-support-backup-20260101T000000Z.tar.gz.age"
    with tarfile.open(artifact, "r:gz") as archive:
        assert set(archive.getnames()) == {".", "./snapshot.data"}
    assert (
        "do-not-log" in (root / "staging.writer-identities/api.before.json").read_text()
    )
    assert "do-not-log" not in result.stdout + result.stderr


def lock_setup() -> str:
    return """
        mkdir -p "$FIXTURE_ROOT/install/api/data"
        export BISQ_SUPPORT_INSTALL_DIR="$FIXTURE_ROOT/install"
        source_deploy_paths() { :; }
        initialize_paths
        flock() { printf '%s\\n' "$*" >> "$FIXTURE_ROOT/flock-calls"; }
    """


@pytest.mark.parametrize("borrowed", [False, True])
def test_common_acquisition_only_releases_backup_owned_descriptor(fixture, borrowed):
    setup = lock_setup()
    if borrowed:
        setup += """
            exec 9<>"$FIXTURE_ROOT/parent-lock"
            export BISQ_SUPPORT_LIFECYCLE_LOCK_FD=9
            verify_inherited_production_lifecycle_lock() {
                test -e /dev/fd/9
                printf 'verified\\n' >> "$FIXTURE_ROOT/verify-calls"
            }
        """
    else:
        setup += "unset BISQ_SUPPORT_LIFECYCLE_LOCK_FD;"
    result = run(
        fixture,
        setup + "acquire_recovery_lock; trap cleanup EXIT; BACKUP_COMPLETED=true",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = fixture[0] / "flock-calls"
    if borrowed:
        assert not calls.exists()
        assert (fixture[0] / "verify-calls").read_text() == "verified\n"
        assert not (fixture[0] / "install/failed_updates").exists()
    else:
        assert calls.read_text().splitlines() == ["-n 202", "-u 202"]


def test_invalid_borrowed_lock_never_reacquires_or_mutates_parent_paths(fixture):
    result = run(
        fixture,
        lock_setup() + """
            export BISQ_SUPPORT_LIFECYCLE_LOCK_FD=9
            verify_inherited_production_lifecycle_lock() { return 41; }
            acquire_recovery_lock
        """,
    )
    assert result.returncode != 0
    assert not (fixture[0] / "flock-calls").exists()
    assert not (fixture[0] / "install/failed_updates").exists()
    assert actions(fixture) == []


def test_already_paused_scheduler_is_preserved_independently_of_lock(fixture):
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; resume_services; BACKUP_COMPLETED=true",
        HAS_SCHEDULER="1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions(fixture) == ["stop", "start"]
    assert json.loads((fixture[0] / "scheduler-state.json").read_text())["Paused"]


def test_standalone_unpaused_scheduler_keeps_existing_stop_start_scope(fixture):
    path = fixture[0] / "scheduler-state.json"
    value = json.loads(path.read_text())
    value["Paused"] = False
    path.write_text(json.dumps(value))
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; resume_services; BACKUP_COMPLETED=true",
        HAS_SCHEDULER="1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions(fixture) == ["stop scheduler", "stop", "start scheduler api"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Paused", False),
        ("Running", False),
        ("Restarting", True),
        ("Pid", 99999),
        ("StartedAt", "2026-01-02T00:00:00Z"),
    ],
)
def test_paused_scheduler_drift_refuses_resume_without_touching_it(
    fixture, field, value
):
    mutate = (
        "import json,os,pathlib; "
        "p=pathlib.Path(os.environ['FIXTURE_ROOT'])/'scheduler-state.json'; "
        f"v=json.loads(p.read_text()); v[{field!r}]={value!r}; "
        "p.write_text(json.dumps(v))"
    )
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; "
        f"python3 -c {shlex.quote(mutate)}; resume_services",
        HAS_SCHEDULER="1",
    )
    assert result.returncode != 0
    assert actions(fixture) == ["stop"]
    assert (fixture[0] / "staging/snapshot.data").exists()
    assert (
        fixture[0] / "staging.writer-identities/scheduler.pause-final.json"
    ).exists()


def test_paused_scheduler_command_drift_is_not_ignored(fixture):
    mutate = (
        "import json,os,pathlib; "
        "p=pathlib.Path(os.environ['FIXTURE_ROOT'])/'scheduler-identity.json'; "
        "v=json.loads(p.read_text()); v['Config']['Cmd']=['changed']; "
        "p.write_text(json.dumps(v))"
    )
    result = run(
        fixture,
        "trap cleanup EXIT; quiesce_services; "
        f"python3 -c {shlex.quote(mutate)}; resume_services",
        HAS_SCHEDULER="1",
    )
    assert result.returncode != 0
    assert actions(fixture) == ["stop"]
    assert "Backup writer identity changed: scheduler" in result.stdout + result.stderr


def test_main_entrypoint_borrows_lock_and_preserves_paused_scheduler(fixture):
    root, _ = fixture
    target = root / "target"
    target.mkdir(mode=0o700)
    helper = root / "api/app/scripts/disaster_recovery.py"
    helper.parent.mkdir(parents=True)
    helper.write_text(
        "import pathlib,sys\n"
        "args = sys.argv\n"
        "flag = '--output-dir' if args[1] == 'snapshot-data' else '--root'\n"
        "root = pathlib.Path(args[args.index(flag)+1])\n"
        "(root/'manifest.json').write_text('{}')\n"
    )
    encryptor = root / "bin/age"
    encryptor.write_text(
        "#!/bin/bash\n"
        "while [ $# -gt 0 ]; do\n"
        '  if [ "$1" = --output ]; then output=$2; shift 2; else shift; fi\n'
        "done\n"
        'cat > "$output"\n'
    )
    encryptor.chmod(0o700)
    result = run(
        fixture,
        lock_setup() + """
            PROJECT_ROOT="$FIXTURE_ROOT"
            export TMPDIR="$FIXTURE_ROOT"
            exec 9<>"$FIXTURE_ROOT/parent-lock"
            export BISQ_SUPPORT_LIFECYCLE_LOCK_FD=9
            verify_inherited_production_lifecycle_lock() {
                test -e /dev/fd/9
                printf 'verified\\n' >> "$FIXTURE_ROOT/verify-calls"
            }
            validate_configuration() {
                test "$OFF_HOST_CONFIRMED" = true
                test "$ENCRYPTION" = age
                test "$RECIPIENT" = fixture
            }
            capture_backup_target_identity() { :; }
            revalidate_backup_target() { :; }
            pin_existing_compose_project() { :; }
            validate_api_data_mount() { :; }
            service_is_configured() { return 1; }
            volume_for_service_path() { printf 'fixture-volume\\n'; }
            container_env_value() { :; }
            snapshot_volume() { touch "$STAGING_DIR/components/volumes/$1.tar.gz"; }
            main --target "$FIXTURE_ROOT/target" --mount-root "$FIXTURE_ROOT" \\
                --confirm-off-host --recipient fixture
        """,
        HAS_SCHEDULER="1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert actions(fixture) == ["stop", "start"]
    assert not (root / "flock-calls").exists()
    assert (root / "verify-calls").read_text() == "verified\n"
    assert len(list(target.glob("bisq-support-backup-*.tar.gz.age"))) == 1
    assert list(root.glob("bisq-support-backup.*")) == []
    assert json.loads((root / "scheduler-state.json").read_text())["Paused"]
