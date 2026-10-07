"""Exact opt-in tooling promotion with real local Git, no production effects."""

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


def promoted_records(records, protocol):
    plan, profile, approval = copy.deepcopy(records)
    plan.update(
        schema="deployment-plan-v3",
        kind="selective-api-web-with-tooling-v1",
        tooling_sha256={"scripts/update.sh": "9" * 64},
        services=["web"],
        phases=protocol.phases_for(["web"]),
    )
    approval.update(
        schema="deployment-approval-v3",
        tooling_sha256=copy.deepcopy(plan["tooling_sha256"]),
        plan_sha256=protocol.canonical_sha256(plan),
        phases=plan["phases"],
        image_consumers={"web": ["web"]},
        smoke_calls=[],
    )
    return plan, profile, approval


def test_default_refuses_every_allowed_tool(repository, tmp_path, protocol):
    root, previous = repository
    candidate = commit(
        root,
        {
            "web/package.json": "{}\n",
            **{p: "fixture\n" for p in protocol.DEPLOYMENT_TOOLING},
        },
    )
    for path in protocol.DEPLOYMENT_TOOLING:
        module = importlib.import_module("deploy_release")
        with pytest.raises(protocol.JournalError, match="unsupported_change_scope"):
            module.classify_services(["web/package.json", path])
    assert_error(
        cli(
            *plan_args(
                root, previous, candidate, tmp_path / "operation", services="web"
            )
        ),
        "unsupported_change_scope",
    )


def test_opt_in_pins_exact_candidate_blobs_and_full_diff(
    repository, tmp_path, protocol
):
    root, previous = repository
    changes = {
        "web/package.json": "{}\n",
        "docs/promotion.md": "fixture\n",
        **{path: path + "\n" for path in protocol.DEPLOYMENT_TOOLING},
    }
    candidate = commit(root, changes)
    # Pins use immutable objects rather than potentially dirty worktree content.
    (root / "scripts/update.sh").write_text("uncommitted local content\n")
    operation = tmp_path / "operation"
    result = cli(
        *plan_args(root, previous, candidate, operation, services="web"),
        "--include-deployment-tooling",
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads((operation / "plan.json").read_text())
    assert plan["schema"] == "deployment-plan-v3"
    assert plan["kind"] == "selective-api-web-with-tooling-v1"
    assert plan["tooling_sha256"] == {
        path: protocol.digest(contents.encode())
        for path, contents in changes.items()
        if path in protocol.DEPLOYMENT_TOOLING
    }
    module = importlib.import_module("deploy_release")
    assert plan["source"]["changed_paths_sha256"] == module.digest(
        module.encode(sorted(changes))
    )
    assert plan["phases"] == protocol.phases_for(["web"])
    assert all(not p.startswith("smoke_") for p in plan["phases"])
    assert json.loads(result.stdout)["execution_supported"] is True


@pytest.mark.parametrize(
    "extra",
    ["scripts/ops.sh", "docker/docker-compose.yml", "api/app/db/migrations/new.sql"],
)
def test_opt_in_still_refuses_unknown_operations(repository, tmp_path, extra):
    root, previous = repository
    candidate = commit(
        root,
        {
            "web/package.json": "{}\n",
            "scripts/update.sh": "fixture\n",
            extra: "fixture\n",
        },
    )
    operation = tmp_path / "operation"
    assert_error(
        cli(
            *plan_args(root, previous, candidate, operation, services="web"),
            "--include-deployment-tooling",
        ),
        "unsupported_change_scope",
    )
    assert not operation.exists()


@pytest.mark.parametrize("change", ["tooling_only", "no_tooling", "deleted", "symlink"])
def test_opt_in_requires_source_and_regular_present_tooling(
    repository, tmp_path, change
):
    root, previous = repository
    if change in {"deleted", "symlink"}:
        previous = commit(root, {"scripts/update.sh": "fixture\n"})
    changes = {"scripts/update.sh": "fixture2\n"}
    expected = "no_service_source_changes"
    if change != "tooling_only":
        changes["web/package.json"] = "{}\n"
    if change == "no_tooling":
        del changes["scripts/update.sh"]
        expected = "no_deployment_tooling_changes"
    elif change == "deleted":
        changes["scripts/update.sh"] = None
        expected = "unsupported_tooling_entry"
    candidate = commit(root, changes)
    if change == "symlink":
        (root / "scripts/update.sh").unlink()
        (root / "scripts/update.sh").symlink_to("../web/package.json")
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
            "Symlink fixture",
        )
        candidate = git(root, "rev-parse", "HEAD").decode().strip()
        expected = "unsupported_source_entry"
    operation = tmp_path / "operation"
    assert_error(
        cli(
            *plan_args(root, previous, candidate, operation, services="web"),
            "--include-deployment-tooling",
        ),
        expected,
    )
    assert not operation.exists()


