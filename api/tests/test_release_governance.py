"""Regression tests for immutable release inputs and repository governance."""

from __future__ import annotations

import copy
import json
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yml"
LOCAL_COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.local.yml"
BRANCH_PROTECTION_PAYLOAD = REPO_ROOT / "docs" / "runbooks" / "branch-protection.json"
SINGLE_OPERATOR_BRANCH_PROTECTION_PAYLOAD = (
    REPO_ROOT / "docs" / "runbooks" / "branch-protection.single-operator-testing.json"
)
BRANCH_PROTECTION_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "branch-protection.md"
SINGLE_OPERATOR_RUNBOOK = (
    REPO_ROOT / "docs" / "runbooks" / "single-operator-production-testing.md"
)
DIGEST_REF_PATTERN = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
WEB_RUNTIME_PACKAGES = {
    "libcrypto3=3.5.9-r0",
    "libssl3=3.5.9-r0",
    "musl=1.2.5-r24",
    "musl-utils=1.2.5-r24",
    "zlib=1.4-r0",
}


def _assert_web_runtime_package_pins(runtime: str) -> None:
    """Require the pinned installation to lead a RUN, with no fallback branch."""
    active = []
    pending = []
    for line in runtime.splitlines():
        if pending:
            delimiter, strip_tabs = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                pending.pop(0)
            continue
        if line.lstrip().startswith("#"):
            continue
        active.append(line)
        if re.match(r"^\s*(?:RUN|COPY|ADD)\b", line, re.IGNORECASE):
            for match in re.finditer(
                r"<<(-?)[ \t]*(?:(['\"])([A-Za-z_][\w.-]*)\2|([A-Za-z_][\w.-]*))",
                line,
            ):
                pending.append((match.group(3) or match.group(4), bool(match.group(1))))
    assert not pending, "unterminated Dockerfile heredoc"
    active_lines = "\n".join(active)
    logical_lines = re.sub(r"\\\r?\n", " ", active_lines)
    installations = []
    for run in re.findall(r"^\s*RUN\s+(.+)$", logical_lines, re.MULTILINE):
        if not re.search(r"\bapk\s+add\b", run):
            continue
        lexer = shlex.shlex(run, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens = list(lexer)
        matches = [i for i in range(len(tokens)) if tokens[i : i + 2] == ["apk", "add"]]
        if not matches:
            continue
        assert matches == [0], "additional or conditional apk installation"
        assert tokens[:3] == ["apk", "add", "--no-cache"]
        # The reviewed contract installs first. Do not attempt to interpret
        # arbitrary shell control flow or accept a fallback that masks failure.
        split = tokens.index("&&") if "&&" in tokens else len(tokens)
        command, cleanup = tokens[:split], tokens[split:]
        # shlex splits 2>&1 into 2>, &, 1; accept only this redirection
        # after a successful install, never a background job or fallback.
        for i, token in enumerate(cleanup):
            if token == "&":
                assert (
                    i > 0
                    and i + 1 < len(cleanup)
                    and re.fullmatch(r"\d+>", cleanup[i - 1])
                    and cleanup[i + 1].isdigit()
                )
        assert not set(command) & {";", "||", "|", "&", "(", ")"}
        assert not set(cleanup) & {";", "||", "|", "(", ")"}
        assert len(command[3:]) == len(WEB_RUNTIME_PACKAGES)
        installations.append(set(command[3:]))
    assert installations == [WEB_RUNTIME_PACKAGES]


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
    """Keep the deployed web image's reviewed security package pins explicit."""
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

    _assert_web_runtime_package_pins(runtime)
    assert "rm -rf /usr/local/lib/node_modules/npm" in runtime
    assert "rm -f /usr/local/bin/npm /usr/local/bin/npx" in runtime
    assert "npm install --global" not in runtime
    assert 'CMD ["node", "node_modules/next/dist/bin/next", "start"]' in runtime
    assert "command" not in compose_web


@pytest.mark.parametrize("decoy", ["# Pinned packages: {pins}", "RUN echo '{pins}'"])
def test_web_runtime_pin_check_rejects_inactive_pins(decoy: str) -> None:
    """Commented or printed pins cannot validate an unversioned installation."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    packages = " ".join(
        pin.split("=", maxsplit=1)[0] for pin in sorted(WEB_RUNTIME_PACKAGES)
    )
    runtime = decoy.format(pins=pins) + "\nRUN apk add --no-cache " + packages
    with pytest.raises(AssertionError):
        _assert_web_runtime_package_pins(runtime)


@pytest.mark.parametrize(
    "command",
    [
        "true || apk add --no-cache {pins}",
        "false && apk add --no-cache {pins}",
        "if false; then apk add --no-cache {pins}; fi",
        "apk add --no-cache {pins} || true",
    ],
)
def test_web_runtime_pin_check_rejects_conditional_install(command: str) -> None:
    """Skipped installs or suppressed install failures cannot prove package pins."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    with pytest.raises(AssertionError):
        _assert_web_runtime_package_pins("RUN " + command.format(pins=pins))


def test_web_pin_check_ignores_dockerfile_heredoc_body() -> None:
    """Content in an unrelated heredoc is not a Dockerfile instruction."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    runtime = (
        "RUN cat <<EOF\nRUN echo it's content\nEOF\nRUN apk add --no-cache " + pins
    )
    _assert_web_runtime_package_pins(runtime)


def test_web_pin_check_does_not_accept_pins_inside_heredoc() -> None:
    """Printed heredoc content cannot stand in for an actual installation."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    runtime = "COPY <<'EOF' /message\nRUN apk add --no-cache " + pins + "\nEOF"
    with pytest.raises(AssertionError):
        _assert_web_runtime_package_pins(runtime)


def test_web_pin_check_rejects_redirection_followed_by_fallback() -> None:
    """A valid redirect cannot mask a later shell failure-suppression branch."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    with pytest.raises(AssertionError):
        _assert_web_runtime_package_pins(
            "RUN apk add --no-cache " + pins + " && rm /tmp/x 2>&1 || true"
        )


def test_web_pin_check_accepts_cleanup_stderr_redirection() -> None:
    """A post-install stderr redirect is not a background shell operator."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    _assert_web_runtime_package_pins(
        "RUN apk add --no-cache " + pins + " && rm -rf /tmp/cache 2>&1"
    )


