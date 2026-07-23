#!/bin/bash
# Focused tests for the one-time release-gate transition bootstrap.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)"
BOOTSTRAP_SOURCE="$SCRIPT_DIR/../bootstrap-release-gate-update.sh"
COMMON_SOURCE="$SCRIPT_DIR/../lib/common.sh"
TEST_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/release-gate-transition-test.XXXXXXXX")
TEST_ROOT="$(cd "$TEST_ROOT" && pwd -P)"
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

cleanup() {
    rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "  PASS: $1"
}

fail_test() {
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo "  FAIL: $1"
    echo "        $2"
}

run_test() {
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "--- Test: $1 ---"
}

make_fixture() {
    local name="$1"
    local root="$TEST_ROOT/$name"
    local seed="$root/seed"
    local remote="$root/remote.git"
    local production="$root/production"
    local candidate_tree="$root/candidate"

    unset TRANSITION_TEST_API_CONTAINER_IDS
    unset TRANSITION_TEST_CANONICAL_CONTAINER_IDS
    unset TRANSITION_TEST_PROJECT_CONTAINER_IDS
    unset TRANSITION_TEST_WORKDIR_CONTAINER_IDS
    unset TRANSITION_TEST_POST_CANONICAL_CONTAINER_IDS
    unset TRANSITION_TEST_POST_PROJECT_CONTAINER_IDS
    unset TRANSITION_TEST_POST_WORKDIR_CONTAINER_IDS
    unset TRANSITION_TEST_COMPOSE_PROJECT
    unset TRANSITION_TEST_API_STATE
    unset TRANSITION_TEST_WORKING_DIR
    unset TRANSITION_TEST_DATA_DIR_ENTRY
    unset TRANSITION_TEST_DATA_SOURCE
    unset TRANSITION_TEST_POST_DATA_SOURCE
    unset TRANSITION_TEST_PERSISTENT_SOURCE
    unset TRANSITION_TEST_POST_PERSISTENT_SOURCE
    unset TRANSITION_TEST_LEGACY_SOURCE_BIND
    unset TRANSITION_TEST_HTTP_BINDING
    unset TRANSITION_TEST_POST_HTTP_BINDING
    unset TRANSITION_TEST_PERSISTED_OVERRIDE
    unset TRANSITION_TEST_COOKIE_ENTRY
    unset TRANSITION_TEST_RUNTIME_TRUE_SETTING
    unset TRANSITION_TEST_POST_API_ID
    unset TRANSITION_TEST_POST_QDRANT_ID
    unset TRANSITION_TEST_POST_NGINX_ID
    unset TRANSITION_TEST_POST_EXTRA_ID
    unset COOKIE_SECURE

    mkdir -p "$seed"
    git -C "$seed" init -q -b main
    git -C "$seed" config user.name "Transition Test"
    git -C "$seed" config user.email "transition-test"
    git -C "$seed" config commit.gpgsign false
    mkdir -p "$seed/docker" "$seed/api/data" "$seed/scripts/lib"
    cat > "$seed/.gitignore" <<'EOF'
docker/.env
api/data/
EOF
    printf '%s\n' "old" > "$seed/version.txt"
    git -C "$seed" add .gitignore version.txt
    git -C "$seed" commit -q -m "Create old release"
    FIXTURE_OLD_COMMIT=$(git -C "$seed" rev-parse HEAD)

    cp "$BOOTSTRAP_SOURCE" "$seed/scripts/bootstrap-release-gate-update.sh"
    cp "$COMMON_SOURCE" "$seed/scripts/lib/common.sh"
    chmod +x "$seed/scripts/bootstrap-release-gate-update.sh"
    cat > "$seed/scripts/verify-release-ai-quality-gate.sh" <<'EOF'
#!/bin/bash
set -euo pipefail

printf 'verify' >> "${TRANSITION_TEST_LOG:?}"
printf ' %q' "$@" >> "$TRANSITION_TEST_LOG"
printf '\n' >> "$TRANSITION_TEST_LOG"

if [ -n "${TRANSITION_TEST_ADVANCE_REMOTE:-}" ] \
    && [ ! -e "${TRANSITION_TEST_ADVANCE_ONCE:?}" ]; then
    git --git-dir="$TRANSITION_TEST_ADVANCE_REMOTE" update-ref \
        refs/heads/main "${TRANSITION_TEST_LATER_COMMIT:?}"
    touch "$TRANSITION_TEST_ADVANCE_ONCE"
fi

[ "${TRANSITION_TEST_FAIL_VERIFIER:-false}" != true ]
EOF
cat > "$seed/scripts/update.sh" <<'EOF'
#!/bin/bash
set -Eeuo pipefail

INSTALL_DIR="${BISQ_SUPPORT_INSTALL_DIR:?}"
DOCKER_DIR="$INSTALL_DIR/docker"
COMPOSE_FILE="docker-compose.yml"

if [ "${TRANSITION_TEST_PERSISTED_OVERRIDE:-false}" = true ]; then
    export BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml
fi

main() {
    printf 'updater_source=%s\n' "${BASH_SOURCE[0]}" >> "${TRANSITION_TEST_LOG:?}"
    printf 'selection=%s/%s\n' "$GIT_REMOTE" "$GIT_BRANCH" \
        >> "$TRANSITION_TEST_LOG"
    PREV_HEAD=$(git -C "$INSTALL_DIR" rev-parse HEAD)
    export PREV_HEAD
    git -C "$INSTALL_DIR" fetch -q "$GIT_REMOTE"
    git -C "$INSTALL_DIR" reset -q --hard "$GIT_REMOTE/$GIT_BRANCH"
    printf 'compose_project=%s\n' "${COMPOSE_PROJECT_NAME:-unset}" \
        >> "$TRANSITION_TEST_LOG"
    touch "${TRANSITION_TEST_HANDOFF_MARKER:?}"
    if [ "${TRANSITION_TEST_FAIL_AFTER_RESET:-false}" = true ]; then
        return 23
    fi
    bash "$INSTALL_DIR/scripts/verify-release-ai-quality-gate.sh" \
        --repository "$INSTALL_DIR" \
        --remote "$GIT_REMOTE" \
        --commit "$(git -C "$INSTALL_DIR" rev-parse HEAD)" \
        --env-file "$DOCKER_DIR/.env"
}

rollback_update() {
    printf 'rollback=%s\n' "$PREV_HEAD" >> "${TRANSITION_TEST_LOG:?}"
    git -C "$INSTALL_DIR" reset -q --hard "$PREV_HEAD"
    exit 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
EOF
    chmod +x \
        "$seed/scripts/verify-release-ai-quality-gate.sh" \
        "$seed/scripts/update.sh"
    printf '%s\n' "candidate" > "$seed/version.txt"
    git -C "$seed" add scripts version.txt
    git -C "$seed" commit -q -m "Add gated candidate"
    FIXTURE_CANDIDATE_COMMIT=$(git -C "$seed" rev-parse HEAD)

    printf '%s\n' "later" > "$seed/version.txt"
    git -C "$seed" add version.txt
    git -C "$seed" commit -q -m "Advance release branch"
    FIXTURE_LATER_COMMIT=$(git -C "$seed" rev-parse HEAD)

    git init -q --bare "$remote"
    git -C "$seed" remote add origin "$remote"
    git -C "$seed" push -q origin \
        "$FIXTURE_CANDIDATE_COMMIT:refs/heads/main" \
        "$FIXTURE_LATER_COMMIT:refs/heads/later"
    git --git-dir="$remote" symbolic-ref HEAD refs/heads/main

    git clone -q "$remote" "$production"
    git -C "$production" reset -q --hard "$FIXTURE_OLD_COMMIT"
    git -C "$production" config fetch.prune true
    mkdir -p "$production/docker" "$production/api/data"
    cat > "$production/docker/.env" <<'EOF'
OPENAI_MODEL=openai:test-model
AUTONOMOUS_DELIVERY_ENABLED=false
MATRIX_SYNC_ENABLED=false
MATRIX_CHATOPS_ENABLED=false
BISQ2_CHANNEL_ENABLED=false
BISQ2_CHATOPS_ENABLED=false
ESCALATION_BISQ2_WS_ENABLED=false
COOKIE_SECURE=false
EOF
    printf '%s\n' "production-state" > "$production/api/data/state.db"

    FIXTURE_BIN="$root/bin"
    FIXTURE_DOCKER_LOG="$root/docker.log"
    FIXTURE_HANDOFF_MARKER="$root/handoff-started"
    mkdir -p "$FIXTURE_BIN"
    cat > "$FIXTURE_BIN/flock" <<'EOF'
#!/bin/bash
exit 0
EOF
    chmod +x "$FIXTURE_BIN/flock"
    cat > "$FIXTURE_BIN/docker" <<'EOF'
#!/bin/bash
set -euo pipefail

printf '%s project=%s\n' "$*" "${COMPOSE_PROJECT_NAME:-unset}" \
    >> "${TRANSITION_TEST_DOCKER_LOG:?}"

api_id=0123456789ab
qdrant_id=abcdef012345
nginx_id=fedcba987654
post_api_id="${TRANSITION_TEST_POST_API_ID-$api_id}"
post_qdrant_id="${TRANSITION_TEST_POST_QDRANT_ID-$qdrant_id}"
post_nginx_id="${TRANSITION_TEST_POST_NGINX_ID-$nginx_id}"
post_extra_id="${TRANSITION_TEST_POST_EXTRA_ID-}"
active_api_id="$api_id"
active_qdrant_id="$qdrant_id"
active_nginx_id="$nginx_id"
canonical_ids="${TRANSITION_TEST_CANONICAL_CONTAINER_IDS-$api_id\\n$qdrant_id\\n$nginx_id}"
project_ids="${TRANSITION_TEST_PROJECT_CONTAINER_IDS-$canonical_ids}"
working_dir_ids="${TRANSITION_TEST_WORKDIR_CONTAINER_IDS-$canonical_ids}"
if [ -e "${TRANSITION_TEST_HANDOFF_MARKER:?}" ]; then
    active_api_id="$post_api_id"
    active_qdrant_id="$post_qdrant_id"
    active_nginx_id="$post_nginx_id"
    default_post_ids="$post_api_id\\n$post_qdrant_id\\n$post_nginx_id"
    [ -z "$post_extra_id" ] || default_post_ids+="\\n$post_extra_id"
    canonical_ids="${TRANSITION_TEST_POST_CANONICAL_CONTAINER_IDS-$default_post_ids}"
    project_ids="${TRANSITION_TEST_POST_PROJECT_CONTAINER_IDS-$canonical_ids}"
    working_dir_ids="${TRANSITION_TEST_POST_WORKDIR_CONTAINER_IDS-$canonical_ids}"
fi

if [ "$1" = ps ]; then
    if [[ "$*" == *"com.docker.compose.service=api"* ]]; then
        container_ids="${TRANSITION_TEST_API_CONTAINER_IDS-$active_api_id}"
    elif [[ "$*" == *"com.docker.compose.project="* ]]; then
        container_ids="$project_ids"
    else
        container_ids="$working_dir_ids"
    fi
    [ -z "$container_ids" ] || printf '%b\n' "$container_ids"
    exit 0
fi

if [ "$1" = compose ] && [[ "$*" == *"-q nginx"* ]]; then
    printf '%s\n' "$active_nginx_id"
    exit 0
fi

if [ "$1" = compose ] \
    && [[ "$*" == *"ps --all --orphans=false --no-trunc -q"* ]]; then
    [ -z "$canonical_ids" ] || printf '%b\n' "$canonical_ids"
    exit 0
fi

if [ "$1" = inspect ] && [ "$2" = --format ]; then
    container_id="${4:-}"
    if [[ "$3" == *'com.docker.compose.container-number'* ]]; then
        service=api
        { [ "$container_id" = "$qdrant_id" ] \
            || [ "$container_id" = "$post_qdrant_id" ]; } && service=qdrant
        { [ "$container_id" = "$nginx_id" ] \
            || [ "$container_id" = "$post_nginx_id" ]; } && service=nginx
        [ -n "$post_extra_id" ] \
            && [ "$container_id" = "$post_extra_id" ] \
            && service=matrix-alert-relay
        printf '%s|%s|%s|1|False|%s\n' \
            "${TRANSITION_TEST_COMPOSE_PROJECT:-transition-project}" \
            "${TRANSITION_TEST_WORKING_DIR:?}" \
            "$service" \
            "${TRANSITION_TEST_API_STATE:-running}"
        exit 0
    fi
    if [[ "$3" == *'com.docker.compose.oneoff'* ]] \
        && [[ "$3" == *'.State.Status'* ]]; then
        printf '%s|%s|api|False|%s\n' \
            "${TRANSITION_TEST_COMPOSE_PROJECT:-transition-project}" \
            "${TRANSITION_TEST_WORKING_DIR:?}" \
            "${TRANSITION_TEST_API_STATE:-running}"
        exit 0
    fi
    if [ "$3" = '{{index .Config.Labels "com.docker.compose.project"}}' ]; then
        printf '%s\n' "${TRANSITION_TEST_COMPOSE_PROJECT:-transition-project}"
        exit 0
    fi
    if [[ "$3" == *'.HostConfig.PortBindings'* ]]; then
        http_binding="${TRANSITION_TEST_HTTP_BINDING-80/tcp|127.0.0.1|80}"
        if [ -e "${TRANSITION_TEST_HANDOFF_MARKER:?}" ] \
            && [ -n "${TRANSITION_TEST_POST_HTTP_BINDING:-}" ]; then
            http_binding="$TRANSITION_TEST_POST_HTTP_BINDING"
        fi
        printf '%b\n' "$http_binding"
        exit 0
    fi
    if [[ "$3" == *'.Config.Env'* ]]; then
        for setting in \
            COOKIE_SECURE \
            AUTONOMOUS_DELIVERY_ENABLED \
            MATRIX_SYNC_ENABLED \
            MATRIX_CHATOPS_ENABLED \
            BISQ2_CHANNEL_ENABLED \
            BISQ2_CHATOPS_ENABLED \
            ESCALATION_BISQ2_WS_ENABLED; do
            if [[ "$3" == *"$setting"* ]]; then
                if [ "$setting" = COOKIE_SECURE ]; then
                    printf '%b\n' \
                        "${TRANSITION_TEST_COOKIE_ENTRY-COOKIE_SECURE=false}"
                elif [ "${TRANSITION_TEST_RUNTIME_TRUE_SETTING:-}" = "$setting" ]; then
                    printf '%s=true\n' "$setting"
                else
                    printf '%s=false\n' "$setting"
                fi
                exit 0
            fi
        done
        printf '%b\n' "${TRANSITION_TEST_DATA_DIR_ENTRY-DATA_DIR=/data}"
        exit 0
    fi
    if [[ "$3" == *'.Destination "/data"'* ]]; then
        data_source="${TRANSITION_TEST_DATA_SOURCE:?}"
        if [ -e "${TRANSITION_TEST_HANDOFF_MARKER:?}" ] \
            && [ -n "${TRANSITION_TEST_POST_DATA_SOURCE:-}" ]; then
            data_source="$TRANSITION_TEST_POST_DATA_SOURCE"
        fi
        printf 'bind|%s\n' "$data_source"
        exit 0
    fi
    if [[ "$3" == *'com.docker.compose.service'* ]] \
        && [[ "$3" == *'volume|%s'* ]]; then
        data_source="${TRANSITION_TEST_DATA_SOURCE:?}"
        persistent_source="${TRANSITION_TEST_PERSISTENT_SOURCE:?}"
        if [ -e "${TRANSITION_TEST_HANDOFF_MARKER:?}" ] \
            && [ -n "${TRANSITION_TEST_POST_DATA_SOURCE:-}" ]; then
            data_source="$TRANSITION_TEST_POST_DATA_SOURCE"
        fi
        if [ -e "${TRANSITION_TEST_HANDOFF_MARKER:?}" ] \
            && [ -n "${TRANSITION_TEST_POST_PERSISTENT_SOURCE:-}" ]; then
            persistent_source="$TRANSITION_TEST_POST_PERSISTENT_SOURCE"
        fi
        if [ "$container_id" = "$active_api_id" ]; then
            printf 'api|/data|bind|%s\n' "$data_source"
            if [ "${TRANSITION_TEST_LEGACY_SOURCE_BIND:-false}" = true ] \
                && [ ! -e "${TRANSITION_TEST_HANDOFF_MARKER:?}" ]; then
                printf 'api|/app/app|bind|%s\n' \
                    "${TRANSITION_TEST_DATA_SOURCE%/data}/app"
            fi
        elif [ "$container_id" = "$active_qdrant_id" ]; then
            printf 'qdrant|/qdrant/storage|volume|%s\n' "$persistent_source"
        fi
        exit 0
    fi
fi

exit 64
EOF
    chmod +x "$FIXTURE_BIN/docker"

    git -C "$seed" worktree add -q --detach \
        "$candidate_tree" "$FIXTURE_CANDIDATE_COMMIT"

    FIXTURE_ROOT="$root"
    FIXTURE_REMOTE="$remote"
    FIXTURE_PRODUCTION="$production"
    FIXTURE_CANDIDATE_TREE="$candidate_tree"
    FIXTURE_LOG="$root/transition.log"
    FIXTURE_OUTPUT="$root/output.log"
    export FIXTURE_BIN FIXTURE_DOCKER_LOG FIXTURE_HANDOFF_MARKER
    export FIXTURE_ROOT FIXTURE_REMOTE FIXTURE_PRODUCTION
    export FIXTURE_CANDIDATE_TREE FIXTURE_LOG FIXTURE_OUTPUT
    export FIXTURE_OLD_COMMIT FIXTURE_CANDIDATE_COMMIT FIXTURE_LATER_COMMIT
    export TRANSITION_TEST_DOCKER_LOG="$FIXTURE_DOCKER_LOG"
    export TRANSITION_TEST_WORKING_DIR="$FIXTURE_PRODUCTION/docker"
    export TRANSITION_TEST_DATA_SOURCE="$FIXTURE_PRODUCTION/api/data"
    export TRANSITION_TEST_PERSISTENT_SOURCE="transition-qdrant-data"
    export TRANSITION_TEST_HANDOFF_MARKER="$FIXTURE_HANDOFF_MARKER"
}

run_bootstrap() {
    PATH="$FIXTURE_BIN:$PATH" TRANSITION_TEST_LOG="$FIXTURE_LOG" \
        bash "$FIXTURE_CANDIDATE_TREE/scripts/bootstrap-release-gate-update.sh" \
        --repository "$FIXTURE_PRODUCTION" \
        --remote origin \
        --ref main \
        --commit "$FIXTURE_CANDIDATE_COMMIT" \
        "$@" > "$FIXTURE_OUTPUT" 2>&1
}

run_test "fresh backup confirmation is mandatory"
make_fixture "backup-confirmation"
if run_bootstrap; then
    fail_test "missing confirmation blocks transition" "bootstrap succeeded"
elif grep -q -- '--confirm-fresh-backup is required' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ]; then
    pass "missing confirmation blocks transition before checkout mutation"
