#!/bin/bash
# Tests for environment configuration validation (source_deploy_paths / validate_app_env)
#
# Usage: bash scripts/tests/test_env_config.sh
#
# These tests verify:
#   1. source_deploy_paths only exports deploy-path vars, NOT app config
#   2. validate_app_env catches missing required Matrix vars
#   3. detect_env_shadowing warns when deploy.env shadows docker/.env app vars
#   4. Legacy deploy.env with app vars is detected and warned about

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
LIB_DIR="$SCRIPT_DIR/../lib"

# Test framework
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "  PASS: $1"
}

fail() {
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo "  FAIL: $1"
    echo "        $2"
}

run_test() {
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "--- Test: $1 ---"
}

# Create temp directory for fixtures
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Source the library under test
# shellcheck disable=SC1091
source "$LIB_DIR/common.sh"
setup_colors

# =============================================================================
# Test: source_deploy_paths exports ONLY path/repo vars
# =============================================================================
run_test "source_deploy_paths exports only deploy-path vars"

cat > "$TMPDIR/deploy.env" <<'EOF'
export BISQ_SUPPORT_INSTALL_DIR="/opt/bisq-support"
export BISQ_SUPPORT_REPO_URL="git@github.com:hiciefte/bisq2-support-agent.git"
export BISQ2_INSTALL_DIR="/opt/bisq2"
export BISQ2_REPO_URL="git@github.com:hiciefte/bisq2.git"
MATRIX_STAFF_ROOM=!should-not-be-exported:matrix.org
OPENAI_API_KEY=sk-should-not-be-exported
TRUST_MONITOR_ENABLED=true
EOF

# Clear any pre-existing values
unset BISQ_SUPPORT_INSTALL_DIR BISQ_SUPPORT_REPO_URL BISQ2_INSTALL_DIR BISQ2_REPO_URL 2>/dev/null || true
unset MATRIX_STAFF_ROOM OPENAI_API_KEY TRUST_MONITOR_ENABLED 2>/dev/null || true

source_deploy_paths "$TMPDIR/deploy.env"

if [ "${BISQ_SUPPORT_INSTALL_DIR:-}" = "/opt/bisq-support" ]; then
    pass "BISQ_SUPPORT_INSTALL_DIR exported"
else
    fail "BISQ_SUPPORT_INSTALL_DIR not exported" "got '${BISQ_SUPPORT_INSTALL_DIR:-}'"
fi

if [ "${BISQ_SUPPORT_REPO_URL:-}" = "git@github.com:hiciefte/bisq2-support-agent.git" ]; then
    pass "BISQ_SUPPORT_REPO_URL exported"
else
    fail "BISQ_SUPPORT_REPO_URL not exported" "got '${BISQ_SUPPORT_REPO_URL:-}'"
fi

if [ -z "${MATRIX_STAFF_ROOM:-}" ]; then
    pass "MATRIX_STAFF_ROOM NOT exported (app config ignored)"
else
    fail "MATRIX_STAFF_ROOM was exported" "should not export app config from deploy.env"
fi

if [ -z "${OPENAI_API_KEY:-}" ]; then
    pass "OPENAI_API_KEY NOT exported (app config ignored)"
else
    fail "OPENAI_API_KEY was exported" "should not export app config from deploy.env"
fi

# =============================================================================
# Test: validate_app_env passes with all required vars
# =============================================================================
run_test "validate_app_env passes with valid config"

cat > "$TMPDIR/good.env" <<'EOF'
MATRIX_SYNC_ROOMS=!room:matrix.org
MATRIX_STAFF_ROOM=!staff:matrix.org
TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=!room:matrix.org
TRUST_MONITOR_MATRIX_STAFF_ROOM=!staff:matrix.org
EOF

