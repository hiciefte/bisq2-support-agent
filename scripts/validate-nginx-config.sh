#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NGINX_IMAGE="${NGINX_TEST_IMAGE:-nginx:alpine}"
CONFIGS=(
  "default.conf"
  "default.prod.conf"
)
TMP_DIRS=()

cleanup() {
  for dir in "${TMP_DIRS[@]:-}"; do
    rm -rf "$dir"
  done
}
trap cleanup EXIT

for config in "${CONFIGS[@]}"; do
  tmp_dir="$(mktemp -d)"
  TMP_DIRS+=("$tmp_dir")
  mkdir -p "$tmp_dir/conf.d"

  cp "$REPO_ROOT/docker/nginx/nginx.conf" "$tmp_dir/nginx.conf"
  cp "$REPO_ROOT/docker/nginx/conf.d/$config" "$tmp_dir/conf.d/default.conf"
  cp "$REPO_ROOT/docker/nginx/conf.d/tor-support.conf.template" \
    "$tmp_dir/conf.d/tor-support.conf.template"
  cp -R "$REPO_ROOT/docker/nginx/conf.d/snippets" "$tmp_dir/conf.d/snippets"

  echo "Validating nginx config: $config"
  docker run --rm \
    --add-host api:127.0.0.1 \
    --add-host web:127.0.0.1 \
    --add-host grafana:127.0.0.1 \
    -v "$tmp_dir/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$tmp_dir/conf.d:/etc/nginx/conf.d:ro" \
    -v "$REPO_ROOT/docker/nginx/error_pages:/usr/share/nginx/html/error_pages:ro" \
    -v "$REPO_ROOT/docker/maintenance/maintenance.html:/usr/share/nginx/html/maintenance.html:ro" \
    "$NGINX_IMAGE" nginx -t
done
