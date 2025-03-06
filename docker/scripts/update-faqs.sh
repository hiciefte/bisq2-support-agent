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

# Run the FAQ extractor
log "Running FAQ extractor"
docker compose exec -T faq-extractor python -m app.scripts.extract_faqs

log "FAQ extraction complete"

# Wait a moment to ensure files are written
sleep 5

# Restart the API service to load the new FAQs
log "Restarting API service"
docker compose restart api

log "API service restarted"
log "FAQ update process completed successfully" 