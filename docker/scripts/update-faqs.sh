#!/bin/bash
# Script to update FAQs and restart the API service
# This script should be run from the server where Docker is running

set -e  # Exit immediately if a command exits with a non-zero status

# Set the project directory - update this to your actual path on the server
PROJECT_DIR="/path/to/bisq2-support-agent"

# Ensure logs directory exists
mkdir -p "$PROJECT_DIR/logs"

# Log file for the script
LOG_FILE="$PROJECT_DIR/logs/faq-updater.log"

# Function to log messages
log() {
  echo "$(date): $1" | tee -a "$LOG_FILE"
}

# Change to the project directory
cd "$PROJECT_DIR"

log "Starting FAQ update process"

# Check if .env file exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
  log "ERROR: .env file not found in $PROJECT_DIR"
  log "Please ensure the .env file exists with the required environment variables"
  exit 1
fi

log "Using .env file from $PROJECT_DIR"

# Run the FAQ extractor as a new container
log "Running FAQ extractor"
# Capture both stdout and stderr, and log the output
docker compose --env-file "$PROJECT_DIR/.env" run --rm faq-extractor python -m app.scripts.extract_faqs > "$PROJECT_DIR/logs/faq-extractor-$(date +%Y%m%d-%H%M%S).log" 2>&1
EXTRACT_STATUS=$?

if [ $EXTRACT_STATUS -ne 0 ]; then
  log "ERROR: FAQ extraction failed with status code $EXTRACT_STATUS"
  log "Check the logs at $PROJECT_DIR/logs/faq-extractor-$(date +%Y%m%d-%H%M%S).log for details"
  exit 1
fi

log "FAQ extraction complete"

# Wait a moment to ensure files are written
sleep 5

# Restart the API service to load the new FAQs
log "Restarting API service"
docker compose --env-file "$PROJECT_DIR/.env" restart api > "$PROJECT_DIR/logs/api-restart-$(date +%Y%m%d-%H%M%S).log" 2>&1
RESTART_STATUS=$?

if [ $RESTART_STATUS -ne 0 ]; then
  log "ERROR: API restart failed with status code $RESTART_STATUS"
  log "Check the logs for details"
  exit 1
fi

log "API service restarted"

# Wait for API to start up
sleep 10

# Simple health check
log "Performing API health check"
if curl -s http://localhost:8000/health | grep -q "healthy"; then
  log "API health check passed"
else
  log "WARNING: API health check failed"
  log "The API may not be fully operational"
fi

log "FAQ update process completed successfully" 