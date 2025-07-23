#!/bin/bash

# Exit on any error
set -e

echo "Starting weekly wiki content update..."

# Names of the services/containers as defined in docker-compose.yml
# The default project name is 'docker' when running 'docker compose' from that directory
PROJECT_NAME="docker"
API_SERVICE_NAME="api"
API_CONTAINER_NAME="${PROJECT_NAME}-${API_SERVICE_NAME}-1"

# Project paths inside the API container
# The project root is mounted at /app in the api container
PROJECT_ROOT="/app"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"
API_APP_SCRIPTS_DIR="$PROJECT_ROOT/app/scripts"
WIKI_DATA_DIR="/app/data/wiki"

# 1. Download the latest Bisq MediaWiki dump by running the script inside the API container
echo "Step 1: Downloading latest wiki data..."
docker exec "$API_CONTAINER_NAME" python3 "$API_APP_SCRIPTS_DIR/download_bisq2_media_wiki.py" --output-dir "$WIKI_DATA_DIR"

# 2. Process the downloaded wiki dump by running the script inside the API container
echo "Step 2: Processing the wiki dump..."
docker exec "$API_CONTAINER_NAME" python3 "$API_APP_SCRIPTS_DIR/process_wiki_dump.py"

# 3. Restart the API service to reload the data and rebuild the vector store
echo "Step 3: Restarting API service to load new data..."
# This command is run from the scheduler, which can run docker commands.
# We find the container by name and restart it.
docker restart "$API_CONTAINER_NAME"

echo "Wiki content update pipeline finished successfully."

# Optional: Add a health check or notification here

exit 0 