else
    fail_test "missing confirmation blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi

run_test "dirty production source is rejected"
make_fixture "dirty-production"
printf '%s\n' "local-change" > "$FIXTURE_PRODUCTION/version.txt"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "dirty source blocks transition" "bootstrap succeeded"
elif grep -q 'production source tree has tracked local changes' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ]; then
    pass "dirty production source blocks transition"
else
    fail_test "dirty source blocks transition" "output: $(cat "$FIXTURE_OUTPUT")"
fi

run_test "failed candidate evidence leaves production untouched"
make_fixture "failed-evidence"
export TRANSITION_TEST_FAIL_VERIFIER=true
if run_bootstrap --confirm-fresh-backup; then
    fail_test "failed evidence blocks transition" "bootstrap succeeded"
elif grep -q 'candidate release AI-quality evidence is missing or invalid' \
        "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && ! grep -q '^updater_source=' "$FIXTURE_LOG"; then
    pass "failed evidence does not invoke updater or change production HEAD"
else
    fail_test "failed evidence blocks transition" "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_FAIL_VERIFIER

run_test "response channels must be explicitly dark"
make_fixture "enabled-channel"
sed -i.bak 's/^MATRIX_SYNC_ENABLED=false$/MATRIX_SYNC_ENABLED=true/' \
    "$FIXTURE_PRODUCTION/docker/.env"
