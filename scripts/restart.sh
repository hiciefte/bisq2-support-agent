#!/bin/bash
set -e

# Get the directory of the currently executing script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
DOCKER_DIR="$PROJECT_ROOT/docker"
COMPOSE_FILE="docker-compose.yml"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
setup_colors
source_deploy_paths "/etc/bisq-support/deploy.env" || true
acquire_production_lifecycle_lock "$PROJECT_ROOT" || exit 1

# Export the verified project once so stop/down and the following start remain
# attached to the same stack even after Compose removes its containers.
pin_existing_compose_project \
    "$DOCKER_DIR" "$COMPOSE_FILE" existing || exit 1

echo "========================================================"
echo " Restarting Bisq Support Assistant"
echo "========================================================"

echo "--- Stopping the application ---"
"$SCRIPT_DIR/stop.sh"

echo ""
echo "--- Starting the application ---"
"$SCRIPT_DIR/start.sh"

echo "========================================================"
echo " Restart complete."
echo "========================================================"
