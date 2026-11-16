"""Exact Staff source capability; all runtime boundaries below are explicit doubles."""

import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest
from test_deploy_release import cli, commit, git, plan_args
from test_deploy_release import repository as repository_fixture
from test_deployment_monitoring import monitoring_host as monitoring_host_fixture
from test_deployment_monitoring import monitoring_plan as monitoring_plan_fixture
from test_deployment_monitoring import monitoring_repo as monitoring_repo_fixture
from test_deployment_protocol import protocol as protocol_fixture
from test_deployment_protocol import records as records_fixture

repository = repository_fixture
protocol = protocol_fixture
records = records_fixture
monitoring_repo = monitoring_repo_fixture
monitoring_plan = monitoring_plan_fixture
monitoring_host = monitoring_host_fixture
ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.unit
ALERTS = "docker/prometheus/alert_rules.yml"
STAFF = {
    "scripts/staff_pilot_watchdog.py",
    "scripts/staff_pilot_watchdog_adapter.py",
    ALERTS,
    "docker/prometheus/tests/staff_pilot_watchdog.test.yml",
}
PRESERVED = {
    "docker/scripts/scheduler-heartbeat.sh",
    "docker/prometheus/tests/privacy_retention.test.yml",
    "scripts/validate-monitoring-config.sh",
}
FLAG = "--include-staff-pilot-monitoring"
APPEND = (ROOT / ALERTS).read_text().split("\n  - name: staff_pilot_watchdog\n", 1)


@pytest.fixture
def staff_repo(repository):
    root, _ = repository
    commit(root, {n: (ROOT / n).read_text() for n in PRESERVED} | {ALERTS: APPEND[0]})
    for name in PRESERVED:
        if name.endswith(".sh"):
            (root / name).chmod(0o755)
    previous = commit(root, {"api/app/example.py": "VERSION = 1\n"})
    candidate = commit(
        root,
        {n: (ROOT / n).read_text() for n in STAFF}
        | {"api/app/example.py": "VERSION = 2\n"},
    )
    return root, previous, candidate


@pytest.fixture
def staff_plan(staff_repo, tmp_path):
    root, previous, candidate = staff_repo
    operation = tmp_path / "staff-operation"
    result = cli(*plan_args(root, previous, candidate, operation), FLAG)
    assert result.returncode == 0, result.stderr
    return json.loads((operation / "plan.json").read_text())


