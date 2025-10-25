#!/bin/bash
set -euo pipefail

# RAG Health Check Script for Healthchecks.io Integration
#
# This script checks RAG metrics from Prometheus and pings healthchecks.io
# if all checks pass. If any check fails, the ping is skipped, causing
# healthchecks.io to alert after Period + Grace Time.
#
# Configuration:
# - Healthchecks.io Period: 15 minutes
# - Healthchecks.io Grace Time: 5 minutes
# - Total alert time: 20 minutes
#
# Run via cron: */15 * * * * /path/to/rag-health-check.sh

LOG_PREFIX="[RAG Health Check]"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://prometheus:9090}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-https://hc-ping.com/27867359-f4f3-4e22-8f46-8d18a73cf219}"

# Alert thresholds (matching unified-monitoring-plan.md)
MAX_ERROR_RATE=0.05          # 5% error rate
MAX_P95_LATENCY=5.0          # 5 seconds
MAX_COST_PER_REQUEST=0.002   # $0.002 per request

# =============================================================================
# Helper Functions
# =============================================================================

log() {
    echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

query_prometheus() {
    local query="$1"
    local result

    result=$(curl -s --max-time 10 \
        "${PROMETHEUS_URL}/api/v1/query" \
        --data-urlencode "query=${query}" \
        | jq -r '.data.result[0].value[1] // "null" | if . == "NaN" then "null" else . end')

    echo "$result"
}

check_metric() {
    local metric_name="$1"
    local threshold="$2"
    local operator="$3"  # "gt" (greater than) or "lt" (less than)
    local value

    value=$(query_prometheus "$metric_name")

    if [ "$value" = "null" ] || [ "$value" = "" ]; then
        log "WARNING: Metric '$metric_name' returned null or empty (insufficient data)"
        # Treat missing data as PASS - don't fail on metrics that haven't been collected yet
        return 0
    fi

    case "$operator" in
        gt)
            if (( $(echo "$value > $threshold" | bc -l) )); then
                log "FAIL: $metric_name = $value (threshold: <= $threshold)"
                return 1
            fi
            ;;
        lt)
            if (( $(echo "$value < $threshold" | bc -l) )); then
                log "FAIL: $metric_name = $value (threshold: >= $threshold)"
                return 1
            fi
            ;;
    esac

    log "PASS: $metric_name = $value"
    return 0
}

# =============================================================================
# RAG Health Checks
# =============================================================================

check_rag_error_rate() {
    log "Checking RAG error rate..."
    check_metric "rag_error_rate" "$MAX_ERROR_RATE" "gt"
}

check_rag_latency() {
    log "Checking RAG P95 latency..."
    local query='histogram_quantile(0.95, rate(rag_stage_latency_seconds_bucket[10m]))'
    check_metric "$query" "$MAX_P95_LATENCY" "gt"
}

check_rag_cost() {
    log "Checking RAG cost per request..."
    local query='avg(rate(rag_cost_per_request_usd_sum[5m]) / rate(rag_cost_per_request_usd_count[5m]))'
    check_metric "$query" "$MAX_COST_PER_REQUEST" "gt"
}

check_rag_request_rate() {
    log "Checking RAG is receiving requests..."
    local query='rate(rag_requests_total[5m])'
    local value

    value=$(query_prometheus "$query")

    if [ "$value" = "null" ] || [ "$value" = "0" ]; then
        log "WARNING: No RAG requests in the last 5 minutes (might be low traffic period)"
        # Don't fail on this - low traffic is not an error
        return 0
    fi

    log "PASS: RAG request rate = $value requests/sec"
    return 0
}

# =============================================================================
# Main Health Check Logic
# =============================================================================

main() {
    log "Starting RAG health check"

    local checks_passed=0
    local checks_failed=0

    # Run all checks
    if check_rag_error_rate; then
        checks_passed=$((checks_passed + 1))
    else
        checks_failed=$((checks_failed + 1))
    fi

    if check_rag_latency; then
        checks_passed=$((checks_passed + 1))
    else
        checks_failed=$((checks_failed + 1))
    fi

    if check_rag_cost; then
        checks_passed=$((checks_passed + 1))
    else
        checks_failed=$((checks_failed + 1))
    fi

    if check_rag_request_rate; then
        checks_passed=$((checks_passed + 1))
    else
        checks_failed=$((checks_failed + 1))
    fi

    # Summary
    log "Health check complete: $checks_passed passed, $checks_failed failed"

    # Ping healthchecks.io only if all checks passed
    if [ $checks_failed -eq 0 ]; then
        log "All checks passed - pinging healthchecks.io"

        if curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL" > /dev/null 2>&1; then
            log "✓ Healthchecks.io ping successful"
            return 0
        else
            log "ERROR: Failed to ping healthchecks.io (network issue?)"
            return 1
        fi
    else
        log "⚠️  Checks failed - skipping healthchecks.io ping (alert will fire)"
        return 1
    fi
}

# =============================================================================
# Execute
# =============================================================================

main "$@"
