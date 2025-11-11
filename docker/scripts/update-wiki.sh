#!/bin/bash

# Exit on any error
set -e

echo "Starting weekly wiki content update..."

# Names of the services/containers as defined in docker-compose.yml
# The default project name is 'docker' when running 'docker compose' from that directory
PROJECT_NAME="docker"
API_SERVICE_NAME="api"
API_CONTAINER_NAME="${PROJECT_NAME}-${API_SERVICE_NAME}-1"

# No additional path configuration needed - the unified wrapper handles all paths internally

# 1. Run the unified wiki update wrapper (downloads and processes wiki dump with metrics instrumentation)
echo "Step 1: Running unified wiki update (download + process with metrics)..."
docker exec "$API_CONTAINER_NAME" python3 -m app.scripts.update_wiki

# 2. Restart the API service to reload the data and rebuild the vector store
echo "Step 2: Restarting API service to load new data..."
# This command is run from the scheduler, which can run docker commands.
# We find the container by name and restart it.
docker restart "$API_CONTAINER_NAME"

echo "Wiki content update pipeline finished successfully."

# Optional: Add a health check or notification here

exit 0
