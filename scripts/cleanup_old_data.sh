#!/bin/bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
# shellcheck disable=SC1091
source "$script_dir/lib/common.sh"
setup_colors
source_deploy_paths "/etc/bisq-support/deploy.env" || true

dry_run=false
if [ "${1:-}" = "--dry-run" ]; then
    dry_run=true
elif [ "$#" -gt 0 ]; then
    echo "Usage: cleanup_old_data.sh [--dry-run]" >&2
    exit 2
fi

repo_root=$(cd "$script_dir/.." && pwd)
docker_dir="$repo_root/docker"
compose_file="docker-compose.yml"
acquire_production_lifecycle_lock "$repo_root"
pin_existing_compose_project \
    "$docker_dir" "$compose_file" existing
command=(/scripts/privacy-retention.sh)
if [ "$dry_run" = true ]; then
    command+=(--dry-run)
fi

run_docker_compose "$docker_dir" "$compose_file" \
    exec -T scheduler "${command[@]}"
