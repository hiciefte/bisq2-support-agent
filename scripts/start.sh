#!/bin/bash
set -e

# --- Get Project Root ---
# This script is location-aware. It will run correctly regardless of the caller's CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
DOCKER_DIR="$PROJECT_ROOT/docker"

echo "========================================================"
echo " Starting Bisq Support Assistant (Production Mode)"
echo "========================================================"

# --- Source Production Environment Configuration --- #
# This script is for managing a deployed production server.
# It sources a centralized deployment file for secrets. If this file
# is not present, it will proceed with defaults, which may not be sufficient.
PROD_ENV_FILE="/etc/bisq-support/deploy.env"
if [ -f "$PROD_ENV_FILE" ]; then
    echo "Sourcing production environment variables from $PROD_ENV_FILE..."
    # shellcheck disable=SC1090,SC1091
    source "$PROD_ENV_FILE"
else
    echo "WARNING: Production environment file not found at $PROD_ENV_FILE."
    echo "Proceeding with defaults. This may not be a complete configuration."
fi
# --- End Source Environment Configuration --- #

# Export UID and GID for Docker Compose, using defaults if not set in the sourced file.
export APP_UID=${APP_UID:-1001}
export APP_GID=${APP_GID:-1001}

echo "Using UID: $APP_UID and GID: $APP_GID for container user."

# Navigate to the Docker directory
cd "$DOCKER_DIR" || {
    echo "Error: Failed to change to Docker directory: $DOCKER_DIR"
    exit 1
}

echo "Starting containers using docker-compose.yml..."
docker compose -f docker-compose.yml up -d

echo "Application started successfully." 