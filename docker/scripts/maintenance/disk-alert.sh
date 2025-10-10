#!/bin/bash
#
# Disk Usage Monitoring and Alert Script
# This script monitors disk usage and sends alerts when thresholds are exceeded
#

# Configuration
WARNING_THRESHOLD=75
CRITICAL_THRESHOLD=90
ALERT_EMAIL="admin@example.com"  # Change to your email
HOSTNAME=$(hostname)
LOG_DIR="/var/log/bisq-support"
mkdir -p $LOG_DIR
LOG_FILE="$LOG_DIR/disk-alert-$(date +%Y%m%d).log"

# Log function
log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Send email alert
send_email_alert() {
  local subject="$1"
  local message="$2"

  if command -v mail &> /dev/null; then
    echo "$message" | mail -s "$subject" "$ALERT_EMAIL"
    log "Email alert sent to $ALERT_EMAIL"
  else
    log "WARNING: mail command not found, couldn't send email alert"
    # Fallback to console output
    echo "ALERT: $subject"
    echo "$message"
  fi
}

# Send Slack/Discord webhook if configured
send_webhook_alert() {
  local message="$1"
  local level="$2"

  # If a webhook URL is defined
  if [ -n "$WEBHOOK_URL" ]; then
    local color="warning"
    if [ "$level" == "critical" ]; then
      color="danger"
    fi

    curl -s -X POST -H "Content-Type: application/json" \
      -d "{\"text\":\"*$HOSTNAME Disk Alert*\", \"attachments\":[{\"color\":\"$color\",\"text\":\"$message\"}]}" \
      "$WEBHOOK_URL" &> /dev/null

    log "Webhook alert sent"
  fi
}

# Check disk usage
check_disk_usage() {
  log "Checking disk usage"

  # Get disk usage percentage
  local disk_usage
  disk_usage=$(df -h / | grep -v Filesystem | awk '{print $5}' | sed 's/%//')

  log "Current disk usage: ${disk_usage}%"

  # Critical alert (highest priority)
  if [ "$disk_usage" -ge "$CRITICAL_THRESHOLD" ]; then
    local subject
    subject="CRITICAL: Disk Usage at ${disk_usage}% on $HOSTNAME"
    local message
    message="
CRITICAL ALERT: Disk usage has reached ${disk_usage}% on $HOSTNAME
Timestamp: $(date)

Action Required:
1. Connect to the server and check running processes
2. Run cleanup script: /path/to/bisq2-support-agent/docker/scripts/maintenance/docker-cleanup.sh
3. Consider extending disk space or archiving old data

Disk usage details:
$(df -h)
    "

    log "CRITICAL: Disk usage at ${disk_usage}%, sending alert"
    send_email_alert "$subject" "$message"
    send_webhook_alert "$message" "critical"

    # Attempt automatic cleanup
    if [ -f "$(dirname "$0")/docker-cleanup.sh" ]; then
      log "Attempting automatic cleanup"
      "$(dirname "$0")/docker-cleanup.sh"
    fi

    return 2

  # Warning alert
  elif [ "$disk_usage" -ge "$WARNING_THRESHOLD" ]; then
    local subject
    subject="WARNING: Disk Usage at ${disk_usage}% on $HOSTNAME"
    local message
    message="
WARNING: Disk usage has reached ${disk_usage}% on $HOSTNAME
Timestamp: $(date)

Recommended actions:
1. Monitor the situation
2. Schedule cleanup if usage continues to increase
3. Consider running: /path/to/bisq2-support-agent/docker/scripts/maintenance/docker-cleanup.sh

Disk usage details:
$(df -h)
    "

    log "WARNING: Disk usage at ${disk_usage}%, sending alert"
    send_email_alert "$subject" "$message"
    send_webhook_alert "$message" "warning"

    return 1
  else
    log "Disk usage is normal at ${disk_usage}%"
    return 0
  fi
}

# Main execution
log "Starting disk usage monitoring"
check_disk_usage
exit_code=$?
log "Disk monitoring completed with status $exit_code"
exit $exit_code
