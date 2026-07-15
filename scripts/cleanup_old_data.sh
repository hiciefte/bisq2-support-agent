#!/bin/bash
set -euo pipefail

dry_run=false
if [ "${1:-}" = "--dry-run" ]; then
    dry_run=true
elif [ "$#" -gt 0 ]; then
    echo "Usage: cleanup_old_data.sh [--dry-run]" >&2
    exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
compose=(
    docker compose
    --project-directory "$repo_root"
    -f "$repo_root/docker/docker-compose.yml"
)
command=(/scripts/privacy-retention.sh)
if [ "$dry_run" = true ]; then
    command+=(--dry-run)
fi

exec "${compose[@]}" exec -T scheduler "${command[@]}"
