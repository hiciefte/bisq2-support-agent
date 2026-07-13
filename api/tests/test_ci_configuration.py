"""Security invariants for GitHub Actions workflow configuration."""

from pathlib import Path

import yaml

CI_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_every_ci_checkout_disables_credential_persistence() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    checkout_steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("uses") == "actions/checkout@v4"
    ]

    assert checkout_steps
    for step in checkout_steps:
        assert step.get("with", {}).get("persist-credentials") is False
