#!/bin/bash
set -euo pipefail

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

echo "Waiting for services to become healthy..."

# Function to check if a service is healthy
check_service_health() {
    local service=$1
    local max_attempts=$2
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if docker compose -f docker-compose.yml ps --format json "$service" 2>/dev/null | grep -q '"Health":"healthy"'; then
            echo "✅ $service is healthy"
            return 0
        elif docker compose -f docker-compose.yml ps --format json "$service" 2>/dev/null | grep -q '"State":"exited"'; then
            echo "❌ $service has exited, attempting restart..."
            docker compose -f docker-compose.yml up -d "$service"
        elif docker compose -f docker-compose.yml ps --format json "$service" 2>/dev/null | grep -q '"Health":"unhealthy"'; then
            echo "🔴 $service reports UNHEALTHY, attempting restart..."
            docker compose -f docker-compose.yml up -d "$service"
        fi

        echo "⏳ Waiting for $service to become healthy (attempt $attempt/$max_attempts)..."
        sleep 10
        attempt=$((attempt + 1))
    done

    echo "⚠️ $service did not become healthy within expected time"
    return 1
}

# Function to start dependent services if they're not running
ensure_dependent_services() {
    local missing_services=""

    # Check if web and nginx are running
    if ! docker compose -f docker-compose.yml ps --format json web 2>/dev/null | grep -q '"State":"running"'; then
        missing_services="$missing_services web"
    fi

    if ! docker compose -f docker-compose.yml ps --format json nginx 2>/dev/null | grep -q '"State":"running"'; then
        missing_services="$missing_services nginx"
    fi

    if [ -n "$missing_services" ]; then
        echo "🔄 Starting missing dependent services:$missing_services"
        docker compose -f docker-compose.yml up -d $missing_services
    fi
}

# Wait for critical services to be healthy
echo "Checking critical services..."
check_service_health "api" 12  # 2 minutes with 10s intervals
api_healthy=$?

check_service_health "bisq2-api" 18  # 3 minutes with 10s intervals

# Ensure dependent services are running
ensure_dependent_services

# Final health check for web and nginx
if [ $api_healthy -eq 0 ]; then
    check_service_health "web" 6   # 1 minute with 10s intervals
    check_service_health "nginx" 6 # 1 minute with 10s intervals
fi

# Display final status
echo ""
echo "📊 Final Service Status:"
docker compose -f docker-compose.yml ps

# Check if any critical services failed
if [ $api_healthy -ne 0 ]; then
    echo ""
    echo "⚠️  WARNING: API service is not healthy. Check logs with:"
    echo "   docker compose -f docker-compose.yml logs api"
    exit 1
fi

echo ""
echo "✅ Application started successfully!"
echo "🌐 Access the application at: http://localhost (or your server IP)"
echo "📈 Access Grafana dashboard at: http://localhost:3001"
