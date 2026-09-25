"""Exercise the workflow's actual preparation fingerprint without network calls."""

import json
import subprocess
from pathlib import Path

import yaml
from app.scripts import refresh_release_evidence

WORKFLOW = Path(__file__).parents[4] / ".github/workflows/release-evidence.yml"


def test_discovery_fingerprint_changes_for_retag_and_preparation_checks_it(
    tmp_path, monkeypatch
):
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["prepare"]["steps"]
    discovery = next(step["run"] for step in steps if step.get("id") == "discovery")
    code = discovery.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    compiled = compile(code, str(WORKFLOW), "exec")
    root = Path(__file__).parents[4]
    files = [
        "api/app/scripts/refresh_release_evidence.py",
        "api/app/services/rag/code_evidence.py",
        "api/app/services/rag/code_evidence_extractor.py",
        "api/app/services/rag/code_evidence_recipes.json",
        "api/app/services/rag/release_notes.py",
        "api/app/services/rag/interfaces.py",
        "api/app/services/rag/source_refs.py",
    ]
    monkeypatch.setattr(
        refresh_release_evidence,
        "fetch_releases",
        lambda repo: [
            {
                "tag_name": "v1.10.8" if repo == "bisq" else "v2.1.13",
                "body": "Public notes",
                "published_at": "2026-09-01T00:00:00Z",
                "html_url": "https://github.com/bisq-network/" + repo,
            }
        ],
    )
    keys = []
    for index, commit in enumerate(["a" * 40, "b" * 40]):
        path = tmp_path / str(index)
        path.mkdir()
        for name in files:
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / name).read_bytes())
        monkeypatch.chdir(path)
        monkeypatch.setenv("GITHUB_OUTPUT", str(path / "outputs"))

        def refs(argv, **kwargs):
            assert argv[:2] == ["git", "ls-remote"]
            assert kwargs["timeout"] == 60
            return f"{'f' * 40}\t{argv[-2]}\n{commit}\t{argv[-1]}\n"

        monkeypatch.setattr(subprocess, "check_output", refs)
        exec(compiled, {})
        keys.append((path / "outputs").read_text())
        bound = json.loads((path / "release-discovery/tag-commits.json").read_text())
        assert set(bound.values()) == {commit}
    assert keys[0] != keys[1]
    preparation = next(
        step["run"]
        for step in steps
        if step.get("name") == "Prepare exact release code and notes"
    )
    guard = preparation.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    (path / "prepared-release-evidence").mkdir()
    (path / "prepared-release-evidence/coverage.json").write_text(
        json.dumps(
            {
                "coverage": [
                    {
                        "repo": key.split(":")[0],
                        "tag": key.split(":")[1],
                        "commit": "a" * 40,
                    }
                    for key in bound
                ]
            }
        )
    )
    import pytest

    with pytest.raises(ValueError, match="tag changed"):
        exec(compile(guard, str(WORKFLOW), "exec"), {})
