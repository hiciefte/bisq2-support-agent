#!/bin/bash
# Script to update FAQs and restart the API service
# This script should be run from the server where Docker is running

# Don't use set -e initially, so we can capture and log errors
# set -e

# Set the project directory - update this to your actual path on the server
PROJECT_DIR="/path/to/bisq2-support-agent"

# Set the Docker Compose file path
DOCKER_COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"

# Ensure logs directory exists
mkdir -p "$PROJECT_DIR/logs"

# Log file for the script
LOG_FILE="$PROJECT_DIR/logs/faq-updater.log"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
EXTRACT_LOG_FILE="$PROJECT_DIR/logs/faq-extractor-$TIMESTAMP.log"

# Function to log messages
log() {
  echo "$(date): $1" | tee -a "$LOG_FILE"
}

# Function to log and exit on error
error_exit() {
  log "ERROR: $1"
  log "Script failed. See logs for details."
  exit 1
}

# Change to the project directory
cd "$PROJECT_DIR" || error_exit "Failed to change to directory $PROJECT_DIR"

log "Starting FAQ update process"
log "Current directory: $(pwd)"
log "Running as user: $(whoami)"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  error_exit "Docker is not running or current user doesn't have permission to use Docker"
fi

# Check if Docker Compose is available
if ! docker compose version > /dev/null 2>&1; then
  error_exit "Docker Compose is not available"
fi

# Check if .env file exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
  error_exit ".env file not found in $PROJECT_DIR"
fi

# Check if Docker Compose file exists
if [ ! -f "$DOCKER_COMPOSE_FILE" ]; then
  error_exit "Docker Compose file not found at $DOCKER_COMPOSE_FILE"
fi

log "Using .env file from $PROJECT_DIR"
log "Using Docker Compose file: $DOCKER_COMPOSE_FILE"
log "Checking Docker Compose configuration..."

# Validate Docker Compose configuration
docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" config > "$PROJECT_DIR/logs/docker-compose-config-$TIMESTAMP.log" 2>&1
if [ $? -ne 0 ]; then
  error_exit "Docker Compose configuration is invalid. Check $PROJECT_DIR/logs/docker-compose-config-$TIMESTAMP.log"
fi

log "Docker Compose configuration is valid"
log "Checking if faq-extractor service is defined..."

# Check if faq-extractor service is defined
if ! docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" config --services | grep -q "faq-extractor"; then
  error_exit "faq-extractor service is not defined in Docker Compose configuration"
fi

log "faq-extractor service is defined"
log "Running FAQ extractor"

# Capture both stdout and stderr, and log the output
log "Command: docker compose -f \"$DOCKER_COMPOSE_FILE\" --env-file \"$PROJECT_DIR/.env\" run --rm faq-extractor python -m app.scripts.extract_faqs"
docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" run --rm faq-extractor python -m app.scripts.extract_faqs > "$EXTRACT_LOG_FILE" 2>&1
EXTRACT_STATUS=$?

log "FAQ extractor command completed with status: $EXTRACT_STATUS"

if [ $EXTRACT_STATUS -ne 0 ]; then
  log "ERROR: FAQ extraction failed with status code $EXTRACT_STATUS"
  log "Last 20 lines of log:"
  tail -n 20 "$EXTRACT_LOG_FILE" | while read -r line; do log "  $line"; done
  error_exit "Check the full logs at $EXTRACT_LOG_FILE for details"
fi

log "FAQ extraction complete"
log "Extraction log saved to $EXTRACT_LOG_FILE"

# Wait a moment to ensure files are written
log "Waiting for files to be written..."
sleep 5

# Check if API service is running
log "Checking if API service is running..."
if ! docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" ps --services --filter "status=running" | grep -q "api"; then
  log "WARNING: API service is not running. Starting it instead of restarting."
  docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" up -d api > "$PROJECT_DIR/logs/api-start-$TIMESTAMP.log" 2>&1
  START_STATUS=$?
  
  if [ $START_STATUS -ne 0 ]; then
    error_exit "Failed to start API service. Check $PROJECT_DIR/logs/api-start-$TIMESTAMP.log"
  fi
  
  log "API service started"
else
  # Restart the API service to load the new FAQs
  log "Restarting API service"
  docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" restart api > "$PROJECT_DIR/logs/api-restart-$TIMESTAMP.log" 2>&1
  RESTART_STATUS=$?

  if [ $RESTART_STATUS -ne 0 ]; then
    error_exit "API restart failed with status code $RESTART_STATUS. Check $PROJECT_DIR/logs/api-restart-$TIMESTAMP.log"
  fi
  
  log "API service restarted"
fi

# Wait for API to start up
log "Waiting for API to start up..."
sleep 10

# Simple health check
log "Performing API health check"
if curl -s http://localhost:8000/health | grep -q "healthy"; then
  log "API health check passed"
else
  log "WARNING: API health check failed"
  log "Getting API container logs for debugging"
  docker compose -f "$DOCKER_COMPOSE_FILE" --env-file "$PROJECT_DIR/.env" logs --tail=50 api > "$PROJECT_DIR/logs/api-logs-$TIMESTAMP.log" 2>&1
  log "API logs saved to $PROJECT_DIR/logs/api-logs-$TIMESTAMP.log"
  log "The API may not be fully operational"
fi

log "FAQ update process completed successfully" 