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

# --- Source Production Environment Configuration --- #
# This is not strictly necessary for 'down', but included for consistency
# and to ensure the correct project context is established if needed.
PROD_ENV_FILE="/etc/bisq-support/deploy.env"
if [ -f "$PROD_ENV_FILE" ]; then
    echo "Sourcing production environment variables from $PROD_ENV_FILE..."
    # shellcheck disable=SC1090,SC1-91
    source "$PROD_ENV_FILE"
fi
# --- End Source Environment Configuration --- #

# Navigate to the Docker directory
cd "$DOCKER_DIR" || {
    echo "Error: Failed to change to Docker directory: $DOCKER_DIR"
    exit 1
}

echo "Stopping and removing containers..."
docker compose -f docker-compose.yml down

echo "Application stopped successfully." 