def test_explicit_v6_pins_all_staff_and_unchanged_retention(staff_plan, protocol):
    assert staff_plan["schema"] == "deployment-plan-v6"
    assert set(staff_plan["staff_monitoring_sha256"]) == STAFF
    assert set(staff_plan["preserved_retention_sha256"]) == PRESERVED
    assert staff_plan["tooling_sha256"] == {}
    for field in ("staff_monitoring_sha256", "preserved_retention_sha256"):
        for fault in ("extra", "missing", "malformed"):
            bad = copy.deepcopy(staff_plan)
            key = next(iter(bad[field]))
            if fault == "extra":
                bad[field]["scripts/arbitrary.py"] = "a" * 64
            elif fault == "missing":
                del bad[field][key]
            else:
                bad[field][key] = "invalid"
            with pytest.raises(protocol.JournalError):
                protocol.validate_plan(bad)
    bad = copy.deepcopy(staff_plan)
    bad["services"] = ["web"]
    bad["phases"] = protocol.phases_for(["web"])
    with pytest.raises(protocol.JournalError, match="staff_monitoring_requires_api"):
        protocol.validate_plan(bad)


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--include-deployment-tooling"],
        ["--include-retention-monitoring"],
        [FLAG, "--include-retention-monitoring"],
        [FLAG, "--preserve-bisq2-heap-repair"],
        [FLAG, "--include-python-runner-pins"],
    ],
)
def test_old_or_mixed_capabilities_cannot_admit_staff(staff_repo, tmp_path, flags):
    root, previous, candidate = staff_repo
    op = tmp_path / "refused"
    assert cli(*plan_args(root, previous, candidate, op), *flags).returncode == 2
    assert not op.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "legacy_heartbeat",
        "legacy_validator",
        "legacy_test",
        "legacy_alert",
        "arbitrary_rule",
        "delete",
        "symlink",
        "unknown_script",
        "missing_bundle",
        "web_only",
    ],
)
def test_staff_refuses_broadened_or_incomplete_source(staff_repo, tmp_path, fault):
    root, previous, candidate = staff_repo
    changes = {}
    target = "scripts/staff_pilot_watchdog.py"
    if fault.startswith("legacy_"):
        target = {
            "legacy_heartbeat": "docker/scripts/scheduler-heartbeat.sh",
            "legacy_validator": "scripts/validate-monitoring-config.sh",
            "legacy_test": "docker/prometheus/tests/privacy_retention.test.yml",
            "legacy_alert": ALERTS,
        }[fault]
        changes[target] = "# changed\n" + (root / target).read_text()
    elif fault == "arbitrary_rule":
        changes[ALERTS] = (root / ALERTS).read_text().replace("for: 2m", "for: 3m")
    elif fault == "delete":
        changes[target] = None
    elif fault == "missing_bundle":
        changes["docker/prometheus/tests/staff_pilot_watchdog.test.yml"] = None
    elif fault == "symlink":
        (root / target).unlink()
        (root / target).symlink_to("staff_pilot_watchdog_adapter.py")
    elif fault == "unknown_script":
        changes["scripts/other.py"] = "pass\n"
    else:
        changes["api/app/example.py"] = "VERSION = 1\n"
        changes["web/src/example.ts"] = "export const value = 1;\n"
    candidate = commit(root, changes)
    op = tmp_path / "refused"
    args = plan_args(root, previous, candidate, op)
    if fault == "web_only":
        args[args.index("--services") + 1] = "web"
    assert cli(*args, FLAG).returncode == 2
    assert not op.exists()


def test_changed_controller_requires_separate_tooling_opt_in(staff_repo, tmp_path):
    root, previous, candidate = staff_repo
    candidate = commit(
        root, {"scripts/deploy_release.py": "# reviewed controller fixture\n"}
    )
    args = plan_args(root, previous, candidate, tmp_path / "op")
    assert cli(*args, FLAG).returncode == 2
    result = cli(*args, FLAG, "--include-deployment-tooling")
    assert result.returncode == 0, result.stderr
    plan = json.loads((tmp_path / "op/plan.json").read_text())
    assert set(plan["tooling_sha256"]) == {"scripts/deploy_release.py"}


def test_v6_approval_and_publication_require_all_pins_and_proofs(
    records, protocol, staff_plan
):
    _old, profile, approval = copy.deepcopy(records)
    # Keep the existing approval's reviewed clock/profile/services, varying only capability.
    plan = copy.deepcopy(_old)
    for field in (
        "schema",
        "kind",
        "tooling_sha256",
        "staff_monitoring_sha256",
        "preserved_retention_sha256",
    ):
        plan[field] = staff_plan[field]
    approval.update(
        schema="deployment-approval-v6",
        plan_sha256=protocol.canonical_sha256(plan),
        **{
            k: copy.deepcopy(plan[k])
            for k in (
                "tooling_sha256",
                "staff_monitoring_sha256",
                "preserved_retention_sha256",
            )
        }
    )
    protocol.validate_approval(approval, plan, profile)
    for field in (
        "staff_monitoring_sha256",
        "preserved_retention_sha256",
        "tooling_sha256",
    ):
        bad = copy.deepcopy(approval)
        bad[field] = {"unknown": "a" * 64}
        with pytest.raises(protocol.JournalError):
            protocol.validate_approval(bad, plan, profile)
    payload = {
        k: plan["source"][k]
        for k in ("candidate_commit", "candidate_tree", "previous_commit")
    }
    payload.update(
        source_clean=True,
        unrelated_preserved=True,
        monitoring_files_verified=True,
        prometheus_reload_verified=True,
    )
    protocol._validate_payload("publish_source", payload, plan)
    for field in ("monitoring_files_verified", "prometheus_reload_verified"):
        bad = dict(payload, **{field: False})
        with pytest.raises(protocol.JournalError):
            protocol._validate_payload("publish_source", bad, plan)
    bad = dict(approval, schema="deployment-approval-v5")
    with pytest.raises(protocol.JournalError):
        protocol.validate_approval(bad, plan, profile)