rm -f "$FIXTURE_PRODUCTION/docker/.env.bak"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "enabled channel blocks transition" "bootstrap succeeded"
elif grep -q 'MATRIX_SYNC_ENABLED must remain false' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "enabled response channel blocks transition before verification"
else
    fail_test "enabled channel blocks transition" "output: $(cat "$FIXTURE_OUTPUT")"
fi

run_test "export-form response override is rejected"
make_fixture "export-form-channel"
printf '%s\n' 'export MATRIX_SYNC_ENABLED=true' \
    >> "$FIXTURE_PRODUCTION/docker/.env"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "export-form channel override blocks transition" \
        "bootstrap succeeded"
elif grep -q 'MATRIX_SYNC_ENABLED must use one canonical protected assignment' \
        "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "Compose-compatible export syntax cannot bypass the dark gate"
else
    fail_test "export-form channel override blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi

run_test "ambient response-channel override is rejected"
make_fixture "ambient-channel"
export MATRIX_SYNC_ENABLED=true
if run_bootstrap --confirm-fresh-backup; then
    fail_test "ambient channel override blocks transition" "bootstrap succeeded"
elif grep -q 'MATRIX_SYNC_ENABLED must not be exported' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "ambient response-channel override blocks transition"
else
    fail_test "ambient channel override blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset MATRIX_SYNC_ENABLED

