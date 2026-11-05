"""Explicit existing-heap reconciliation; real Git with no live services."""

import copy
import importlib
import json
import subprocess
from pathlib import Path

import pytest
from test_deploy_release import assert_error, cli, commit, git, plan_args
from test_deploy_release import repository as repository_fixture
from test_deployment_protocol import protocol as protocol_fixture
from test_deployment_protocol import records as records_fixture

repository = repository_fixture
protocol = protocol_fixture
records = records_fixture
pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[3]
OLD = {
    "docker/docker-compose.yml": "services:\n  bisq2-api:\n    environment:\n      - JAVA_OPTS=-Xmx1g\n",
    "docker/bisq2-api/Dockerfile": 'FROM fixture\nENV JAVA_OPTS="-Xmx1g"\n',
    "docker/.env.example": "BISQ_USER_RATE_LIMIT_ENABLED=true\n",
}
NEW = {
    "docker/docker-compose.yml": "services:\n  bisq2-api:\n    environment:\n      # Leave room within the 4G limit for native memory, threads and Tor.\n      - JAVA_OPTS=${BISQ2_JAVA_OPTS:--Xmx2g -XX:+ExitOnOutOfMemoryError}\n",
    "docker/bisq2-api/Dockerfile": 'FROM fixture\nENV JAVA_OPTS="-Xmx2g -XX:+ExitOnOutOfMemoryError"\n',
    "docker/.env.example": 'BISQ_USER_RATE_LIMIT_ENABLED=true\n# JVM options for the containerized Bisq2 node (not the support API).\n# Keep heap below its 4G container limit; retain exit-on-OOM for Docker recovery.\nBISQ2_JAVA_OPTS="-Xmx2g -XX:+ExitOnOutOfMemoryError"\n',
}


