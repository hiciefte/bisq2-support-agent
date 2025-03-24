#!/bin/bash
# Script to process feedback data
# Must be run in a context where 'docker' command is available

set -e  # Exit immediately if a command exits with a non-zero status

# Log function with timestamps
log() {
  echo "[$(date)] $1"
}

log "Starting weekly feedback processing..."

# Check if API container exists and is running
API_CONTAINER="docker-api-1"
if ! docker ps --format '{{.Names}}' | grep -q "$API_CONTAINER"; then
  log "ERROR: API container $API_CONTAINER not found or not running"
  exit 1
fi

# Run the feedback processor
log "Running feedback processor in API container..."
if ! docker exec $API_CONTAINER python -m app.scripts.process_feedback; then
  log "ERROR: Feedback processing failed"
  exit 1
fi

log "Feedback processing completed successfully"
exit 0 