@pytest.mark.parametrize(
    "additional",
    [
        "RUN echo ok && apk add --no-cache libcrypto3 || true",
        "RUN echo ok && apk add libcrypto3",
        "RUN apk add --no-cache {pins}",
        "repeat",
    ],
)
def test_web_pin_check_rejects_additional_or_repeated_installation(
    additional: str,
) -> None:
    """Extra installs or repeated arguments cannot satisfy the exact pin contract."""
    pins = " ".join(sorted(WEB_RUNTIME_PACKAGES))
    runtime = "RUN apk add --no-cache " + pins
    runtime += (
        " " + sorted(WEB_RUNTIME_PACKAGES)[0]
        if additional == "repeat"
        else "\n" + additional.format(pins=pins)
    )
    with pytest.raises(AssertionError):
        _assert_web_runtime_package_pins(runtime)


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


def test_single_operator_main_profile_changes_only_approval_count() -> None:
    canonical = json.loads(BRANCH_PROTECTION_PAYLOAD.read_text(encoding="utf-8"))
    single_operator = json.loads(
        SINGLE_OPERATOR_BRANCH_PROTECTION_PAYLOAD.read_text(encoding="utf-8")
    )
    expected = copy.deepcopy(canonical)
    expected["required_pull_request_reviews"]["required_approving_review_count"] = 0

    assert single_operator == expected


def test_single_operator_runbook_retains_technical_release_gates() -> None:
    runbook = SINGLE_OPERATOR_RUNBOOK.read_text(encoding="utf-8")
    normalized_runbook = " ".join(runbook.split())
    apply_section, restore_section = runbook.split(
        "## Restore launch-ready separation", maxsplit=1
    )

    assert "not launch-ready" in runbook
    assert "does not authorize a production change" in runbook
    assert "required_signatures" in runbook
    assert "branch-protection.single-operator-testing.json" in runbook
    assert "release-ai-quality-environment.single-operator-testing.json" in runbook
    assert (
        "release-ai-quality-release-branch-changes.single-operator-testing.json"
        in runbook
    )
    assert "release-ai-quality-release-branch-lifecycle.json" in runbook
    assert "release-ai-quality-version-tags.json" in runbook
    assert apply_section.count('select(.name == "Release branch lifecycle")') == 1
    assert apply_section.count('select(.name == "Version tag lifecycle")') == 1
    assert apply_section.count('jq --argjson id "$OPERATOR_ID"') == 3
    assert '--input "$WORK_DIR/release-branch-lifecycle.json"' in apply_section
    assert '--input "$WORK_DIR/version-tags.json"' in apply_section
    assert apply_section.count("rulesets/${RELEASE_LIFECYCLE_RULESET_ID}") == 2
    assert apply_section.count("rulesets/${VERSION_TAG_RULESET_ID}") == 2
    assert restore_section.count('select(.name == "Release branch lifecycle")') == 1
    assert restore_section.count('select(.name == "Version tag lifecycle")') == 1
    assert 'RELEASE_MANAGER_ID=""' in restore_section
    assert '[[ "$RELEASE_MANAGER_ID" =~ ^[1-9][0-9]*$ ]]' in restore_section
    assert 'test "$INDEPENDENT_REVIEWER_ID" != "$RELEASE_MANAGER_ID"' in restore_section
    assert restore_section.count('jq --argjson id "$RELEASE_MANAGER_ID"') == 2
    assert (
        '--input "$WORK_DIR/release-branch-lifecycle.canonical.json"' in restore_section
    )
    assert '--input "$WORK_DIR/version-tags.canonical.json"' in restore_section
    assert restore_section.count("rulesets/${RELEASE_LIFECYCLE_RULESET_ID}") == 1
    assert restore_section.count("rulesets/${VERSION_TAG_RULESET_ID}") == 1
    assert "AI_QUALITY_GATE_MARKER_APP_PRIVATE_KEY" in runbook
    assert "AI_QUALITY_GATE_MARKER_APP_CLIENT_ID" in runbook
    assert ".prevent_self_review] | first" in runbook
    assert "id: .reviewer.id" in runbook
    for disabled_switch in (
        "AUTONOMOUS_DELIVERY_ENABLED=false",
        "MATRIX_SYNC_ENABLED=false",
        "MATRIX_CHATOPS_ENABLED=false",
        "BISQ2_CHANNEL_ENABLED=false",
        "BISQ2_CHATOPS_ENABLED=false",
        "ESCALATION_BISQ2_WS_ENABLED=false",
    ):
        assert disabled_switch in runbook
    assert "--input docs/runbooks/branch-protection.json" in runbook
    assert "--input docs/runbooks/release-ai-quality-release-branch-changes.json" in (
        runbook
    )
    assert (
        "Evidence approved under the single-operator profile is not launch evidence"
        in normalized_runbook
    )
