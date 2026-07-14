#!/bin/bash
set -euo pipefail

# shellcheck source=lib/scheduler-api.sh
source /scripts/lib/scheduler-api.sh

log() {
    echo "[$(date)] $1"
}

log "Starting LLM-Wiki coverage reconciliation..."
response=$(
    scheduler_api_post "/internal/scheduler/reconcile-llm-wiki-coverage" 900
)
log "LLM-Wiki coverage reconciliation completed: $response"
