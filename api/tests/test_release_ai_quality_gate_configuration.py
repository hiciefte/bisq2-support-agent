from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/ai-quality-gate.yml"
OVERLAY = REPO_ROOT / "docker/docker-compose.ai-quality.yml"
VERIFIER = REPO_ROOT / "scripts/verify-release-ai-quality-gate.sh"
DEPLOY = REPO_ROOT / "scripts/deploy.sh"
UPDATE = REPO_ROOT / "scripts/update.sh"
GIT_UTILS = REPO_ROOT / "scripts/lib/git-utils.sh"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
BISQ_DOCKERIGNORE = REPO_ROOT / "docker/bisq2-api/.dockerignore"
GITIGNORE = REPO_ROOT / ".gitignore"
EMPTY_OFFERBOOK_FIXTURE = (
    REPO_ROOT
    / "api/data/evaluation/release_ai_quality_stub/api/v1/offerbook/markets/EUR/offers"
)
PROTECTION_RUNBOOK = REPO_ROOT / "docs/runbooks/release-ai-quality-protection.md"
ENVIRONMENT_PAYLOAD = REPO_ROOT / "docs/runbooks/release-ai-quality-environment.json"
RELEASE_BRANCH_LIFECYCLE = (
    REPO_ROOT / "docs/runbooks/release-ai-quality-release-branch-lifecycle.json"
)
RELEASE_BRANCH_CHANGES = (
    REPO_ROOT / "docs/runbooks/release-ai-quality-release-branch-changes.json"
)
VERSION_TAG_RULESET = REPO_ROOT / "docs/runbooks/release-ai-quality-version-tags.json"
MARKER_TAG_RULESET = REPO_ROOT / "docs/runbooks/release-ai-quality-marker-tags.json"


def _git(repo: Path, *args: str) -> str:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _model_hash(model_id: str) -> str:
    return hashlib.sha256(model_id.encode("utf-8")).hexdigest()