def test_v3_approval_binds_explicit_capability_and_preserves_v2(records, protocol):
    plan, profile, approval = promoted_records(records, protocol)
    protocol.validate_approval(approval, plan, profile)
    assert (
        protocol.effect_guard(
            plan, profile, approval, "build", "2026-01-01T10:02:00+00:00"
        )
        > 0
    )
    protocol.validate_approval(records[2], records[0], records[1])
    for mutation, expected in [
        (lambda a: a.pop("tooling_sha256"), "approval_schema"),
        (lambda a: a.update(schema="deployment-approval-v2"), "approval_binding"),
        (lambda a: a.update(tooling_sha256={}), "approval_tooling"),
        (
            lambda a: a["tooling_sha256"].update({"scripts/update.sh": "8" * 64}),
            "approval_tooling",
        ),
        (lambda a: a.update(extra=True), "approval_schema"),
    ]:
        altered = copy.deepcopy(approval)
        mutation(altered)
        with pytest.raises(protocol.JournalError, match=expected):
            protocol.validate_approval(altered, plan, profile)
    ordinary = copy.deepcopy(records[2])
    ordinary["tooling_sha256"] = plan["tooling_sha256"]
    with pytest.raises(protocol.JournalError, match="approval_schema"):
        protocol.validate_approval(ordinary, records[0], profile)


@pytest.mark.parametrize(
    "tooling", [{}, {"scripts/ops.sh": "9" * 64}, {"scripts/update.sh": "bad"}, []]
)
def test_v3_plan_refuses_invalid_tooling_capability(records, protocol, tooling):
    plan, _, _ = promoted_records(records, protocol)
    plan["tooling_sha256"] = tooling
    with pytest.raises(protocol.JournalError, match="release_tooling"):
        protocol.validate_plan(plan)


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("tamper", ["hash", "omitted", "added", "worktree", "approval"])
def test_host_rederives_exact_tooling_before_effects_and_publication(
    repository, tmp_path, records, protocol, monkeypatch, published, tamper
):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    planner = importlib.import_module("deploy_release")
    module = importlib.import_module("lib.deployment_host")
    root, previous = repository
    candidate = commit(
        root,
        {
            "web/package.json": "{}\n",
            "scripts/update.sh": "fixture\n",
            "scripts/backup.sh": "backup\n",
        },
    )
    plan, _, approval = promoted_records(records, protocol)
    paths = planner.changed_paths(root, previous, candidate)
    plan["source"] = {
        "candidate_commit": candidate,
        "candidate_tree": git(root, "rev-parse", candidate + "^{tree}")
        .decode()
        .strip(),
        "previous_commit": previous,
        "previous_tree": git(root, "rev-parse", previous + "^{tree}").decode().strip(),
        "changed_paths_sha256": planner.digest(planner.encode(paths)),
    }
    plan["tooling_sha256"] = planner.tooling_hashes(root, candidate, paths)
    approval["tooling_sha256"] = copy.deepcopy(plan["tooling_sha256"])
    install = tmp_path / "install"
    subprocess.run(["git", "clone", "--quiet", str(root), str(install)], check=True)
    git(install, "checkout", "--quiet", candidate if published else previous)
    host = module.DeploymentHost.__new__(module.DeploymentHost)
    host.plan, host.approval, host.install, host.candidate = (
        plan,
        approval,
        install,
        root,
    )
    host._git = lambda path, *args: git(path, *args).decode().strip()
    host._source(published=published)
    expected = "host_source_tooling"
    if tamper == "hash":
        plan["tooling_sha256"]["scripts/update.sh"] = "8" * 64
    elif tamper == "omitted":
        del plan["tooling_sha256"]["scripts/backup.sh"]
    elif tamper == "added":
        plan["tooling_sha256"]["scripts/restore.sh"] = "8" * 64
    elif tamper == "worktree":
        (root / "scripts/update.sh").write_text("tampered\n")
        expected = "host_source_dirty"
    else:
        approval["tooling_sha256"]["scripts/update.sh"] = "8" * 64
        expected = "approval_tooling"
    with pytest.raises(module.JournalError, match=expected):
        host._source(published=published)
