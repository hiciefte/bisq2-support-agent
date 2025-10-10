#!/bin/bash
set -e

echo "====================================="
echo "  Starting Local Development Setup"
echo "====================================="

# Check if .env file exists in the docker directory
if [ ! -f docker/.env ]; then
  echo "WARNING: docker/.env file not found. Creating an example one for you."
  mkdir -p docker
  echo "OPENAI_API_KEY=your_api_key_here" > docker/.env
  echo "ADMIN_API_KEY=test_admin_key" >> docker/.env
  echo "Edit the docker/.env file with your actual API keys before proceeding."
  exit 1
fi

echo "1. Stopping any existing containers..."
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml down

echo "2. Building and starting containers with the local configuration..."
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml up -d --build

echo "====================================="
echo "Local development environment started!"
echo "====================================="
echo "Web UI: http://localhost:3000"
echo "API: http://localhost:8000"
echo ""
echo "Development Tips:"
echo "- Frontend changes will automatically reload due to volume mounts"
echo "- API changes require manual restart with: docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml restart api"
echo "- View logs with: docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml logs -f"
echo "====================================="
