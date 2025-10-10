#!/bin/bash
# Script to update FAQs and restart the API container
# Must be run in a context where 'docker' command is available

set -e  # Exit immediately if a command exits with a non-zero status

# Log function with timestamps
log() {
  echo "[$(date)] $1"
}

log "Starting FAQ update process..."

# Check if API container exists and is running
API_CONTAINER="docker-api-1"
if ! docker ps --format '{{.Names}}' | grep -q "$API_CONTAINER"; then
  log "ERROR: API container $API_CONTAINER not found or not running"
  exit 1
fi

# Run the FAQ extractor
log "Running FAQ extractor in API container..."
if ! docker exec $API_CONTAINER python -m app.scripts.extract_faqs; then
  log "ERROR: FAQ extraction failed"
  exit 1
fi

log "FAQ extraction finished."

log "Restarting API container ($API_CONTAINER) to load new FAQs..."
if ! docker restart $API_CONTAINER; then
  log "ERROR: Failed to restart API container $API_CONTAINER"
  # Optionally, decide if this should be a script-halting error
  # exit 1
else
  log "API container $API_CONTAINER restarted successfully."
fi

exit 0
