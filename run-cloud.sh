#!/bin/bash
set -e

echo "====================================="
echo "  Starting Production Deployment"
echo "====================================="

# Check if .env file exists in the docker directory
if [ ! -f docker/.env ]; then
  echo "ERROR: docker/.env file not found. Please create one with required environment variables."
  echo "Required variables include OPENAI_API_KEY and ADMIN_API_KEY at minimum."
  exit 1
fi

echo "1. Stopping any existing containers..."
docker compose -f docker/docker-compose.yml down

echo "2. Removing any dangling volumes to ensure clean state..."
docker volume prune -f

echo "3. Building and starting containers with production configuration..."
docker compose -f docker/docker-compose.yml up -d --build

echo "====================================="
echo "Production environment started!"
echo "====================================="
echo "Web UI: http://localhost:80"
echo "API: http://localhost:8000"
echo "Prometheus: http://localhost:9090"
echo "Grafana: http://localhost:3001"
echo ""
echo "Production Tips:"
echo "- To check container status: docker compose -f docker/docker-compose.yml ps"
echo "- View logs with: docker compose -f docker/docker-compose.yml logs -f"
echo "- Monitor services through Grafana dashboards"
echo "=====================================" 