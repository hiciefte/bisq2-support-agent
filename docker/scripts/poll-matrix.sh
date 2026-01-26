#!/bin/bash
# Unified Training Sync Script
# Polls Bisq 2 and Matrix support conversations and processes them through the unified training pipeline
#
# Usage: ./poll-matrix.sh
# Expected to run via cron every 30 minutes

set -euo pipefail

# Configuration
API_HOST="${API_HOST:-api}"
API_PORT="${API_PORT:-8000}"
BISQ_SYNC_ENDPOINT="http://${API_HOST}:${API_PORT}/admin/training/sync/bisq"
MATRIX_SYNC_ENDPOINT="http://${API_HOST}:${API_PORT}/admin/training/sync/matrix"
TIMEOUT="${POLL_TIMEOUT:-60}"
LOG_PREFIX="[training-sync]"
ADMIN_API_KEY="${ADMIN_API_KEY:-}"

# Track overall success
SYNC_FAILED=0

# Logging functions
log_info() {
    echo "${LOG_PREFIX} INFO: $*" >&2
}

log_error() {
    echo "${LOG_PREFIX} ERROR: $*" >&2
}

log_success() {
    echo "${LOG_PREFIX} SUCCESS: $*" >&2
}

# Generic sync function
sync_source() {
    local source_name="$1"
    local endpoint="$2"

    # Skip if no admin API key configured
    if [[ -z "${ADMIN_API_KEY}" ]]; then
        log_info "ADMIN_API_KEY not set, skipping ${source_name} sync"
        return 0
    fi

    local start_time
    start_time=$(date +%s)

    log_info "Starting ${source_name} sync at $(date --iso-8601=seconds)"

    local http_code
    local response

    if ! response=$(curl -s -w "\n%{http_code}" \
        --max-time "${TIMEOUT}" \
        -X POST \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${ADMIN_API_KEY}" \
        "${endpoint}" 2>&1); then
        log_error "${source_name} sync curl failed: ${response}"
        return 1
    fi

    # Extract HTTP status code (last line)
    http_code=$(echo "${response}" | tail -n 1)
    # Extract response body (everything except last line)
    response=$(echo "${response}" | head -n -1)

    if [[ "${http_code}" -eq 200 ]]; then
        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))

        # Check for "skipped" status (Matrix not configured)
        if echo "${response}" | grep -q '"status"[[:space:]]*:[[:space:]]*"skipped"'; then
            log_info "${source_name} sync skipped: not configured"
            return 0
        fi

        log_success "${source_name} sync completed in ${duration}s"
        log_info "Response: ${response}"
        return 0
    elif [[ "${http_code}" -eq 503 ]]; then
        log_info "Unified pipeline service not initialized yet"
        return 0
    else
        log_error "${source_name} sync HTTP ${http_code}: ${response}"
        return 1
    fi
}

# Execute syncs
log_info "Starting unified training sync"

# Sync Bisq conversations
if ! sync_source "Bisq" "${BISQ_SYNC_ENDPOINT}"; then
    SYNC_FAILED=1
fi

# Sync Matrix conversations
if ! sync_source "Matrix" "${MATRIX_SYNC_ENDPOINT}"; then
    SYNC_FAILED=1
fi

if [[ "${SYNC_FAILED}" -eq 1 ]]; then
    log_error "One or more sync operations failed"
    exit 1
fi

log_success "Unified training sync complete"
exit 0
