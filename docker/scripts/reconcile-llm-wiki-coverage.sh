#!/bin/bash

set -e

log() {
  echo "[$(date)] $1"
}

PROJECT_NAME="docker"
API_SERVICE_NAME="api"
API_CONTAINER_NAME="${PROJECT_NAME}-${API_SERVICE_NAME}-1"

log "Starting LLM Wiki coverage reconciliation..."

if ! docker ps --format '{{.Names}}' | grep -q "$API_CONTAINER_NAME"; then
  log "ERROR: API container $API_CONTAINER_NAME not found or not running"
  exit 1
fi

if ! OUTPUT=$(docker exec "$API_CONTAINER_NAME" python3 -m app.scripts.reconcile_llm_wiki_coverage 2>&1); then
  log "ERROR: LLM Wiki coverage reconciliation failed"
  log "Output: $OUTPUT"
  exit 1
fi

log "LLM Wiki coverage reconciliation finished."
log "Output: $OUTPUT"
