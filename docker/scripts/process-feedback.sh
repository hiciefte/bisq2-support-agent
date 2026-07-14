#!/bin/bash
set -euo pipefail

# shellcheck source=lib/scheduler-api.sh
source /scripts/lib/scheduler-api.sh

log() {
    echo "[$(date)] $1"
}

log "Starting weekly feedback processing..."
response=$(scheduler_api_post "/internal/scheduler/process-feedback" 900)
log "Feedback processing completed: $response"