output=$(validate_app_env "$TMPDIR/good.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -eq 0 ]; then
    pass "valid config passes validation"
else
    fail "valid config should pass" "exit code $rc, output: $output"
fi

# =============================================================================
# Test: validate_app_env fails when MATRIX_STAFF_ROOM is missing
# =============================================================================
run_test "validate_app_env fails when MATRIX_STAFF_ROOM missing"

cat > "$TMPDIR/missing_staff.env" <<'EOF'
MATRIX_SYNC_ROOMS=!room:matrix.org
TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=!room:matrix.org
TRUST_MONITOR_MATRIX_STAFF_ROOM=!staff:matrix.org
EOF

output=$(validate_app_env "$TMPDIR/missing_staff.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -ne 0 ]; then
    pass "missing MATRIX_STAFF_ROOM detected"
else
    fail "should fail when MATRIX_STAFF_ROOM missing" "exit code $rc"
fi

# =============================================================================
# Test: validate_app_env fails when MATRIX_SYNC_ROOMS is missing
# =============================================================================
run_test "validate_app_env fails when MATRIX_SYNC_ROOMS missing"

cat > "$TMPDIR/missing_sync.env" <<'EOF'
MATRIX_STAFF_ROOM=!staff:matrix.org
TRUST_MONITOR_MATRIX_PUBLIC_ROOMS=!room:matrix.org
TRUST_MONITOR_MATRIX_STAFF_ROOM=!staff:matrix.org
EOF

output=$(validate_app_env "$TMPDIR/missing_sync.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -ne 0 ]; then
    pass "missing MATRIX_SYNC_ROOMS detected"
else
    fail "should fail when MATRIX_SYNC_ROOMS missing" "exit code $rc"
fi

# =============================================================================
# Test: validate_app_env warns when TRUST_MONITOR vars are missing
# =============================================================================
run_test "validate_app_env warns on missing trust monitor room vars"

cat > "$TMPDIR/missing_trust.env" <<'EOF'
MATRIX_SYNC_ROOMS=!room:matrix.org
MATRIX_STAFF_ROOM=!staff:matrix.org
EOF

output=$(validate_app_env "$TMPDIR/missing_trust.env" 2>&1) && rc=$? || rc=$?
# Should still pass (warnings not errors) but output should contain warning
if [ "$rc" -eq 0 ] && echo "$output" | grep -qi "warn"; then
    pass "missing trust monitor vars produce warning"
else
    fail "should warn about missing trust monitor vars" "rc=$rc, output: $output"
fi

# =============================================================================
# Test: detect_env_shadowing warns on app vars in deploy.env
# =============================================================================
run_test "detect_env_shadowing detects app config in deploy.env"

cat > "$TMPDIR/shadow_deploy.env" <<'EOF'
export BISQ_SUPPORT_INSTALL_DIR="/opt/bisq-support"
MATRIX_CHATOPS_ENABLED=true
TRUST_MONITOR_MATRIX_STAFF_ROOM=!wrong:matrix.org
OPENAI_API_KEY=sk-shadow
EOF

cat > "$TMPDIR/shadow_docker.env" <<'EOF'
MATRIX_CHATOPS_ENABLED=true
TRUST_MONITOR_MATRIX_STAFF_ROOM=!correct:matrix.org
OPENAI_API_KEY=sk-correct
EOF

output=$(detect_env_shadowing "$TMPDIR/shadow_deploy.env" "$TMPDIR/shadow_docker.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -ne 0 ]; then
    pass "shadowing detected returns non-zero"
else
    fail "should detect shadowing" "exit code $rc"
fi

if echo "$output" | grep -q "TRUST_MONITOR_MATRIX_STAFF_ROOM"; then
    pass "identifies shadowed var by name"
else
    fail "should name the shadowed variable" "output: $output"
fi

# =============================================================================
# Test: detect_env_shadowing passes when deploy.env has only path vars
# =============================================================================
run_test "detect_env_shadowing passes with clean deploy.env"

cat > "$TMPDIR/clean_deploy.env" <<'EOF'
export BISQ_SUPPORT_INSTALL_DIR="/opt/bisq-support"
export BISQ_SUPPORT_REPO_URL="git@github.com:hiciefte/bisq2-support-agent.git"
export BISQ2_INSTALL_DIR="/opt/bisq2"
export BISQ2_REPO_URL="git@github.com:hiciefte/bisq2.git"
EOF

output=$(detect_env_shadowing "$TMPDIR/clean_deploy.env" "$TMPDIR/shadow_docker.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -eq 0 ]; then
    pass "clean deploy.env has no shadowing"
else
    fail "should pass with clean deploy.env" "exit code $rc, output: $output"
fi

# =============================================================================
# Test: source_deploy_paths handles missing file gracefully
# =============================================================================
run_test "source_deploy_paths handles missing file"

output=$(source_deploy_paths "$TMPDIR/nonexistent.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -ne 0 ]; then
    pass "missing file returns non-zero"
else
    fail "should fail for missing file" "exit code $rc"
fi

# =============================================================================
# Test: validate_runtime_configuration reads from file
# =============================================================================
run_test "validate_runtime_configuration reads from env file"

cat > "$TMPDIR/runtime_ok.env" <<'EOF'
TRUST_MONITOR_ENABLED=true
TRUST_MONITOR_ACTOR_KEY_SECRET=some-secret
MATRIX_CHATOPS_ENABLED=true
MATRIX_CHATOPS_ROOM_IDS=!ops:matrix.org
EOF

output=$(validate_runtime_configuration "$TMPDIR/runtime_ok.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -eq 0 ]; then
    pass "valid runtime config passes"
else
    fail "valid runtime config should pass" "exit code $rc, output: $output"
fi

# =============================================================================
# Test: validate_runtime_configuration detects missing chatops rooms
# =============================================================================
run_test "validate_runtime_configuration detects missing chatops rooms from file"

cat > "$TMPDIR/runtime_bad.env" <<'EOF'
MATRIX_CHATOPS_ENABLED=true
EOF

output=$(validate_runtime_configuration "$TMPDIR/runtime_bad.env" 2>&1) && rc=$? || rc=$?
if [ "$rc" -ne 0 ]; then
    pass "missing MATRIX_CHATOPS_ROOM_IDS detected from file"
else
    fail "should fail when chatops enabled without room IDs" "exit code $rc"
fi

# =============================================================================
# Test: validate_runtime_configuration still works without file (backward compat)
# =============================================================================
run_test "validate_runtime_configuration backward compat (no file arg)"

# Clear relevant env vars
unset TRUST_MONITOR_ENABLED MATRIX_CHATOPS_ENABLED BISQ2_CHATOPS_ENABLED 2>/dev/null || true

output=$(validate_runtime_configuration 2>&1) && rc=$? || rc=$?
if [ "$rc" -eq 0 ]; then
    pass "no-arg call with clean env passes"
else
    fail "should pass with defaults when no file given" "exit code $rc, output: $output"
fi

# =============================================================================
# Test: Grafana provisioning preserves legacy .env values
# =============================================================================
run_test "Grafana provisioning preserves legacy env secrets"

legacy_env="$TMPDIR/grafana-legacy.env"
legacy_secrets="$TMPDIR/grafana-legacy-secrets"
cat > "$legacy_env" <<'EOF'
GRAFANA_ADMIN_PASSWORD=legacy-admin-password
GRAFANA_DATASOURCE_API_KEY=legacy-datasource-key
EOF

output=$(ensure_grafana_runtime_secrets "$legacy_env" "$legacy_secrets" 2>&1) && rc=$? || rc=$?
if [ "$rc" -eq 0 ] &&
   [ "$(cat "$legacy_secrets/grafana_admin_password")" = "legacy-admin-password" ] &&
   [ "$(cat "$legacy_secrets/grafana_datasource_api_key")" = "legacy-datasource-key" ] &&
   [ "$(_secret_file_mode "$legacy_secrets/grafana_admin_password")" = "600" ] &&
   [ "$(_secret_file_mode "$legacy_secrets/grafana_datasource_api_key")" = "600" ]; then
    pass "legacy env values are persisted without rotation"
else
    fail "legacy env values should be preserved" "rc=$rc, output: $output"
fi

# =============================================================================
# Test: Grafana provisioning restores env values from existing secret files
# =============================================================================
run_test "Grafana provisioning restores env from secret files"

file_env="$TMPDIR/grafana-files.env"
file_secrets="$TMPDIR/grafana-file-secrets"
mkdir -p "$file_secrets"
printf '%s\n' "file-admin-password" > "$file_secrets/grafana_admin_password"
printf '%s\n' "file-datasource-key" > "$file_secrets/grafana_datasource_api_key"
touch "$file_env"

output=$(ensure_grafana_runtime_secrets "$file_env" "$file_secrets" 2>&1) && rc=$? || rc=$?
if [ "$rc" -eq 0 ] &&
   grep -q '^GRAFANA_ADMIN_PASSWORD=file-admin-password$' "$file_env" &&
   grep -q '^GRAFANA_DATASOURCE_API_KEY=file-datasource-key$' "$file_env"; then
    pass "existing secret files repopulate missing env values"
else
    fail "secret files should repopulate env" "rc=$rc, output: $output"
fi

# =============================================================================
# Test: repeated Grafana provisioning never rotates generated values
# =============================================================================
run_test "Grafana provisioning is non-rotating"

generated_env="$TMPDIR/grafana-generated.env"
generated_secrets="$TMPDIR/grafana-generated-secrets"
touch "$generated_env"
ensure_grafana_runtime_secrets "$generated_env" "$generated_secrets" >/dev/null
first_admin=$(cat "$generated_secrets/grafana_admin_password")
first_datasource=$(cat "$generated_secrets/grafana_datasource_api_key")
output=$(ensure_grafana_runtime_secrets "$generated_env" "$generated_secrets" 2>&1) && rc=$? || rc=$?

if [ "$rc" -eq 0 ] &&
   [ -n "$first_admin" ] &&
   [ -n "$first_datasource" ] &&
   [ "$(cat "$generated_secrets/grafana_admin_password")" = "$first_admin" ] &&
   [ "$(cat "$generated_secrets/grafana_datasource_api_key")" = "$first_datasource" ]; then
    pass "repeated provisioning preserves both generated values"
else
    fail "repeated provisioning should not rotate secrets" "rc=$rc, output: $output"
fi

# =============================================================================
# Test: Grafana provisioning fails closed on mismatched sources
# =============================================================================
run_test "Grafana provisioning rejects mismatched env and secret file"

mismatch_env="$TMPDIR/grafana-mismatch.env"
mismatch_secrets="$TMPDIR/grafana-mismatch-secrets"
mkdir -p "$mismatch_secrets"
cat > "$mismatch_env" <<'EOF'
GRAFANA_ADMIN_PASSWORD=env-admin-password
GRAFANA_DATASOURCE_API_KEY=matching-datasource-key
EOF
printf '%s\n' "different-file-password" > "$mismatch_secrets/grafana_admin_password"
printf '%s\n' "matching-datasource-key" > "$mismatch_secrets/grafana_datasource_api_key"

output=$(ensure_grafana_runtime_secrets "$mismatch_env" "$mismatch_secrets" 2>&1) && rc=$? || rc=$?
if [ "$rc" -ne 0 ] &&
   grep -q '^GRAFANA_ADMIN_PASSWORD=env-admin-password$' "$mismatch_env" &&
   [ "$(cat "$mismatch_secrets/grafana_admin_password")" = "different-file-password" ]; then
    pass "mismatched sources fail without rotating either value"
else
    fail "mismatched sources should fail closed" "rc=$rc, output: $output"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "========================================="
echo " Results: $TESTS_PASSED/$TESTS_RUN passed, $TESTS_FAILED failed"
echo "========================================="

[ "$TESTS_FAILED" -eq 0 ]
