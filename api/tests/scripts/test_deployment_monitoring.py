"""Monitoring release boundaries with real Git and deterministic runtime doubles."""

import copy
import importlib
import json
import subprocess
import time
from pathlib import Path

import pytest
from test_deploy_release import cli, commit, git, plan_args
from test_deploy_release import repository as repository_fixture
from test_deployment_preserved_heap import NEW, OLD
from test_deployment_protocol import protocol as protocol_fixture
from test_deployment_protocol import records as records_fixture

repository = repository_fixture
protocol = protocol_fixture
records = records_fixture
ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.unit
MONITORING = [
    "docker/scripts/scheduler-heartbeat.sh",
    "docker/prometheus/alert_rules.yml",
    "docker/prometheus/tests/privacy_retention.test.yml",
    "scripts/validate-monitoring-config.sh",
]
WORKFLOWS = {
    ".github/workflows/ci.yml": "jobs:\n  lint-and-test:\n    runs-on: ubuntu-latest\n    permissions:\n      contents: read\n  staff-alignment-offline:\n    runs-on: ubuntu-latest\n",
    ".github/workflows/ai-quality-gate.yml": "jobs:\n  release-ai-quality:\n    runs-on: ubuntu-latest\n    environment: release-ai-quality\n",
}
FLAGS = [
    "--preserve-bisq2-heap-repair",
    "--include-retention-monitoring",
    "--include-python-runner-pins",
]


@pytest.fixture
def monitoring_repo(repository):
    root, _ = repository
    previous = commit(
        root,
        OLD
        | WORKFLOWS
        | {n: "old\n" for n in MONITORING if not n.endswith(".test.yml")},
    )
    for name in MONITORING:
        if name.endswith(".sh"):
            (root / name).chmod(0o755)
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Executable fixture",
    )
    previous = git(root, "rev-parse", "HEAD").decode().strip()
    changes = NEW | {n: (ROOT / n).read_text() for n in MONITORING}
    changes.update(
        {
            n: text.replace(
                "runs-on: ubuntu-latest",
                "runs-on: ubuntu-24.04 # Matches the pinned Python 3.11.11 distribution.",
            )
            for n, text in WORKFLOWS.items()
        }
    )
    changes["api/app/example.py"] = "NEW = 2\n"
    candidate = commit(root, changes)
    return root, previous, candidate


@pytest.fixture
def monitoring_plan(monitoring_repo, tmp_path):
    root, previous, candidate = monitoring_repo
    op = tmp_path / "operation"
    result = cli(*plan_args(root, previous, candidate, op), *FLAGS)
    assert result.returncode == 0, result.stderr
    return json.loads((op / "plan.json").read_text())


def test_v5_requires_full_fixed_pins_and_explicit_scope(monitoring_plan, protocol):
    assert monitoring_plan["schema"] == "deployment-plan-v5"
    assert set(monitoring_plan["monitoring_sha256"]) == set(MONITORING)
    assert set(monitoring_plan["python_runner_sha256"]) == set(WORKFLOWS)
    assert len(monitoring_plan["phases"]) == 11  # API-only fixture; API/web is12.
    for key in ["monitoring_sha256", "python_runner_sha256", "preserved_heap_sha256"]:
        bad = copy.deepcopy(monitoring_plan)
        bad[key]["unreviewed/path"] = "a" * 64
        with pytest.raises(protocol.JournalError):
            protocol.validate_plan(bad)


@pytest.mark.parametrize(
    "fault", ["permissions", "model", "extra_runner", "rule_delete", "unknown_script"]
)
def test_runner_and_monitoring_options_refuse_unreviewed_changes(
    monitoring_repo, tmp_path, fault
):
    root, previous, candidate = monitoring_repo
    changes = {}
    workflow = root / ".github/workflows/ci.yml"
    if fault == "permissions":
        changes[".github/workflows/ci.yml"] = workflow.read_text().replace(
            "contents: read", "contents: write"
        )
    elif fault == "model":
        changes[".github/workflows/ai-quality-gate.yml"] = (
            root / ".github/workflows/ai-quality-gate.yml"
        ).read_text() + "    env:\n      MODEL: other\n"
    elif fault == "extra_runner":
        changes[".github/workflows/ci.yml"] = (
            workflow.read_text() + "  extra:\n    runs-on: ubuntu-24.04\n"
        )
    elif fault == "rule_delete":
        changes["docker/prometheus/alert_rules.yml"] = None
    else:
        changes["scripts/unreviewed.sh"] = "echo unknown\n"
    candidate = commit(root, changes)
    op = tmp_path / "refused"
    assert cli(*plan_args(root, previous, candidate, op), *FLAGS).returncode == 2
    assert not op.exists()