run_test "ambient model override is rejected"
make_fixture "ambient-model"
export OPENAI_MODEL=openai:different-test-model
if run_bootstrap --confirm-fresh-backup; then
    fail_test "ambient model override blocks transition" "bootstrap succeeded"
elif grep -q 'OPENAI_MODEL must not be exported' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "ambient model override blocks transition"
else
    fail_test "ambient model override blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset OPENAI_MODEL

run_test "temporary HTTP testing requires non-secure cookies"
make_fixture "secure-cookie-mode"
sed -i.bak 's/^COOKIE_SECURE=false$/COOKIE_SECURE=true/' \
    "$FIXTURE_PRODUCTION/docker/.env"
rm -f "$FIXTURE_PRODUCTION/docker/.env.bak"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "secure cookies block temporary HTTP transition" \
        "bootstrap succeeded"
elif grep -q 'COOKIE_SECURE must remain false' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "HTTP cookie mode is explicit before checkout mutation"
else
    fail_test "secure cookies block temporary HTTP transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi

run_test "ambient Compose and Docker selection controls are rejected"
make_fixture "ambient-compose-control"
compose_control_failures=()
for compose_control in \
    COMPOSE_ENV_FILES \
    COMPOSE_DISABLE_ENV_FILE \
    COMPOSE_FILE \
    COMPOSE_PATH_SEPARATOR \
    COMPOSE_PROJECT_NAME \
    COMPOSE_PROFILES \
    DOCKER_HOST \
    DOCKER_CONTEXT; do
    export "$compose_control=transition-test-value"
    if run_bootstrap --confirm-fresh-backup; then
        compose_control_failures+=("$compose_control succeeded")
    elif ! grep -q "$compose_control must not be exported" "$FIXTURE_OUTPUT"; then
        compose_control_failures+=("$compose_control returned unexpected output")
    elif [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" != \
        "$FIXTURE_OLD_COMMIT" ]; then
        compose_control_failures+=("$compose_control changed production HEAD")
    elif [ -e "$FIXTURE_LOG" ]; then
        compose_control_failures+=("$compose_control invoked candidate code")
    fi
    unset "$compose_control"
done
if [ "${#compose_control_failures[@]}" -eq 0 ]; then
    pass "ambient orchestration controls cannot replace the verified stack"
else
    fail_test "ambient orchestration controls block transition" \
        "${compose_control_failures[*]}"
fi

run_test "protected Compose control assignment is rejected"
make_fixture "compose-env-file-control"
printf '%s\n' 'export COMPOSE_ENV_FILES=alternate.env' \
    >> "$FIXTURE_PRODUCTION/docker/.env"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "protected Compose control blocks transition" "bootstrap succeeded"
elif grep -q 'COMPOSE_ENV_FILES must be absent' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "project .env cannot select an unreviewed environment file"
else
    fail_test "protected Compose control blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi

run_test "missing existing Compose stack is rejected"
make_fixture "missing-existing-stack"
export TRANSITION_TEST_API_CONTAINER_IDS=""
if run_bootstrap --confirm-fresh-backup; then
    fail_test "missing stack blocks transition" "bootstrap succeeded"
elif grep -q 'Exactly one API container' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "missing existing stack blocks transition before candidate handoff"
else
    fail_test "missing stack blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_API_CONTAINER_IDS

run_test "ambiguous existing Compose stack is rejected"
make_fixture "ambiguous-existing-stack"
export TRANSITION_TEST_API_CONTAINER_IDS='aaaaaaaaaaaa\nbbbbbbbbbbbb'
if run_bootstrap --confirm-fresh-backup; then
    fail_test "ambiguous stack blocks transition" "bootstrap succeeded"
elif grep -q 'Exactly one API container' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "ambiguous existing stack cannot be selected implicitly"
else
    fail_test "ambiguous stack blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_API_CONTAINER_IDS

run_test "different Compose working directory is rejected"
make_fixture "different-compose-working-directory"
mkdir -p "$FIXTURE_ROOT/other-docker"
export TRANSITION_TEST_WORKING_DIR="$FIXTURE_ROOT/other-docker"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "different working directory blocks transition" "bootstrap succeeded"
elif grep -q 'different Compose working directory' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "different Compose working directory cannot replace the existing stack"
else
    fail_test "different working directory blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_WORKING_DIR

run_test "stopped API is rejected for the live transition"
make_fixture "stopped-api"
export TRANSITION_TEST_API_STATE=exited
if run_bootstrap --confirm-fresh-backup; then
    fail_test "stopped API blocks transition" "bootstrap succeeded"
elif grep -q 'API container is not running' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "transition requires the existing API to be running"
else
    fail_test "stopped API blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_API_STATE

run_test "restarting API is rejected as an unstable data anchor"
make_fixture "restarting-api"
export TRANSITION_TEST_API_STATE=restarting
if run_bootstrap --confirm-fresh-backup; then
    fail_test "restarting API blocks transition" "bootstrap succeeded"
elif grep -q 'API container is not running' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "crash-looping API cannot anchor the existing production stack"
else
    fail_test "restarting API blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_API_STATE

run_test "API data directory setting must be unique"
make_fixture "duplicate-data-setting"
export TRANSITION_TEST_DATA_DIR_ENTRY='DATA_DIR=/data\nDATA_DIR=/data'
if run_bootstrap --confirm-fresh-backup; then
    fail_test "duplicate API data setting blocks transition" "bootstrap succeeded"
elif grep -q 'must use exactly DATA_DIR=/data' "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_LOG" ]; then
    pass "duplicate API data settings cannot satisfy data identity"
