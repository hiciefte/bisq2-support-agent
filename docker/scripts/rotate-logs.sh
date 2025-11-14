#!/bin/bash
# Script to rotate log files for the Bisq Support Agent
# This script should be run periodically (e.g., monthly) via cron

set -e  # Exit immediately if a command exits with a non-zero status

# Set the project directory - update this to your actual path on the server
PROJECT_DIR="/path/to/bisq2-support-agent"

# Log directory
LOG_DIR="$PROJECT_DIR/logs"

# Maximum number of log files to keep per type
MAX_LOG_FILES=5

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Function to rotate a specific log file
rotate_log() {
  local log_file="$1"
  local base_name="$(basename "$log_file" .log)"

  if [ -f "$log_file" ] && [ -s "$log_file" ]; then
    local timestamp=$(date +"%Y%m%d")
    echo "Rotating $log_file to ${log_file%.log}-$timestamp.log"

    # Move current log to timestamped version
    mv "$log_file" "${log_file%.log}-$timestamp.log"

    # Create a new empty log file
    touch "$log_file"

    # Keep only the most recent logs
    ls -t "$LOG_DIR"/$base_name-*.log 2>/dev/null | tail -n +$((MAX_LOG_FILES+1)) | xargs -r rm

    echo "Rotation complete for $log_file"
  else
    echo "Log file $log_file does not exist or is empty. Skipping rotation."
  fi
}

echo "Starting log rotation at $(date)"

# Rotate FAQ updater logs
rotate_log "$LOG_DIR/faq-updater.log"

# Add more log files to rotate as needed
# rotate_log "$LOG_DIR/another-log-file.log"

echo "Log rotation completed at $(date)"
