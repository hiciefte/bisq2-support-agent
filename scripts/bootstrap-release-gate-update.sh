#!/bin/bash
set -Eeuo pipefail

# One-time transition from an updater that predates the release AI-quality
# gate. Run this script from a clean, detached worktree of the exact candidate
# commit; it deliberately never loads code from the production checkout.

SCRIPT_NAME="bootstrap-release-gate-update.sh"
SCRIPT_RELATIVE_PATH="scripts/$SCRIPT_NAME"
PRODUCTION_REPOSITORY=""
REMOTE="origin"
RELEASE_REF=""
RELEASE_COMMIT=""
FRESH_BACKUP_CONFIRMED=false
TRANSITION_REMOTE=""
PINNED_BRANCH="candidate"
HANDOFF_STARTED=false
UPDATE_COMPLETED=false
PRODUCTION_HEAD=""
ACTIVE_COMPOSE_PROJECT=""
ACTIVE_API_DATA_SOURCE=""
ACTIVE_PERSISTENT_MOUNTS=""

usage() {
    cat <<'EOF'
Usage: bootstrap-release-gate-update.sh [options]

Transition an existing production checkout to an exact, quality-gated commit.
Run this script from a clean detached worktree at the candidate commit.

Required options:
  --repository DIR        Existing production checkout
  --ref BRANCH            Reviewed main or one-level release/* branch
  --commit SHA            Exact full candidate commit ID
  --confirm-fresh-backup  Confirm an encrypted off-host backup passed scratch
                          restore verification before this invocation

Optional:
  --remote NAME           Existing Git remote (default: origin)
  -h, --help              Show this help
EOF
}

fail() {
    echo "Transition blocked: $1" >&2
    exit 1
}

cleanup() {
    local status=$?
    local current_head=""
    local recovered_head=""

    trap - EXIT INT TERM
    set +e
    if [ "$status" -ne 0 ] \
        && [ "$HANDOFF_STARTED" = true ] \
        && [ "$UPDATE_COMPLETED" != true ] \
        && [ -n "$PRODUCTION_HEAD" ] \
        && [ -n "$PRODUCTION_REPOSITORY" ]; then
        current_head=$(git -C "$PRODUCTION_REPOSITORY" rev-parse HEAD 2>/dev/null)
        if [ -n "$current_head" ] && [ "$current_head" != "$PRODUCTION_HEAD" ]; then
            echo "Transition failed after checkout mutation; starting guarded rollback." >&2
            if declare -F rollback_update >/dev/null 2>&1; then
                PREV_HEAD="$PRODUCTION_HEAD"
                export PREV_HEAD
                (
                    set -Eeuo pipefail
                    rollback_update "one-time transition exited unexpectedly"
                ) || true
                recovered_head=$(git -C "$PRODUCTION_REPOSITORY" \
                    rev-parse HEAD 2>/dev/null)
                if [ "$recovered_head" = "$PRODUCTION_HEAD" ]; then
                    echo "Guarded rollback restored the prior production commit." >&2
                else
                    echo "Guarded rollback did not restore the prior commit; human recovery is required." >&2
                fi
            else
                echo "Candidate rollback function is unavailable; human recovery is required." >&2
            fi
        fi
    fi
    if [ -n "$TRANSITION_REMOTE" ] \
        && [ -n "$PRODUCTION_REPOSITORY" ] \
        && git -C "$PRODUCTION_REPOSITORY" remote get-url \
            "$TRANSITION_REMOTE" >/dev/null 2>&1; then
        git -C "$PRODUCTION_REPOSITORY" remote remove \
            "$TRANSITION_REMOTE" >/dev/null 2>&1
    fi
    exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repository)
            [ "$#" -ge 2 ] || fail "missing value for --repository"
            PRODUCTION_REPOSITORY="$2"
            shift 2
            ;;
        --remote)
            [ "$#" -ge 2 ] || fail "missing value for --remote"
            REMOTE="$2"
            shift 2
            ;;
        --ref)
            [ "$#" -ge 2 ] || fail "missing value for --ref"
            RELEASE_REF="$2"
            shift 2
            ;;
        --commit)
            [ "$#" -ge 2 ] || fail "missing value for --commit"
            RELEASE_COMMIT="$2"
            shift 2
            ;;
        --confirm-fresh-backup)
            FRESH_BACKUP_CONFIRMED=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "unknown option: $1"
            ;;
    esac
done

[ -n "$PRODUCTION_REPOSITORY" ] || fail "--repository is required"
[ -n "$RELEASE_REF" ] || fail "--ref is required"
[ -n "$RELEASE_COMMIT" ] || fail "--commit is required"
[ "$FRESH_BACKUP_CONFIRMED" = true ] || {
    fail "--confirm-fresh-backup is required"
}

if [[ ! "$REMOTE" =~ ^[A-Za-z0-9._-]+$ ]]; then
    fail "invalid Git remote name"
fi
if [[ ! "$RELEASE_REF" =~ ^(main|release/[^/]+)$ ]]; then
    fail "release ref must be main or a one-level release/* branch"
fi

RELEASE_COMMIT=$(printf '%s' "$RELEASE_COMMIT" | tr '[:upper:]' '[:lower:]')
if [[ ! "$RELEASE_COMMIT" =~ ^[0-9a-f]{40,64}$ ]]; then
    fail "--commit must be a full Git object ID"
fi

for command_name in awk cp curl docker flock git grep jq mktemp mv rm sort tr; do
    command -v "$command_name" >/dev/null 2>&1 \
        || fail "required command is unavailable: $command_name"
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)"
CANDIDATE_REPOSITORY=$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null) \
    || fail "candidate source is not a Git worktree"
CANDIDATE_REPOSITORY="$(cd "$CANDIDATE_REPOSITORY" && pwd -P)"
EXPECTED_SCRIPT="$CANDIDATE_REPOSITORY/$SCRIPT_RELATIVE_PATH"
if [ ! -f "$EXPECTED_SCRIPT" ] || [ -L "$EXPECTED_SCRIPT" ] \
    || [ "$SCRIPT_DIR/$SCRIPT_NAME" != "$EXPECTED_SCRIPT" ]; then
    fail "run the tracked bootstrap script from the candidate worktree"
fi
git -C "$CANDIDATE_REPOSITORY" ls-files --error-unmatch \
    "$SCRIPT_RELATIVE_PATH" >/dev/null 2>&1 \
    || fail "bootstrap script is not tracked by the candidate commit"

PRODUCTION_REPOSITORY=$(cd "$PRODUCTION_REPOSITORY" 2>/dev/null && pwd -P) \
    || fail "production checkout is unavailable"
PRODUCTION_TOPLEVEL=$(git -C "$PRODUCTION_REPOSITORY" rev-parse \
    --show-toplevel 2>/dev/null) || fail "production path is not a Git checkout"
PRODUCTION_TOPLEVEL="$(cd "$PRODUCTION_TOPLEVEL" && pwd -P)"
[ "$PRODUCTION_REPOSITORY" = "$PRODUCTION_TOPLEVEL" ] \
    || fail "--repository must name the production checkout root"
[ "$CANDIDATE_REPOSITORY" != "$PRODUCTION_REPOSITORY" ] \
    || fail "candidate source must be separate from the production checkout"

if git -C "$CANDIDATE_REPOSITORY" symbolic-ref -q HEAD >/dev/null 2>&1; then
    fail "candidate source must be a detached worktree"
fi
CANDIDATE_HEAD=$(git -C "$CANDIDATE_REPOSITORY" rev-parse HEAD | \
    tr '[:upper:]' '[:lower:]')
[ "$CANDIDATE_HEAD" = "$RELEASE_COMMIT" ] \
    || fail "candidate worktree does not match --commit"

ensure_clean_tree() {
    local repository="$1"
    local label="$2"
    local untracked_found=false

    if ! git -C "$repository" diff --quiet HEAD --; then
        fail "$label source tree has tracked local changes"
    fi
    while IFS= read -r -d '' _path; do
        untracked_found=true
        break
    done < <(git -C "$repository" ls-files --others --exclude-standard -z)
    if [ "$untracked_found" = true ]; then
        fail "$label source tree has untracked local inputs"
    fi
}

ensure_clean_tree "$CANDIDATE_REPOSITORY" "candidate"
ensure_clean_tree "$PRODUCTION_REPOSITORY" "production"

for repository in "$CANDIDATE_REPOSITORY" "$PRODUCTION_REPOSITORY"; do
    git -C "$repository" remote get-url "$REMOTE" >/dev/null 2>&1 \
        || fail "release remote is unavailable"
done
CANDIDATE_REMOTE_URL=$(git -C "$CANDIDATE_REPOSITORY" remote get-url "$REMOTE")
PRODUCTION_REMOTE_URL=$(git -C "$PRODUCTION_REPOSITORY" remote get-url "$REMOTE")
[ "$CANDIDATE_REMOTE_URL" = "$PRODUCTION_REMOTE_URL" ] \
    || fail "candidate and production remotes do not match"

fetch_exact_ref() {
    local repository="$1"
    local fetched_commit

    git -C "$repository" fetch --quiet --no-tags "$REMOTE" \
        "refs/heads/$RELEASE_REF" \
        || fail "could not fetch the reviewed release ref"
    fetched_commit=$(git -C "$repository" rev-parse FETCH_HEAD | \
        tr '[:upper:]' '[:lower:]')
    [ "$fetched_commit" = "$RELEASE_COMMIT" ] \
        || fail "reviewed release ref no longer points to --commit"
}

fetch_exact_ref "$CANDIDATE_REPOSITORY"
fetch_exact_ref "$PRODUCTION_REPOSITORY"

PRODUCTION_HEAD=$(git -C "$PRODUCTION_REPOSITORY" rev-parse HEAD | \
    tr '[:upper:]' '[:lower:]')
[ "$PRODUCTION_HEAD" != "$RELEASE_COMMIT" ] \
    || fail "production already has the candidate; use scripts/update.sh"
git -C "$PRODUCTION_REPOSITORY" merge-base --is-ancestor \
    "$PRODUCTION_HEAD" "$RELEASE_COMMIT" \
    || fail "candidate is not a forward update from production"

MODEL_ENV_FILE="$PRODUCTION_REPOSITORY/docker/.env"
if [ ! -f "$MODEL_ENV_FILE" ] || [ -L "$MODEL_ENV_FILE" ]; then
    fail "protected production model configuration is unavailable"
fi

require_explicit_false() {
    local setting="$1"
    local assignment_state=""
    local assignment_count=""
    local canonical_count=""
    local value=""
    local extra_state=""

    assignment_state=$(awk -v key="$setting" '
        {
            raw = $0
            normalized = $0
            sub(/^[[:space:]]+/, "", normalized)
            if (normalized ~ /^export[[:space:]]+/) {
                sub(/^export[[:space:]]+/, "", normalized)
            }
            if (normalized ~ ("^" key "([[:space:]]*=|[[:space:]]*$)")) {
                assignments++
                if (index(raw, key "=") == 1) {
                    canonical++
                    value = substr(raw, length(key) + 2)
                }
            }
        }
        END {
            printf "%d|%d|%s\n", assignments + 0, canonical + 0, value
        }
    ' "$MODEL_ENV_FILE") || fail "$setting could not be parsed"
    IFS='|' read -r assignment_count canonical_count value extra_state \
        <<< "$assignment_state"
    if [ "$assignment_count" -ne 1 ] \
        || [ "$canonical_count" -ne 1 ] \
        || [ -n "$extra_state" ]; then
        fail "$setting must use one canonical protected assignment"
    fi
    [ "$value" = false ] \
        || fail "$setting must remain false for production testing"
}

for dark_setting in \
    AUTONOMOUS_DELIVERY_ENABLED \
    MATRIX_SYNC_ENABLED \
    MATRIX_CHATOPS_ENABLED \
    BISQ2_CHANNEL_ENABLED \
    BISQ2_CHATOPS_ENABLED \
    ESCALATION_BISQ2_WS_ENABLED; do
    require_explicit_false "$dark_setting"
done
require_explicit_false COOKIE_SECURE

require_compose_control_absent() {
    local setting="$1"
    local assignment_count=""

    assignment_count=$(awk -v key="$setting" '
        {
            normalized = $0
            sub(/^[[:space:]]+/, "", normalized)
            if (normalized ~ /^export[[:space:]]+/) {
                sub(/^export[[:space:]]+/, "", normalized)
            }
            if (normalized ~ ("^" key "([[:space:]]*=|[[:space:]]*$)")) {
                assignments++
            }
        }
        END { print assignments + 0 }
    ' "$MODEL_ENV_FILE") || fail "$setting could not be inspected"
    [ "$assignment_count" -eq 0 ] \
        || fail "$setting must be absent from protected Compose configuration"
}

for compose_control in \
    COMPOSE_ENV_FILES \
    COMPOSE_DISABLE_ENV_FILE \
    COMPOSE_FILE \
    COMPOSE_PATH_SEPARATOR \
    COMPOSE_PROFILES \
    DOCKER_HOST \
    DOCKER_CONTEXT; do
    require_compose_control_absent "$compose_control"
done

# Docker Compose gives exported shell variables precedence over docker/.env.
# Reject these critical overrides instead of silently evaluating one value and
# deploying another.
for protected_setting in \
    OPENAI_MODEL \
    AUTONOMOUS_DELIVERY_ENABLED \
    MATRIX_SYNC_ENABLED \
    MATRIX_CHATOPS_ENABLED \
    BISQ2_CHANNEL_ENABLED \
    BISQ2_CHATOPS_ENABLED \
    ESCALATION_BISQ2_WS_ENABLED \
    COOKIE_SECURE \
    NGINX_HTTP_BIND_ADDRESS \
    NGINX_HTTPS_BIND_ADDRESS \
    NGINX_TLS_CERTIFICATE_DIR \
    NGINX_TLS_CERTIFICATE_FILENAME \
    NGINX_TLS_PRIVATE_KEY_FILENAME \
    NGINX_TLS_REDIRECT_HTTP \
    BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE \
    COMPOSE_ENV_FILES \
    COMPOSE_DISABLE_ENV_FILE \
    COMPOSE_FILE \
    COMPOSE_PATH_SEPARATOR \
    COMPOSE_PROJECT_NAME \
    COMPOSE_PROFILES \
    DOCKER_HOST \
    DOCKER_CONTEXT \
    BISQ_SUPPORT_LIFECYCLE_LOCK_FD; do
    if printenv "$protected_setting" >/dev/null 2>&1; then
        fail "$protected_setting must not be exported by the operator shell"
    fi
done

CANDIDATE_VERIFIER="$CANDIDATE_REPOSITORY/scripts/verify-release-ai-quality-gate.sh"
CANDIDATE_UPDATER="$CANDIDATE_REPOSITORY/scripts/update.sh"
CANDIDATE_COMMON="$CANDIDATE_REPOSITORY/scripts/lib/common.sh"
if [ ! -f "$CANDIDATE_VERIFIER" ] || [ -L "$CANDIDATE_VERIFIER" ]; then
    fail "candidate release verifier is unavailable"
fi
if [ ! -f "$CANDIDATE_UPDATER" ] || [ -L "$CANDIDATE_UPDATER" ]; then
    fail "candidate updater is unavailable"
fi
if [ ! -f "$CANDIDATE_COMMON" ] || [ -L "$CANDIDATE_COMMON" ]; then
    fail "candidate production helper library is unavailable"
fi

# Resolve the live project from Docker's labels, never from a caller-provided
# name. This permits an existing non-default project while preventing Compose
# from creating a parallel empty stack during the handoff.
# shellcheck disable=SC1090
source "$CANDIDATE_COMMON"
setup_colors
acquire_production_lifecycle_lock "$PRODUCTION_REPOSITORY" \
    || fail "another production lifecycle operation is active"
pin_existing_compose_project \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml running \
    || fail "existing production Compose project could not be pinned"
ACTIVE_COMPOSE_PROJECT="$COMPOSE_PROJECT_NAME"
ACTIVE_API_DATA_SOURCE=$(
    cd "$PRODUCTION_REPOSITORY/api/data" 2>/dev/null && pwd -P
) || fail "existing production application data directory is unavailable"
validate_existing_api_data_identity \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml \
    "$ACTIVE_API_DATA_SOURCE" running \
    || fail "existing production API data identity is invalid"
ACTIVE_PERSISTENT_MOUNTS=$(capture_compose_persistent_mounts \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml) \
    || fail "existing production persistent mount identity is unavailable"

echo "Verifying release evidence for exact commit $RELEASE_COMMIT..."
if ! bash "$CANDIDATE_VERIFIER" \
    --repository "$CANDIDATE_REPOSITORY" \
    --remote "$REMOTE" \
    --commit "$RELEASE_COMMIT" \
    --env-file "$MODEL_ENV_FILE"; then
    fail "candidate release AI-quality evidence is missing or invalid"
fi

# Pin the already-verified object behind a temporary local remote-tracking ref.
# The candidate updater may fetch after this point, but a branch advance cannot
# change the exact object selected for reset, comparison, or rollback.
PROPOSED_TRANSITION_REMOTE="release-transition-$$"
if git -C "$PRODUCTION_REPOSITORY" remote get-url \
    "$PROPOSED_TRANSITION_REMOTE" >/dev/null 2>&1; then
    fail "temporary transition remote already exists"
fi
TRANSITION_REMOTE="$PROPOSED_TRANSITION_REMOTE"
git -C "$PRODUCTION_REPOSITORY" config \
    "remote.$TRANSITION_REMOTE.url" "$PRODUCTION_REMOTE_URL"
git -C "$PRODUCTION_REPOSITORY" update-ref \
    "refs/remotes/$TRANSITION_REMOTE/$PINNED_BRANCH" "$RELEASE_COMMIT"

echo "Release evidence verified; handing off to the candidate updater."
export BISQ_SUPPORT_INSTALL_DIR="$PRODUCTION_REPOSITORY"
export GIT_REMOTE="$TRANSITION_REMOTE"
export GIT_BRANCH="$PINNED_BRANCH"
export COMPOSE_PROJECT_NAME="$ACTIVE_COMPOSE_PROJECT"
unset INSTALL_DIR DOCKER_DIR COMPOSE_FILE

# shellcheck disable=SC1090
source "$CANDIDATE_UPDATER"

RESOLVED_INSTALL_DIR="$(cd "$INSTALL_DIR" 2>/dev/null && pwd -P)" \
    || fail "candidate updater resolved an unavailable installation path"
RESOLVED_DOCKER_DIR="$(cd "$DOCKER_DIR" 2>/dev/null && pwd -P)" \
    || fail "candidate updater resolved an unavailable Docker path"
[ "$RESOLVED_INSTALL_DIR" = "$PRODUCTION_REPOSITORY" ] \
    || fail "candidate updater resolved a different installation checkout"
[ "$RESOLVED_DOCKER_DIR" = "$PRODUCTION_REPOSITORY/docker" ] \
    || fail "candidate updater resolved a different Docker directory"
if [ -n "${BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE:-}" ]; then
    fail "production testing requires base Compose mode without a TLS overlay"
fi
validate_base_compose_exposure "$DOCKER_DIR" \
    || fail "candidate base HTTP exposure is not loopback-only"

# Preserve the label-derived project across a later `docker compose down`.
# Docker Compose reads this protected project .env automatically, so future
# start/stop/recovery commands cannot fall back to a parallel default project.
persist_compose_project_name "$PRODUCTION_REPOSITORY/docker" \
    || fail "existing production Compose project could not be persisted"

HANDOFF_STARTED=true
main
pin_existing_compose_project \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml running \
    || fail "production Compose project identity changed during transition"
validate_existing_api_data_identity \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml \
    "$ACTIVE_API_DATA_SOURCE" running \
    || fail "production API data identity changed during transition"
UPDATED_PERSISTENT_MOUNTS=$(capture_compose_persistent_mounts \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml) \
    || fail "production persistent mount identity is unavailable after transition"
validate_compose_loopback_http_binding \
    "$PRODUCTION_REPOSITORY/docker" docker-compose.yml \
    || fail "production HTTP listener is not loopback-only after transition"
validate_api_runtime_false_settings \
    "$PRODUCTION_REPOSITORY/docker" \
    AUTONOMOUS_DELIVERY_ENABLED \
    MATRIX_SYNC_ENABLED \
    MATRIX_CHATOPS_ENABLED \
    BISQ2_CHANNEL_ENABLED \
    BISQ2_CHATOPS_ENABLED \
    ESCALATION_BISQ2_WS_ENABLED \
    || fail "production response channels are not dark after transition"
validate_api_http_cookie_mode \
    "$PRODUCTION_REPOSITORY/docker" \
    || fail "production API cookie mode is unsafe for temporary HTTP testing"
while IFS= read -r mount_identity; do
    [ -n "$mount_identity" ] || continue
    grep -Fqx -- "$mount_identity" <<< "$UPDATED_PERSISTENT_MOUNTS" \
        || fail "production persistent mount identity changed during transition"
done <<< "$ACTIVE_PERSISTENT_MOUNTS"
UPDATE_COMPLETED=true
echo "Production transition completed at exact commit $RELEASE_COMMIT."
