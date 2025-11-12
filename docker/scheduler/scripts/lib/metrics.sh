#!/bin/bash
# Metrics reporting functions for scheduled tasks
# These functions send metrics to the API's /admin/metrics endpoints

# Configuration
API_HOST="${API_HOST:-api:8000}"
METRICS_ENDPOINT="http://$API_HOST/admin/metrics"

# Report FAQ extraction metrics
report_faq_extraction_metrics() {
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