else
    fail_test "duplicate API data setting blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_DATA_DIR_ENTRY

run_test "unexpected post-reset failure rolls back"
make_fixture "post-reset-failure"
export TRANSITION_TEST_FAIL_AFTER_RESET=true
if run_bootstrap --confirm-fresh-backup; then
    fail_test "post-reset failure rolls back" "bootstrap succeeded"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG" \
        && ! git -C "$FIXTURE_PRODUCTION" remote \
            | grep -q '^release-transition-'; then
        pass "unexpected post-reset failure restores commit and preserves data"
    else
        fail_test "post-reset failure rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_FAIL_AFTER_RESET

run_test "post-update data identity change rolls back"
make_fixture "post-update-data-change"
mkdir -p "$FIXTURE_ROOT/parallel-data"
export TRANSITION_TEST_POST_DATA_SOURCE="$FIXTURE_ROOT/parallel-data"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "changed data identity rolls back" \
        "bootstrap succeeded; Docker log: $(cat "$FIXTURE_DOCKER_LOG")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && grep -q 'production API data identity changed' "$FIXTURE_OUTPUT" \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG"; then
        pass "post-update data identity change restores the prior release"
    else
        fail_test "changed data identity rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_POST_DATA_SOURCE

run_test "post-update persistent volume change rolls back"
make_fixture "post-update-volume-change"
export TRANSITION_TEST_POST_PERSISTENT_SOURCE="parallel-qdrant-data"
if run_bootstrap --confirm-fresh-backup; then
    fail_test "changed volume identity rolls back" \
        "bootstrap succeeded; Docker log: $(cat "$FIXTURE_DOCKER_LOG")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && grep -q 'persistent mount identity changed' "$FIXTURE_OUTPUT" \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG"; then
        pass "post-update persistent volume change restores the prior release"
    else
        fail_test "changed volume identity rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_POST_PERSISTENT_SOURCE

