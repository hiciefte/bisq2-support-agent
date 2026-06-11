#!/bin/bash
set -euo pipefail

# Refresh Bisq live-data readiness metrics inside the API process.
#
# The Prometheus BisqReadinessChecksStale alert watches the timestamp that is
# updated by MCP live-data probes. Calling the existing internal MCP endpoint
# keeps that timestamp fresh without adding another public API route.

LOG_PREFIX="[Bisq Readiness Check]"
API_HOST="${API_HOST:-api}"
API_PORT="${API_PORT:-8000}"
API_URL="${BISQ_READINESS_API_URL:-http://${API_HOST}:${API_PORT}}"
BISQ_READINESS_CURRENCY="${BISQ_READINESS_CURRENCY:-EUR}"
BISQ_READINESS_DIRECTION="${BISQ_READINESS_DIRECTION:-SELL}"
CURL_TIMEOUT="${BISQ_READINESS_TIMEOUT_SECONDS:-30}"

log() {
    echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

call_mcp_tool() {
    local tool_name="$1"
    local args_json="$2"
    local payload
    local response
    local error_message
    local content_prefix

    payload=$(jq -n \
        --arg tool_name "$tool_name" \
        --argjson args "$args_json" \
        '{
            jsonrpc: "2.0",
            id: $tool_name,
            method: "tools/call",
            params: {
                name: $tool_name,
                arguments: $args
            }
        }')

    if ! response=$(curl -fsS --max-time "$CURL_TIMEOUT" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$API_URL/mcp"); then
        log "FAIL: $tool_name request failed"
        return 1
    fi

    if ! error_message=$(echo "$response" | jq -r '.error.message // empty' 2>/dev/null); then
        log "FAIL: $tool_name returned non-JSON response"
        return 1
    fi
    if [ -n "$error_message" ]; then
        log "FAIL: $tool_name returned MCP error: $error_message"
        return 1
    fi

    if ! echo "$response" | jq -e '.result.content[0].text | type == "string" and length > 0' >/dev/null; then
        log "FAIL: $tool_name returned no text content"
        return 1
    fi

    content_prefix=$(echo "$response" | jq -r '.result.content[0].text' | tr '\n' ' ' | cut -c 1-140)
    log "PASS: $tool_name refreshed readiness metrics (${content_prefix})"
}

main() {
    local failures=0
    local market_args
    local offerbook_args

    log "Starting Bisq readiness check via $API_URL/mcp"

    market_args=$(jq -n --arg currency "$BISQ_READINESS_CURRENCY" '{currency: $currency}')
    offerbook_args=$(jq -n \
        --arg currency "$BISQ_READINESS_CURRENCY" \
        --arg direction "$BISQ_READINESS_DIRECTION" \
        '{currency: $currency, direction: $direction}')

    call_mcp_tool "get_market_prices" "$market_args" || failures=$((failures + 1))
    call_mcp_tool "get_offerbook" "$offerbook_args" || failures=$((failures + 1))

    if [ "$failures" -gt 0 ]; then
        log "Bisq readiness check failed ($failures probe failure(s))"
        return 1
    fi

    log "Bisq readiness check complete"
}

main "$@"
