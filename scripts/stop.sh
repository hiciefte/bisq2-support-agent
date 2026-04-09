#!/bin/bash
set -e

# --- Get Project Root ---
# This script is location-aware. It will run correctly regardless of the caller's CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
DOCKER_DIR="$PROJECT_ROOT/docker"

echo "========================================================"
echo " Stopping Bisq Support Assistant (Production Mode)"
echo "========================================================"

# --- Source Environment Configuration --- #
# Only deploy-path vars; docker/.env provides app config to Docker Compose.
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"
setup_colors
source_deploy_paths "/etc/bisq-support/deploy.env" || true
# --- End Source Environment Configuration --- #

# Navigate to the Docker directory
cd "$DOCKER_DIR" || {
    echo "Error: Failed to change to Docker directory: $DOCKER_DIR"
    exit 1
}

echo "Stopping and removing containers..."
docker compose -f docker-compose.yml down

echo "Application stopped successfully."
