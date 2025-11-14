#!/bin/bash
# Script to process feedback data
# Must be run in a context where 'docker' command is available

set -e  # Exit immediately if a command exits with a non-zero status

# Source metrics library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/metrics.sh"

# Log function with timestamps
log() {
  echo "[$(date)] $1"
}

log "Starting weekly feedback processing..."

# Check if API container exists and is running
API_CONTAINER="docker-api-1"
if ! docker ps --format '{{.Names}}' | grep -q "$API_CONTAINER"; then
  log "ERROR: API container $API_CONTAINER not found or not running"
  report_feedback_processing_metrics "failure" 0 0
  exit 1
fi

# Record start time for duration calculation
START_TIME=$(date +%s)

# Run the feedback processor and capture output
log "Running feedback processor in API container..."
OUTPUT=$(docker exec $API_CONTAINER python -m app.scripts.process_feedback 2>&1)
EXIT_CODE=$?

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Check if execution succeeded
if [ $EXIT_CODE -ne 0 ]; then
  log "ERROR: Feedback processing failed"
  echo "$OUTPUT"
  report_feedback_processing_metrics "failure" 0 "$DURATION"
  exit 1
fi

# Extract metrics from output
log "Feedback processing completed successfully"
echo "$OUTPUT"

# Parse processed entries count from output
# Expected format from app.scripts.process_feedback: "Processed <N> entries"
ENTRIES_PROCESSED=$(echo "$OUTPUT" | grep -o 'Processed [0-9]* entries' | grep -o '[0-9]*' | tail -1 || echo "0")

# Validate that we got a valid number
if ! [[ "$ENTRIES_PROCESSED" =~ ^[0-9]+$ ]]; then
  log "WARNING: Could not parse entry count from feedback processor output"
  ENTRIES_PROCESSED="0"
fi

# Report metrics
report_feedback_processing_metrics "success" "$ENTRIES_PROCESSED" "$DURATION"

exit 0
