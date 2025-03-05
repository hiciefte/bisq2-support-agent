#!/bin/bash

# Stop any running containers
docker compose -f docker/docker-compose.yml down

# Build and start containers with the cloud configuration
docker compose -f docker/docker-compose.yml up -d

echo "Cloud environment started!"
echo "Web UI: http://localhost:3000"
echo "API: http://localhost:8000"
echo "Prometheus: http://localhost:9090"
echo "Grafana: http://localhost:3001" 