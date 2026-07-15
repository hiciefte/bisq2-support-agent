"""Security invariants for GitHub Actions workflow configuration."""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW = WORKFLOW_DIR / "ci.yml"
ACTION_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _load_workflow(path: Path = CI_WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _workflow_paths(directory: Path = WORKFLOW_DIR) -> list[Path]:
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def _external_action_uses(workflow: dict) -> list[str]:
    action_uses: list[str] = []
    for job in workflow["jobs"].values():
        job_use = str(job.get("uses", ""))
        if job_use and not job_use.startswith("./"):
            action_uses.append(job_use)
        action_uses.extend(
            str(step["uses"])
            for step in job.get("steps", [])
            if "uses" in step and not str(step["uses"]).startswith("./")
        )
    return action_uses


def _assert_workflows_use_commit_pinned_actions(workflow_paths: list[Path]) -> None:
    checked_actions = 0
    for workflow_path in workflow_paths:
        for action_use in _external_action_uses(_load_workflow(workflow_path)):
            checked_actions += 1
            action, separator, ref = action_use.rpartition("@")
            assert (
                action and separator == "@" and ACTION_SHA_PATTERN.fullmatch(ref)
            ), f"{workflow_path.name}: {action_use}"
    assert checked_actions


def test_every_ci_checkout_disables_credential_persistence() -> None:
    workflow = _load_workflow()
    checkout_steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]

    assert checkout_steps
    for step in checkout_steps:
        assert step.get("with", {}).get("persist-credentials") is False


def test_every_external_action_in_every_workflow_is_pinned_to_a_commit() -> None:
    _assert_workflows_use_commit_pinned_actions(_workflow_paths())


@pytest.mark.parametrize("mutable_ref", ["actions/checkout@v4", "owner/action@main"])
def test_action_pin_check_rejects_mutable_refs(
    tmp_path: Path, mutable_ref: str
) -> None:
    workflow = tmp_path / "mutable.yaml"
    workflow.write_text(
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: {mutable_ref}\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match=re.escape(mutable_ref)):
        _assert_workflows_use_commit_pinned_actions(_workflow_paths(tmp_path))


def test_security_job_scans_the_built_production_images() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["security"]["steps"]
    build_commands = "\n".join(str(step.get("run", "")) for step in steps)
    expected_images = {
        "bisq-support-agent-api:ci",
        "bisq-support-agent-web:ci",
    }

    for image in expected_images:
        assert f"--tag {image}" in build_commands

    scan_steps = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("aquasecurity/trivy-action@")
    ]
    assert {step["with"]["image-ref"] for step in scan_steps} == expected_images
    for step in scan_steps:
        assert step["with"]["scan-type"] == "image"
        assert "scan-ref" not in step["with"]