@pytest.fixture
def repaired(repository, tmp_path):
    root, _previous = repository
    previous = commit(root, OLD)
    candidate = commit(root, NEW | {"api/app/example.py": "NEW = 2\n"})
    operation = tmp_path / "operation"
    result = cli(
        *plan_args(root, previous, candidate, operation), "--preserve-bisq2-heap-repair"
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((operation / "plan.json").read_text())
    return root, previous, candidate, plan


def test_plan_pins_fixed_patch_and_preserves_full_diff(repaired, protocol):
    root, previous, candidate, plan = repaired
    assert plan["schema"] == "deployment-plan-v4"
    assert plan["kind"] == "selective-api-web-preserved-heap-v1"
    assert plan["tooling_sha256"] == {}
    assert plan["preserved_heap_sha256"] == {
        p: protocol.digest(c.encode()) for p, c in NEW.items()
    }
    assert plan["source"]["changed_paths_sha256"] == protocol.digest(
        importlib.import_module("deploy_release").encode(
            sorted([*NEW, "api/app/example.py"])
        )
    )
    assert plan["services"] == ["api"]
    protocol.validate_plan(plan)


@pytest.mark.parametrize(
    "fault",
    ["unknown_compose", "wrong_heap", "missing_file", "extra_path", "no_service"],
)
def test_option_does_not_admit_arbitrary_operations(repository, tmp_path, fault):
    root, _ = repository
    previous = commit(root, OLD)
    changes = NEW | {"api/app/example.py": "NEW = 2\n"}
    if fault == "unknown_compose":
        changes["docker/docker-compose.yml"] += "extra: service\n"
    elif fault == "wrong_heap":
        changes["docker/bisq2-api/Dockerfile"] = changes[
            "docker/bisq2-api/Dockerfile"
        ].replace("2g", "4g")
    elif fault == "missing_file":
        del changes["docker/.env.example"]
    elif fault == "extra_path":
        changes["docker/prometheus/alert_rules.yml"] = "unreviewed\n"
    else:
        del changes["api/app/example.py"]
    candidate = commit(root, changes)
    operation = tmp_path / "operation"
    result = cli(
        *plan_args(root, previous, candidate, operation), "--preserve-bisq2-heap-repair"
    )
    assert result.returncode == 2
    assert not operation.exists()


def test_default_and_tooling_capabilities_still_refuse_heap_changes(repaired, tmp_path):
    root, previous, candidate, _ = repaired
    for i, flags in enumerate([[], ["--include-deployment-tooling"]]):
        assert_error(
            cli(
                *plan_args(root, previous, candidate, tmp_path / f"default{i}"), *flags
            ),
            "unsupported_change_scope",
        )


def heap_records(records, protocol):
    plan, profile, approval = copy.deepcopy(records)
    plan.update(
        schema="deployment-plan-v4",
        kind="selective-api-web-preserved-heap-v1",
        tooling_sha256={},
        preserved_heap_sha256={p: protocol.digest(c.encode()) for p, c in NEW.items()},
    )
    approval.update(
        schema="deployment-approval-v4",
        tooling_sha256={},
        preserved_heap_sha256=copy.deepcopy(plan["preserved_heap_sha256"]),
        plan_sha256=protocol.canonical_sha256(plan),
    )
    return plan, profile, approval


def test_approval_and_receipt_require_explicit_heap_scope(records, protocol):
    plan, profile, approval = heap_records(records, protocol)
    protocol.validate_approval(approval, plan, profile)
    assert (
        protocol.effect_guard(
            plan, profile, approval, "publish_source", "2026-01-01T10:02:00+00:00"
        )
        > 0
    )
    for change in ["missing", "hash", "old_schema"]:
        bad = copy.deepcopy(approval)
        if change == "missing":
            bad.pop("preserved_heap_sha256")
        elif change == "hash":
            bad["preserved_heap_sha256"]["docker/docker-compose.yml"] = "a" * 64
        else:
            bad["schema"] = "deployment-approval-v3"
        with pytest.raises(protocol.JournalError):
            protocol.validate_approval(bad, plan, profile)
    payload = {
        k: plan["source"][k]
        for k in ("candidate_commit", "candidate_tree", "previous_commit")
    }
    payload.update(source_clean=True, unrelated_preserved=True)
    with pytest.raises(protocol.JournalError, match="receipt_payload"):
        protocol._validate_payload("publish_source", payload, plan)
    payload["preserved_heap_reconciled"] = True
    protocol._validate_payload("publish_source", payload, plan)
    payload["preserved_heap_reconciled"] = False
    with pytest.raises(protocol.JournalError):
        protocol._validate_payload("publish_source", payload, plan)


@pytest.fixture
def source_host(repaired, tmp_path, monkeypatch, protocol):
    root, previous, _candidate, plan = repaired
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("lib.deployment_host")
    install = tmp_path / "install"
    subprocess.run(["git", "clone", "--quiet", str(root), str(install)], check=True)
    git(install, "checkout", "--quiet", "--detach", previous)
    (install / "docker/docker-compose.yml").write_text(NEW["docker/docker-compose.yml"])
    host = module.DeploymentHost.__new__(module.DeploymentHost)
    host.plan = plan
    host.approval = {
        "tooling_sha256": {},
        "preserved_heap_sha256": copy.deepcopy(plan["preserved_heap_sha256"]),
    }
    host.install, host.candidate = install, root
    host._git = lambda path, *args: git(path, *args).decode().strip()
    host._configuration = lambda: None
    host._inspect = lambda: {}
    host._preserved = lambda _containers: None
    return host, module


def test_publish_adopts_only_matching_blob_without_rewriting_compose(source_host):
    host, _module = source_host
    compose = host.install / "docker/docker-compose.yml"
    before = compose.stat(), compose.read_bytes()
    host._source()
    result = host._publish()
    assert result["preserved_heap_reconciled"] is True
    assert host._git(host.install, "status", "--porcelain") == ""
    assert (
        host._git(host.install, "rev-parse", "HEAD")
        == host.plan["source"]["candidate_commit"]
    )
    after = compose.stat(), compose.read_bytes()
    assert before[1] == after[1]
    # Git does not rewrite a worktree file already matching the staged target.
    assert before[0].st_ino == after[0].st_ino
    assert before[0].st_mtime_ns == after[0].st_mtime_ns
    host._source(published=True)


@pytest.mark.parametrize(
    "fault",
    [
        "extra_dirty",
        "staged",
        "wrong_compose",
        "symlink",
        "index_flag",
        "candidate_dirty",
        "approval",
    ],
)
def test_host_refuses_unapproved_source_drift(source_host, fault):
    host, module = source_host
    if fault == "extra_dirty":
        (host.install / "api/app/example.py").write_text("unknown\n")
    elif fault == "staged":
        git(host.install, "add", "docker/docker-compose.yml")
    elif fault == "wrong_compose":
        (host.install / "docker/docker-compose.yml").write_text("unknown\n")
    elif fault == "symlink":
        (host.install / "docker/docker-compose.yml").unlink()
        (host.install / "docker/docker-compose.yml").symlink_to(
            host.candidate / "docker/docker-compose.yml"
        )
    elif fault == "index_flag":
        git(host.install, "update-index", "--assume-unchanged", "api/app/example.py")
    elif fault == "candidate_dirty":
        (host.candidate / "api/app/example.py").write_text("unknown\n")
    else:
        host.approval["preserved_heap_sha256"]["docker/docker-compose.yml"] = "f" * 64
    with pytest.raises(module.JournalError):
        host._source()


def test_publish_partial_index_adoption_cannot_restart_as_unattempted(source_host):
    host, module = source_host
    original_git = host._git

    def fail_merge(path, *args):
        if args[0] == "merge":
            raise module.HostCommandError("injected_publish_failure", uncertain=True)
        return original_git(path, *args)

    host._git = fail_merge
    with pytest.raises(module.HostCommandError):
        host._publish()
    assert (
        original_git(host.install, "rev-parse", "HEAD")
        == host.plan["source"]["previous_commit"]
    )
    assert (
        original_git(host.install, "diff", "--cached", "--name-only")
        == "docker/docker-compose.yml"
    )
    with pytest.raises(module.JournalError, match="host_heap_source_dirty"):
        host._source()


@pytest.mark.parametrize("fault", [None, "options", "memory", "restart", "duplicate"])
def test_runtime_requires_actual_existing_repair(source_host, fault):
    host, module = source_host
    node = {
        "Config": {"Env": ["JAVA_OPTS=-Xmx2g -XX:+ExitOnOutOfMemoryError"]},
        "HostConfig": {"Memory": 4294967296, "RestartPolicy": {"Name": "always"}},
    }
    if fault == "options":
        node["Config"]["Env"] = ["JAVA_OPTS=-Xmx1g"]
    elif fault == "memory":
        node["HostConfig"]["Memory"] = 1
    elif fault == "restart":
        node["HostConfig"]["RestartPolicy"]["Name"] = "no"
    elif fault == "duplicate":
        node["Config"]["Env"] *= 2
    if fault is None:
        host._heap_runtime({"bisq2-api": node})
    else:
        with pytest.raises(module.JournalError):
            host._heap_runtime({"bisq2-api": node})
