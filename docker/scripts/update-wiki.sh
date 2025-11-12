#!/bin/bash

# Exit on any error
set -e

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

log "Starting weekly wiki content update..."

# Track start time for duration calculation
START_TIME=$(date +%s)

# Names of the services/containers as defined in docker-compose.yml
# The default project name is 'docker' when running 'docker compose' from that directory
PROJECT_NAME="docker"
API_SERVICE_NAME="api"
API_CONTAINER_NAME="${PROJECT_NAME}-${API_SERVICE_NAME}-1"

# No additional path configuration needed - the unified wrapper handles all paths internally

# 1. Run the unified wiki update wrapper with JSON output (downloads and processes wiki dump with metrics instrumentation)
log "Step 1: Running unified wiki update (download + process with metrics)..."
OUTPUT=$(docker exec "$API_CONTAINER_NAME" python3 -m app.scripts.update_wiki --json-output 2>&1)
EXIT_CODE=$?

# Calculate duration
DURATION=$(($(date +%s) - START_TIME))

if [ $EXIT_CODE -ne 0 ]; then
  log "ERROR: Wiki update failed"
  log "Output: $OUTPUT"

  # Report failure metrics
  if command -v report_wiki_update_metrics >/dev/null 2>&1; then
      report_wiki_update_metrics "failure" 0 "$DURATION"
  fi

  exit 1
fi

log "Wiki update finished."
log "Output: $OUTPUT"

# Parse metrics from JSON output (more reliable than grep)
PAGES_PROCESSED=$(echo "$OUTPUT" | jq -r '.pages_processed // 0' 2>/dev/null || echo "0")

# Report success metrics
if command -v report_wiki_update_metrics >/dev/null 2>&1; then
    report_wiki_update_metrics "success" "$PAGES_PROCESSED" "$DURATION"
fi

# 2. Restart the API service to reload the data and rebuild the vector store
log "Step 2: Restarting API service to load new data..."
# This command is run from the scheduler, which can run docker commands.
# We find the container by name and restart it.
if ! docker restart "$API_CONTAINER_NAME"; then
  log "ERROR: Failed to restart API container $API_CONTAINER_NAME"
  exit 1
else
  log "API container $API_CONTAINER_NAME restarted successfully."
fi

log "Wiki content update pipeline finished successfully."

exit 0
