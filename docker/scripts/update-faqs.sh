#!/bin/bash
# Script to update FAQs and restart the API container
# Must be run in a context where 'docker' command is available

set -e  # Exit immediately if a command exits with a non-zero status

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source metrics reporting functions
if [ -f "$SCRIPT_DIR/lib/metrics.sh" ]; then
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/lib/metrics.sh"
fi

# Log function with timestamps
log() {
  echo "[$(date)] $1"
}

log "Starting FAQ update process..."

# Track start time for duration calculation
START_TIME=$(date +%s)

# Check if API container exists and is running
API_CONTAINER="docker-api-1"
if ! docker ps --format '{{.Names}}' | grep -q "$API_CONTAINER"; then
  log "ERROR: API container $API_CONTAINER not found or not running"

  # Report failure metrics
  if command -v report_faq_extraction_metrics >/dev/null 2>&1; then
      DURATION=$(($(date +%s) - START_TIME))
      report_faq_extraction_metrics "failure" 0 0 "$DURATION"
  fi

  exit 1
fi

# Run the FAQ extractor with JSON output and capture output
log "Running FAQ extractor in API container..."
OUTPUT=$(docker exec $API_CONTAINER python -m app.scripts.extract_faqs --json-output 2>&1)
EXIT_CODE=$?

# Calculate duration
DURATION=$(($(date +%s) - START_TIME))

if [ $EXIT_CODE -ne 0 ]; then
  log "ERROR: FAQ extraction failed"
  log "Output: $OUTPUT"

  # Report failure metrics
  if command -v report_faq_extraction_metrics >/dev/null 2>&1; then
      report_faq_extraction_metrics "failure" 0 0 "$DURATION"
  fi

  exit 1
fi

log "FAQ extraction finished."
log "Output: $OUTPUT"

# Extract and validate JSON metrics using shared helper
if ! extract_json_metrics "$OUTPUT"; then
  log "ERROR: Failed to extract JSON metrics from output"

  # Report failure metrics - cannot parse results
  if command -v report_faq_extraction_metrics >/dev/null 2>&1; then
      report_faq_extraction_metrics "failure" 0 0 "$DURATION"
  fi

  exit 1
fi

# Parse metrics from extracted JSON (EXTRACTED_JSON is set by extract_json_metrics)
MESSAGES_PROCESSED=$(echo "$EXTRACTED_JSON" | jq -r '.messages_processed')
FAQS_GENERATED=$(echo "$EXTRACTED_JSON" | jq -r '.faqs_generated')

if [ "$MESSAGES_PROCESSED" = "null" ] || [ "$FAQS_GENERATED" = "null" ]; then
  log "ERROR: Missing required fields in JSON (messages_processed or faqs_generated)"

  # Report failure metrics - invalid JSON structure
  if command -v report_faq_extraction_metrics >/dev/null 2>&1; then
      report_faq_extraction_metrics "failure" 0 0 "$DURATION"
  fi

  exit 1
fi

# Report success metrics only when JSON extraction and parsing succeed
if command -v report_faq_extraction_metrics >/dev/null 2>&1; then
    report_faq_extraction_metrics "success" "$MESSAGES_PROCESSED" "$FAQS_GENERATED" "$DURATION"
fi

log "Restarting API container ($API_CONTAINER) to load new FAQs..."
if ! docker restart $API_CONTAINER; then
  log "ERROR: Failed to restart API container $API_CONTAINER"
  exit 1
else
  log "API container $API_CONTAINER restarted successfully."
fi

exit 0