def _run_verifier(
    repo: Path,
    commit: str,
    *,
    model_id: str = "openai:release-model",
    env_text: str | None = None,
    workflow_runs: list[dict[str, object]] | None = None,
    curl_succeeds: bool = True,
) -> subprocess.CompletedProcess[str]:
    env_file = repo / ".git/release-test.env"
    env_file.write_text(
        env_text if env_text is not None else f"OPENAI_MODEL={model_id}\n",
        encoding="utf-8",
    )
    runs = workflow_runs
    if runs is None:
        runs = [
            {
                "head_sha": commit,
                "event": "push",
                "head_branch": "release/candidate",
                "run_number": 1,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
            }
        ]
    fixture = repo / ".git/workflow-runs.json"
    fixture.write_text(json.dumps({"workflow_runs": runs}), encoding="utf-8")
    bin_dir = repo / ".git/test-bin"
    bin_dir.mkdir(exist_ok=True)
    curl_stub = bin_dir / "curl"
    curl_stub.write_text(
        "#!/bin/sh\n"
        'if [ "${WORKFLOW_RUNS_CURL_FAIL:-false}" = true ]; then exit 22; fi\n'
        'exec cat "$WORKFLOW_RUNS_FIXTURE"\n',
        encoding="utf-8",
    )
    curl_stub.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["WORKFLOW_RUNS_FIXTURE"] = str(fixture)
    env["WORKFLOW_RUNS_CURL_FAIL"] = "false" if curl_succeeds else "true"
    return subprocess.run(
        [
            "bash",
            str(VERIFIER),
            "--repository",
            str(repo),
            "--commit",
            commit,
            "--env-file",
            str(env_file),
            "--repository-slug",
            "example/repository",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_workflow_is_release_bound_scheduled_and_not_in_pr_path() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '"release/*"' in workflow
    assert '"v*"' in workflow
    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "Fresh-Answer AI Quality Gate" in workflow
    assert "if: always()" in workflow
    assert "retention-days: 30" in workflow
    assert "group: release-ai-quality-${{ github.sha }}" in workflow
    assert "needs: invalidate-pass-marker" in workflow
    assert "Remove prior markers for this commit" in workflow
    assert "git/matching-refs/tags/release-ai-quality/${GITHUB_SHA}" in workflow
    assert 'marker="release-ai-quality/${GITHUB_SHA}/${MODEL_SHA256}"' in workflow
    assert "Verify Version Tag AI Quality Gate" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow


def test_workflow_actions_are_commit_pinned_and_secret_is_narrowly_scoped() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", workflow)

    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)
    assert workflow.count("secrets.AI_QUALITY_GATE_OPENAI_API_KEY") == 1
    assert workflow.count("secrets.AI_QUALITY_GATE_MARKER_TOKEN") == 2
    assert workflow.count("environment: release-ai-quality") == 3
    assert "permissions:\n      contents: read" in workflow
    assert "contents: write" not in workflow

    build_index = workflow.index("Build release-candidate API image")
    runtime_config_index = workflow.index("Prepare isolated quality-gate environment")
    secret_index = workflow.index("secrets.AI_QUALITY_GATE_OPENAI_API_KEY")
    assert build_index < runtime_config_index < secret_index
    assert '"OPENAI_API_KEY": ""' in workflow
    assert "^openai:[A-Za-z0-9][A-Za-z0-9._-]{0,99}$" in workflow
    assert "up --no-build -d" in workflow

    version_tag_job = workflow[workflow.index("verify-version-tag:") :]
    assert "secrets.AI_QUALITY_GATE_OPENAI_API_KEY" not in version_tag_job
    assert "secrets.AI_QUALITY_GATE_MARKER_TOKEN" not in version_tag_job
    assert "environment: release-ai-quality" not in version_tag_job
    assert "GH_TOKEN: ${{ github.token }}" in version_tag_job


def test_docker_context_and_report_outputs_exclude_runtime_files() -> None:
    dockerignore = DOCKERIGNORE.read_text(encoding="utf-8")
    bisq_dockerignore = BISQ_DOCKERIGNORE.read_text(encoding="utf-8")
    gitignore = GITIGNORE.read_text(encoding="utf-8")

    assert "**/.env" in dockerignore
    assert "**/.env.*" in dockerignore
    assert "!**/.env.example" in dockerignore
    for build_contaminant in (
        "api/data/",
        "runtime_secrets/",
        "failed_updates/",
        "onion-keys/",
        "**/__pycache__/",
        "**/*.py[cod]",
        "web/node_modules/",
        "web/.next/",
    ):
        assert build_contaminant in dockerignore
    assert ".env" in bisq_dockerignore
    for build_contaminant in (
        "runtime_secrets/",
        "build/",
        "node_modules/",
        "**/__pycache__/",
        "**/*.py[cod]",
        "*.db",
        "logs/",
        ".git",
    ):
        assert build_contaminant in bisq_dockerignore
    assert "api/data/evaluation/release_ai_quality.summary.json" in gitignore


def test_workflow_clears_and_strictly_validates_report_before_upload() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    clear_index = workflow.index("Clear prior quality report")
    generate_index = workflow.index("Generate and score fresh answers")
    ensure_index = workflow.index("release_ai_quality_report.py ensure")
    upload_index = workflow.index("Archive sanitized quality report")
    require_index = workflow.index("release_ai_quality_report.py require-pass")
    assert clear_index < generate_index < ensure_index < upload_index < require_index
    ensure_block = workflow[
        workflow.index("Ensure a sanitized result exists") : upload_index
    ]
    upload_block = workflow[upload_index:require_index]
    assert "id: report_safety" in ensure_block
    assert "--model-sha256" in ensure_block
    assert (
        "if: ${{ always() && steps.report_safety.outcome == 'success' }}"
        in upload_block
    )
    assert "AI_QUALITY_GATE_OPENAI_MODEL" not in upload_block


def test_unsafe_prior_report_cannot_be_uploaded_when_safety_step_fails() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    upload_index = workflow.index("Archive sanitized quality report")
    require_index = workflow.index("Require a passing quality report")
    upload_block = workflow[upload_index:require_index]

    assert "if: always()\n" not in upload_block
    assert "steps.report_safety.outcome == 'success'" in upload_block
    assert "if-no-files-found: error" in upload_block


def test_quality_overlay_keeps_response_channels_disabled() -> None:
    overlay = OVERLAY.read_text(encoding="utf-8")

    for setting in (
        "MATRIX_SYNC_ENABLED",
        "MATRIX_CHATOPS_ENABLED",
        "BISQ2_CHANNEL_ENABLED",
        "BISQ2_CHATOPS_ENABLED",
        "ESCALATION_BISQ2_WS_ENABLED",
    ):
        assert f'{setting}: "false"' in overlay
    assert 'LLM_TEMPERATURE: "0"' in overlay
    assert 'ENABLE_BISQ_MCP_INTEGRATION: "true"' in overlay


def test_live_offerbook_fixture_is_a_successful_empty_inventory() -> None:
    assert json.loads(EMPTY_OFFERBOOK_FIXTURE.read_text(encoding="utf-8")) == []


def test_protection_payloads_scope_credentials_and_release_refs() -> None:
    environment = json.loads(ENVIRONMENT_PAYLOAD.read_text(encoding="utf-8"))
    lifecycle = json.loads(RELEASE_BRANCH_LIFECYCLE.read_text(encoding="utf-8"))
    changes = json.loads(RELEASE_BRANCH_CHANGES.read_text(encoding="utf-8"))
    version_tags = json.loads(VERSION_TAG_RULESET.read_text(encoding="utf-8"))
    marker_tags = json.loads(MARKER_TAG_RULESET.read_text(encoding="utf-8"))

    assert environment["prevent_self_review"] is True
    assert environment["reviewers"] == [{"type": "User", "id": 0}]
    assert environment["deployment_branch_policy"] == {
        "protected_branches": False,
        "custom_branch_policies": True,
    }

    assert lifecycle["target"] == "branch"
    assert lifecycle["enforcement"] == "active"
    assert lifecycle["conditions"]["ref_name"]["include"] == ["refs/heads/release/*"]
    assert lifecycle["bypass_actors"] == [
        {"actor_id": 0, "actor_type": "User", "bypass_mode": "always"}
    ]
    assert {rule["type"] for rule in lifecycle["rules"]} == {
        "creation",
        "deletion",
    }

    assert changes["bypass_actors"] == []
    change_rules = {rule["type"]: rule for rule in changes["rules"]}
    assert (
        change_rules["pull_request"]["parameters"]["required_approving_review_count"]
        == 1
    )
    assert (
        change_rules["pull_request"]["parameters"]["require_last_push_approval"] is True
    )
    status_parameters = change_rules["required_status_checks"]["parameters"]
    assert status_parameters["strict_required_status_checks_policy"] is True
    assert {
        item["context"] for item in status_parameters["required_status_checks"]
    } == {
        "Lint, Type Check & Test",
        "Frontend Lint, Type Check & Test",
        "Shell Lint & Deployment Tests",
        "Security Scan",
        "Offline Staff-Alignment Gate",
    }

    assert version_tags["target"] == "tag"
    assert version_tags["conditions"]["ref_name"]["include"] == ["refs/tags/v*"]
    assert marker_tags["target"] == "tag"
    assert marker_tags["conditions"]["ref_name"]["include"] == [
        "refs/tags/release-ai-quality/**/*"
    ]
    assert marker_tags["bypass_actors"][0]["actor_type"] == "User"
    assert {rule["type"] for rule in marker_tags["rules"]} == {
        "creation",
        "update",
        "deletion",
    }


def test_protection_runbook_renders_ids_and_uses_environment_secrets() -> None:
    runbook = PROTECTION_RUNBOOK.read_text(encoding="utf-8")

    assert "release-ai-quality-environment.json" in runbook
    assert ".reviewers[0].id = $id" in runbook
    assert ".bypass_actors[0].actor_id = $id" in runbook
    assert "gh secret set AI_QUALITY_GATE_OPENAI_API_KEY --env" in runbook
    assert "gh secret set AI_QUALITY_GATE_MARKER_TOKEN --env" in runbook
    assert "Never define either" in runbook
    assert "repository or organization secret" in runbook
    assert "deployment-branch-policies" in runbook
    assert '"repos/${OWNER}/${REPOSITORY}/rulesets"' in runbook


def test_remote_pass_marker_must_match_exact_release_commit(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()
    _git(remote, "init", "--bare")
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "CI")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "release.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release candidate")
    commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "origin", "HEAD:refs/heads/main")

    missing = _run_verifier(repo, commit)
    assert missing.returncode == 1
    assert "no matching AI-quality pass marker" in missing.stderr

    marker = f"release-ai-quality/{commit}/{_model_hash('openai:release-model')}"
    _git(repo, "tag", marker, commit)
    _git(repo, "push", "origin", f"refs/tags/{marker}")

    verified = _run_verifier(repo, commit)
    assert verified.returncode == 0, verified.stderr
    assert "pass marker verified" in verified.stdout

    mismatched_model = _run_verifier(repo, commit, model_id="openai:other-model")
    assert mismatched_model.returncode == 1
    assert "no matching AI-quality pass marker" in mismatched_model.stderr


