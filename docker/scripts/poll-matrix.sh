#!/bin/bash
# Matrix Polling Script
# Polls Matrix support channels for new questions via shadow mode endpoint
#
# Usage: ./poll-matrix.sh
# Expected to run via cron every 30 minutes

set -euo pipefail

# Configuration
API_HOST="${API_HOST:-api}"
API_PORT="${API_PORT:-8000}"
API_ENDPOINT="http://${API_HOST}:${API_PORT}/admin/shadow-mode/poll"
TIMEOUT="${POLL_TIMEOUT:-30}"
LOG_PREFIX="[matrix-poll]"

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

# Main polling function
poll_matrix() {
    local start_time
    start_time=$(date +%s)

    log_info "Starting Matrix poll at $(date --iso-8601=seconds)"

    # Call API endpoint with timeout and error handling
    local http_code
    local response

    if ! response=$(curl -s -w "\n%{http_code}" \
        --max-time "${TIMEOUT}" \
        -X POST \
        -H "Content-Type: application/json" \
        "${API_ENDPOINT}" 2>&1); then
        log_error "curl failed: ${response}"
        return 1
    fi

    # Extract HTTP status code (last line)
    http_code=$(echo "${response}" | tail -n 1)
    # Extract response body (everything except last line)
    response=$(echo "${response}" | head -n -1)

    # Check HTTP status
    if [[ "${http_code}" -eq 200 ]]; then
        local end_time
        end_time=$(date +%s)
        local duration=$((end_time - start_time))

        log_success "Poll completed in ${duration}s"
        log_info "Response: ${response}"
        return 0
    else
        log_error "HTTP ${http_code}: ${response}"
        return 1
    fi
}

# Execute poll with error handling
if poll_matrix; then
    exit 0
else
    exit 1
fi