def test_approval_and_receipts_bind_monitoring(records, protocol):
    plan, profile, approval = copy.deepcopy(records)
    plan.update(
        schema="deployment-plan-v5",
        kind="selective-api-web-with-monitoring-v1",
        tooling_sha256={},
        preserved_heap_sha256={},
        monitoring_sha256={n: "a" * 64 for n in MONITORING},
        python_runner_sha256={},
    )
    approval.update(
        schema="deployment-approval-v5",
        tooling_sha256={},
        preserved_heap_sha256={},
        monitoring_sha256=copy.deepcopy(plan["monitoring_sha256"]),
        python_runner_sha256={},
        plan_sha256=protocol.canonical_sha256(plan),
    )
    protocol.validate_approval(approval, plan, profile)
    for name in ("monitoring_sha256", "python_runner_sha256"):
        bad = copy.deepcopy(approval)
        bad[name] = {"unknown": "a" * 64}
        with pytest.raises(protocol.JournalError):
            protocol.validate_approval(bad, plan, profile)
    publish = {
        k: plan["source"][k]
        for k in ("candidate_commit", "candidate_tree", "previous_commit")
    }
    publish.update(
        source_clean=True,
        unrelated_preserved=True,
        monitoring_files_verified=True,
        prometheus_reload_verified=True,
    )
    protocol._validate_payload("publish_source", publish, plan)
    for key in ("monitoring_files_verified", "prometheus_reload_verified"):
        bad = copy.deepcopy(publish)
        bad[key] = False
        with pytest.raises(protocol.JournalError):
            protocol._validate_payload("publish_source", bad, plan)
    resume = dict(
        scheduler_id="a" * 64,
        original_process_preserved=True,
        original_pause_restored=True,
        job_config_preserved=True,
        unrelated_preserved=True,
        monitoring_heartbeat_observed=True,
    )
    protocol._validate_payload("resume_scheduler", resume, plan)
    resume["monitoring_heartbeat_observed"] = False
    with pytest.raises(protocol.JournalError):
        protocol._validate_payload("resume_scheduler", resume, plan)


@pytest.fixture
def monitoring_host(monitoring_repo, monitoring_plan, tmp_path, monkeypatch):
    root, previous, _candidate = monitoring_repo
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("lib.deployment_host")
    install = tmp_path / "install"
    subprocess.run(["git", "clone", "--quiet", str(root), str(install)], check=True)
    git(install, "checkout", "--quiet", "--detach", previous)
    (install / "docker/docker-compose.yml").write_text(NEW["docker/docker-compose.yml"])
    host = module.DeploymentHost.__new__(module.DeploymentHost)
    host.plan = monitoring_plan
    host.install = install
    host.candidate = root
    host.approval = {
        k: copy.deepcopy(monitoring_plan[k])
        for k in (
            "tooling_sha256",
            "preserved_heap_sha256",
            "monitoring_sha256",
            "python_runner_sha256",
        )
    }
    host._git = lambda path, *args: git(path, *args).decode().strip()
    host._configuration = lambda: None
    host._preserved = lambda _containers: None
    host._inspect = lambda: {"scheduler": {"Id": "a" * 64, "State": {"Paused": True}}}
    host._monitoring_mounts = lambda _containers: None
    host._monitoring_reload = lambda: None
    host.baseline = {
        "containers": {
            "prometheus": {
                "State": {"Pid": 1, "StartedAt": "2026-11-05T09:00:00Z"},
                "RestartCount": 0,
            }
        },
        "monitoring": {
            "reload_timestamp": 100,
            "heartbeat_file": host._monitoring_file(
                "docker/scripts/scheduler-heartbeat.sh"
            ),
        },
    }
    return host, module


def test_publish_preserves_existing_heartbeat_inode_with_real_git(monitoring_host):
    host, _ = monitoring_host
    path = host.install / "docker/scripts/scheduler-heartbeat.sh"
    before = path.stat()
    with path.open("rb") as mounted:
        host._source()
        result = host._publish()
        mounted.seek(0)
        assert (
            mounted.read()
            == (host.candidate / "docker/scripts/scheduler-heartbeat.sh").read_bytes()
        )
    assert (before.st_ino, before.st_mode, before.st_uid, before.st_gid) == (
        path.stat().st_ino,
        path.stat().st_mode,
        path.stat().st_uid,
        path.stat().st_gid,
    )
    assert result["monitoring_files_verified"] and result["prometheus_reload_verified"]
    host._source(published=True)


