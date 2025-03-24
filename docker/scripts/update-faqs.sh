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

# Wait briefly for files to be written
sleep 2

# Restart the API container
log "Restarting API container to load new FAQs..."
if ! docker restart $API_CONTAINER; then
  log "ERROR: Failed to restart API container"
  exit 1
fi

# Wait for API to start up
log "Waiting for API to become available..."
sleep 5

# Health check
log "Performing API health check..."
MAX_RETRIES=5
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if docker exec $API_CONTAINER curl -s http://localhost:8000/health | grep -q "healthy"; then
    log "API health check passed"
    log "FAQ update process completed successfully"
    exit 0
  else
    RETRY_COUNT=$((RETRY_COUNT+1))
    log "Health check attempt $RETRY_COUNT/$MAX_RETRIES failed, retrying in 5 seconds..."
    sleep 5
  fi
done

log "WARNING: API health check failed after $MAX_RETRIES attempts"
log "FAQ update completed but API may not be fully operational"
exit 1 