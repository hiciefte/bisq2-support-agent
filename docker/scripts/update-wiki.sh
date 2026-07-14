#!/bin/bash
set -euo pipefail

# shellcheck source=lib/scheduler-api.sh
source /scripts/lib/scheduler-api.sh

log() {
    echo "[$(date)] $1"
}

log "Starting weekly wiki content update..."
response=$(scheduler_api_post "/internal/scheduler/update-wiki" 3600)
log "Wiki content update completed: $response"