def test_remote_pass_marker_rejects_dirty_release_tree(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()
    _git(remote, "init", "--bare")
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "CI")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "release.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release candidate")
    commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "origin", "HEAD:refs/heads/main")
    marker = f"release-ai-quality/{commit}/{_model_hash('openai:release-model')}"
    _git(repo, "tag", marker, commit)
    _git(repo, "push", "origin", f"refs/tags/{marker}")

    (repo / "release.txt").write_text("locally changed\n", encoding="utf-8")
    tracked = _run_verifier(repo, commit)
    assert tracked.returncode == 1
    assert "build tree differs" in tracked.stderr

    _git(repo, "restore", "release.txt")
    (repo / "untracked-source.txt").write_text("local input\n", encoding="utf-8")
    untracked = _run_verifier(repo, commit)
    assert untracked.returncode == 1
    assert "untracked inputs" in untracked.stderr


def test_remote_pass_marker_requires_latest_successful_workflow_run(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()
    _git(remote, "init", "--bare")
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "CI")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "release.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release candidate")
    commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "origin", "HEAD:refs/heads/main")
    marker = f"release-ai-quality/{commit}/{_model_hash('openai:release-model')}"
    _git(repo, "tag", marker, commit)
    _git(repo, "push", "origin", f"refs/tags/{marker}")
    successful = {
        "head_sha": commit,
        "event": "push",
        "head_branch": "release/candidate",
        "run_number": 1,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    failed = {
        **successful,
        "run_number": 2,
        "conclusion": "failure",
    }

    stale_marker = _run_verifier(repo, commit, workflow_runs=[successful, failed])
    assert stale_marker.returncode == 1
    assert "Latest AI-quality workflow run is not successful" in stale_marker.stderr

    tag_only = _run_verifier(
        repo,
        commit,
        workflow_runs=[
            {
                **successful,
                "head_branch": "v1.0.0",
                "run_number": 3,
            }
        ],
    )
    assert tag_only.returncode == 1
    assert "No authoritative AI-quality workflow run" in tag_only.stderr

    unavailable = _run_verifier(repo, commit, curl_succeeds=False)
    assert unavailable.returncode == 1
    assert "Could not verify the authoritative" in unavailable.stderr


def test_remote_pass_marker_rejects_unsafe_or_ambiguous_runtime_model(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    remote.mkdir()
    repo.mkdir()
    _git(remote, "init", "--bare")
    _git(repo, "init")
    _git(repo, "config", "user.email", "ci@example.invalid")
    _git(repo, "config", "user.name", "CI")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "release.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release candidate")
    commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "remote", "add", "origin", str(remote))

    interpolated = _run_verifier(
        repo,
        commit,
        env_text="OPENAI_MODEL=${OPENAI_API_KEY}\n",
    )
    assert interpolated.returncode == 1
    assert "runtime model ID is invalid" in interpolated.stderr
    assert "OPENAI_API_KEY" not in interpolated.stderr

    duplicate = _run_verifier(
        repo,
        commit,
        env_text=(
            "OPENAI_MODEL=openai:release-model\n" "OPENAI_MODEL=openai:other-model\n"
        ),
    )
    assert duplicate.returncode == 1
    assert "must contain one model ID" in duplicate.stderr


