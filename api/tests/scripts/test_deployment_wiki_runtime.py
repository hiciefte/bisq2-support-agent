"""Wiki source classification does not widen runtime deployment authority."""

import copy
import importlib
import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from test_deploy_release import assert_error, cli, commit, git, plan_args
from test_deploy_release import repository as repository_fixture

repository = repository_fixture
ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.unit
WIKI_MODULES = (
    "api/app/scripts/download_bisq2_media_wiki.py",
    "api/app/scripts/process_wiki_dump.py",
    "api/app/scripts/wiki_atomic.py",
    "api/app/scripts/wiki_text.py",
)


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return (
        importlib.import_module("deploy_release"),
        importlib.import_module("lib.deployment_host"),
    )


@pytest.mark.parametrize("published", [False, True])
@pytest.mark.parametrize("tamper", ["service", "diff", "unknown_script"])
def test_host_reclassifies_complete_wiki_delta(
    repository, tmp_path, modules, published, tamper
):
    planner, backend = modules
    root, previous = repository
    candidate = commit(
        root,
        {
            **{path: "SOURCE = 1\n" for path in WIKI_MODULES},
            "docker/web/Dockerfile": "FROM fixture\n",
        },
    )
    operation = tmp_path / "operation"
    result = cli(*plan_args(root, previous, candidate, operation, services="api,web"))
    assert result.returncode == 0, result.stderr
    plan = json.loads((operation / "plan.json").read_text())
    assert plan["services"] == ["api", "web"]
    assert plan["source"]["changed_paths_sha256"] == planner.digest(
        planner.encode(sorted([*WIKI_MODULES, "docker/web/Dockerfile"]))
    )
    install = tmp_path / "install"
    subprocess.run(["git", "clone", "--quiet", str(root), str(install)], check=True)
    git(install, "checkout", "--quiet", candidate if published else previous)
    host = backend.DeploymentHost.__new__(backend.DeploymentHost)
    host.plan, host.install, host.candidate = plan, install, root
    host._git = lambda path, *args: git(path, *args).decode().strip()
    host._source(published=published)

    if tamper == "service":
        plan["services"] = ["web"]
        expected = "host_source_scope"
    elif tamper == "diff":
        plan["source"]["changed_paths_sha256"] = "0" * 64
        expected = "host_source_diff"
    else:
        candidate = commit(root, {"api/app/scripts/rebuild.py": "SOURCE = 2\n"})
        git(install, "fetch", "--quiet", str(root), candidate)
        if published:
            git(install, "checkout", "--quiet", candidate)
        # An attacker cannot authorize an extra script by supplying a coherent
        # tree/diff digest; the host independently applies the exact allowlist.
        plan["source"].update(
            candidate_commit=candidate,
            candidate_tree=git(root, "rev-parse", candidate + "^{tree}")
            .decode()
            .strip(),
            changed_paths_sha256=planner.digest(
                planner.encode(planner.changed_paths(root, previous, candidate))
            ),
        )
        expected = "unsupported_change_scope"
    with pytest.raises(backend.JournalError, match=expected):
        host._source(published=published)


@pytest.mark.parametrize("path", WIKI_MODULES)
def test_wiki_module_symlink_is_not_an_api_source_exception(repository, tmp_path, path):
    root, previous = repository
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to("../example.py")
    candidate = commit(root, {"docs/note.md": "Fixture\n"})
    operation = tmp_path / "operation"
    assert_error(
        cli(*plan_args(root, previous, candidate, operation)),
        "unsupported_source_entry",
    )
    assert not operation.exists()


@pytest.mark.parametrize("enabled_field", ["sync", "generation"])
def test_wiki_classification_keeps_active_pilot_refusal(
    tmp_path, modules, enabled_field
):
    planner, backend = modules
    assert planner.classify_services(list(WIKI_MODULES)) == ["api"]
    host = backend.DeploymentHost.__new__(backend.DeploymentHost)
    host.install = tmp_path
    data = tmp_path / "api/data"
    data.mkdir(parents=True)
    with closing(sqlite3.connect(data / "feedback.db")) as db:
        db.execute(
            "CREATE TABLE channel_autoresponse_policy "
            "(channel_id TEXT, enabled INTEGER, generation_enabled INTEGER)"
        )
        db.executemany(
            "INSERT INTO channel_autoresponse_policy VALUES (?, 0, 0)",
            [("matrix",), ("bisq2",)],
        )
        db.execute(
            "CREATE TABLE channel_launch_global "
            "(singleton_id INTEGER, autonomous_delivery_enabled INTEGER)"
        )
        db.execute("INSERT INTO channel_launch_global VALUES (1, 0)")
        db.commit()
    containers = {
        "api": {
            "Config": {
                "Env": ["DATA_DIR=/data"]
                + [flag + "=false" for flag in backend.DISABLED_FLAGS]
            }
        }
    }
    host._disabled(containers)
    active = copy.deepcopy(containers)
    if enabled_field == "sync":
        active["api"]["Config"]["Env"].remove("MATRIX_SYNC_ENABLED=false")
        active["api"]["Config"]["Env"].append("MATRIX_SYNC_ENABLED=true")
        expected = "host_channels_enabled"
    else:
        with closing(sqlite3.connect(data / "feedback.db")) as db:
            db.execute(
                "UPDATE channel_autoresponse_policy SET generation_enabled=1 "
                "WHERE channel_id='matrix'"
            )
            db.commit()
        expected = "host_generation_enabled"
    before = (data / "feedback.db").read_bytes()
    with pytest.raises(backend.JournalError, match=expected):
        host._disabled(active)
    assert (data / "feedback.db").read_bytes() == before
