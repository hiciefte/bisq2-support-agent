#!/bin/bash
set -euo pipefail

# Unified training sync for Bisq and Matrix support conversations.
# shellcheck source=lib/scheduler-api.sh
source /scripts/lib/scheduler-api.sh

LOG_PREFIX="[training-sync]"
SYNC_FAILED=0

log_info() {
    echo "${LOG_PREFIX} INFO: $*" >&2
}

log_error() {
    echo "${LOG_PREFIX} ERROR: $*" >&2
}

log_success() {
    echo "${LOG_PREFIX} SUCCESS: $*" >&2
}

sync_source() {
    local source_name="$1"
    local endpoint_path="$2"
    local response

    log_info "Starting ${source_name} sync at $(date --iso-8601=seconds)"
    if ! response=$(scheduler_api_post "$endpoint_path" 300); then
        log_error "${source_name} sync request failed"
        return 1
    fi

    if echo "$response" | grep -q '"status"[[:space:]]*:[[:space:]]*"skipped"'; then
        log_info "${source_name} sync skipped: not configured"
        return 0
    fi

    log_success "${source_name} sync completed"
    log_info "Response: $response"
}

log_info "Starting unified training sync"

if ! sync_source "Bisq" "/internal/scheduler/training-sync/bisq"; then
    SYNC_FAILED=1
fi

if ! sync_source "Matrix" "/internal/scheduler/training-sync/matrix"; then
    SYNC_FAILED=1
fi

if [ "$SYNC_FAILED" -eq 1 ]; then
    log_error "One or more sync operations failed"
    exit 1
fi

log_success "Unified training sync complete"
