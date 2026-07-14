#!/bin/bash
# Shared client for narrowly scoped internal scheduler endpoints.

# shellcheck source=runtime-secret.sh
. /scripts/lib/runtime-secret.sh

if [ -d "/run/bisq-secrets/scheduler" ]; then
    load_runtime_secret_from_file \
        "SCHEDULER_API_TOKEN" \
        "/run/bisq-secrets/scheduler/scheduler_api_token"
fi

SCHEDULER_API_HOST="${API_HOST:-api}"
SCHEDULER_API_PORT="${API_PORT:-8000}"
SCHEDULER_API_BASE_URL="${SCHEDULER_API_BASE_URL:-http://${SCHEDULER_API_HOST}:${SCHEDULER_API_PORT}}"

scheduler_api_post() {
    local path="$1"
    local timeout_seconds="${2:-300}"

    if [ -z "${SCHEDULER_API_TOKEN:-}" ]; then
        echo "ERROR: SCHEDULER_API_TOKEN is not configured" >&2
        return 1
    fi

    curl --fail --silent --show-error \
        --max-time "$timeout_seconds" \
        --request POST \
        --header "X-Scheduler-Token: ${SCHEDULER_API_TOKEN}" \
        "${SCHEDULER_API_BASE_URL}${path}"
}