@pytest.mark.parametrize(
    "fault", ["not_paused", "changed_inode", "changed_bytes", "partial_write"]
)
def test_monitoring_publication_refuses_or_retains_partial_attempt(
    monitoring_host, monkeypatch, fault
):
    """Refuse unsafe heartbeat publication and retain evidence of partial writes."""
    host, module = monitoring_host
    path = host.install / "docker/scripts/scheduler-heartbeat.sh"
    if fault == "not_paused":
        host._inspect = lambda: {"scheduler": {"State": {"Paused": False}}}
    elif fault == "changed_inode":
        # Create the replacement while the old inode is still allocated; an
        # unlink followed by creation can reuse that inode on Linux filesystems.
        before = path.stat()
        replacement = path.with_name("replacement-heartbeat.sh")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(before.st_mode & 0o777)
        replacement.replace(path)
        after = path.stat()
        assert (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        assert (after.st_mode, after.st_uid, after.st_gid) == (
            before.st_mode,
            before.st_uid,
            before.st_gid,
        )
    elif fault == "changed_bytes":
        path.write_text("unknown\n")
    else:

        def partial(_fd, _raw):
            raise OSError("injected partial failure")

        monkeypatch.setattr(module.os, "write", partial)
    expected = "host_monitoring_heartbeat_changed" if fault == "changed_inode" else None
    with pytest.raises((module.JournalError, OSError), match=expected):
        host._monitoring_publish_heartbeat()
    assert (
        host._git(host.install, "rev-parse", "HEAD")
        == host.plan["source"]["previous_commit"]
    )


@pytest.mark.parametrize(
    "raw", [b"", b"x 1\nx 2\n", b"x NaN\n", b"x +Inf\n", b"x -1\n"]
)
def test_metric_refuses_absent_duplicate_nonfinite(monitoring_host, raw):
    host, module = monitoring_host
    with pytest.raises(module.JournalError):
        host._metric(raw, "x")


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "old_recording_sample",
        "future_observed",
        "not_scraped",
        "critical_active",
        "old_consumed",
        "later_scrape",
    ],
)
def test_scraped_proof_uses_stored_recording_sample_time(
    monitoring_host, monkeypatch, fault
):
    host, _ = monitoring_host
    monkeypatch.setattr(time, "time", lambda: 1000)

    def query(_prom, expression):
        if expression.startswith("timestamp(privacy_retention:"):
            value = 980 if fault == "old_recording_sample" else 995
        elif expression.startswith("timestamp(scheduler_"):
            assert " @ 995.000000" in expression
            value = 989 if fault == "old_consumed" else 992
        elif " @ " in expression:
            value = 989 if fault == "old_consumed" else 990
        elif expression.startswith("scheduler_"):
            value = (
                1001
                if fault == "future_observed"
                else 989 if fault == "not_scraped" else 990
            )
        else:
            value = 1
        return {"timestamp": 1000, "value": value}

    host._monitoring_query = query
    alerts = (
        [{"labels": {"alertname": "PrivacyRetentionMetricsMissing"}}]
        if fault == "critical_active"
        else []
    )
    host._run = lambda *_a, **_k: json.dumps(
        {"status": "success", "data": {"alerts": alerts}}
    ).encode()
    proof = host._monitoring_scraped_hold({"Id": "a" * 64}, 990)
    assert (proof is not None) == (fault in {None, "later_scrape"})
    if proof:
        assert proof["hold_recording_sample_timestamp"] == 995


@pytest.mark.parametrize(
    "fault", [None, "expression", "duplicate", "health", "unknown"]
)
def test_loaded_rules_require_exact_candidate_expressions(monitoring_host, fault):
    host, module = monitoring_host
    names = [
        "privacy_retention:verified_scheduler_hold",
        "PrivacyRetentionHeld",
        "PrivacyRetentionHoldInvalid",
        "PrivacyRetentionMetricsMissing",
        "PrivacyRetentionJobStale",
        "PrivacyRetentionLogMetricsMissing",
        "PrivacyRetentionLogJobStale",
        "PrivacyRetentionWindowExceeded",
    ]
    rules = []
    for name in names:
        query = "vector(1)"
        if name in names[3:7]:
            query += " unless on () privacy_retention:verified_scheduler_hold"
        rules.append(
            {
                "name": name,
                "query": query,
                "type": "recording" if name == names[0] else "alerting",
                "health": "ok",
                "labels": {"severity": "warning" if name == names[1] else "critical"},
            }
        )
    host.baseline["monitoring"]["expected_rules"] = {
        r["name"]: {k: r[k] for k in ("type", "query")} for r in rules
    }
    if fault == "expression":
        rules[0]["query"] = "vector(2)"
    elif fault == "duplicate":
        rules.append(copy.deepcopy(rules[0]))
    elif fault in {"health", "unknown"}:
        rules[0]["health"] = "err" if fault == "health" else "unknown"

    def run(args, label, **_kwargs):
        if label == "monitoring-loaded-rules":
            return json.dumps(
                {"status": "success", "data": {"groups": [{"rules": rules}]}}
            ).encode()
        return args[-1].encode()

    host._run = run
    if fault in {"expression", "duplicate", "health"}:
        with pytest.raises(module.JournalError):
            host._monitoring_loaded_rules({"Id": "a" * 64})
    else:
        assert (host._monitoring_loaded_rules({"Id": "a" * 64}) is None) == (
            fault == "unknown"
        )


