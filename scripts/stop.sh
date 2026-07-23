#!/bin/bash
set -e

# --- Get Project Root ---
# This script is location-aware. It will run correctly regardless of the caller's CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
DOCKER_DIR="$PROJECT_ROOT/docker"
COMPOSE_FILE="docker-compose.yml"

echo "========================================================"
echo " Stopping Bisq Support Assistant (Production Mode)"
echo "========================================================"

# --- Source Environment Configuration --- #
# Only allowlisted deploy settings; docker/.env provides app config to Compose.
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
setup_colors
source_deploy_paths "/etc/bisq-support/deploy.env" || true
# --- End Source Environment Configuration --- #

acquire_production_lifecycle_lock "$PROJECT_ROOT" || exit 1
pin_existing_compose_project \
    "$DOCKER_DIR" "$COMPOSE_FILE" existing || exit 1
persist_compose_project_name "$DOCKER_DIR" || exit 1

# Navigate to the Docker directory
cd "$DOCKER_DIR" || {
    echo "Error: Failed to change to Docker directory: $DOCKER_DIR"
    exit 1
}

echo "Stopping and removing containers..."
run_docker_compose "$DOCKER_DIR" "$COMPOSE_FILE" down

echo "Application stopped successfully."
