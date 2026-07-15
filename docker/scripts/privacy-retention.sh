#!/bin/bash
set -euo pipefail

# shellcheck source=lib/scheduler-api.sh
source /scripts/lib/scheduler-api.sh

dry_run=false
if [ "${1:-}" = "--dry-run" ]; then
    dry_run=true
elif [ "$#" -gt 0 ]; then
    echo "Usage: privacy-retention.sh [--dry-run]" >&2
    exit 2
fi

endpoint="/internal/scheduler/privacy-retention"
if [ "$dry_run" = true ]; then
    endpoint="${endpoint}?dry_run=true"
fi

response=$(scheduler_api_post "$endpoint" 3600)
printf '%s\n' "$response" | jq -e '{status, dry_run, deleted_rows}'