run_test "candidate persisted TLS override is rejected before handoff"
make_fixture "persisted-tls-override"
export TRANSITION_TEST_PERSISTED_OVERRIDE=true
if run_bootstrap --confirm-fresh-backup; then
    fail_test "persisted TLS override blocks transition" "bootstrap succeeded"
elif grep -q 'requires base Compose mode without a TLS overlay' \
        "$FIXTURE_OUTPUT" \
    && [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" = "$FIXTURE_OLD_COMMIT" ] \
    && [ ! -e "$FIXTURE_HANDOFF_MARKER" ]; then
    pass "candidate deploy selection cannot enable the TLS overlay"
else
    fail_test "persisted TLS override blocks transition" \
        "output: $(cat "$FIXTURE_OUTPUT")"
fi
unset TRANSITION_TEST_PERSISTED_OVERRIDE

run_test "post-update public HTTP binding rolls back"
make_fixture "post-update-public-http"
export TRANSITION_TEST_POST_HTTP_BINDING='80/tcp|0.0.0.0|80'
if run_bootstrap --confirm-fresh-backup; then
    fail_test "public HTTP binding rolls back" \
        "bootstrap succeeded; Docker log: $(cat "$FIXTURE_DOCKER_LOG")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && grep -q 'production HTTP listener is not loopback-only' \
            "$FIXTURE_OUTPUT" \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG"; then
        pass "transition rejects an all-interface production listener"
    else
        fail_test "public HTTP binding rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_POST_HTTP_BINDING

run_test "post-update extra HTTPS binding rolls back"
make_fixture "post-update-extra-https"
export TRANSITION_TEST_POST_HTTP_BINDING='80/tcp|127.0.0.1|80\n443/tcp|0.0.0.0|443'
if run_bootstrap --confirm-fresh-backup; then
    fail_test "extra HTTPS binding rolls back" \
        "bootstrap succeeded; Docker log: $(cat "$FIXTURE_DOCKER_LOG")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && grep -q 'production HTTP listener is not loopback-only' \
            "$FIXTURE_OUTPUT" \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG"; then
        pass "transition rejects every additional published port"
    else
        fail_test "extra HTTPS binding rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_POST_HTTP_BINDING

run_test "post-update secure cookie mode rolls back"
make_fixture "post-update-secure-cookie"
export TRANSITION_TEST_COOKIE_ENTRY=COOKIE_SECURE=true
if run_bootstrap --confirm-fresh-backup; then
    fail_test "secure runtime cookie mode rolls back" \
        "bootstrap succeeded; Docker log: $(cat "$FIXTURE_DOCKER_LOG")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && grep -q 'production API cookie mode is unsafe' "$FIXTURE_OUTPUT" \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG"; then
        pass "transition verifies the effective API cookie mode"
    else
        fail_test "secure runtime cookie mode rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_COOKIE_ENTRY

run_test "post-update response channels remain dark"
runtime_flag_failures=()
for runtime_flag in \
    AUTONOMOUS_DELIVERY_ENABLED \
    MATRIX_SYNC_ENABLED \
    MATRIX_CHATOPS_ENABLED \
    BISQ2_CHANNEL_ENABLED \
    BISQ2_CHATOPS_ENABLED \
    ESCALATION_BISQ2_WS_ENABLED; do
    make_fixture "post-update-runtime-$runtime_flag"
    export TRANSITION_TEST_RUNTIME_TRUE_SETTING="$runtime_flag"
    if run_bootstrap --confirm-fresh-backup; then
        runtime_flag_failures+=("$runtime_flag succeeded")
    elif [ "$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)" != \
        "$FIXTURE_OLD_COMMIT" ]; then
        runtime_flag_failures+=("$runtime_flag did not roll back")
    elif ! grep -q 'production response channels are not dark' \
        "$FIXTURE_OUTPUT"; then
        runtime_flag_failures+=("$runtime_flag returned unexpected output")
    fi
    unset TRANSITION_TEST_RUNTIME_TRUE_SETTING
done
if [ "${#runtime_flag_failures[@]}" -eq 0 ]; then
    pass "all six effective response settings are verified after restart"
else
    fail_test "post-update response channels remain dark" \
        "${runtime_flag_failures[*]}"
fi

run_test "stale container cannot satisfy post-update continuity"
make_fixture "post-update-stale-container"
export TRANSITION_TEST_POST_PROJECT_CONTAINER_IDS='0123456789ab\nabcdef012345\nfedcba987654\n111111111111'
if run_bootstrap --confirm-fresh-backup; then
    fail_test "stale container identity rolls back" \
        "bootstrap succeeded; Docker log: $(cat "$FIXTURE_DOCKER_LOG")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_OLD_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && grep -q 'Compose project identity changed' "$FIXTURE_OUTPUT" \
        && grep -q "^rollback=$FIXTURE_OLD_COMMIT$" "$FIXTURE_LOG"; then
        pass "stale containers cannot mask replacement mount identity"
    else
        fail_test "stale container identity rolls back" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_POST_PROJECT_CONTAINER_IDS

run_test "reviewed legacy source bind removal preserves state"
make_fixture "legacy-source-bind-removal"
export TRANSITION_TEST_LEGACY_SOURCE_BIND=true
if ! run_bootstrap --confirm-fresh-backup; then
    fail_test "legacy source bind removal is allowed" \
        "output: $(cat "$FIXTURE_OUTPUT")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    if [ "$final_head" = "$FIXTURE_CANDIDATE_COMMIT" ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && ! grep -q '|/app/app|bind|' "$FIXTURE_OUTPUT"; then
        pass "source hardening does not look like persistent-data loss"
    else
        fail_test "legacy source bind removal is allowed" \
            "head=$final_head output: $(cat "$FIXTURE_OUTPUT")"
    fi
fi
unset TRANSITION_TEST_LEGACY_SOURCE_BIND

run_test "candidate updater receives exact pinned commit"
make_fixture "successful-transition"
export TRANSITION_TEST_POST_API_ID=1123456789ab
export TRANSITION_TEST_POST_QDRANT_ID=bbcdef012345
export TRANSITION_TEST_POST_NGINX_ID=eedcba987654
export TRANSITION_TEST_POST_EXTRA_ID=999999999999
export TRANSITION_TEST_ADVANCE_REMOTE="$FIXTURE_REMOTE"
export TRANSITION_TEST_ADVANCE_ONCE="$FIXTURE_ROOT/advanced"
export TRANSITION_TEST_LATER_COMMIT="$FIXTURE_LATER_COMMIT"
if ! run_bootstrap --confirm-fresh-backup; then
    fail_test "successful transition" "output: $(cat "$FIXTURE_OUTPUT")"
else
    final_head=$(git -C "$FIXTURE_PRODUCTION" rev-parse HEAD)
    verifier_calls=$(grep -c '^verify ' "$FIXTURE_LOG" || true)
    updater_source=$(sed -n 's/^updater_source=//p' "$FIXTURE_LOG")
    if [ "$final_head" = "$FIXTURE_CANDIDATE_COMMIT" ] \
        && [ "$verifier_calls" -eq 2 ] \
        && [[ "$updater_source" == "$FIXTURE_CANDIDATE_TREE/"* ]] \
        && grep -q '^compose_project=transition-project$' "$FIXTURE_LOG" \
        && [ "$(grep -c '^COMPOSE_PROJECT_NAME=transition-project$' \
            "$FIXTURE_PRODUCTION/docker/.env")" -eq 1 ] \
        && [ "$(cat "$FIXTURE_PRODUCTION/api/data/state.db")" = "production-state" ] \
        && ! git -C "$FIXTURE_PRODUCTION" remote | grep -q '^release-transition-'; then
        pass "candidate code verifies twice, pins the exact commit, and preserves data"
    else
        fail_test "successful transition" \
            "head=$final_head verifier_calls=$verifier_calls updater=$updater_source"
    fi
fi
unset TRANSITION_TEST_ADVANCE_REMOTE
unset TRANSITION_TEST_ADVANCE_ONCE
unset TRANSITION_TEST_LATER_COMMIT
unset TRANSITION_TEST_POST_API_ID
unset TRANSITION_TEST_POST_QDRANT_ID
unset TRANSITION_TEST_POST_NGINX_ID
unset TRANSITION_TEST_POST_EXTRA_ID

echo ""
echo "========================================="
echo " Results: $TESTS_PASSED/$TESTS_RUN passed, $TESTS_FAILED failed"
echo "========================================="

[ "$TESTS_FAILED" -eq 0 ]
