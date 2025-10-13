#!/bin/bash
#
# Docker System Cleanup Script
# This script safely cleans Docker resources to prevent disk space issues
#
set -Eeuo pipefail
trap 'log "ERROR: Line $LINENO failed with exit code $?."' ERR

# Log file setup with fallback for non-root execution
LOG_DIR="/var/log/bisq-support"
if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
  LOG_DIR="/tmp/bisq-support"
  mkdir -p "$LOG_DIR"
fi
LOG_FILE="$LOG_DIR/docker-cleanup-$(date +%Y%m%d).log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Determine docker compose command (docker compose vs docker-compose)
DOCKER_COMPOSE="docker compose"
$DOCKER_COMPOSE version >> /dev/null 2>&1 || DOCKER_COMPOSE="docker-compose"

# Log function
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Check if cleanup is needed (>75% disk usage)
check_disk_usage() {
  local threshold=75
  local usage
  usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')

  # Ensure numeric usage to avoid integer comparison errors
  if ! [[ "$usage" =~ ^[0-9]+$ ]]; then
    log "ERROR: Failed to parse disk usage: '$usage'"
    return 1
  fi

  if [ "$usage" -gt "$threshold" ]; then
    log "Disk usage is at ${usage}%, above threshold of ${threshold}%. Proceeding with cleanup."
    return 0
  else
    log "Disk usage is at ${usage}%, below threshold of ${threshold}%. Skipping aggressive cleanup."
    return 1
  fi
}

# Start logging
log "Starting Docker cleanup process"
cd "$PROJECT_DIR" || { log "ERROR: Failed to change to project directory"; exit 1; }

# Stop containers if disk space is critical (>90%)
critical_usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')

# Ensure numeric critical_usage to avoid integer comparison errors
if ! [[ "$critical_usage" =~ ^[0-9]+$ ]]; then
  log "ERROR: Failed to parse critical disk usage: '$critical_usage'. Skipping container stop."
  critical_usage=0  # Set to 0 to prevent restart logic from triggering
elif [ "$critical_usage" -gt 90 ]; then
  log "CRITICAL: Disk usage at ${critical_usage}%. Stopping all containers to prevent data loss."
  log "Running: $DOCKER_COMPOSE -f docker/docker-compose.yml down"
  $DOCKER_COMPOSE -f docker/docker-compose.yml down >> "$LOG_FILE" 2>&1
fi

# Remove stopped containers
log "Removing stopped containers"
docker container prune -f >> "$LOG_FILE" 2>&1

# Remove unused images
log "Removing dangling images"
docker image prune -f >> "$LOG_FILE" 2>&1

# If disk usage is high, perform more aggressive cleanup
if check_disk_usage; then
  log "Performing aggressive cleanup due to high disk usage"

  # Remove unused images older than 24 hours (not just dangling ones)
  log "Removing unused images older than 24 hours"
  docker image prune -a -f --filter "until=24h" >> "$LOG_FILE" 2>&1

  # Remove unused build cache older than 24 hours to preserve recent builds
  log "Removing build cache older than 24 hours"
  docker builder prune -f --all --filter "until=24h" >> "$LOG_FILE" 2>&1 || \
    log "builder prune not supported; skipping"

  # Remove unused networks
  log "Removing unused networks"
  docker network prune -f >> "$LOG_FILE" 2>&1

  # Prune volumes carefully (only if not attached to any container)
  log "Removing unused volumes"
  docker volume prune -f >> "$LOG_FILE" 2>&1

  # Clean up Docker container logs
  log "Cleaning up Docker logs"
  if [ -d /var/lib/docker/containers ]; then
    find /var/lib/docker/containers -type f -name "*.log" -exec truncate -s 0 {} \; >> "$LOG_FILE" 2>&1
    log "Docker logs have been truncated"
  fi

  # Check disk usage after cleanup
  after_usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')
  log "Disk usage after aggressive cleanup: ${after_usage}%"
else
  # Perform light cleanup that preserves build cache
  log "Performing standard cleanup (preserving build cache)"
  log "Standard cleanup complete - build cache preserved"
fi

# If services were stopped, restart them only if usage is now safe
if [ "$critical_usage" -gt 90 ]; then
  final_usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')

  # Ensure numeric final_usage
  if ! [[ "$final_usage" =~ ^[0-9]+$ ]]; then
    log "ERROR: Failed to parse final disk usage: '$final_usage'. Skipping restart."
  elif [ "$final_usage" -lt 85 ]; then
    log "Disk usage now ${final_usage}%. Restarting services."
    $DOCKER_COMPOSE -f docker/docker-compose.yml up -d >> "$LOG_FILE" 2>&1
  else
    log "Disk usage still high at ${final_usage}%. Skipping restart."
  fi
fi

log "Docker cleanup process completed"
exit 0
