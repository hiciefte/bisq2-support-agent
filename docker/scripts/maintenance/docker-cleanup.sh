#!/bin/bash
#
# Docker System Cleanup Script
# This script safely cleans Docker resources to prevent disk space issues
# 

# Log file setup
LOG_DIR="/var/log/bisq-support"
mkdir -p $LOG_DIR
LOG_FILE="$LOG_DIR/docker-cleanup-$(date +%Y%m%d).log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Log function
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Check if cleanup is needed (>75% disk usage)
check_disk_usage() {
  local threshold=75
  local usage
  usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')
  
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
if [ "$critical_usage" -gt 90 ]; then
  log "CRITICAL: Disk usage at ${critical_usage}%. Stopping all containers to prevent data loss."
  log "Running: docker compose -f docker/docker-compose.yml down"
  docker compose -f docker/docker-compose.yml down >> "$LOG_FILE" 2>&1
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
  
  # Remove all unused images, not just dangling ones
  log "Removing all unused images"
  docker image prune -a -f --filter "until=24h" >> "$LOG_FILE" 2>&1
  
  # Remove unused build cache
  log "Removing build cache"
  docker builder prune -f >> "$LOG_FILE" 2>&1
  
  # Remove unused networks
  log "Removing unused networks"
  docker network prune -f >> "$LOG_FILE" 2>&1
  
  # Prune volumes carefully (only if not attached to any container)
  log "Removing unused volumes"
  docker volume prune -f >> "$LOG_FILE" 2>&1
  
  # Clean up logs
  log "Cleaning up Docker logs"
  if [ -d /var/lib/docker/containers ]; then
    find /var/lib/docker/containers -type f -name "*.log" -exec truncate -s 0 {} \;
    log "Docker logs have been truncated"
  fi
  
  # Check disk usage after cleanup
  after_usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')
  log "Disk usage after aggressive cleanup: ${after_usage}%"
else
  # Just do a system prune without volumes if disk usage isn't critical
  log "Performing standard cleanup"
  docker system prune -f >> "$LOG_FILE" 2>&1
fi

# If services were stopped, restart them
if [ "$critical_usage" -gt 90 ]; then
  log "Restarting services"
  docker compose -f docker/docker-compose.yml up -d >> "$LOG_FILE" 2>&1
fi

log "Docker cleanup process completed"
exit 0 