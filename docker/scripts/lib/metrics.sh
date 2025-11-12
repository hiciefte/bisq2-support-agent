#!/bin/bash
# Metrics reporting functions for scheduled tasks
# These functions send metrics to the API's /admin/metrics endpoints
#
# Requirements:
#   - jq: JSON processor (install via: apt-get install jq)
#   - ADMIN_API_KEY: Environment variable for API authentication
#   - curl: HTTP client (usually pre-installed)

# Configuration
API_HOST="${API_HOST:-api:8000}"
METRICS_ENDPOINT="http://$API_HOST/admin/metrics"

# Validate required dependencies and environment variables
validate_metrics_environment() {
    local missing_deps=()

    # Check for jq
    if ! command -v jq >/dev/null 2>&1; then
        missing_deps+=("jq")
    fi

    # Check for curl
    if ! command -v curl >/dev/null 2>&1; then
        missing_deps+=("curl")
    fi

    # Check for ADMIN_API_KEY
    if [ -z "${ADMIN_API_KEY}" ]; then
        echo "ERROR: ADMIN_API_KEY environment variable is not set" >&2
        echo "Metrics cannot be reported without authentication" >&2
        return 1
    fi

    # Report missing dependencies
    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo "ERROR: Missing required dependencies: ${missing_deps[*]}" >&2
        echo "Install with: apt-get install ${missing_deps[*]}" >&2
        return 1
    fi

    return 0
}

# Report FAQ extraction metrics
report_faq_extraction_metrics() {
    # Validate environment before proceeding
    if ! validate_metrics_environment; then
        return 1
    fi

    local status="$1"              # success or failure
    local messages_processed="${2:-0}"
    local faqs_generated="${3:-0}"
    local duration="${4:-}"        # optional, in seconds

    local payload
    payload=$(jq -n \
        --arg status "$status" \
        --argjson messages "$messages_processed" \
        --argjson faqs "$faqs_generated" \
        --arg dur "$duration" \
        '{
            status: $status,
            messages_processed: $messages,
            faqs_generated: $faqs,
            duration: (if $dur != "" then ($dur | tonumber) else null end)
        }')

    curl -s -X POST "$METRICS_ENDPOINT/faq-extraction" \
        -H "X-API-Key: ${ADMIN_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        || echo "Warning: Failed to report FAQ extraction metrics" >&2
}

# Report wiki update metrics
report_wiki_update_metrics() {
    # Validate environment before proceeding
    if ! validate_metrics_environment; then
        return 1
    fi

    local status="$1"          # success or failure
    local pages_processed="${2:-0}"
    local duration="${3:-}"    # optional, in seconds

    local payload
    payload=$(jq -n \
        --arg status "$status" \
        --argjson pages "$pages_processed" \
        --arg dur "$duration" \
        '{
            status: $status,
            pages_processed: $pages,
            duration: (if $dur != "" then ($dur | tonumber) else null end)
        }')

    curl -s -X POST "$METRICS_ENDPOINT/wiki-update" \
        -H "X-API-Key: ${ADMIN_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        || echo "Warning: Failed to report wiki update metrics" >&2
}

# Report feedback processing metrics
report_feedback_processing_metrics() {
    # Validate environment before proceeding
    if ! validate_metrics_environment; then
        return 1
    fi

    local status="$1"             # success or failure
    local entries_processed="${2:-0}"
    local duration="${3:-}"       # optional, in seconds

    local payload
    payload=$(jq -n \
        --arg status "$status" \
        --argjson entries "$entries_processed" \
        --arg dur "$duration" \
        '{
            status: $status,
            entries_processed: $entries,
            duration: (if $dur != "" then ($dur | tonumber) else null end)
        }')

    curl -s -X POST "$METRICS_ENDPOINT/feedback-processing" \
        -H "X-API-Key: ${ADMIN_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        || echo "Warning: Failed to report feedback processing metrics" >&2
}

# Example usage:
# report_faq_extraction_metrics "success" 42 5 123.45
# report_wiki_update_metrics "failure" 0 89.12
# report_feedback_processing_metrics "success" 25 15.67
