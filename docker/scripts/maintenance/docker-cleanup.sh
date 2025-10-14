#!/bin/bash
#
# Docker System Cleanup Script
# This script safely cleans Docker resources to prevent disk space issues
#
set -Eeuo pipefail

# Log file setup with fallback for non-root execution
LOG_DIR="/var/log/bisq-support"
if ! mkdir -p "$LOG_DIR" 2>/dev/null; then
  LOG_DIR="/tmp/bisq-support"
  # Use install -d instead of mkdir -p -m to ensure correct permissions (SC2174)
  install -d -m 0755 "$LOG_DIR"
fi
LOG_FILE="$LOG_DIR/docker-cleanup-$(date +%Y%m%d).log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Determine docker compose command (docker compose vs docker-compose)
DOCKER_COMPOSE="docker compose"
# Ensure at least one compose frontend is available
if ! command -v docker >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  echo "ERROR: Neither 'docker' nor 'docker-compose' found in PATH"
  exit 1
fi
if ! $DOCKER_COMPOSE version >/dev/null 2>&1; then
  DOCKER_COMPOSE="docker-compose"
  if ! command -v docker-compose >/dev/null 2>&1; then
    echo "ERROR: No compose frontend available (docker compose/docker-compose)"
    exit 1
  fi
fi

# Verify docker CLI is present and daemon is reachable
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker CLI not found in PATH"
  exit 1
fi
if ! docker version >/dev/null 2>&1; then
  echo "ERROR: Cannot connect to Docker daemon. Is the Docker service running?"
  exit 1
fi

# Log function
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Register ERR trap after log function is defined
trap 'log "ERROR: Line $LINENO: \"$BASH_COMMAND\" exited with $?"' ERR

# Helper function to get disk usage percentage for a given path
get_usage() {
  local path="${1:-/}"
  df -P "$path" | awk 'NR==2{gsub(/%/,"",$5); print $5}'
}

# Check if cleanup is needed (>75% disk usage)
check_disk_usage() {
  local threshold=75
  local usage
  local target_path="/"

  # Attempt to detect Docker's actual data root mount
  if command -v docker >/dev/null 2>&1; then
    local root
    root="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
    [ -n "$root" ] && target_path="$root"
  fi

  usage=$(get_usage "$target_path")

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
critical_usage=$(get_usage /)

# Ensure numeric critical_usage to avoid integer comparison errors
if ! [[ "$critical_usage" =~ ^[0-9]+$ ]]; then
  log "ERROR: Failed to parse critical disk usage: '$critical_usage'. Skipping container stop."
  critical_usage=0  # Set to 0 to prevent restart logic from triggering
elif [ "$critical_usage" -gt 90 ]; then
  log "CRITICAL: Disk usage at ${critical_usage}%. Stopping all containers to prevent data loss."
  if [ -f "docker/docker-compose.yml" ]; then
    log "Running: $DOCKER_COMPOSE -f docker/docker-compose.yml down --remove-orphans --timeout 30"
    $DOCKER_COMPOSE -f docker/docker-compose.yml down --remove-orphans --timeout 30 >> "$LOG_FILE" 2>&1
  else
    log "WARNING: docker/docker-compose.yml not found; skipping container stop."
  fi
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
  # NOTE: For production, consider configuring max-size/max-file in docker-compose.yml
  # logging section or use logrotate for /var/lib/docker/containers to prevent unbounded growth
  log "Cleaning up Docker logs"
  if [ -d /var/lib/docker/containers ]; then
    # Use || true to prevent permission errors from aborting the script
    # Errors are still logged but won't trigger the ERR trap
    find /var/lib/docker/containers -type f -name "*.log" -exec truncate -s 0 {} \; >> "$LOG_FILE" 2>&1 || true
    log "Docker logs have been truncated (permission errors ignored)"
  fi

  # Check disk usage after cleanup
  after_usage=$(get_usage /)
  log "Disk usage after aggressive cleanup: ${after_usage}%"
else
  # Perform light cleanup that preserves build cache
  log "Performing standard cleanup (preserving build cache)"
  # Only remove dangling images and stopped containers (already done above)
  # Preserve build cache entirely for faster future builds
  log "Standard cleanup complete - build cache preserved"
fi

# If services were stopped, restart them only if usage is now safe
if [ "$critical_usage" -gt 90 ]; then
  final_usage=$(get_usage /)

  # Ensure numeric final_usage
  if ! [[ "$final_usage" =~ ^[0-9]+$ ]]; then
    log "ERROR: Failed to parse final disk usage: '$final_usage'. Skipping restart."
  elif [ "$final_usage" -lt 85 ]; then
    log "Disk usage now ${final_usage}%. Restarting services."
    if [ -f "docker/docker-compose.yml" ]; then
      # Use start_services if available for proper health checks
      if [ -f "scripts/lib/docker-utils.sh" ]; then
        # shellcheck source=/dev/null
        . "scripts/lib/docker-utils.sh"
        start_services "docker" "docker-compose.yml" >> "$LOG_FILE" 2>&1 || log "ERROR: start_services failed"
      else
        $DOCKER_COMPOSE -f docker/docker-compose.yml up -d >> "$LOG_FILE" 2>&1
      fi
    else
      log "WARNING: docker/docker-compose.yml not found; skipping restart."
    fi
  else
    log "Disk usage still high at ${final_usage}%. Skipping restart."
  fi
fi

log "Docker cleanup process completed"
exit 0
