#!/bin/bash
# Focused tests for the one-time release-gate transition bootstrap.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)"
BOOTSTRAP_SOURCE="$SCRIPT_DIR/../bootstrap-release-gate-update.sh"
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

    mkdir -p "$seed"
    git -C "$seed" init -q -b main
    git -C "$seed" config user.name "Transition Test"
    git -C "$seed" config user.email "transition-test"
    git -C "$seed" config commit.gpgsign false
    mkdir -p "$seed/docker" "$seed/api/data" "$seed/scripts"
    cat > "$seed/.gitignore" <<'EOF'
docker/.env
api/data/
EOF
    printf '%s\n' "old" > "$seed/version.txt"
    git -C "$seed" add .gitignore version.txt
    git -C "$seed" commit -q -m "Create old release"
    FIXTURE_OLD_COMMIT=$(git -C "$seed" rev-parse HEAD)

    cp "$BOOTSTRAP_SOURCE" "$seed/scripts/bootstrap-release-gate-update.sh"
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

main() {
    printf 'updater_source=%s\n' "${BASH_SOURCE[0]}" >> "${TRANSITION_TEST_LOG:?}"
    printf 'selection=%s/%s\n' "$GIT_REMOTE" "$GIT_BRANCH" \
        >> "$TRANSITION_TEST_LOG"
    PREV_HEAD=$(git -C "$INSTALL_DIR" rev-parse HEAD)
    export PREV_HEAD
    git -C "$INSTALL_DIR" fetch -q "$GIT_REMOTE"
    git -C "$INSTALL_DIR" reset -q --hard "$GIT_REMOTE/$GIT_BRANCH"
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
EOF
    printf '%s\n' "production-state" > "$production/api/data/state.db"

    git -C "$seed" worktree add -q --detach \
        "$candidate_tree" "$FIXTURE_CANDIDATE_COMMIT"

    FIXTURE_ROOT="$root"
    FIXTURE_REMOTE="$remote"
    FIXTURE_PRODUCTION="$production"
    FIXTURE_CANDIDATE_TREE="$candidate_tree"
    FIXTURE_LOG="$root/transition.log"
    FIXTURE_OUTPUT="$root/output.log"
    export FIXTURE_ROOT FIXTURE_REMOTE FIXTURE_PRODUCTION
    export FIXTURE_CANDIDATE_TREE FIXTURE_LOG FIXTURE_OUTPUT
    export FIXTURE_OLD_COMMIT FIXTURE_CANDIDATE_COMMIT FIXTURE_LATER_COMMIT
}

run_bootstrap() {
    TRANSITION_TEST_LOG="$FIXTURE_LOG" \
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

run_test "candidate updater receives exact pinned commit"
make_fixture "successful-transition"
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

echo ""
echo "========================================="
echo " Results: $TESTS_PASSED/$TESTS_RUN passed, $TESTS_FAILED failed"
echo "========================================="

[ "$TESTS_FAILED" -eq 0 ]