def test_v6_publish_uses_real_git_and_never_rewrites_heartbeat(
    staff_repo, staff_plan, tmp_path, monkeypatch
):
    root, previous, candidate = staff_repo
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("lib.deployment_host")
    host = module.DeploymentHost.__new__(module.DeploymentHost)
    host.plan = staff_plan
    host.candidate = root
    host.install = tmp_path / "install"
    subprocess.run(
        ["git", "clone", "--quiet", str(root), str(host.install)], check=True
    )
    git(host.install, "checkout", "--quiet", "--detach", previous)
    host.approval = {
        k: copy.deepcopy(staff_plan[k])
        for k in (
            "tooling_sha256",
            "staff_monitoring_sha256",
            "preserved_retention_sha256",
        )
    }
    host._git = lambda path, *args: git(path, *args).decode().strip()
    host._configuration = lambda: None
    host._inspect = lambda: {}
    host._preserved = lambda _containers: None
    calls = []
    host._monitoring_reload = lambda: calls.append("reload")
    host._monitoring_publish_heartbeat = lambda: pytest.fail(
        "unchanged heartbeat must never be rewritten"
    )
    heartbeat = host.install / "docker/scripts/scheduler-heartbeat.sh"
    before = heartbeat.stat()
    before_bytes = heartbeat.read_bytes()
    with heartbeat.open("rb") as mounted:
        receipt = host._publish()
        assert mounted.read() == before_bytes
    assert heartbeat.stat().st_ino == before.st_ino
    assert heartbeat.stat().st_mtime_ns == before.st_mtime_ns
    assert heartbeat.read_bytes() == before_bytes
    assert calls == ["reload"] and receipt["prometheus_reload_verified"]
    assert git(host.install, "rev-parse", "HEAD").decode().strip() == candidate
    host.approval["preserved_retention_sha256"] = {}
    with pytest.raises(module.JournalError, match="host_staff_monitoring_source"):
        host._source(published=True)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing_staff",
        "missing_privacy",
        "duplicate",
        "expression",
        "duration",
        "component",
    ],
)
def test_v6_actual_loaded_staff_and_privacy_rules_are_required(monitoring_host, fault):
    host, module = monitoring_host
    host.plan["schema"] = "deployment-plan-v6"
    raw = (ROOT / ALERTS).read_bytes()
    host._run = lambda args, *_a, **_k: args[-1].encode()
    expected = host._monitoring_expected_rules({"Id": "a" * 64}, raw)
    host.baseline["monitoring"]["expected_rules"] = expected
    staff_name = "StaffPilotWatchdogMissingOrFailed"
    rules = [
        {
            "name": name,
            **proof,
            "health": "ok",
            "duration": 120,
            "labels": {
                "severity": "warning" if name == "PrivacyRetentionHeld" else "critical",
                "component": "monitoring",
            },
        }
        for name, proof in expected.items()
    ]
    staff = next(r for r in rules if r["name"] == staff_name)
    if fault == "missing_staff":
        rules.remove(staff)
    elif fault == "missing_privacy":
        rules.remove(
            next(r for r in rules if r["name"] == "PrivacyRetentionMetricsMissing")
        )
    elif fault == "duplicate":
        rules.append(copy.deepcopy(staff))
    elif fault == "expression":
        staff["query"] = "vector(0)"
    elif fault == "duration":
        staff["duration"] = 0
    elif fault == "component":
        staff["labels"]["component"] = "other"
    host._run = lambda args, label, **_k: (
        json.dumps(
            {"status": "success", "data": {"groups": [{"rules": rules}]}}
        ).encode()
        if label == "monitoring-loaded-rules"
        else args[-1].encode()
    )
    if fault:
        with pytest.raises(module.JournalError):
            host._monitoring_loaded_rules({"Id": "a" * 64})
    else:
        assert host._monitoring_loaded_rules({"Id": "a" * 64})