@pytest.mark.parametrize("failure", ["no_advance", "readback"])
def test_reload_signal_is_never_repeated_after_failed_proof(
    monitoring_host, monkeypatch, tmp_path, failure
):
    host, module = monitoring_host
    host.root = tmp_path
    host.host = {"readiness_timeout_seconds": 1}
    host._inspect = lambda: {"prometheus": {"Id": "a" * 64}}
    host._monitoring_file = lambda name: {
        "sha256": host.plan["monitoring_sha256"][name]
    }
    host.baseline["monitoring"]["reload_timestamp"] = 100
    calls = []
    host._run = lambda args, *_a, **_k: calls.append(args) or b""
    states = iter(
        [
            {"success": 1, "timestamp": 100},
            {"success": 1, "timestamp": 100 if failure == "no_advance" else 101},
        ]
    )
    host._monitoring_reload_state = lambda _p: next(states)
    host._monitoring_loaded_rules = lambda _p: module.require(
        False, "injected_rule_readback"
    )
    ticks = iter([0, 2])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    with pytest.raises(module.JournalError):
        module.DeploymentHost._monitoring_reload(host)
    assert (
        len([c for c in calls if c[:4] == ["docker", "kill", "--signal", "HUP"]]) == 1
    )
    assert not (tmp_path / "monitoring-reload.private.json").exists()


def test_monitoring_refuses_originally_paused_scheduler(monitoring_host):
    host, module = monitoring_host
    with pytest.raises(module.JournalError, match="host_monitoring_originally_paused"):
        host._monitoring_baseline({"scheduler": {"State": {"Paused": True}}})


@pytest.mark.parametrize("fault", ["source", "mounted_bytes"])
def test_monitoring_requires_actual_bind_source_and_bytes(monitoring_host, fault):
    host, module = monitoring_host
    containers = {
        "scheduler": {
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(host.install / MONITORING[0]),
                    "Destination": "/scripts/scheduler-heartbeat.sh",
                }
            ]
        },
        "prometheus": {
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(host.install / "docker/prometheus"),
                    "Destination": "/etc/prometheus",
                }
            ]
        },
    }
    if fault == "source":
        containers["scheduler"]["Mounts"][0]["Source"] += ".other"
    host._container_file = lambda *_a: b"wrong bytes"
    with pytest.raises(module.JournalError):
        module.DeploymentHost._monitoring_mounts(host, containers)


@pytest.mark.parametrize("fault", [None, "legacy_only", "partial", "invalid"])
def test_heartbeat_waits_for_ordinary_complete_new_sample(
    monitoring_host, monkeypatch, tmp_path, fault
):
    host, module = monitoring_host
    host.root = tmp_path
    host.host = {"readiness_timeout_seconds": 1}
    host.baseline["monitoring"]["heartbeat_timestamp"] = 900
    host._inspect = lambda: {"scheduler": {}, "prometheus": {}}
    old = b"scheduler_heartbeat_timestamp_seconds 990\n"
    new = (
        old
        + (
            "scheduler_retention_hold_active 1\n"
            "scheduler_retention_hold_invalid 0\n"
            "scheduler_retention_hold_cutoff_timestamp_seconds 800\n"
            "scheduler_retention_hold_observed_timestamp_seconds 990\n"
        ).encode()
    )
    if fault == "partial":
        new = old + b"scheduler_retention_hold_active 1\n"
    if fault == "invalid":
        new = new.replace(b"hold_invalid 0", b"hold_invalid 1")
    raw = iter([old, old if fault == "legacy_only" else new])
    host._container_file = lambda *_a: next(raw)
    state = {"timestamp": 950, "success": 1}
    module.private_bytes(
        tmp_path / "monitoring-reload.private.json", module.encode(state)
    )
    host._monitoring_reload_state = lambda _p: state
    host._monitoring_scraped_hold = lambda *_a: {"held_job_stale_alerts_inactive": True}
    ticks = iter([0, 0.5, 2])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(time, "time", lambda: 1000)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    host._run = lambda *_a, **_k: pytest.fail("must not invoke a heartbeat job")
    if fault:
        with pytest.raises(module.JournalError):
            host._monitoring_observe_heartbeat(980)
        assert not (tmp_path / "monitoring-heartbeat.private.json").exists()
    else:
        host._monitoring_observe_heartbeat(980)
        assert json.loads((tmp_path / "monitoring-heartbeat.private.json").read_text())[
            "ordinary_heartbeat_observed"
        ]
