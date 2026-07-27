"""Regression tests for immutable release inputs and repository governance."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yml"
LOCAL_COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.local.yml"
BRANCH_PROTECTION_PAYLOAD = REPO_ROOT / "docs" / "runbooks" / "branch-protection.json"
BRANCH_PROTECTION_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "branch-protection.md"
DIGEST_REF_PATTERN = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_production_uses_baked_api_source_and_local_keeps_bind_mount() -> None:
    production_api = _load_yaml(COMPOSE_PATH)["services"]["api"]
    local_api = _load_yaml(LOCAL_COMPOSE_PATH)["services"]["api"]
    api_dockerfile = (REPO_ROOT / "docker" / "api" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "../api/app:/app/app" not in production_api["volumes"]
    assert "../api/app:/app/app" in local_api["volumes"]
    assert "COPY api/app /app/app" in api_dockerfile


def test_production_registry_images_are_digest_pinned() -> None:
    services = _load_yaml(COMPOSE_PATH)["services"]
    locally_built_services = {"api", "matrix-alert-relay"}
    registry_images = {
        name: service["image"]
        for name, service in services.items()
        if "image" in service and name not in locally_built_services
    }

    assert registry_images
    for service_name, image in registry_images.items():
        assert DIGEST_REF_PATTERN.fullmatch(image), service_name

    assert services["api"]["image"] == services["matrix-alert-relay"]["image"]
    assert "build" in services["api"]
    assert services["api"]["pull_policy"] == "never"
    assert services["matrix-alert-relay"]["pull_policy"] == "never"


def test_production_dockerfile_base_images_are_digest_pinned() -> None:
    dockerfiles = (
        REPO_ROOT / "docker" / "api" / "Dockerfile",
        REPO_ROOT / "docker" / "web" / "Dockerfile",
        REPO_ROOT / "docker" / "bisq2-api" / "Dockerfile",
    )

    for dockerfile in dockerfiles:
        from_refs = [
            line.split()[1]
            for line in dockerfile.read_text(encoding="utf-8").splitlines()
            if line.startswith("FROM ")
        ]
        assert from_refs, dockerfile.name
        for image in from_refs:
            assert DIGEST_REF_PATTERN.fullmatch(image), f"{dockerfile.name}: {image}"


def test_api_builder_pins_setuptools_after_application_dependencies() -> None:
    dockerfile = (REPO_ROOT / "docker" / "api" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    builder = dockerfile.split("# --- Development Stage ---", maxsplit=1)[0]

    requirements_install = "pip install --no-cache-dir -r requirements.txt"
    setuptools_install = "pip install --no-cache-dir setuptools==83.0.0"

    assert requirements_install in builder
    assert setuptools_install in builder
    assert builder.index(requirements_install) < builder.index(setuptools_install)

    final = dockerfile.split("# --- Final Stage ---", maxsplit=1)[1]
    base_cleanup = "RUN pip uninstall --yes setuptools"
    builder_copy = (
        "COPY --from=builder /usr/local/lib/python3.11/site-packages "
        "/usr/local/lib/python3.11/site-packages"
    )
    assert base_cleanup in final
    assert builder_copy in final
    assert final.index(base_cleanup) < final.index(builder_copy)


def test_web_image_contains_only_pinned_fixed_runtime_dependencies() -> None:
    dockerfile = (REPO_ROOT / "docker" / "web" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    compose_web = _load_yaml(COMPOSE_PATH)["services"]["web"]
    builder, runtime = dockerfile.split("# Stage 2: Runtime", maxsplit=1)

    assert "RUN npm run build" in builder
    assert "RUN npm prune --omit=dev" in builder
    assert builder.index("RUN npm run build") < builder.index(
        "RUN npm prune --omit=dev"
    )

    assert "libcrypto3=3.5.7-r0" in runtime
    assert "libssl3=3.5.7-r0" in runtime
    assert "rm -rf /usr/local/lib/node_modules/npm" in runtime
    assert "rm -f /usr/local/bin/npm /usr/local/bin/npx" in runtime
    assert "npm install --global" not in runtime
    assert 'CMD ["node", "node_modules/next/dist/bin/next", "start"]' in runtime
    assert "command" not in compose_web


def test_bisq_build_fetches_and_verifies_a_full_commit() -> None:
    dockerfile = (REPO_ROOT / "docker" / "bisq2-api" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    commit = re.search(r"^ARG BISQ2_COMMIT=([0-9a-f]{40})$", dockerfile, re.MULTILINE)

    assert commit
    assert "BISQ2_BRANCH" not in dockerfile
    assert "BISQ2_BRANCH" not in compose
    assert 'git fetch --depth 1 origin "${BISQ2_COMMIT}"' in dockerfile
    assert 'test "$(git rev-parse FETCH_HEAD)" = "${BISQ2_COMMIT}"' in dockerfile
    assert "git checkout --detach FETCH_HEAD" in dockerfile


def test_branch_protection_payload_enforces_launch_requirements() -> None:
    payload = json.loads(BRANCH_PROTECTION_PAYLOAD.read_text(encoding="utf-8"))
    status_checks = payload["required_status_checks"]
    reviews = payload["required_pull_request_reviews"]

    assert status_checks["strict"] is True
    assert set(status_checks["contexts"]) == {
        "Lint, Type Check & Test",
        "Frontend Lint, Type Check & Test",
        "Shell Lint & Deployment Tests",
        "Security Scan",
        "Offline Staff-Alignment Gate",
    }
    assert reviews["required_approving_review_count"] == 1
    assert reviews["dismiss_stale_reviews"] is True
    assert payload["enforce_admins"] is True
    assert payload["allow_force_pushes"] is False
    assert payload["allow_deletions"] is False


def test_branch_protection_runbook_is_human_executed_and_verifiable() -> None:
    runbook = BRANCH_PROTECTION_RUNBOOK.read_text(encoding="utf-8")

    assert "human" in runbook.lower()
    assert "gh api" in runbook
    assert "--method PUT" in runbook
    assert "branches/${BRANCH}/protection" in runbook
    assert "--input docs/runbooks/branch-protection.json" in runbook
    assert "enforce_admins" in runbook
    assert "required_approving_review_count" in runbook
    assert "allow_force_pushes" in runbook
    assert "allow_deletions" in runbook
