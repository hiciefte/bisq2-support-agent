#!/bin/bash
set -e

echo "====================================="
echo "  Starting Local Development Setup"
echo "====================================="

COMPOSE_CMD=(
  docker compose
  --env-file docker/.env
  -f docker/docker-compose.yml
  -f docker/docker-compose.local.yml
)

# Check if .env file exists in the docker directory
if [ ! -f docker/.env ]; then
  echo "WARNING: docker/.env file not found. Creating an example one for you."
  mkdir -p docker
  echo "OPENAI_API_KEY=your_api_key_here" > docker/.env
  echo "ADMIN_API_KEY=test_admin_key" >> docker/.env
  echo "Edit the docker/.env file with your actual API keys before proceeding."
  exit 1
fi

generate_local_secret() {
  openssl rand -base64 32
}

ensure_env_var() {
  local key="$1"
  local value="$2"
  if ! grep -q "^${key}=" docker/.env; then
    echo "${key}=${value}" >> docker/.env
  elif grep -q "^${key}=[[:space:]]*$" docker/.env; then
    local tmp_file
    tmp_file="$(mktemp)"
    awk -v key="${key}" -v value="${value}" '
      $0 ~ "^" key "=[[:space:]]*$" && !updated {
        print key "=" value
        updated = 1
        next
      }
      { print }
    ' docker/.env > "${tmp_file}"
    mv "${tmp_file}" docker/.env
  fi
}

ensure_env_var "GRAFANA_ADMIN_PASSWORD" "$(generate_local_secret)"
ensure_env_var "GRAFANA_DATASOURCE_API_KEY" "$(generate_local_secret)"
ensure_env_var "REACTOR_IDENTITY_SALT" "$(generate_local_secret)"

echo "1. Stopping any existing containers..."
"${COMPOSE_CMD[@]}" down

echo "2. Building and starting containers with the local configuration..."
"${COMPOSE_CMD[@]}" up -d --build

echo "====================================="
echo "Local development environment started!"
echo "====================================="
echo "Web UI: http://localhost:3000"
echo "API: http://localhost:8000"
echo "Optional Nginx (profile): ${COMPOSE_CMD[*]} --profile nginx up -d nginx"
echo ""
echo "Development Tips:"
echo "- Frontend changes will automatically reload due to volume mounts"
echo "- API changes require manual restart with: ${COMPOSE_CMD[*]} restart api"
echo "- View logs with: ${COMPOSE_CMD[*]} logs -f"
echo "====================================="
