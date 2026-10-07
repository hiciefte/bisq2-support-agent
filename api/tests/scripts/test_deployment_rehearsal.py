"""Ordinary CLI rehearsal in an isolated Linux fixture, never against live Docker.

Run directly with --source and --output for an evidence-producing Linux rehearsal.
Docker/GitHub/provider commands are external-boundary models; recovery capture,
encryption and restore are explicitly synthetic. Real Git, lifecycle flock,
client/bootstrap/stdio owner/host backend, ciphertext transfer and journals run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures/deployment_rehearsal"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return sha(
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )


def private_record(path, record):
    path.write_text(json.dumps(record, sort_keys=True) + "\n")
    path.chmod(0o600)


def git(path, *args):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return (
        subprocess.check_output(
            [
                shutil.which("git"),
                "-C",
                str(path),
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            env=env,
            stderr=subprocess.PIPE,
        )
        .decode()
        .strip()
    )


def commit(path):
    git(path, "add", ".")
    git(
        path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Synthetic rehearsal",
    )
    return git(path, "rev-parse", "HEAD")


def container(service, install, build_id):
    cid = sha((service + "original").encode())
    image = "sha256:" + sha((service + "image").encode())
    env = ["BUILD_ID=" + build_id, "DATA_DIR=/data"]
    if service == "api":
        env += [
            key + "=false"
            for key in (
                "MATRIX_SYNC_ENABLED",
                "MATRIX_CHATOPS_ENABLED",
                "BISQ2_CHANNEL_ENABLED",
                "BISQ2_CHATOPS_ENABLED",
                "ESCALATION_BISQ2_WS_ENABLED",
                "AUTONOMOUS_DELIVERY_ENABLED",
            )
        ]
    return {
        "Id": cid,
        "Image": image,
        "Created": "synthetic-original",
        "Config": {
            "Image": "old-" + service,
            "Hostname": cid[:12],
            "Env": env,
            "Labels": {
                "com.docker.compose.service": service,
                "com.docker.compose.project": "fixture",
                "com.docker.compose.project.working_dir": str(install / "docker"),
                "com.docker.compose.config-hash": "old",
                "com.docker.compose.container-number": "1",
                "com.docker.compose.oneoff": "False",
            },
            "Cmd": ["fixture-service"],
        },
        "Mounts": [
            {"Source": str(install / "api/data"), "Destination": "/data", "RW": True}
        ],
        "HostConfig": {"NetworkMode": "fixture_default", "Binds": ["synthetic-data"]},
        "State": {
            "Running": True,
            "Status": "running",
            "Paused": False,
            "Restarting": False,
            "Pid": int(cid[:4], 16) + 1,
            "StartedAt": "synthetic-original-start",
            "Health": {"Status": "healthy"},
        },
        "RestartCount": 0,
    }


def prepare(source, root, scenario):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    candidate, install = root / "candidate", root / "install"
    candidate.mkdir()
    shutil.copytree(
        source / "scripts",
        candidate / "scripts",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (candidate / "api/app/scripts").mkdir(parents=True)
    shutil.copyfile(
        source / "api/app/scripts/disaster_recovery.py",
        candidate / "api/app/scripts/disaster_recovery.py",
    )
    (candidate / "docker").mkdir()
    (candidate / "docker/docker-compose.yml").write_text("services: {}\n")
    (candidate / ".gitignore").write_text(
        "api/data/\ndocker/.env\nfailed_updates/\n__pycache__/\n"
    )
    (candidate / "api/app/release_fixture.py").write_text("VERSION = 1\n")
    (candidate / "web/src").mkdir(parents=True)
    (candidate / "web/src/release_fixture.ts").write_text("export const version = 1;\n")
    # This substitution exists only in the disposable committed fixture tree.
    with (candidate / "scripts/lib/deployment_recovery.py").open("a") as output:
        output.write("\n" + (FIXTURES / "recovery_adapter.txt").read_text())
    git(candidate, "init", "-q")
    previous = commit(candidate)
    (candidate / "api/app/release_fixture.py").write_text("VERSION = 2\n")
    (candidate / "web/src/release_fixture.ts").write_text("export const version = 2;\n")
    revision = commit(candidate)
    subprocess.run(
        [
            shutil.which("git"),
            "clone",
            "--quiet",
            "--no-hardlinks",
            str(candidate),
            str(install),
        ],
        check=True,
        capture_output=True,
    )
    git(install, "checkout", "--quiet", previous)
    git(
        candidate, "remote", "add", "origin", "https://github.com/fixture/rehearsal.git"
    )
    (install / "docker/.env").write_text(
        "COMPOSE_PROJECT_NAME=fixture\nOPENAI_MODEL=openai:fixture\n"
        "ENABLE_BISQ_MCP_INTEGRATION=true\n"
    )
    (install / "docker/.env").chmod(0o600)
    data = install / "api/data"
    data.mkdir()
    with sqlite3.connect(data / "feedback.db") as db:
        db.executescript(
            "CREATE TABLE channel_autoresponse_policy("
            "channel_id TEXT, enabled INTEGER, generation_enabled INTEGER); "
            "INSERT INTO channel_autoresponse_policy VALUES ('matrix',0,0),('bisq2',0,0); "
            "CREATE TABLE channel_launch_global("
            "singleton_id INTEGER, autonomous_delivery_enabled INTEGER); "
            "INSERT INTO channel_launch_global VALUES(1,0);"
        )
    with sqlite3.connect(data / "escalations.db") as db:
        db.executescript(
            "CREATE TABLE escalations("
            "id INTEGER, channel TEXT, question TEXT, channel_metadata TEXT); "
            "INSERT INTO escalations VALUES(1,'matrix','Synthetic saved case',NULL); "
            "CREATE TABLE matrix_context_trials(id TEXT); "
            "INSERT INTO matrix_context_trials VALUES('synthetic-predecessor'); "
            "CREATE TABLE matrix_context_trial_cases(id TEXT); "
            "CREATE TABLE matrix_context_attempts(id TEXT);"
        )
    (data / "matrix_session.json").write_text('{"fixture_identity":"unchanged"}\n')
    (data / "matrix_polling_state.json").write_text('{"fixture_cursor":"unchanged"}\n')
    for directory in (
        root / "host-operations",
        root / "export",
        root / "local",
        root / "home",
        root / "bin",
    ):
        directory.mkdir(mode=0o700)
    shutil.copyfile(FIXTURES / "boundary.py", root / "bin/boundary.py")
    (root / "bin/boundary.py").chmod(0o700)
    for name in ("docker", "curl", "git"):
        (root / "bin" / name).symlink_to("boundary.py")
    build_id = "build-" + previous[:7]
    containers = {
        name: container(name, install, build_id)
        for name in ("api", "web", "nginx", "scheduler")
    }
    if scenario == "preflight_refusal":
        containers["api"]["Config"]["Env"] = [
            (
                "MATRIX_SYNC_ENABLED=true"
                if value == "MATRIX_SYNC_ENABLED=false"
                else value
            )
            for value in containers["api"]["Config"]["Env"]
        ]
    state = {
        "scenario": scenario,
        "candidate": revision,
        "real_git": shutil.which("git"),
        "containers": containers,
        "images": {
            value["Image"]: {
                "Id": value["Image"],
                "Config": {"Env": ["BUILD_ID=" + build_id]},
            }
            for value in containers.values()
        },
        "build_ids": {value["Image"]: build_id for value in containers.values()},
        "cron": "# Six held fixture jobs; never execute\n"
        + "\n".join("# held fixture-job-" + str(n) for n in range(6)),
        "calls": [],
        "provider_calls": [],
        "builds": [],
        "switches": [],
        "nginx_reloads": 0,
        "synthetic_validator_calls": 0,
    }
    private_record(root / "boundary-state.json", state)
    env = os.environ.copy()
    env.update(
        PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
        HOME=str(root / "home"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    instant = datetime.now(timezone.utc)
    deadline = (instant + timedelta(minutes=20)).isoformat()
    operation = root / "local/operation"
    planned = invoke(
        candidate,
        env,
        "plan",
        "--repository",
        str(candidate),
        "--previous",
        previous,
        "--commit",
        revision,
        "--services",
        "api,web",
        "--profile",
        "fixture",
        "--deadline",
        deadline,
        "--operation",
        str(operation),
    )
    assert planned.returncode == 0, planned.stderr
    plan = json.loads((operation / "plan.json").read_text())
    # Load the same public contract to derive its fixed helper allowlists.
    sys.path.insert(0, str(candidate / "scripts"))
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "fixture_protocol_" + scenario,
            candidate / "scripts/lib/deployment_protocol.py",
        )
        protocol = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(protocol)
    finally:
        sys.path.pop(0)

    def pins(names):
        return {name: sha((candidate / name).read_bytes()) for name in names}

    profile = {
        "schema": "deployment-profile-v1",
        "name": "fixture",
        "transport": {
            "kind": "local_rehearsal",
            "ssh_alias": None,
            "host_python": sys.executable,
        },
        "host": {
            "repository": str(install),
            "candidate": str(candidate),
            "operation_root": str(root / "host-operations"),
            "compose_project": "fixture",
            "compose_file": "docker-compose.yml",
            "quality_remote": "origin",
            "readiness_timeout_seconds": 30,
            "nginx_url": "http://127.0.0.1:8000",
        },
        "phase_timeout_seconds": 90,
        "helper_sha256": pins(protocol.HOST_HELPERS),
        "recovery": {
            "export_directory": str(root / "export"),
            "encryption": "age",
            "recipient_file": str(root / "recipient"),
            "local_directory": str(root / "local"),
            "verifier_repository": str(candidate),
            "identity_file": str(root / "identity"),
            "expected_helper_sha256": pins(protocol.VERIFIER_HELPERS),
            "verifier_runtime": {
                "docker_executable": str(root / "bin/boundary.py"),
                "docker_executable_sha256": sha(
                    (root / "bin/boundary.py").read_bytes()
                ),
                "docker_socket": str(root / "unused-fixture.sock"),
                "runtime_image_id": "sha256:" + "d" * 64,
                "api_image_id": "sha256:" + "e" * 64,
                "qdrant_image_id": "sha256:" + "f" * 64,
                "uid": os.getuid(),
                "gid": os.getgid(),
            },
        },
    }
    approval = {
        "schema": "deployment-approval-v2",
        "plan_sha256": canonical(plan),
        "profile_sha256": canonical(profile),
        "phases": plan["phases"],
        "operator": "Synthetic rehearsal fixture",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "deadline": deadline,
        "smoke_calls": ["standard", "live_mcp"],
        "image_consumers": {"api": ["api"], "web": ["web"]},
        "data_compatible_rollback": True,
        "policy": "private-disabled-channels",
    }
    private_record(root / "profile.json", profile)
    private_record(root / "approval.json", approval)
    return candidate, install, operation, env, plan, state


def invoke(candidate, env, *arguments):
    return subprocess.run(
        ["bash", str(candidate / "scripts/update.sh"), *arguments],
        capture_output=True,
        text=True,
        env=env,
        timeout=240,
    )


def run_case(source, root, scenario):
    assert sys.platform == "linux", "real lifecycle ownership requires Linux /proc"
    for command in ("git", "flock", "jq", "openssl", "bash", "python3"):
        assert shutil.which(command), "missing local fixture tool: " + command
    candidate, install, operation, env, plan, original = prepare(source, root, scenario)
    data_before = {
        path.name: sha(path.read_bytes()) for path in (install / "api/data").iterdir()
    }
    applied = invoke(
        candidate,
        env,
        "apply",
        "--operation",
        str(operation),
        "--profile",
        str(root / "profile.json"),
        "--approval",
        str(root / "approval.json"),
    )
    private_record(
        root / "apply-output.json",
        {
            "returncode": applied.returncode,
            "stdout": applied.stdout,
            "stderr": applied.stderr,
        },
    )
    state = json.loads((root / "boundary-state.json").read_text())
    status = invoke(candidate, env, "status", "--operation", str(operation))
    private_record(
        root / "status-output.json",
        {
            "returncode": status.returncode,
            "stdout": status.stdout,
            "stderr": status.stderr,
        },
    )
    assert status.returncode == 0, status.stderr
    report = {
        "scenario": scenario,
        "apply_returncode": applied.returncode,
        "provider_boundary_calls": state["provider_calls"],
        "actual_linux_lifecycle_lock": (
            install / "failed_updates/disaster-recovery/recovery.lock"
        ).exists(),
        "real_git_previous": plan["source"]["previous_commit"],
        "real_git_candidate": plan["source"]["candidate_commit"],
        "limitations": [
            "Docker/container readiness and image operations are command models",
            "GitHub quality evidence and provider responses are command models",
            "capture encryption and restore verification are explicitly synthetic adapters",
            "real ciphertext framing/receive hashing and fsync run over synthetic bytes",
        ],
    }
    if scenario == "success":
        assert applied.returncode == 0, applied.stderr
        outcome = json.loads(applied.stdout)
        assert outcome["completed"] is True
        assert outcome["transport"] == "local_rehearsal"
        assert outcome["fresh_runtime_verified"] is True
        assert state["builds"] == ["api", "web"] and state["switches"] == ["api", "web"]
        assert state["provider_calls"] == ["standard", "live_mcp"]
        assert git(install, "rev-parse", "HEAD") == plan["source"]["candidate_commit"]
        assert not (
            install / "failed_updates/disaster-recovery/deployment-active.json"
        ).exists()
        assert state["containers"]["scheduler"] == original["containers"]["scheduler"]
        assert state["containers"]["nginx"] == original["containers"]["nginx"]
        before = len(state["calls"])
        continued = invoke(candidate, env, "continue", "--operation", str(operation))
        assert (
            continued.returncode == 0
            and json.loads(continued.stdout)["already_complete"] is True
        )
        assert (
            len(json.loads((root / "boundary-state.json").read_text())["calls"])
            == before
        )
        report["all_phase_receipts"] = len(
            list((operation / "receipts").glob("*.json"))
        )
        report["already_complete_no_replay"] = True
    elif scenario == "preflight_refusal":
        assert (
            applied.returncode == 2
            and not state["builds"]
            and not state["provider_calls"]
        )
        assert not list(operation.glob("*.intent.json"))
        assert not (
            install / "failed_updates/disaster-recovery/deployment-active.json"
        ).exists()
        assert git(install, "rev-parse", "HEAD") == plan["source"]["previous_commit"]
        assert state["containers"] == original["containers"]
        report["no_effect_intent"] = True
    else:
        assert scenario == "lost_smoke"
        assert applied.returncode == 2 and state["provider_calls"] == ["standard"]
        assert state.get("killed_owner_pid")
        assert (
            json.loads((operation / "smoke_standard.result.json").read_text())["status"]
            == "uncertain"
        )
        before = len(state["provider_calls"])
        continued = invoke(candidate, env, "continue", "--operation", str(operation))
        assert (
            continued.returncode == 2
            and json.loads(continued.stderr)["error"] == "reconciliation_required"
        )
        reconciled = invoke(candidate, env, "reconcile", "--operation", str(operation))
        private_record(
            root / "reconcile-output.json",
            {
                "returncode": reconciled.returncode,
                "stdout": reconciled.stdout,
                "stderr": reconciled.stderr,
            },
        )
        assert reconciled.returncode == 0, reconciled.stderr
        assert (
            len(
                json.loads((root / "boundary-state.json").read_text())["provider_calls"]
            )
            == before
        )
        assert (
            install / "failed_updates/disaster-recovery/deployment-active.json"
        ).exists()
        assert state["containers"]["scheduler"]["State"]["Paused"] is True
        assert git(install, "rev-parse", "HEAD") == plan["source"]["previous_commit"]
        report["lost_smoke_not_replayed"] = True
        report["read_only_reconciliation"] = True
    assert data_before == {
        path.name: sha(path.read_bytes()) for path in (install / "api/data").iterdir()
    }
    report["synthetic_identity_cursor_history_unchanged"] = True
    report["passed"] = True
    private_record(root / "result.json", report)
    return report


class ExternalBoundaryRegression(unittest.TestCase):
    def test_identity_template_respects_requested_fields(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            (root / "bin").mkdir()
            shutil.copyfile(FIXTURES / "boundary.py", root / "bin/boundary.py")
            (root / "bin/docker").symlink_to("boundary.py")
            api = container("api", root / "install", "build-01234567")
            private_record(
                root / "boundary-state.json",
                {"calls": [], "containers": {"api": api}},
            )
            labels = api["Config"]["Labels"]
            for include_number in (False, True):
                keys = [
                    "com.docker.compose.project",
                    "com.docker.compose.project.working_dir",
                    "com.docker.compose.service",
                ]
                if include_number:
                    keys.append("com.docker.compose.container-number")
                keys.append("com.docker.compose.oneoff")
                template = "|".join(
                    ['{{index .Config.Labels "' + key + '"}}' for key in keys]
                    + ["{{.State.Status}}"]
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        str(root / "bin/docker"),
                        "inspect",
                        "--format",
                        template,
                        api["Id"],
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(
                    result.stdout.strip().split("|"),
                    [labels[key] for key in keys] + ["running"],
                )


@unittest.skipUnless(
    sys.platform == "linux" and os.environ.get("BISQ_RUN_DEPLOYMENT_REHEARSAL") == "1",
    "explicit isolated Linux rehearsal only",
)
class OrdinaryDeploymentRehearsal(unittest.TestCase):
    def test_full_success(self):
        with tempfile.TemporaryDirectory() as parent:
            run_case(SOURCE, Path(parent) / "success", "success")

    def test_early_preflight_refusal(self):
        with tempfile.TemporaryDirectory() as parent:
            run_case(SOURCE, Path(parent) / "refusal", "preflight_refusal")

    def test_lost_smoke_response_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as parent:
            run_case(SOURCE, Path(parent) / "lost", "lost_smoke")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=["success", "preflight_refusal", "lost_smoke"],
        required=True,
    )
    args = parser.parse_args()
    print(json.dumps(run_case(args.source, args.output, args.scenario), sort_keys=True))