def test_deploy_paths_verify_gate_before_build_or_restart() -> None:
    deploy = DEPLOY.read_text(encoding="utf-8")
    update = UPDATE.read_text(encoding="utf-8")
    git_utils = GIT_UTILS.read_text(encoding="utf-8")

    assert deploy.index("verify-release-ai-quality-gate.sh") < deploy.index(
        'run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" build'
    )
    assert deploy.index('check_command "jq"') < deploy.index(
        "verify-release-ai-quality-gate.sh"
    )
    assert deploy.index("apt-get install -y jq") < deploy.index(
        "verify-release-ai-quality-gate.sh"
    )
    assert deploy.index('update_env_var "BISQ_API_URL"') < deploy.index(
        "verify-release-ai-quality-gate.sh"
    )
    assert '--env-file "$DOCKER_DIR/.env"' in deploy
    assert '--env-file "$DOCKER_DIR/.env"' in update
    assert '--remote "${GIT_REMOTE:-origin}"' in deploy
    assert '--remote "$GIT_REMOTE"' in update
    main = update[update.index("main() {") :]
    assert main.index("ensure_release_source_tree_clean") < main.index(
        "validate_environment"
    )
    assert (
        'update_repository "$INSTALL_DIR" "$GIT_REMOTE" "$GIT_BRANCH" false' in update
    )
    assert "git ls-files --others --exclude-standard -z" in git_utils
    verifier_index = main.index("verify_release_ai_quality_gate")
    assert verifier_index < main.index('run_faq_migration "$INSTALL_DIR"')
    assert verifier_index < main.index("run_faq_sqlite_migration")
    assert verifier_index < main.index("analyze_changes")
    assert verifier_index < main.index("apply_updates")

    update_repository = git_utils[
        git_utils.index("update_repository() {") : git_utils.index(
            "# Function to check if a full rebuild is needed"
        )
    ]
    assert "run_faq_migration" not in update_repository
